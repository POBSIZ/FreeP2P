"""Capture the real web UI using only synthetic, non-connectable demo data.

Also render original instructional diagrams (not OS or Minecraft screenshots).
Developer dependency: playwright and its Chromium browser.
"""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright, expect
from minecraft_web import create_app

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/images'


async def diagram(page, filename, title, subtitle, cards, footer):
    from html import escape as e
    blocks = ''.join(f'<article><span class="number">{i}</span><h2>{e(h)}</h2><p>{e(p)}</p><div class="action">{e(a)}</div></article>' for i, (h, p, a) in enumerate(cards, 1))
    await page.set_content('''<!doctype html><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#0e1713;color:#eff8f0;font:20px "Malgun Gothic",sans-serif}
    main{width:1200px;padding:55px}header{color:#b9f485;letter-spacing:3px;font-size:15px}h1{font-size:38px;margin:16px 0}
    .subtitle{color:#aec2b6;font-size:19px;margin-bottom:34px}.grid{display:flex;gap:20px}article{flex:1;background:#19251f;border:1px solid #34493b;border-radius:18px;padding:26px;min-height:300px}
    .number{display:inline-grid;place-items:center;background:#b9f485;color:#122016;width:40px;height:40px;border-radius:50%;font-weight:bold}h2{font-size:24px;margin:24px 0 12px}p{line-height:1.7;font-size:18px;color:#c6d8cb}.action{margin-top:24px;padding:14px;border-radius:9px;background:#263e2b;color:#caffaa;font-weight:bold;font-size:19px}footer{margin-top:30px;font-size:17px;color:#b6c7bb;line-height:1.7}
    </style><main><header>FreeP2P · 따라 하기</header>''' + f'<h1>{e(title)}</h1><div class="subtitle">{e(subtitle)}</div><div class="grid">{blocks}</div><footer>{e(footer)}</footer></main>')
    await page.locator('main').screenshot(path=str(OUT / filename))


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runner = web.AppRunner(create_app('documentation-demo', local=True))
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    base = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
    state = {'node': None, 'local_test': False}
    async def fake_api(route):
        await route.fulfill(content_type='application/json', body=json.dumps(state if route.request.url.endswith('/state') else {'ok': True}))
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={'width':1280,'height':1000}, device_scale_factor=1)
            await page.route('**/api/**', fake_api)
            await page.goto(base + '/#documentation-demo')
            await page.locator('#start-button').wait_for()
            await page.locator('.local-pill').evaluate("el=>el.textContent='가이드 예시 · 실제 연결 정보 없음'")
            await page.locator('#name').fill('친구들과 생존 월드')
            await page.locator('#port').fill('51234')
            await page.locator('#setup .setup-card').screenshot(path=str(OUT/'host-setup.png'))
            await page.locator('#choose-guest').click()
            await page.locator('#host-code').fill('fpm1:호스트가_보낸_전체_코드 (연결 불가 예시)')
            await page.locator('#setup .setup-card').screenshot(path=str(OUT/'guest-setup.png'))
            node = {'role':'host','name':'친구들과 생존 월드','status':'ready',
                    'code':'fpm1:가이드용_예시입니다_실제_연결_불가',
                    'public':'192.0.2.10:40000','udp_port':40000,'game_port':51234,
                    'listen_port':25565,'max_peers':16,'peers':[],
                    'events':[{'time':'12:00','message':'가이드용 예시 화면입니다. 실제 연결 정보가 아닙니다.'}]}
            state['node'] = node
            await expect(page.locator('#workspace')).to_be_visible()
            await page.locator('.code-panel').screenshot(path=str(OUT/'share-code.png'))
            await page.locator('#guest-code').fill('fpm1:친구가_돌려준_전체_코드 (연결 불가 예시)')
            await page.locator('#live-max-peers').fill('32')
            await page.locator('#add-panel').screenshot(path=str(OUT/'register-peer.png'))
            await page.locator('#live-max-peers').fill('16')
            await page.locator('#guest-code').fill('')
            node['peers'] = [{'id':'demo','name':'친구 (예시)','state':'connected','error':'','rtt':30,'streams':1,'uploaded':1048576,'downloaded':1048576}]
            await expect(page.locator('.badge.connected')).to_be_visible()
            await page.screenshot(path=str(OUT/'overview.png'), full_page=True)
            node['role'] = 'guest'
            node['name'] = '참가자 (예시)'
            await expect(page.locator('#count-title')).to_have_text('호스트 연결')
            await page.locator('.code-panel').screenshot(path=str(OUT/'guest-code.png'))
            await page.locator('.stats').screenshot(path=str(OUT/'guest-connected.png'))
            await page.locator('#quit-app').click()
            await page.locator('#quit-dialog').screenshot(path=str(OUT/'quit.png'))
            # Fresh document: the app's restrictive CSP must not affect diagrams.
            page = await browser.new_page(viewport={'width':1280,'height':1000})
            await diagram(page,'download.png','받은 파일을 이렇게 열어 주세요','사용법 페이지의 Windows용 또는 Mac용 받기 링크를 누르세요.',[
                ('Windows','받은 파일을 오른쪽 클릭하고 모두 압축 풀기를 누릅니다. 풀린 FreeP2P 폴더를 엽니다.','FreeP2P.exe 두 번 클릭'),
                ('Mac M 시리즈','받은 압축 파일을 두 번 클릭합니다. 풀린 FreeP2P 앱을 엽니다.','FreeP2P 앱 열기'),
                ('화면이 열리면 준비 끝','월드를 여는 사람은 내 월드 열기, 들어갈 친구는 친구 월드 참가를 선택합니다.','두 사람 모두 실행하세요')], 'Windows의 _internal 폴더는 지우지 마세요. 다른 프로그램을 추가로 설치할 필요는 없습니다.')
            await diagram(page,'minecraft-lan.png','월드를 여는 사람이 할 일','게임에서 누를 메뉴를 설명한 그림입니다. 실제 게임 화면은 아닙니다.',[
                ('내 월드 열기','함께할 싱글플레이 월드에 들어갑니다. 키보드의 Esc를 누릅니다.','LAN 서버 열기'),
                ('번호 확인하기','LAN 월드를 시작하면 게임이 포트 번호를 알려 줍니다. 그 숫자를 기억해 두세요.','예: 51234'),
                ('숫자 옮겨 적기','FreeP2P에서 내 월드 열기를 고르고, 게임에서 알려 준 숫자를 입력합니다.','게임에서 표시된 LAN 포트')], '51234는 예시입니다. 본인 게임에 나온 숫자를 적으세요. 포트가 무엇인지 몰라도 됩니다.')
            await diagram(page,'minecraft-join.png','들어갈 친구가 할 일','게임에서 누를 메뉴를 설명한 그림입니다. 실제 게임 화면은 아닙니다.',[
                ('연결됨 기다리기','코드를 서로 주고받고 등록했다면 연결됨이 나올 때까지 기다립니다.','게임 접속 주소 복사'),
                ('게임으로 돌아가기','Minecraft에서 멀티플레이를 누른 다음 직접 연결을 선택합니다.','멀티플레이 → 직접 연결'),
                ('복사한 주소 넣기','서버 주소 칸에 방금 복사한 내용을 그대로 붙여넣고 접속합니다.','예: 127.0.0.1:25565')], '메신저로 주고받은 긴 코드를 넣는 곳이 아닙니다. 자기 FreeP2P의 게임 접속 주소 복사 버튼을 사용하세요.')
            await diagram(page,'windows-warning.png','Windows에서 실행을 막는 경고가 뜬다면','순서를 설명한 안내 그림입니다. 실제 경고창과 모양이 다를 수 있습니다.',[
                ('받은 곳 확인','사용법 페이지의 다운로드 링크에서 직접 받은 FreeP2P인지 확인하세요.','모르는 사람이 보낸 파일은 주의'),
                ('추가 정보 누르기','Windows의 PC 보호 창에서 추가 정보를 누릅니다. 앱 이름을 확인하세요.','FreeP2P.exe인지 확인'),
                ('실행 누르기','직접 받은 파일이 맞고 실행하기로 했다면 실행 버튼을 누릅니다.','실행')], '실행 버튼이 없으면 관리자에게 문의하세요. 바이러스가 발견됐다는 경고는 다른 경우이니 억지로 실행하지 마세요.')
            await diagram(page,'mac-warning.png','Mac에서 개발자를 확인할 수 없다면','순서를 설명한 안내 그림입니다. Mac 버전에 따라 문구가 다를 수 있습니다.',[
                ('앱을 한 번 열기','직접 받은 FreeP2P 앱을 열어 경고를 확인합니다. 화면 왼쪽 위 사과 메뉴를 누릅니다.','Apple → 시스템 설정'),
                ('차단 안내 찾기','개인정보 보호 및 보안에 들어가 아래로 내립니다. FreeP2P 안내를 찾으세요.','그래도 열기'),
                ('앱 이름 확인하기','FreeP2P가 맞는지 확인하세요. Mac이 암호나 지문 확인을 요청하면 진행합니다.','FreeP2P 열기')], '컴퓨터를 손상시킨다거나 앱이 손상됐다는 경고는 이 절차로 넘기지 마세요. 사용법 페이지의 경고 안내를 확인하세요.')
            await browser.close()
    finally:
        await runner.cleanup()
    print('Created guide images using synthetic data only:', OUT)

if __name__ == '__main__':
    asyncio.run(main())
