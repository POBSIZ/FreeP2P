"""Minecraft TCP streams over authenticated, multiplexed QUIC/UDP.

One datagram socket per node handles STUN, hole punching and every peer's QUIC.
Only the configured loopback game port is reachable through a host.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.buffer import Buffer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import ConnectionTerminated, HandshakeCompleted, StreamReset
from aioquic.quic.packet import pull_quic_header, QuicPacketType
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from freep2p import COOKIE, DEFAULT_STUN, encode, parse_stun

MAGIC = b'FQM1'
CHUNK = 16384
WINDOW = 16
DEFAULT_MAX_PEERS = 16
MAX_STREAMS = 16


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def unb64(text):
    return base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)


def decode_code(code):
    try:
        if not isinstance(code, str) or not code.startswith('fpm1:') or len(code) > 4096:
            raise ValueError()
        obj = json.loads(unb64(code[5:]))
        ip = ipaddress.IPv4Address(obj['ip'])
        if ip.is_unspecified or ip.is_multicast or ip == ipaddress.IPv4Address('255.255.255.255'):
            raise ValueError()
        if type(obj['port']) is not int or not 1 <= obj['port'] <= 65535:
            raise ValueError()
        if obj['role'] not in ('host', 'guest') or len(unb64(obj['token'])) != 32:
            raise ValueError()
        if not isinstance(obj['name'], str) or not 1 <= len(obj['name']) <= 40:
            raise ValueError()
        if obj['role'] == 'host':
            x509.load_der_x509_certificate(unb64(obj['cert']))
        return obj
    except (ValueError, TypeError, KeyError):
        raise ValueError('올바른 fpm1: 연결 코드 전체를 입력하세요.') from None


def certificate():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'freep2p.local')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=7))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('freep2p.local')]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .sign(key, hashes.SHA256()))
    return key, cert


@dataclass
class Session:
    node: 'TunnelNode'
    code: dict
    sid: bytes
    key: bytes
    addr: tuple
    state: str = 'punching'
    error: str = ''
    protocol: object = None
    original_cid: bytes = b''
    tx: int = 0
    highest: int = 0
    seen: set = field(default_factory=set)
    challenges: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    next_probe: float = 0
    last_rx: float = field(default_factory=time.monotonic)
    rtt: float | None = None
    streams: int = 0
    uploaded: int = 0
    downloaded: int = 0
    tasks: set = field(default_factory=set)

    def task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def send(self, kind, payload):
        if self.node.closed:
            return
        self.tx += 1
        header = MAGIC + self.sid + kind + self.tx.to_bytes(8, 'big') + payload
        wire = header + hmac.digest(self.key, header, 'sha256')
        self.node.transport.sendto(wire, self.addr)

    def stop(self, reason='연결 종료'):
        self.state = 'closed'
        self.error = reason
        if self.protocol:
            self.protocol.dispose()
            self.protocol = None
        for task in list(self.tasks):
            task.cancel()


class WrappedTransport:
    def __init__(self, session):
        self.session = session

    def sendto(self, data, addr=None):
        self.session.send(b'Q', data)


class TunnelProtocol(QuicConnectionProtocol):
    def __init__(self, quic, session):
        self.session = session
        super().__init__(quic, stream_handler=self.incoming_stream)
        self.connection_ids = {quic.host_cid, session.original_cid}
        self._connection_id_issued_handler = self.connection_ids.add
        self._connection_id_retired_handler = self.connection_ids.discard
        self.connection_made(WrappedTransport(session))

    def incoming_stream(self, reader, writer):
        session = self.session
        if session.node.role != 'host' or session.streams >= MAX_STREAMS:
            writer.close()
            return
        session.streams += 1
        session.task(session.node.serve_game(session, reader, writer))

    def quic_event_received(self, event):
        super().quic_event_received(event)
        session = self.session
        if isinstance(event, HandshakeCompleted):
            session.state = 'connected'
            session.error = ''
            session.node.log(f"{session.code['name']} · 암호화된 직접 연결 완료")
        elif isinstance(event, ConnectionTerminated):
            session.state = 'failed' if session.state != 'closed' else 'closed'
            session.error = event.reason_phrase or '연결 종료 또는 응답 시간 초과'
            for task in list(session.tasks):
                task.cancel()
        elif isinstance(event, StreamReset):
            reader = self._stream_readers.get(event.stream_id)
            if reader:
                reader.set_exception(ConnectionError('상대가 게임 스트림을 종료했습니다.'))

    def dispose(self):
        self.close(reason_phrase='Session closed')
        # aioquic 1.3.0 owns timers but not our shared datagram transport.
        if self._timer:
            self._timer.cancel()
        if self._transmit_task:
            self._transmit_task.cancel()
        for reader in self._stream_readers.values():
            reader.feed_eof()

    def forget_stream(self, writer):
        self._stream_readers.pop(writer.get_extra_info('stream_id'), None)


async def bridge(tcp_reader, tcp_writer, quic_reader, quic_writer, session):
    """Bound memory to WINDOW*CHUNK per direction; preserve TCP half-closes."""
    slots = asyncio.Semaphore(WINDOW)
    outstanding = 0
    all_acked = asyncio.Event()
    all_acked.set()
    remote_ended = asyncio.Event()

    async def upload():
        nonlocal outstanding
        while True:
            await slots.acquire()
            data = await tcp_reader.read(CHUNK)
            if not data:
                slots.release()
                quic_writer.write(b'E\0\0\0\0')
                return
            outstanding += 1
            all_acked.clear()
            quic_writer.write(b'D' + len(data).to_bytes(4, 'big') + data)
            session.uploaded += len(data)

    async def download():
        nonlocal outstanding
        remote_eof = False
        while True:
            try:
                header = await quic_reader.readexactly(5)
            except asyncio.IncompleteReadError:
                if remote_eof:
                    return
                raise ConnectionError('게임 터널이 예기치 않게 종료되었습니다.')
            kind, length = header[:1], int.from_bytes(header[1:], 'big')
            if kind == b'D' and 0 < length <= CHUNK and not remote_eof:
                data = await quic_reader.readexactly(length)
                tcp_writer.write(data)
                await tcp_writer.drain()
                quic_writer.write(b'A\0\0\0\0')
                session.downloaded += len(data)
            elif kind == b'A' and length == 0 and outstanding > 0:
                outstanding -= 1
                slots.release()
                if outstanding == 0:
                    all_acked.set()
            elif kind == b'E' and length == 0 and not remote_eof:
                remote_eof = True
                remote_ended.set()
                if tcp_writer.can_write_eof():
                    tcp_writer.write_eof()
            else:
                raise ConnectionError('올바르지 않은 터널 프레임')

    up = asyncio.create_task(upload())
    down = asyncio.create_task(download())
    async def finish():
        await up
        await remote_ended.wait()
        await all_acked.wait()
        quic_writer.write_eof()
    finisher = asyncio.create_task(finish())
    try:
        await asyncio.gather(up, down, finisher)
    finally:
        up.cancel()
        down.cancel()
        finisher.cancel()
        await asyncio.gather(up, down, finisher, return_exceptions=True)


class TunnelNode(asyncio.DatagramProtocol):
    def __init__(self, role, name, game_port=25565, listen_port=25565, *,
                 local=False, bind='0.0.0.0', udp_port=0, timeout=45, servers=None,
                 max_peers=DEFAULT_MAX_PEERS):
        if role not in ('host', 'guest'):
            raise ValueError('호스트 또는 참가자를 선택하세요.')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ValueError('이름은 1~40자로 입력하세요.')
        for port in (game_port, listen_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('포트는 1~65535 범위여야 합니다.')
        self.role, self.name = role, name.strip()
        self.game_port, self.listen_port = game_port, listen_port
        self.local, self.bind, self.udp_port = local, bind, udp_port
        self.timeout = timeout
        self.token = secrets.token_bytes(32)
        self.transport = self.listener = self.tick_task = None
        self.sessions = {}
        self.set_max_peers(max_peers)
        self.events = deque(maxlen=100)
        self.public = None
        self.status = 'discovering'
        self.closed = False
        self.servers = []
        self.server_names = servers or DEFAULT_STUN
        self.stun_pending = {}
        self.active_stun = None
        self.stun_index = 0
        self.next_stun = 0
        self.stun_failures = 0
        self.private_key, self.cert = certificate() if role == 'host' else (None, None)

    def log(self, text):
        self.events.append({'time': time.strftime('%H:%M:%S'), 'message': str(text)[:300]})

    async def start(self):
        loop = asyncio.get_running_loop()
        try:
            await loop.create_datagram_endpoint(lambda: self, local_addr=(self.bind, self.udp_port), family=socket.AF_INET)
            if self.role == 'guest':
                self.listener = await asyncio.start_server(self.accept_game, '127.0.0.1', self.listen_port)
            if self.local:
                self.public = ('127.0.0.1' if self.bind == '0.0.0.0' else self.bind, self.transport.get_extra_info('sockname')[1])
                self.status = 'ready'
            else:
                for name in self.server_names:
                    try:
                        host, port = name.rsplit(':', 1)
                        info = await asyncio.wait_for(loop.getaddrinfo(host, int(port), family=socket.AF_INET, type=socket.SOCK_DGRAM), 5)
                        self.servers.append(info[0][4])
                    except (OSError, ValueError, asyncio.TimeoutError):
                        self.log(f'STUN 주소 조회 실패: {name}')
                if not self.servers:
                    self.status = 'stun_failed'
            self.tick_task = asyncio.create_task(self.tick())
            self.log('외부 주소 확인 중' if not self.local else '로컬 테스트 모드')
            return self
        except BaseException:
            await self.close()
            raise

    def connection_made(self, transport):
        self.transport = transport

    def error_received(self, exc):
        self.log(f'UDP 오류: {exc}')

    @property
    def code(self):
        if not self.public:
            return ''
        data = {'role': self.role, 'name': self.name, 'ip': self.public[0],
                'port': self.public[1], 'token': b64(self.token)}
        if self.cert:
            data['cert'] = b64(self.cert.public_bytes(serialization.Encoding.DER))
        return 'fpm1:' + b64(encode(data))

    def set_max_peers(self, value):
        if type(value) is not int or not 1 <= value <= 9007199254740991:
            raise ValueError('최대 참가자 수는 1 이상의 정수로 입력하세요.')
        if value < len(self.sessions):
            raise ValueError(f'이미 등록된 참가자가 {len(self.sessions)}명입니다. 먼저 참가자를 해제하세요.')
        self.max_peers = value

    def add_peer(self, code):
        if len(self.sessions) >= (self.max_peers if self.role == 'host' else 1):
            raise ValueError('등록 가능한 참가자 수에 도달했습니다. 최대 인원을 늘리거나 기존 참가자를 해제하세요.')
        other = decode_code(code.strip())
        if other['role'] == self.role:
            raise ValueError('호스트는 참가 코드를, 참가자는 호스트 코드를 입력해야 합니다.')
        key = hashlib.sha256(b'freep2p-minecraft-v1' + b''.join(sorted([self.token, unb64(other['token'])]))).digest()
        sid = hashlib.sha256(key).digest()[:16]
        if sid in self.sessions:
            raise ValueError('이미 등록된 상대입니다.')
        session = Session(self, other, sid, key, (other['ip'], other['port']))
        self.sessions[sid] = session
        self.log(f"{other['name']} · 연결 탐색 시작")
        return session

    def remove_peer(self, sid):
        session = self.sessions.pop(bytes.fromhex(sid), None)
        if session:
            session.stop('사용자가 연결을 해제했습니다.')
            self.log(f"{session.code['name']} · 연결 해제")

    def retry_peer(self, sid):
        session = self.sessions[bytes.fromhex(sid)]
        session.stop('재연결 중')
        session.state, session.error = 'punching', ''
        session.started, session.next_probe = time.monotonic(), 0
        session.challenges.clear()

    def make_protocol(self, session, initial=None):
        config = QuicConfiguration(is_client=self.role == 'guest', alpn_protocols=['freep2p-mc/1'],
                                   idle_timeout=35, max_data=2**20, max_stream_data=2**18)
        if self.role == 'host':
            config.certificate, config.private_key = self.cert, self.private_key
            quic = QuicConnection(configuration=config, original_destination_connection_id=initial)
            session.original_cid = initial
        else:
            cert = x509.load_der_x509_certificate(unb64(session.code['cert']))
            config.load_verify_locations(cadata=cert.public_bytes(serialization.Encoding.PEM))
            config.server_name = 'freep2p.local'
            quic = QuicConnection(configuration=config)
        protocol = TunnelProtocol(quic, session)
        session.protocol = protocol
        session.state = 'handshaking'
        if self.role == 'guest':
            protocol.connect(session.addr)
        return protocol

    def datagram_received(self, data, addr):
        now = time.monotonic()
        if len(data) >= 20 and data[8:20] in self.stun_pending:
            tid = data[8:20]
            if self.stun_pending[tid][0] == addr:
                result = parse_stun(data, tid)
                if result:
                    self.stun_pending.pop(tid)
                    self.active_stun, self.next_stun = addr, now + 20
                    self.stun_failures = 0
                    if result != self.public:
                        self.log('연결 코드 준비 완료' if self.public is None else '외부 주소 변경 · 새 코드를 상대에게 다시 전달하세요.')
                        self.public = result
                    self.status = 'ready'
                    return
        if len(data) < 61 or len(data) > 1500 or not data.startswith(MAGIC):
            return
        session = self.sessions.get(data[4:20])
        if not session or session.state == 'closed':
            return
        if not hmac.compare_digest(data[-32:], hmac.digest(session.key, data[:-32], 'sha256')):
            return
        seq = int.from_bytes(data[21:29], 'big')
        if seq in session.seen or seq <= session.highest - 4096:
            return
        session.seen.add(seq)
        session.highest = max(session.highest, seq)
        if len(session.seen) > 8192:
            session.seen = {n for n in session.seen if n > session.highest - 4096}
        kind, payload = data[20:21], data[29:-32]
        session.addr, session.last_rx = addr, now
        if kind == b'P' and len(payload) == 16:
            session.send(b'A', payload)
        elif kind == b'A' and payload in session.challenges:
            session.rtt = (now - session.challenges.pop(payload)) * 1000
            if self.role == 'guest' and session.protocol is None and session.state == 'punching':
                self.make_protocol(session)
        elif kind == b'Q':
            try:
                header = pull_quic_header(Buffer(data=payload), host_cid_length=8)
                if self.role == 'host' and header.packet_type == QuicPacketType.INITIAL and (session.protocol is None or header.destination_cid not in session.protocol.connection_ids):
                    if session.protocol:
                        session.stop('상대 재연결')
                    self.make_protocol(session, header.destination_cid)
                if session.protocol:
                    session.protocol.datagram_received(payload, addr)
            except (ValueError, AssertionError):
                return

    async def tick(self):
        while not self.closed:
            now = time.monotonic()
            for tid, (_, deadline) in list(self.stun_pending.items()):
                if now >= deadline:
                    self.stun_pending.pop(tid)
                    self.stun_failures += 1
                    self.active_stun = None
                    self.next_stun = now + (10 if self.stun_failures >= 4 else 0)
                    if self.stun_failures >= 4 and self.public is None:
                        self.status = 'stun_failed'
            if self.servers and not self.stun_pending and now >= self.next_stun:
                target = self.active_stun or self.servers[self.stun_index % len(self.servers)]
                self.stun_index += 1
                tid = secrets.token_bytes(12)
                self.stun_pending[tid] = (target, now + 2)
                self.transport.sendto(struct.pack('!HHI12s', 1, 0, COOKIE, tid), target)
                self.next_stun = now + 20
            for session in list(self.sessions.values()):
                if session.state in ('punching', 'handshaking') and now - session.started > self.timeout:
                    session.stop('직접 연결 시간 초과 · 코드 교환, NAT 또는 방화벽을 확인하세요.')
                    session.state = 'failed'
                    self.log(f"{session.code['name']} · 직접 연결 실패 (릴레이 전환 없음)")
                if session.state in ('punching', 'handshaking', 'connected') and now >= session.next_probe:
                    nonce = secrets.token_bytes(16)
                    session.challenges[nonce] = now
                    session.challenges = {k: v for k, v in session.challenges.items() if now - v < 20}
                    session.send(b'P', nonce)
                    session.next_probe = now + (8 if session.state == 'connected' else .5)
                    if session.protocol and session.state == 'connected':
                        session.protocol._quic.send_ping(session.tx)
                        session.protocol.transmit()
            await asyncio.sleep(.05)

    async def serve_game(self, session, reader, writer):
        tcp_writer = None
        protocol = session.protocol
        try:
            if await asyncio.wait_for(reader.readexactly(4), 8) != b'MC1\n':
                raise ConnectionError('잘못된 게임 스트림')
            try:
                tcp_reader, tcp_writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.game_port), 5)
            except (OSError, asyncio.TimeoutError):
                writer.write(b'\x00')
                self.log(f'LAN 서버 :{self.game_port}에 연결할 수 없습니다. 게임에서 LAN 열기를 확인하세요.')
                return
            writer.write(b'\x01')
            await bridge(tcp_reader, tcp_writer, reader, writer, session)
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError) as error:
            self.log(f'게임 연결 종료: {error}')
        finally:
            session.streams -= 1
            writer.close()
            protocol.forget_stream(writer)
            if tcp_writer:
                tcp_writer.close()
                try:
                    await tcp_writer.wait_closed()
                except OSError:
                    pass

    async def accept_game(self, reader, writer):
        session = next((s for s in self.sessions.values() if s.state == 'connected'), None)
        if not session or session.streams >= MAX_STREAMS:
            writer.close()
            return
        session.streams += 1
        task = asyncio.current_task()
        session.tasks.add(task)
        qr = qw = None
        protocol = session.protocol
        try:
            qr, qw = await protocol.create_stream()
            qw.write(b'MC1\n')
            if await asyncio.wait_for(qr.readexactly(1), 10) != b'\x01':
                raise ConnectionError('호스트의 LAN 서버가 열려 있지 않습니다.')
            await bridge(reader, writer, qr, qw, session)
        except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.TimeoutError) as error:
            self.log(f'게임 연결 종료: {error}')
        finally:
            session.streams -= 1
            session.tasks.discard(task)
            if qw:
                qw.close()
                protocol.forget_stream(qw)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def snapshot(self):
        return {'role': self.role, 'name': self.name, 'status': self.status, 'code': self.code,
                'public': f'{self.public[0]}:{self.public[1]}' if self.public else None,
                'udp_port': self.transport.get_extra_info('sockname')[1],
                'game_port': self.game_port, 'listen_port': self.listen_port, 'local_test': self.local,
                'max_peers': self.max_peers,
                'peers': [{'id': s.sid.hex(), 'name': s.code['name'], 'state': s.state,
                           'error': s.error, 'rtt': round(s.rtt, 1) if s.rtt is not None else None,
                           'streams': s.streams, 'uploaded': s.uploaded, 'downloaded': s.downloaded}
                          for s in self.sessions.values()], 'events': list(self.events)}

    async def close(self):
        if self.closed:
            return
        for session in self.sessions.values():
            session.stop()
        self.closed = True
        if self.tick_task:
            self.tick_task.cancel()
            await asyncio.gather(self.tick_task, return_exceptions=True)
        tasks = [task for s in self.sessions.values() for task in s.tasks]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()
        if self.transport:
            self.transport.close()
