#!/usr/bin/env python3
"""FreeP2P: one UDP socket, public STUN, manual signaling, no relay."""
from __future__ import annotations

import argparse
import base64
import codecs
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import select
import shutil
import socket
import struct
import sys
import time
import unicodedata
from collections import deque

COOKIE = 0x2112A442
DEFAULT_STUN = ['stun.cloudflare.com:3478', 'stun.l.google.com:19302']


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def parse_stun(data, transaction):
    if len(data) < 20:
        return None
    kind, length, cookie, tid = struct.unpack('!HHI12s', data[:20])
    end = 20 + length
    if (kind, cookie, tid) != (0x101, COOKIE, transaction) or end > len(data) or length % 4:
        return None
    pos = 20
    while pos + 4 <= end:
        attr, size = struct.unpack_from('!HH', data, pos)
        start = pos + 4
        if start + size > end:
            return None
        value = data[start:start + size]
        pos = start + ((size + 3) & ~3)
        if attr == 0x20 and size == 8 and value[1] == 1:
            port = struct.unpack('!H', value[2:4])[0] ^ (COOKIE >> 16)
            address = struct.unpack('!I', value[4:])[0] ^ COOKIE
            if port:
                return socket.inet_ntoa(struct.pack('!I', address)), port
    return None


def invitation(endpoint, token):
    return 'fp1:' + base64.urlsafe_b64encode(encode([*endpoint, token])).decode().rstrip('=')


def parse_invitation(code):
    try:
        if not code.startswith('fp1:') or len(code) > 512:
            raise ValueError()
        raw = code[4:]
        host, port, token = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4), altchars=b'-_', validate=True))
        ipaddress.IPv4Address(host)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError()
        if not isinstance(token, str) or len(token) != 32 or len(bytes.fromhex(token)) != 16:
            raise ValueError()
        return (host, port), token
    except (ValueError, TypeError, KeyError):
        raise ValueError('fp1:로 시작하는 연결 코드 전체를 입력하세요.') from None


