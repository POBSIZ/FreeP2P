#!/usr/bin/env python3
"""Loopback-only web control panel for the Minecraft tunnel."""
import argparse
import asyncio
import hmac
import secrets
import webbrowser
from types import SimpleNamespace
from pathlib import Path

from aiohttp import web

from mc_tunnel import TunnelNode, decode_code

STATIC = Path(__file__).with_name('web')
CONTROL = web.AppKey('control', SimpleNamespace)


def create_app(token=None, *, local=False):
    app = web.Application(client_max_size=8192)
    control = SimpleNamespace(token=token or secrets.token_urlsafe(32), node=None, lock=asyncio.Lock(), shutdown=asyncio.Event())
    app[CONTROL] = control

    @web.middleware
    async def protect(request, handler):
        # Host checks also prevent DNS rebinding into this loopback control service.
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            raise web.HTTPForbidden(text='Local access only')
        origin = request.headers.get('Origin')
        if origin and origin != f'http://{request.host}':
            raise web.HTTPForbidden(text='Invalid origin')
        if request.path.startswith('/api/'):
            supplied = request.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied.encode(), ('Bearer ' + control.token).encode()):
                raise web.HTTPUnauthorized(text='Launch URL required')
        try:
            response = await handler(request)
        except (ValueError, KeyError, TypeError) as error:
            response = web.json_response({'error': str(error) or '입력값을 확인하세요.'}, status=400)
        except OSError as error:
            response = web.json_response({'error': f'포트를 열 수 없습니다. 다른 프로그램의 사용 여부를 확인하세요. ({error})'}, status=400)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    app.middlewares.append(protect)

    async def state(request):
        node = control.node
        return web.json_response({'node': node.snapshot() if node else None, 'local_test': local})

    async def start(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('올바른 설정 객체가 필요합니다.')
        async with control.lock:
            if control.node is not None:
                return web.json_response({'error': '현재 세션을 종료한 뒤 새로 시작하세요.'}, status=409)
            role = data.get('role')
            code = data.get('host_code', '').strip()
            if role == 'guest':
                if decode_code(code)['role'] != 'host':
                    raise ValueError('호스트 코드를 입력하세요.')
            node = TunnelNode(role, data.get('name', ''), data.get('game_port', 25565),
                              data.get('listen_port', 25565), local=local,
                              max_peers=data.get('max_peers', 16))
            try:
                await node.start()
                if role == 'guest':
                    node.add_peer(code)
            except BaseException:
                await node.close()
                raise
            control.node = node
            return web.json_response({'ok': True})

    async def stop(request):
        async with control.lock:
            if control.node:
                await control.node.close()
                control.node = None
        return web.json_response({'ok': True})

    async def peer_action(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('올바른 참가자 설정이 필요합니다.')
        async with control.lock:
            node = control.node
            if not node:
                raise ValueError('먼저 호스트 또는 참가 세션을 시작하세요.')
            action = data.get('action')
            if action == 'add':
                if node.role != 'host':
                    raise ValueError('호스트만 참가자를 등록할 수 있습니다.')
                node.add_peer(data.get('code', ''))
            elif action == 'retry':
                node.retry_peer(data['id'])
            elif action == 'remove':
                node.remove_peer(data['id'])
            else:
                raise ValueError('지원하지 않는 동작입니다.')
        return web.json_response({'ok': True})

    async def settings(request):
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('올바른 설정 객체가 필요합니다.')
        async with control.lock:
            node = control.node
            if not node or node.role != 'host':
                raise ValueError('호스트 세션에서만 최대 인원을 변경할 수 있습니다.')
            node.set_max_peers(data.get('max_peers'))
            node.log(f'최대 참가자 수를 {node.max_peers}명으로 변경했습니다.')
        return web.json_response({'ok': True})

    async def check_game(request):
        node = control.node
        if not node or node.role != 'host':
            raise ValueError('호스트를 먼저 시작하세요.')
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', node.game_port), 3)
            writer.close()
            await writer.wait_closed()
            return web.json_response({'ok': True, 'message': 'LAN 포트가 응답합니다. 게임 프로토콜까지 검증한 것은 아닙니다.'})
        except (OSError, asyncio.TimeoutError):
            return web.json_response({'ok': False, 'message': 'LAN 서버에 연결할 수 없습니다. LAN 열기와 포트를 확인하세요.'})

    async def asset(request):
        name = request.match_info.get('name', 'index.html')
        if name not in ('index.html', 'app.js', 'style.css'):
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name)

    async def cleanup(app):
        if control.node:
            await control.node.close()

    async def shutdown(request):
        asyncio.get_running_loop().call_later(0.2, control.shutdown.set)
        return web.json_response({'ok': True})

    app.router.add_post('/api/shutdown', shutdown)
    app.router.add_get('/', asset)
    app.router.add_get('/{name:app.js|style.css}', asset)
    app.router.add_get('/api/state', state)
    app.router.add_post('/api/start', start)
    app.router.add_post('/api/stop', stop)
    app.router.add_post('/api/peers', peer_action)
    app.router.add_post('/api/settings', settings)
    app.router.add_post('/api/check-game', check_game)
    app.on_cleanup.append(cleanup)
    return app


async def run(args):
    app = create_app(local=args.local)
    control = app[CONTROL]
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', args.port)
    try:
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        url = f'http://127.0.0.1:{port}/#' + control.token
        if getattr(args, 'on_ready', None):
            args.on_ready(url)
        print('\nFreeP2P Minecraft · 로컬 제어 화면\n' + url + '\n종료: Ctrl+C\n', flush=True)
        if not args.no_browser:
            await asyncio.to_thread(webbrowser.open, url)
        await control.shutdown.wait()
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description='Minecraft Java LAN · FreeP2P 웹 제어')
    parser.add_argument('--port', type=int, default=8765, help='로컬 웹 UI 포트')
    parser.add_argument('--no-browser', action='store_true', help='브라우저 자동 열기 생략')
    parser.add_argument('--local', action='store_true', help='STUN 없는 루프백 테스트 모드')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('포트는 1~65535여야 합니다.')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except OSError as error:
        print(f'실행 실패: {error}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
