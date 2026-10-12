import asyncio
import hashlib
import hmac
import os
import socket
import time
import unittest

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from freep2p import encode
from mc_tunnel import MAGIC, TunnelNode, b64, decode_code, encode_code
from minecraft_web import create_app


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def wait_for(predicate, timeout=8):
    async def poll():
        while not predicate():
            await asyncio.sleep(.025)
    await asyncio.wait_for(poll(), timeout)


def legacy_code(node, cert=None):
    data = {'role': node.role, 'name': node.name, 'ip': node.public[0],
            'port': node.public[1], 'token': b64(node.token)}
    if node.role == 'host':
        data['cert'] = b64((cert or node.cert).public_bytes(serialization.Encoding.DER))
    return 'fpm1:' + b64(encode(data))


def encrypted_name(session, sender_role, challenge, name):
    nonce = bytes(range(12))
    key = hmac.digest(session.key, b'freep2p-name-v3/' + sender_role.encode('ascii'), 'sha256')
    encrypted = AESGCM(key).encrypt(nonce, name, b'FQN3' + session.sid + challenge)
    return challenge + nonce + encrypted


class MinecraftTunnelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.nodes = []
        self.echo = await asyncio.start_server(self.handle_echo, '127.0.0.1', 0)
        self.game_port = self.echo.sockets[0].getsockname()[1]

    async def handle_echo(self, reader, writer):
        try:
            while data := await reader.read(32768):
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def asyncTearDown(self):
        for node in reversed(self.nodes):
            await node.close()
        self.echo.close()
        await self.echo.wait_closed()
        await asyncio.sleep(.05)

    async def node(self, role):
        node = await TunnelNode(role, role + str(len(self.nodes)), game_port=self.game_port,
                                listen_port=free_port(), local=True, timeout=2).start()
        self.nodes.append(node)
        return node

    async def pair(self):
        host, guest = await self.node('host'), await self.node('guest')
        guest.add_peer(host.code)
        host.add_peer(guest.code)
        await wait_for(lambda: all(s.state == 'connected' for n in (host, guest) for s in n.sessions.values()))
        await wait_for(lambda: next(iter(host.sessions.values())).code['name'] == guest.name
                       and next(iter(guest.sessions.values())).code['name'] == host.name)
        return host, guest

    async def exchange(self, guest, payload):
        reader, writer = await asyncio.open_connection('127.0.0.1', guest.listen_port)
        async def send():
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
        sender = asyncio.create_task(send())
        try:
            result = await asyncio.wait_for(reader.readexactly(len(payload)), 20)
            self.assertEqual(result, payload)
            self.assertEqual(await asyncio.wait_for(reader.read(1), 5), b'')
            await sender
        finally:
            sender.cancel()
            writer.close()
            await writer.wait_closed()

    async def test_multi_guest_concurrent_streams_one_host_socket(self):
        host = await self.node('host')
        port = host.snapshot()['udp_port']
        guests = [await self.node('guest') for _ in range(3)]
        for guest in guests:
            guest.add_peer(host.code)
            host.add_peer(guest.code)
        await wait_for(lambda: all(s.state == 'connected' for n in self.nodes for s in n.sessions.values()))
        await asyncio.gather(*(self.exchange(guest, os.urandom(300000)) for guest in guests for _ in range(2)))
        self.assertEqual(host.snapshot()['udp_port'], port)
        self.assertEqual(len(host.sessions), 3)
        await wait_for(lambda: all(s.streams == 0 for n in self.nodes for s in n.sessions.values()))

    async def test_packet_loss_and_reordering_preserve_tcp_bytes(self):
        host, guest = await self.pair()
        for node in (host, guest):
            session = next(iter(node.sessions.values()))
            original = session.send
            def lossy(kind, payload, original=original, counter=[0]):
                counter[0] += 1
                if kind == b'Q' and counter[0] % 13 == 0:
                    return
                if kind == b'Q' and counter[0] % 7 == 0:
                    asyncio.get_running_loop().call_later(.03, original, kind, payload)
                else:
                    original(kind, payload)
            session.send = lossy
        await self.exchange(guest, os.urandom(600000))

    async def test_host_approval_is_required_and_timeout_visible(self):
        host, guest = await self.node('host'), await self.node('guest')
        session = guest.add_peer(host.code)
        await wait_for(lambda: session.state == 'failed', 4)
        self.assertFalse(host.sessions)
        self.assertIn('시간 초과', session.error)

    async def test_remove_peer_closes_only_its_session(self):
        host, first = await self.pair()
        second = await self.node('guest')
        second.add_peer(host.code)
        added = host.add_peer(second.code)
        await wait_for(lambda: added.state == 'connected')
        first_id = next(sid for sid, s in host.sessions.items() if s.code['name'] == first.name)
        host.remove_peer(first_id.hex())
        await self.exchange(second, b'other guest still works')

    async def test_wrong_host_certificate_rejected(self):
        host, guest, other = await self.node('host'), await self.node('guest'), await self.node('host')
        session = guest.add_peer(legacy_code(host, other.cert))
        host.add_peer(legacy_code(guest))
        await wait_for(lambda: session.state == 'failed', 5)
        self.assertNotEqual(session.state, 'connected')

    async def test_legacy_and_mixed_code_formats_connect(self):
        for host_version, guest_version in ((1, 1), (1, 3), (2, 2), (2, 3), (3, 2)):
            with self.subTest(host_version=host_version, guest_version=guest_version):
                host, guest = await self.node('host'), await self.node('guest')
                def code_for(node, version):
                    return (legacy_code(node) if version == 1
                            else encode_code(decode_code(legacy_code(node)), version=version))
                guest_session = guest.add_peer(code_for(host, host_version))
                host_session = host.add_peer(code_for(guest, guest_version))
                await wait_for(lambda: guest_session.state == host_session.state == 'connected')
                await wait_for(lambda: guest_session.code['name'] == host.name
                               and host_session.code['name'] == guest.name)
                await self.exchange(guest, b'compatible code exchange')

    async def test_names_arrive_before_or_after_the_certificate(self):
        for name_first in (True, False):
            with self.subTest(name_first=name_first):
                host, guest = await self.node('host'), await self.node('guest')
                host.name, guest.name = '친구의 월드 🧱', '함께 할 친구'
                guest_session = guest.add_peer(host.code)
                host_session = host.add_peer(guest.code)
                self.assertTrue(guest_session.code['name'].startswith('호스트'))
                self.assertTrue(host_session.code['name'].startswith('참가자'))
                original = host_session.send
                held = {}
                delivered = asyncio.Event()

                def deliver_second(kind, payload):
                    original(kind, payload)
                    delivered.set()

                def ordered(kind, payload):
                    if kind in (b'C', b'N') and not delivered.is_set():
                        held[kind] = payload
                        if len(held) == 2:
                            first, second = (b'N', b'C') if name_first else (b'C', b'N')
                            original(first, held[first])
                            asyncio.get_running_loop().call_later(.03, deliver_second, second, held[second])
                        return
                    original(kind, payload)

                host_session.send = ordered
                await wait_for(lambda: guest_session.state == host_session.state == 'connected')
                await asyncio.wait_for(delivered.wait(), 2)
                await wait_for(lambda: guest_session.code['name'] == host.name
                               and host_session.code['name'] == guest.name)
                await self.exchange(guest, b'names do not alter the authenticated TCP tunnel')
                host_session.send = original

    async def test_name_response_loss_and_reordering_recover(self):
        host, guest = await self.node('host'), await self.node('guest')
        host.timeout = guest.timeout = 5
        guest_session = guest.add_peer(host.code)
        host_session = host.add_peer(guest.code)
        original = host_session.send
        responses = 0
        held = None
        delayed = asyncio.Event()

        def deliver_late(payload):
            original(b'N', payload)
            delayed.set()

        def lossy(kind, payload):
            nonlocal responses, held
            if kind == b'N':
                responses += 1
                if responses == 1:
                    return
                if responses == 2:
                    held = payload
                    return
                if responses == 3:
                    original(kind, payload)
                    asyncio.get_running_loop().call_later(.03, deliver_late, held)
                    return
            original(kind, payload)

        host_session.send = lossy
        await wait_for(lambda: guest_session.state == host_session.state == 'connected', 5)
        self.assertNotEqual(guest_session.code['name'], host.name)
        await self.exchange(guest, b'game works while the name response is missing')
        # Advance the normal keepalive probes without waiting two eight-second periods.
        guest_session.next_probe = 0
        await wait_for(lambda: responses >= 2)
        guest_session.next_probe = 0
        await asyncio.wait_for(delayed.wait(), 2)
        self.assertGreaterEqual(responses, 3)
        self.assertEqual(guest_session.code['name'], host.name)
        self.assertEqual(host_session.code['name'], guest.name)
        await self.exchange(guest, b'name packet loss preserves game connection')

    async def test_unverified_or_invalid_names_do_not_change_peer_identity(self):
        host, guest = await self.node('host'), await self.node('guest')
        for node in self.nodes:
            node.tick_task.cancel()
        await asyncio.gather(*(node.tick_task for node in self.nodes), return_exceptions=True)
        nonce = bytes(range(16))
        valid_name = ('🧱' * 40).encode('utf-8')
        cases = (
            ('unknown nonce', b'Imposter', True),
            ('invalid HMAC', b'Imposter', False),
            ('invalid tag', b'Imposter', True),
            ('wrong direction key', b'Imposter', True),
            ('wrong associated challenge', b'Imposter', True),
            ('invalid UTF-8', b'\xff', True),
            ('empty name', b'', True),
            ('too many characters', b'A' * 41, True),
            ('too many UTF-8 bytes', ('🧱' * 41).encode('utf-8'), True),
            ('whitespace only', b' \t\n ', True),
        )
        for label, raw_name, valid_mac in cases:
            with self.subTest(packet=label):
                session = host.add_peer(guest.code)
                original_name = session.code['name']
                session.name_challenges[nonce] = time.monotonic()
                try:
                    challenge = b'unknown nonce!!!' if label in ('unknown nonce', 'wrong associated challenge') else nonce
                    role = 'host' if label == 'wrong direction key' else 'guest'
                    payload = encrypted_name(session, role, challenge, raw_name)
                    if label == 'invalid tag':
                        payload = payload[:-1] + bytes([payload[-1] ^ 1])
                    elif label == 'wrong associated challenge':
                        payload = nonce + payload[16:]
                    def deliver(body, sequence, authenticated=True):
                        header = MAGIC + session.sid + b'N' + sequence.to_bytes(8, 'big') + body
                        mac = hmac.digest(session.key, header, 'sha256') if authenticated else b'\0' * 32
                        host.datagram_received(header + mac, guest.public)
                    deliver(payload, 1, valid_mac)
                    self.assertEqual(session.code['name'], original_name)
                    self.assertIn(nonce, session.name_challenges)
                    self.assertEqual(session.state, 'punching')
                    self.assertIsNone(session.protocol)
                    deliver(encrypted_name(session, 'guest', nonce, valid_name), 2)
                    self.assertEqual(session.code['name'], '🧱' * 40)
                    self.assertNotIn(nonce, session.name_challenges)
                    deliver(encrypted_name(session, 'guest', nonce, b'Replayed name'), 3)
                    self.assertEqual(session.code['name'], '🧱' * 40)
                finally:
                    host.remove_peer(session.sid.hex())

    async def test_expired_name_challenge_is_rejected(self):
        host, guest = await self.node('host'), await self.node('guest')
        for node in self.nodes:
            node.tick_task.cancel()
        await asyncio.gather(*(node.tick_task for node in self.nodes), return_exceptions=True)
        session = host.add_peer(guest.code)
        original_name = session.code['name']
        nonce = bytes(range(16))
        session.name_challenges[nonce] = time.monotonic() - 21
        payload = encrypted_name(session, 'guest', nonce, b'Expired name')
        header = MAGIC + session.sid + b'N' + (1).to_bytes(8, 'big') + payload
        host.datagram_received(header + hmac.digest(session.key, header, 'sha256'), guest.public)
        self.assertEqual(session.code['name'], original_name)

    async def test_name_responses_encrypt_the_display_name_with_fresh_nonces(self):
        host, guest = await self.node('host'), await self.node('guest')
        host.name = '친구와 함께 하는 비공개 월드'
        session = host.add_peer(guest.code)
        packets = []
        session.send = lambda kind, payload: packets.append((kind, payload))
        challenge = bytes(range(16))
        session.send_name(challenge)
        session.send_name(challenge)
        self.assertEqual(len(packets), 2)
        first, second = packets[0][1], packets[1][1]
        self.assertEqual([kind for kind, _ in packets], [b'N', b'N'])
        self.assertEqual(first[:16], challenge)
        self.assertEqual(second[:16], challenge)
        self.assertNotEqual(first[16:28], second[16:28])
        key = hmac.digest(session.key, b'freep2p-name-v3/host', 'sha256')
        for payload in (first, second):
            self.assertNotIn(host.name.encode('utf-8'), payload)
            self.assertEqual(AESGCM(key).decrypt(payload[16:28], payload[28:],
                                               b'FQN3' + session.sid + challenge).decode('utf-8'), host.name)
        receiver = guest.add_peer(host.code)
        receiver.name_challenges[challenge] = time.monotonic()
        header = MAGIC + session.sid + b'N' + (1).to_bytes(8, 'big') + first
        guest.datagram_received(header + hmac.digest(session.key, header, 'sha256'), host.public)
        self.assertEqual(receiver.code['name'], host.name)
        self.assertEqual(receiver.state, 'punching')
        self.assertIsNone(receiver.peer_certificate)
        self.assertIsNone(receiver.protocol)

    async def test_initial_certificate_response_loss_and_reordering_recover(self):
        host, guest = await self.node('host'), await self.node('guest')
        host.timeout = guest.timeout = 5
        guest_session = guest.add_peer(host.code)
        host_session = host.add_peer(guest.code)
        original = host_session.send
        responses = 0
        held_response = None
        delayed = asyncio.Event()

        def deliver_late(kind, payload):
            original(kind, payload)
            delayed.set()

        def lossy(kind, payload):
            nonlocal responses, held_response
            if kind == b'C':
                responses += 1
                if responses == 1:
                    return
                if responses == 2:
                    held_response = (kind, payload)
                    return
                if responses == 3:
                    original(kind, payload)
                    asyncio.get_running_loop().call_later(.03, deliver_late, *held_response)
                    return
            original(kind, payload)

        host_session.send = lossy
        await wait_for(lambda: guest_session.state == host_session.state == 'connected', 5)
        await asyncio.wait_for(delayed.wait(), 2)
        self.assertGreaterEqual(responses, 3)
        self.assertEqual(guest_session.peer_certificate, host.cert.public_bytes(serialization.Encoding.DER))
        await self.exchange(guest, os.urandom(65536))

    async def test_unverified_certificate_packets_cannot_start_quic(self):
        host, guest, other = await self.node('host'), await self.node('guest'), await self.node('host')
        for node in self.nodes:
            node.tick_task.cancel()
        await asyncio.gather(*(node.tick_task for node in self.nodes), return_exceptions=True)
        der = host.cert.public_bytes(serialization.Encoding.DER)
        other_der = other.cert.public_bytes(serialization.Encoding.DER)
        nonce = bytes(range(16))
        cases = (
            ('unknown nonce', b'C', b'unknown nonce!!!' + der, True, None, 'punching'),
            ('wrong fingerprint', b'C', nonce + other_der, True, None, 'failed'),
            ('invalid HMAC', b'C', nonce + der, False, None, 'punching'),
            ('invalid DER', b'C', nonce + b'invalid DER', True,
             b64(hashlib.sha256(b'invalid DER').digest()), 'failed'),
            ('empty certificate', b'C', nonce, True, None, 'punching'),
            ('ACK without certificate', b'A', nonce, True, None, 'punching'),
        )
        for label, kind, payload, valid_mac, fingerprint, expected_state in cases:
            with self.subTest(packet=label):
                session = guest.add_peer(host.code)
                session.challenges[nonce] = time.monotonic()
                if fingerprint:
                    session.code['cert_sha256'] = fingerprint
                try:
                    self.assertEqual(session.state, 'punching')
                    header = MAGIC + session.sid + kind + (1).to_bytes(8, 'big') + payload
                    mac = hmac.digest(session.key, header, 'sha256') if valid_mac else b'\0' * 32
                    guest.datagram_received(header + mac, host.public)
                    self.assertEqual(session.state, expected_state)
                    self.assertIsNone(session.protocol)
                    self.assertIsNone(session.peer_certificate)
                finally:
                    guest.remove_peer(session.sid.hex())

    async def test_retry_reestablishes_compact_code_session(self):
        host, guest = await self.pair()
        guest_session = next(iter(guest.sessions.values()))
        host_session = next(iter(host.sessions.values()))
        guest.retry_peer(guest_session.sid.hex())
        await wait_for(lambda: guest_session.state == host_session.state == 'connected')
        await self.exchange(guest, b'retry retains authenticated identity')

    async def test_configurable_limit_enforced_and_change_preserves_peers(self):
        host, first, second = await self.node('host'), await self.node('guest'), await self.node('guest')
        host.set_max_peers(1)
        existing = host.add_peer(first.code)
        with self.assertRaises(ValueError):
            host.add_peer(second.code)
        host.set_max_peers(24)
        host.add_peer(second.code)
        self.assertIs(host.sessions[existing.sid], existing)
        self.assertEqual(host.snapshot()['max_peers'], 24)
        with self.assertRaises(ValueError):
            host.set_max_peers(1)
        for invalid in (0, -1, 1.5, True, '16', None):
            with self.assertRaises(ValueError):
                host.set_max_peers(invalid)
        self.assertEqual(host.max_peers, 24)

    async def test_web_auth_origin_and_local_binding(self):
        app = create_app('test-secret', local=True)
        async with TestServer(app, host='127.0.0.1') as server:
            async with ClientSession() as client:
                url = str(server.make_url('/api/state'))
                async with client.get(url) as response:
                    self.assertEqual(response.status, 401)
                auth = {'Authorization': 'Bearer test-secret'}
                async with client.get(url, headers={**auth, 'Origin': 'https://evil.example'}) as response:
                    self.assertEqual(response.status, 403)
                async with client.get(url, headers={**auth, 'Host': 'evil.example'}) as response:
                    self.assertEqual(response.status, 403)
                async with client.post(server.make_url('/api/start'), headers=auth,
                                       json={'role':'host','name':'test','game_port':self.game_port,'max_peers':32}) as response:
                    self.assertEqual(response.status, 200, await response.text())
                async with client.get(url, headers=auth) as response:
                    state = await response.json()
                    self.assertTrue(state['node']['code'].startswith('f3h:'))
                    self.assertEqual(state['node']['max_peers'], 32)
                async with client.post(server.make_url('/api/settings'), headers=auth, json={'max_peers':48}) as response:
                    self.assertEqual(response.status, 200)
                async with client.get(url, headers=auth) as response:
                    self.assertEqual((await response.json())['node']['max_peers'], 48)
                async with client.post(server.make_url('/api/settings'), headers=auth, json={'max_peers':0}) as response:
                    self.assertEqual(response.status, 400)
                async with client.post(server.make_url('/api/stop'), headers=auth, json={}) as response:
                    self.assertEqual(response.status, 200)


if __name__ == '__main__':
    unittest.main()