class Peer:
    def __init__(self, bind='0.0.0.0', port=0, servers=None, timeout=45, local=False):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((bind, port))
        except OSError:
            self.sock.close()
            raise
        self.sock.setblocking(False)
        self.token = secrets.token_hex(16)
        self.timeout = timeout
        self.events = deque(maxlen=200)
        self.state = 'DISCOVERING'
        self.public = None
        self.target = self.key = None
        self.sent = 0
        self.highest = 0
        self.seen = set()
        self.pending = {}
        self.challenges = {}
        self.stun_pending = {}
        self.servers = []
        self.stun_index = 0
        self.next_stun = 0
        self.next_probe = 0
        self.started = self.last_rx = 0
        self.rtt = None
        self.stun_failures = 0
        self.active_stun = None
        if local:
            if bind == '0.0.0.0':
                self.sock.close()
                raise ValueError('--local은 --bind에 실제 LAN IP 또는 127.0.0.1을 지정해야 합니다.')
            self.public = (bind, self.sock.getsockname()[1])
            self.state = 'WAITING'
            self.note('로컬 테스트 모드 · STUN과 NAT 통과 여부는 검증하지 않습니다.')
        else:
            for server in servers or DEFAULT_STUN:
                try:
                    host, server_port = server.rsplit(':', 1)
                    self.servers.append((socket.gethostbyname(host), int(server_port)))
                except (OSError, ValueError):
                    self.note(f'STUN 주소 확인 실패: {server}')
            if not self.servers:
                self.state = 'STUN_FAILED'
        self.note('명령: /connect 코드 · /copy · /retry · /quit')

    def close(self):
        self.sock.close()

    def note(self, message):
        self.events.append((time.strftime('%H:%M:%S'), message))

    @property
    def code(self):
        return invitation(self.public, self.token) if self.public else ''

    def connect(self, code):
        endpoint, token = parse_invitation(code.strip())
        if token == self.token:
            raise ValueError('자신의 연결 코드입니다.')
        if self.pending:
            self.note(f'상대 변경으로 미확인 메시지 {len(self.pending)}개 취소')
        self.target = endpoint
        self.key = hashlib.sha256(b'freep2p-v1' + b''.join(sorted([bytes.fromhex(token), bytes.fromhex(self.token)]))).digest()
        self.highest = 0
        self.seen.clear()
        self.pending.clear()
        self.retry()

    def retry(self):
        if not self.target:
            raise ValueError('상대 연결 코드를 먼저 입력하세요.')
        self.state = 'PUNCHING'
        self.started = time.monotonic()
        self.next_probe = 0
        self.challenges.clear()
        self.note('홀 펀칭 중 · 상대도 내 코드를 입력해야 합니다.')

    def send(self, kind, body, seq=None):
        if not self.target:
            return None
        if seq is None:
            self.sent += 1
            seq = self.sent
        packet = {'v': 1, 'n': seq, 't': kind, 'd': body}
        mac = hmac.new(self.key, encode(packet), hashlib.sha256).hexdigest()
        try:
            self.sock.sendto(encode({'b': packet, 'm': mac}), self.target)
        except OSError as error:
            self.note(f'UDP 송신 오류: {error}')
        return seq

    def chat(self, message):
        if self.state != 'CONNECTED':
            raise ValueError('연결된 후 메시지를 보낼 수 있습니다.')
        if not message or len(message.encode()) > 800:
            raise ValueError('메시지는 UTF-8 기준 1~800바이트여야 합니다.')
        if len(self.pending) >= 32:
            raise ValueError('미확인 메시지가 많습니다. 잠시 후 다시 시도하세요.')
        seq = self.send('chat', message)
        self.pending[seq] = [message, time.monotonic(), 1]
        self.note(f'나 #{seq} › {message}')

    def receive(self, data, source, now):
        if len(data) >= 20:
            tid = data[8:20]
            pending = self.stun_pending.get(tid)
            if pending and source == pending[0]:
                result = parse_stun(data, tid)
                if result:
                    del self.stun_pending[tid]
                    self.active_stun = source
                    self.stun_failures = 0
                    self.next_stun = now + 20
                    if result != self.public:
                        self.note('외부 주소 후보 확인' if self.public is None else '외부 주소 변경 · 새 코드를 다시 공유하세요.')
                        self.public = result
                    if self.state in ('DISCOVERING', 'STUN_FAILED'):
                        self.state = 'WAITING'
                    return
        if not self.key or self.state not in ('PUNCHING', 'CONNECTED'):
            return
        try:
            packet = json.loads(data)
            body, mac = packet['b'], packet['m']
            expected = hmac.new(self.key, encode(body), hashlib.sha256).hexdigest()
            if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
                return
            seq, kind, value = body['n'], body['t'], body['d']
            if body['v'] != 1 or type(seq) is not int or seq <= 0 or not isinstance(value, str):
                return
            if kind not in ('probe', 'pong', 'chat', 'receipt') or len(value.encode()) > 800:
                return
        except (ValueError, TypeError, KeyError, RecursionError):
            return
        if seq <= self.highest - 512:
            return
        if kind in ('chat', 'receipt') and self.state != 'CONNECTED':
            return
        duplicate = seq in self.seen
        if duplicate:
            # ACK repeated chats, but display them only once.
            if kind == 'chat' and source == self.target and self.state == 'CONNECTED':
                self.send('receipt', str(seq))
            return
        self.highest = max(self.highest, seq)
        self.seen.add(seq)
        self.seen = {n for n in self.seen if n > self.highest - 512}
        self.target = source  # Only authenticated packets can change the endpoint.
        if kind == 'probe':
            self.send('pong', value)
        elif kind == 'pong' and value in self.challenges:
            self.rtt = (now - self.challenges.pop(value)) * 1000
            self.last_rx = now
            if self.state != 'CONNECTED':
                self.state = 'CONNECTED'
                self.note(f'직접 연결 성공 · {source[0]}:{source[1]}')
        elif kind == 'chat' and self.state == 'CONNECTED':
            self.send('receipt', str(seq))
            self.note(f'상대 › {value}')
        elif kind == 'receipt' and value.isdecimal() and len(value) < 20:
            if self.pending.pop(int(value), None):
                self.note(f'전달 확인 #{value}')

    def tick(self):
        now = time.monotonic()
        for _ in range(64):
            try:
                data, source = self.sock.recvfrom(4096)
            except BlockingIOError:
                break
            except OSError:
                break
            self.receive(data, source, now)
        for tid, (_, deadline) in list(self.stun_pending.items()):
            if now >= deadline:
                del self.stun_pending[tid]
                self.stun_failures += 1
                if self.stun_failures >= 4 and self.public is None and self.state == 'DISCOVERING':
                    self.state = 'STUN_FAILED'
                    self.note('STUN 응답 없음 · UDP 차단/네트워크 확인. 주기적으로 재시도합니다.')
                self.next_stun = min(self.next_stun, now + (15 if self.stun_failures >= 4 else 0))
        if self.servers and now >= self.next_stun and not self.stun_pending:
            target = self.active_stun or self.servers[self.stun_index % len(self.servers)]
            self.stun_index += 1
            tid = secrets.token_bytes(12)
            try:
                self.sock.sendto(struct.pack('!HHI12s', 1, 0, COOKIE, tid), target)
                self.stun_pending[tid] = (target, now + 2)
            except OSError:
                pass
            self.next_stun = now + 20
            if self.stun_failures >= 2:
                self.active_stun = None
        if self.state == 'PUNCHING' and now - self.started >= self.timeout:
            self.state = 'FAILED'
            self.note('직접 연결 시간 초과 · 상대 실행/주소/NAT/방화벽 확인 후 /retry')
        if self.state == 'CONNECTED' and now - self.last_rx >= 35:
            self.state = 'DISCONNECTED'
            self.note('상대 응답 끊김 · /retry로 재연결')
        if self.state in ('PUNCHING', 'CONNECTED') and now >= self.next_probe:
            self.next_probe = now + (0.5 if self.state == 'PUNCHING' else 10)
            challenge = secrets.token_hex(12)
            self.challenges[challenge] = now
            self.challenges = {k: v for k, v in self.challenges.items() if now - v < 30}
            self.send('probe', challenge)
        for seq, item in list(self.pending.items()):
            if now - item[1] >= 1:
                if item[2] >= 5 or self.state != 'CONNECTED':
                    del self.pending[seq]
                    self.note(f'전달 미확인 #{seq} · 수신됐으나 ACK가 유실됐을 수도 있습니다.')
                else:
                    self.send('chat', item[0], seq)
                    item[1], item[2] = now, item[2] + 1


