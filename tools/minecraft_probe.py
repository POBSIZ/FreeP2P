"""Two-host smoke harness; synthetic TCP data, not a running Minecraft game."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mc_tunnel import TunnelNode
from tools.network_probe import read_control, save


async def echo(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def run(args):
    folder = Path(args.directory)
    folder.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    server = await asyncio.start_server(echo, '127.0.0.1', 0) if args.role == 'host' else None
    game_port = server.sockets[0].getsockname()[1] if server else 25565
    node = await TunnelNode(args.role, args.role + '-smoke', game_port=game_port, listen_port=port).start()
    result = {'pass':False,'role':args.role}
    try:
        deadline = time.monotonic() + 150
        while not node.code and time.monotonic() < deadline:
            await asyncio.sleep(.1)
        if not node.code:
            raise TimeoutError('STUN failed')
        save(folder/'ready.json', {'code':node.code})
        while time.monotonic() < deadline:
            control = read_control(folder/'peer.json')
            if control:
                session = node.add_peer(control['code'])
                break
            await asyncio.sleep(.1)
        else:
            raise TimeoutError('Peer code not received')
        while session.state not in ('connected','failed') and time.monotonic() < deadline:
            await asyncio.sleep(.1)
        if session.state != 'connected':
            raise ConnectionError(session.error or 'Connection timeout')
        if args.role == 'guest':
            async def transfer():
                reader, writer = await asyncio.open_connection('127.0.0.1', port)
                payload = os.urandom(524288)
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                received = await asyncio.wait_for(reader.readexactly(len(payload)), 40)
                assert payload == received, 'TCP payload mismatch'
                assert await asyncio.wait_for(reader.read(1), 5) == b''
                writer.close()
                await writer.wait_closed()
                return hashlib.sha256(received).hexdigest()
            result['sha256'] = await asyncio.gather(transfer(), transfer())
            result['bytes_each_direction'] = 1048576
            result['pass'] = True
        else:
            while time.monotonic() < deadline:
                if session.uploaded >= 1048576 and session.downloaded >= 1048576 and session.streams == 0:
                    result['pass'] = True
                    break
                await asyncio.sleep(.1)
        result['snapshot'] = node.snapshot()
        result['snapshot'].pop('code', None)
    except Exception as error:
        result['error'] = str(error)
        result['snapshot'] = node.snapshot()
        result['snapshot'].pop('code', None)
    finally:
        save(folder/'result.json', result)
        await node.close()
        if server:
            server.close()
            await server.wait_closed()
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', choices=['host','guest'], required=True)
    parser.add_argument('--directory', required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
