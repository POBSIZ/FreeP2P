import asyncio
import os
import socket
import unittest

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from mc_tunnel import TunnelNode, decode_code
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
        from freep2p import encode
        from mc_tunnel import b64
        host, guest, other = await self.node('host'), await self.node('guest'), await self.node('host')
        code = decode_code(host.code)
        code['cert'] = decode_code(other.code)['cert']
        session = guest.add_peer('fpm1:' + b64(encode(code)))
        host.add_peer(guest.code)
        await wait_for(lambda: session.state == 'failed', 5)
        self.assertNotEqual(session.state, 'connected')

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
                    self.assertTrue(state['node']['code'].startswith('fpm1:'))
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