def safe(text):
    return ''.join(c for c in str(text) if c.isprintable() and unicodedata.category(c) != 'Cf')


def cell_width(char):
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1


def wrap(text, width):
    rows, row, used = [], '', 0
    for char in safe(text):
        size = cell_width(char)
        if used + size > width:
            rows.append(row)
            row, used = '', 0
        row += char
        used += size
    return rows + [row]


class Terminal:
    def __enter__(self):
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.old = None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.windll.kernel32
            self.kernel.GetStdHandle.restype = wintypes.HANDLE
            self.kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            self.kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.handle = self.kernel.GetStdHandle(-11)
            mode = wintypes.DWORD()
            if self.kernel.GetConsoleMode(self.handle, ctypes.byref(mode)):
                self.old = mode.value
                self.kernel.SetConsoleMode(self.handle, mode.value | 4)
        else:
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write('\033[?1049h\033[?2004h')
        sys.stdout.flush()
        return self

    def __exit__(self, *_):
        sys.stdout.write('\033[?2004l\033[?1049l')
        sys.stdout.flush()
        if os.name == 'nt':
            if self.old is not None:
                self.kernel.SetConsoleMode(self.handle, self.old)
        else:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)

    def read(self):
        if os.name == 'nt':
            import msvcrt
            chars = []
            while msvcrt.kbhit() and len(chars) < 4096:
                value = msvcrt.getwch()
                if value in ('\x00', '\xe0'):
                    msvcrt.getwch()
                else:
                    chars.append(value)
            return ''.join(chars)
        if select.select([sys.stdin], [], [], 0)[0]:
            return self.decoder.decode(os.read(sys.stdin.fileno(), 4096))
        return ''


