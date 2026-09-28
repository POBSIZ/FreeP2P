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
    </style><main><header>FreeP2P / GUIDE · 설명용 도식</header>''' + f'<h1>{e(title)}</h1><div class="subtitle">{e(subtitle)}</div><div class="grid">{blocks}</div><footer>{e(footer)}</footer></main>')
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
            node['peers'] = [{'id':'demo','name':'친구 (예시)','state':'connected','error':'','rtt':30,'streams':1,'uploaded':1048576,'downloaded':1048576}]
            await expect(page.locator('.badge.connected')).to_be_visible()
            await page.screenshot(path=str(OUT/'overview.png'), full_page=True)
            node['role'] = 'guest'
            node['name'] = '참가자 (예시)'
            await expect(page.locator('#count-title')).to_have_text('호스트 연결')
            await page.locator('.stats').screenshot(path=str(OUT/'guest-connected.png'))
            await page.locator('#quit-app').click()
            await page.locator('#quit-dialog').screenshot(path=str(OUT/'quit.png'))
            # Fresh document: the app's restrictive CSP must not affect diagrams.
            page = await browser.new_page(viewport={'width':1280,'height':1000})
            await diagram(page,'download.png','다운로드 후 실행하기','Releases → Assets에서 내 PC에 맞는 ZIP을 선택하세요.',[
                ('Windows x64','ZIP 전체 압축 해제 → FreeP2P 폴더. _internal 폴더도 함께 보관하세요.','FreeP2P.exe 실행'),
                ('Mac M 시리즈','darwin-arm64 ZIP 압축 해제. 앱을 응용 프로그램 폴더로 옮겨도 됩니다.','FreeP2P.app 실행'),
                ('브라우저에서 조작','Python 설치 없이 웹 화면이 열립니다. 화면을 닫았다면 앱을 다시 실행하세요.','내 월드 열기 / 친구 월드 참가')], 'Source code ZIP은 실행용 배포본이 아닙니다. Intel Mac용은 제공하지 않습니다.')
            await diagram(page,'minecraft-lan.png','호스트: 게임에서 LAN 포트 확인','Minecraft Java Edition 메뉴 경로를 설명하는 도식입니다. 실제 게임 캡처가 아닙니다.',[
                ('월드에 들어가기','싱글플레이 월드에 들어간 뒤 Esc를 누릅니다.','LAN 서버 열기'),
                ('LAN 월드 시작','표시되는 포트를 확인합니다. 버전에 따라 포트를 직접 지정할 수도 있습니다.','예시 포트: 51234'),
                ('FreeP2P에 입력','게임이 표시한 실제 숫자를 호스트 시작 화면에 입력합니다.','게임에서 표시된 LAN 포트')], '51234는 예시입니다. 게임의 LAN 포트와 FreeP2P의 UDP 포트는 서로 다릅니다.')
            await diagram(page,'minecraft-join.png','참가자: 게임의 직접 연결로 입장','Minecraft Java Edition 메뉴 경로를 설명하는 도식입니다. 실제 게임 캡처가 아닙니다.',[
                ('연결 상태 확인','호스트가 내 참가 코드를 등록해야 합니다. FreeP2P에서 연결됨을 기다리세요.','게임 접속 주소 복사'),
                ('멀티플레이','Minecraft Java의 멀티플레이 화면에서 직접 연결을 선택합니다.','직접 연결'),
                ('로컬 주소 붙여넣기','FreeP2P 참가자 화면의 주소를 사용합니다. 호스트 IP나 fpm1 코드를 넣지 않습니다.','127.0.0.1:25565 → 서버 참여')], '25565는 참가자 포트의 기본값입니다. 바꿨다면 앱이 표시하는 주소를 사용하세요. LAN 목록 자동 검색은 지원하지 않습니다.')
            await diagram(page,'windows-warning.png','Windows: SmartScreen 확인','공식 안내에 따른 설명용 도식입니다. 실제 경고창 캡처가 아니며 OS에 따라 문구가 다릅니다.',[
                ('출처 확인','이 저장소의 Releases에서 받은 FreeP2P인지 먼저 확인합니다.','파일 이름 / SHA-256 확인'),
                ('Windows의 PC 보호','미서명 앱 경고에서 추가 정보를 누르면 앱 이름과 게시자를 확인할 수 있습니다.','추가 정보 (More info)'),
                ('실행 여부 결정','출처를 신뢰하고 경고를 이해한 경우에만 실행 버튼을 선택합니다.','실행 (Run anyway)')], '실행 버튼이 없으면 정책 또는 Smart App Control 차단일 수 있습니다. Defender·SmartScreen 전체를 끄거나 악성코드 탐지를 무시하지 마세요.')
            await diagram(page,'mac-warning.png','Mac: 확인되지 않은 개발자의 앱 열기','공식 안내에 따른 설명용 도식입니다. 실제 설정창 캡처가 아니며 OS에 따라 문구가 다릅니다.',[
                ('앱 실행 시도','Releases에서 받은 FreeP2P.app을 먼저 열어 봅니다. 차단되면 설정으로 이동합니다.','시스템 설정'),
                ('앱별 허용 확인','개인정보 보호 및 보안 아래쪽에서 FreeP2P의 차단 안내를 찾습니다.','그래도 열기 / Open Anyway'),
                ('출처 확인 후 승인','앱 이름을 확인하고 시스템이 요구하는 확인 및 인증 절차를 진행합니다.','FreeP2P 다시 열기')], '출처가 확실할 때만 진행하세요. “컴퓨터를 손상시킵니다”·악성코드 탐지·손상된 앱 경고를 이 절차로 무시하지 마세요. Gatekeeper를 전체 해제하지 않습니다.')
            await browser.close()
    finally:
        await runner.cleanup()
    print('Created guide images using synthetic data only:', OUT)

if __name__ == '__main__':
    asyncio.run(main())
