"""Exercise two packaged apps, with Python removed from their PATH."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile

import aiohttp


async def check(executable):
    processes, clients = [], []
    env = os.environ.copy()
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    env['PATH'] = str(Path(env.get('SystemRoot', 'C:/Windows')) / 'System32') if os.name == 'nt' else '/usr/bin:/bin'
    with tempfile.TemporaryDirectory(prefix='freep2p-package-') as temp:
        async with aiohttp.ClientSession() as http:
            async def launch(name):
                directory = Path(temp) / name
                process = subprocess.Popen([executable, '--no-browser', '--local', '--data-dir', str(directory)], cwd=temp, env=env)
                processes.append(process)
                for _ in range(200):
                    assert process.poll() is None, f'{name} exited: {process.returncode}'
                    try:
                        url = json.loads((directory / 'instance.json').read_text())['url']
                        base, token = url.split('/#')
                        client = (base, {'Authorization': 'Bearer ' + token})
                        clients.append(client)
                        return client, directory
                    except (OSError, ValueError, KeyError):
                        await asyncio.sleep(0.1)
                raise AssertionError('Application did not start')

            async def api(client, path, data=None):
                base, headers = client
                async with http.request('GET' if data is None else 'POST', base + '/api/' + path, headers=headers, json=data) as response:
                    body = await response.json()
                    assert response.status == 200, body
                    return body

            async def echo(reader, writer):
                try:
                    while chunk := await reader.read(65536):
                        writer.write(chunk)
                        await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            server = await asyncio.start_server(echo, '127.0.0.1', 0)
            game_port = server.sockets[0].getsockname()[1]
            try:
                host, hostdir = await launch('host')
                guest, _ = await launch('guest')
                for asset in ('/', '/app.js', '/style.css'):
                    async with http.get(host[0] + asset) as response:
                        assert response.status == 200 and len(await response.read()) > 100
                async with http.post(host[0] + '/api/shutdown', json={}) as response:
                    assert response.status == 401
                duplicate = subprocess.Popen([executable, '--no-browser', '--data-dir', str(hostdir)], cwd=temp, env=env)
                assert await asyncio.to_thread(duplicate.wait, 15) == 0
                await api(host, 'start', {'role': 'host', 'name': 'Packaged host', 'game_port': game_port, 'max_peers': 32})
                hoststate = (await api(host, 'state'))['node']
                # Reserve an available local TCP port, then hand it to the guest.
                probe = await asyncio.start_server(echo, '127.0.0.1', 0)
                guest_port = probe.sockets[0].getsockname()[1]
                probe.close()
                await probe.wait_closed()
                await api(guest, 'start', {'role': 'guest', 'name': 'Packaged guest', 'listen_port': guest_port, 'host_code': hoststate['code']})
                gueststate = (await api(guest, 'state'))['node']
                await api(host, 'peers', {'action': 'add', 'code': gueststate['code']})
                for _ in range(100):
                    state = (await api(guest, 'state'))['node']
                    if state['peers'] and state['peers'][0]['state'] == 'connected':
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError('Packaged QUIC peers did not connect')
                reader, writer = await asyncio.open_connection('127.0.0.1', guest_port)
                payload = os.urandom(524288)
                writer.write(payload)
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(len(payload)), 20) == payload
                writer.write_eof()
                assert await asyncio.wait_for(reader.read(), 10) == b''
                writer.close()
                await writer.wait_closed()
                await api(host, 'settings', {'max_peers': 48})
                assert (await api(host, 'state'))['node']['max_peers'] == 48
                print('PASS: assets, authentication, single instance, QUIC/TCP 512 KiB echo, peer limit')
            finally:
                for client in clients:
                    try:
                        await api(client, 'shutdown', {})
                    except Exception:
                        pass
                for process in processes:
                    try:
                        assert await asyncio.to_thread(process.wait, 10) == 0
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise AssertionError('Packaged app did not exit')
                server.close()
                await server.wait_closed()
            assert not (hostdir / 'instance.json').exists()
            print('PASS: clean shutdown and state cleanup')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable')
    args = parser.parse_args()
    asyncio.run(check(str(Path(args.executable).resolve())))