class UI:
    def __init__(self, peer):
        self.peer = peer
        self.buffer = ''
        self.escape = ''
        self.pasting = False
        self.previous = None

    def submit(self):
        text, self.buffer = self.buffer.strip(), ''
        if text == '/quit':
            return False
        try:
            if text == '/copy':
                if not self.peer.code:
                    raise ValueError('외부 주소 확인을 기다리세요.')
                # tkinter is optional. No shell interpolation or OSC clipboard commands.
                try:
                    import tkinter
                    root = tkinter.Tk()
                    root.withdraw()
                    root.clipboard_clear()
                    root.clipboard_append(self.peer.code)
                    root.update()
                    root.destroy()
                    self.peer.note('클립보드에 복사 요청 완료 · 붙여넣기로 확인하세요.')
                except Exception:
                    self.peer.note('클립보드 사용 불가 · 상단 코드를 직접 선택해 복사하세요.')
            elif text == '/retry':
                self.peer.retry()
            elif text.startswith('/connect ') or text.startswith('fp1:'):
                self.peer.connect(text.removeprefix('/connect ').strip())
            elif text.startswith('/'):
                self.peer.note('명령: /connect 코드 · /copy · /retry · /quit')
            elif text:
                self.peer.chat(text)
        except ValueError as error:
            self.peer.note(str(error))
        return True

    def input(self, chars):
        for char in chars:
            if self.escape:
                self.escape += char
                if len(self.escape) == 2 and char in '[O':
                    continue
                if len(self.escape) > 2 and '@' <= char <= '~':
                    if self.escape == '\x1b[200~':
                        self.pasting = True
                    elif self.escape == '\x1b[201~':
                        self.pasting = False
                    self.escape = ''
                elif len(self.escape) == 2 or len(self.escape) > 24:
                    self.escape = ''
                continue
            if char == '\x1b':
                self.escape = char
            elif char in ('\x03', '\x04'):
                return False
            elif char in ('\r', '\n'):
                if not self.pasting and not self.submit():
                    return False
            elif char in ('\b', '\x7f'):
                self.buffer = self.buffer[:-1]
            elif char == '\x15':
                self.buffer = ''
            elif char.isprintable() and len(self.buffer) < 1000:
                self.buffer += char
        return True

    def draw(self):
        width, height = shutil.get_terminal_size((96, 28))
        width = max(10, width - 1)
        peer = self.peer
        status = peer.state
        if status == 'PUNCHING':
            status += f'  {max(0, int(peer.timeout - (time.monotonic() - peer.started)))}s'
        if peer.rtt is not None and peer.state == 'CONNECTED':
            status += f'  RTT {peer.rtt:.0f}ms'
        lines = ['FREEP2P  /  DIRECT UDP', status,
                 f'로컬 UDP :{peer.sock.getsockname()[1]}  |  릴레이 없음 · 암호화 없음',
                 '내 연결 코드 · /copy 또는 직접 복사', peer.code or 'STUN 응답 대기 중…', '─' * width]
        header = [row for line in lines for row in wrap(line, width)]
        log = [row for stamp, msg in peer.events for row in wrap(f'{stamp}  {msg}', width)]
        room = max(0, height - len(header) - 3)
        visible = log[-room:] if room else []
        content = header + visible + [''] * (room - len(visible))
        content += ['─' * width, '코드 입력 / 메시지 · /retry 재시도 · /quit 종료']
        prompt = '› ' + wrap(self.buffer, max(1, width - 2))[-1]
        # Clip narrow/short terminals and clear each line without full-screen flashing.
        content = [wrap(line, width)[0] for line in content][-max(1, height - 1):]
        signature = (tuple(content), prompt, width, height)
        if signature == self.previous:
            return
        self.previous = signature
        def style(line):
            if line.startswith('FREEP2P'):
                return '\033[1;36m' + line + '\033[0m'
            if line.startswith(peer.state):
                color = '32' if peer.state == 'CONNECTED' else ('31' if peer.state in ('FAILED', 'STUN_FAILED', 'DISCONNECTED') else '33')
                return '\033[1;' + color + 'm' + line + '\033[0m'
            if line.startswith('─'):
                return '\033[2m' + line + '\033[0m'
            return line
        output = '\033[?25l\033[H' + ''.join(style(line) + '\033[K\n' for line in content)
        output += '\033[36m' + prompt + '\033[0m\033[K\033[J\033[?25h'
        sys.stdout.write(output)
        sys.stdout.flush()

    def run(self):
        with Terminal() as terminal:
            while True:
                self.peer.tick()
                if not self.input(terminal.read()):
                    break
                self.draw()
                time.sleep(0.025)


def main():
    parser = argparse.ArgumentParser(description='FreeP2P · 수동 코드 교환 방식의 UDP 홀 펀칭 채팅')
    parser.add_argument('--bind', default='0.0.0.0', help='로컬 IPv4 바인딩 주소')
    parser.add_argument('--port', type=int, default=0, help='로컬 UDP 포트 (기본: 자동)')
    parser.add_argument('--timeout', type=float, default=45, help='홀 펀칭 제한 시간, 초')
    parser.add_argument('--stun', action='append', help='STUN host:port, 여러 번 지정 가능')
    parser.add_argument('--local', action='store_true', help='STUN 없이 LAN/루프백 테스트')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or not 0 < args.timeout <= 600:
        parser.error('port: 0~65535, timeout: 0 초과 600 이하')
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('대화형 터미널에서 실행하세요.')
    peer = None
    try:
        print('FreeP2P · 네트워크 준비 중…', flush=True)
        peer = Peer(args.bind, args.port, args.stun, args.timeout, args.local)
        UI(peer).run()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        print(f'오류: {error}', file=sys.stderr)
        return 1
    finally:
        if peer:
            peer.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
