"""Optional browser QA: pip install playwright && playwright install chromium."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright, expect
from minecraft_web import create_app


async def main():
    output = Path(__file__).resolve().parents[1] / 'test_runs' / 'web-ui'
    output.mkdir(parents=True, exist_ok=True)
    runners = []
    try:
        for port in (18765, 18766):
            runner = web.AppRunner(create_app('ui-test', local=True))
            await runner.setup()
            await web.TCPSite(runner, '127.0.0.1', port).start()
            runners.append(runner)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            host = await browser.new_page(viewport={'width':1440,'height':1050}, device_scale_factor=1)
            guest = await browser.new_page(viewport={'width':1280,'height':1000})
            errors = []
            for page in (host, guest):
                page.on('pageerror', lambda error: errors.append(str(error)))
            await host.goto('http://127.0.0.1:18765/#ui-test')
            await host.locator('#start-button').wait_for()
            await host.screenshot(path=str(output/'setup-desktop.png'), full_page=True)
            await host.locator('#name').fill('우리들의 생존 월드')
            await host.locator('#max-peers').fill('32')
            await host.locator('#start-button').click()
            await host.locator('#workspace').wait_for(state='visible')
            await host.wait_for_function("document.getElementById('own-code').value.startsWith('fpm1:')")
            host_code = await host.locator('#own-code').input_value()
            assert await host.locator('#max-peers-tag').inner_text() == '최대 32명'
            await host.locator('#guest-code').fill('invalid')
            await host.locator('#add-button').click()
            await host.locator('#add-error').wait_for(state='visible')
            await guest.goto('http://127.0.0.1:18766/#ui-test')
            await guest.locator('#choose-guest').click()
            await guest.locator('#name').fill('친구 민수')
            await guest.locator('#port').fill('25575')
            await guest.locator('#host-code').fill(host_code)
            await guest.locator('#start-button').click()
            await guest.locator('#workspace').wait_for(state='visible')
            await guest.wait_for_function("document.getElementById('own-code').value.startsWith('fpm1:')")
            await host.locator('#guest-code').fill(await guest.locator('#own-code').input_value())
            await host.locator('#add-button').click()
            await host.locator('.badge.connected').wait_for(timeout=15000)
            await guest.locator('.badge.connected').wait_for(timeout=15000)
            await host.locator('#live-max-peers').fill('48')
            await host.locator('#save-limit').click()
            await expect(host.locator('#max-peers-tag')).to_have_text('최대 48명')
            assert await host.locator('.badge.connected').count() == 1
            await host.screenshot(path=str(output/'host-connected.png'), full_page=True)
            await guest.screenshot(path=str(output/'guest-connected.png'), full_page=True)
            await host.set_viewport_size({'width':390,'height':844})
            await host.screenshot(path=str(output/'host-mobile.png'), full_page=True)
            assert await host.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'mobile overflow'
            await guest.locator('#stop-button').click()
            await guest.locator('#confirm-stop').click()
            await guest.locator('#setup').wait_for(state='visible')
            await host.locator('#stop-button').click()
            await host.locator('#confirm-stop').click()
            await host.locator('#setup').wait_for(state='visible')
            await host.locator('#quit-app').click()
            await host.locator('#cancel-quit').click()
            await expect(host.locator('#setup')).to_be_visible()
            await host.locator('#quit-app').click()
            await host.locator('#confirm-quit').click()
            await expect(host.get_by_text('FreeP2P가 종료되었습니다.', exact=True)).to_be_visible()
            assert not errors, errors
            print('PASS: host/guest forms, invalid code, manual exchange, encrypted connection, stop, mobile layout, no JS errors')
            print(output)
            await browser.close()
    finally:
        for runner in runners:
            await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
