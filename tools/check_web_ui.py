"""Optional browser QA: pip install playwright && playwright install chromium."""
import asyncio
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright, expect
from minecraft_web import create_app


def unused_tcp_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def set_details(page, selector, opened):
    details = page.locator(selector)
    if await details.evaluate('(el) => el.open') != opened:
        await details.locator('summary').click()
    assert await details.evaluate('(el) => el.open') == opened


async def assert_no_overflow(page, label):
    assert await page.evaluate(
        'document.documentElement.scrollWidth <= window.innerWidth'
    ), f'{label}: horizontal overflow'


async def invalid_folded_setting(page, details, field, submit):
    """Native form validation must reveal the field before trying to focus it."""
    await set_details(page, details, True)
    await page.locator(field).fill('0')
    await set_details(page, details, False)
    await page.locator(submit).click()
    try:
        await expect(page.locator(field)).to_be_visible()
    except AssertionError as error:
        error.add_note(str(await page.evaluate("""() => ({
            invalid: [...document.querySelectorAll(':invalid')].map(el => ({id: el.id, value: el.value, disabled: el.disabled})),
            active: document.activeElement.id,
            details: [...document.querySelectorAll('details')].map(el => ({id: el.id, open: el.open}))
        })""")))
        raise
    await expect(page.locator(field)).to_be_focused()
    assert not await page.locator(field).evaluate('(el) => el.validity.valid')


async def stop_session(page):
    await page.locator('#stop-button').click()
    await page.locator('#confirm-stop').click()
    await expect(page.locator('#setup')).to_be_visible()
    assert not await page.evaluate(
        "document.activeElement.closest('#workspace') !== null"
    ), 'focus remained inside the hidden session'


async def main():
    output = Path(__file__).resolve().parents[1] / 'test_runs' / 'web-ui'
    output.mkdir(parents=True, exist_ok=True)
    runners = []
    game_server = None
    errors = []
    try:
        async def accept_game(reader, writer):
            writer.close()
            await writer.wait_closed()

        game_server = await asyncio.start_server(accept_game, '127.0.0.1', 0)
        game_port = game_server.sockets[0].getsockname()[1]
        for port in (18765, 18766):
            runner = web.AppRunner(create_app('ui-test', local=True))
            await runner.setup()
            await web.TCPSite(runner, '127.0.0.1', port).start()
            runners.append(runner)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            host = await browser.new_page(viewport={'width': 1440, 'height': 1050})
            guest = await browser.new_page(viewport={'width': 1280, 'height': 1000})
            for page in (host, guest):
                page.on('pageerror', lambda error: errors.append(error.stack or str(error)))

            await host.goto('http://127.0.0.1:18765/#ui-test')
            assert not errors, errors
            await expect(host.locator('#start-button')).to_be_visible()
            await host.locator('.skip-link').focus()
            await host.keyboard.press('Enter')
            await expect(host.locator('#main')).to_be_focused()
            assert await host.evaluate('location.hash') == ''
            await host.reload()
            await expect(host.locator('#start-button')).to_be_visible()
            assert await host.evaluate("sessionStorage.getItem('freep2p-token')") == 'ui-test'
            await expect(host.locator('#port')).to_have_value('')
            await host.locator('#start-button').click()
            await expect(host.locator('#setup')).to_be_visible()
            await expect(host.locator('#port')).to_be_focused()
            await host.screenshot(path=str(output / 'setup-desktop.png'), full_page=True)
            await host.locator('#name').fill('우리들의 생존 월드')
            await host.locator('#port').fill(str(game_port))
            await host.locator('#choose-guest').click()
            await expect(host.locator('#host-code')).to_be_visible()
            await expect(host.locator('#listen-port')).to_have_value('25565')
            await host.locator('#choose-host').click()
            await expect(host.locator('#port')).to_be_visible()
            await expect(host.locator('#name')).to_have_value('우리들의 생존 월드')
            await expect(host.locator('#port')).to_have_value(str(game_port))
            await invalid_folded_setting(host, '#host-options', '#max-peers', '#start-button')
            await host.locator('#max-peers').fill('32')
            await set_details(host, '#host-options', False)
            await host.locator('#start-button').click()
            await expect(host.locator('#workspace')).to_be_visible()
            await expect(host.locator('#own-code')).to_have_value(re.compile(r'^fpm1:'))
            host_code = await host.locator('#own-code').input_value()
            await expect(host.locator('#max-peers-tag')).to_have_text('최대 32명')
            await expect(host.locator('#next-title')).not_to_be_empty()
            await expect(host.locator('#next-description')).not_to_be_empty()
            await host.locator('#check-game').click()
            await expect(host.locator('#game-check-result')).to_be_visible()
            await expect(host.locator('#game-check-result')).not_to_be_empty()
            await host.locator('#guest-code').fill('invalid')
            await host.locator('#add-button').click()
            await expect(host.locator('#add-error')).to_be_visible()

            await guest.goto('http://127.0.0.1:18766/#ui-test')
            await guest.locator('#choose-guest').click()
            await guest.locator('#name').fill('친구 민수')
            await guest.locator('#host-code').fill(host_code)
            await invalid_folded_setting(guest, '#guest-options', '#listen-port', '#start-button')
            first_guest_port = unused_tcp_port()
            await guest.locator('#listen-port').fill(str(first_guest_port))
            await set_details(guest, '#guest-options', False)
            await guest.locator('#start-button').click()
            await expect(guest.locator('#workspace')).to_be_visible()
            await expect(guest.locator('#own-code')).to_have_value(re.compile(r'^fpm1:'))
            guest_code = await guest.locator('#own-code').input_value()
            await host.locator('#guest-code').fill(guest_code)
            await host.locator('#add-button').click()
            await expect(host.locator('.badge.connected')).to_be_visible(timeout=15000)
            await expect(guest.locator('.badge.connected')).to_be_visible(timeout=15000)
            await expect(guest.locator('#game-address')).to_have_value(f'127.0.0.1:{first_guest_port}')
            await expect(guest.locator('#copy-address')).to_be_enabled()

            await set_details(host, '#live-options', True)
            await host.locator('#live-max-peers').fill('48')
            await host.locator('#save-limit').click()
            await expect(host.locator('#max-peers-tag')).to_have_text('최대 48명')
            await set_details(host, '#live-options', False)
            await expect(host.locator('.badge.connected')).to_have_count(1)

            # Clipboard denial must leave a selected address that can be copied manually.
            await guest.evaluate("""() => {
                Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
                    writeText: () => Promise.reject(new DOMException('Clipboard denied', 'NotAllowedError'))
                }});
            }""")
            await guest.locator('#copy-address').click()
            await expect(guest.locator('#game-address')).to_be_focused()
            assert await guest.locator('#game-address').evaluate(
                '(el) => el.selectionStart === 0 && el.selectionEnd === el.value.length'
            ), 'clipboard fallback did not select the full address'

            # Force changing telemetry while a participant button has keyboard focus.
            changed = asyncio.Event()
            poll_count = 0

            async def changing_telemetry(route):
                nonlocal poll_count
                response = await route.fetch()
                data = await response.json()
                poll_count += 1
                for peer in data['node']['peers']:
                    peer['rtt'] = poll_count
                    peer['uploaded'] += poll_count * 1024
                await route.fulfill(response=response, json=data)
                if poll_count >= 3:
                    changed.set()

            await host.route('**/api/state', changing_telemetry)
            remove = host.locator('.peer-actions button:visible').last
            await remove.focus()
            await asyncio.wait_for(changed.wait(), timeout=8)
            await expect(remove).to_be_focused()
            await host.unroute('**/api/state', changing_telemetry)
            await expect(guest.locator('.peer-actions button:visible')).to_have_count(0)

            # A failed peer must offer recovery instead of repeating the exchange step.
            async def failed_peer(route):
                response = await route.fetch()
                data = await response.json()
                for peer in data['node']['peers']:
                    peer['state'] = 'failed'
                    peer['error'] = '연결 시간을 초과했습니다.'
                await route.fulfill(response=response, json=data)

            await guest.route('**/api/state', failed_peer)
            await expect(guest.locator('.badge.failed')).to_be_visible(timeout=5000)
            await expect(guest.locator('#node-state')).not_to_have_text('코드 교환 대기')
            await expect(guest.locator('.peer-actions button:visible')).to_have_count(1)
            await expect(guest.locator('#next-description')).not_to_be_empty()
            await guest.unroute('**/api/state', failed_peer)
            await expect(guest.locator('.badge.connected')).to_be_visible(timeout=5000)

            async def disconnected_app(route):
                await route.abort('connectionrefused')

            await host.route('**/api/state', disconnected_app)
            await expect(host.locator('#app-connection')).to_be_visible(timeout=5000)
            await expect(host.locator('#refresh-connection')).to_be_visible()
            await host.unroute('**/api/state', disconnected_app)
            await expect(host.locator('#app-connection')).to_be_hidden(timeout=6000)
            await expect(host.locator('.badge.connected')).to_be_visible()

            await host.screenshot(path=str(output / 'host-connected.png'), full_page=True)
            await guest.screenshot(path=str(output / 'guest-connected.png'), full_page=True)
            for width in (390, 320):
                for page, label in ((host, 'host'), (guest, 'guest')):
                    await page.set_viewport_size({'width': width, 'height': 844})
                    await assert_no_overflow(page, f'{label} {width}px')
                    await page.screenshot(path=str(output / f'{label}-mobile-{width}.png'), full_page=True)
                    await page.locator('#stop-button').click()
                    await expect(page.locator('#stop-dialog')).to_be_visible()
                    await assert_no_overflow(page, f'{label} stop dialog {width}px')
                    await page.keyboard.press('Escape')
                    await expect(page.locator('#stop-dialog')).to_be_hidden()
                    await expect(page.locator('#stop-button')).to_be_focused()

            await remove.click()
            await expect(host.locator('#remove-dialog')).to_be_visible()
            await assert_no_overflow(host, 'remove dialog 320px')
            await host.locator('#cancel-remove').click()
            await expect(host.locator('.badge.connected')).to_have_count(1)
            await expect(remove).to_be_focused()
            await remove.click()
            await host.locator('#confirm-remove').click()
            await expect(host.locator('.peer-row')).to_have_count(0)
            await expect(host.locator('#remove-dialog')).to_be_hidden()

            # Re-enter as a guest with a new port: all guidance must use the new address.
            await stop_session(guest)
            await guest.locator('#choose-guest').click()
            await guest.locator('#host-code').fill(host_code)
            await set_details(guest, '#guest-options', True)
            second_guest_port = unused_tcp_port()
            while second_guest_port == first_guest_port:
                second_guest_port = unused_tcp_port()
            await guest.locator('#listen-port').fill(str(second_guest_port))
            await guest.locator('#start-button').click()
            await expect(guest.locator('#workspace')).to_be_visible()
            await expect(guest.locator('#own-code')).not_to_have_value(guest_code)
            await expect(guest.locator('#own-code')).to_have_value(re.compile(r'^fpm1:'))
            await host.locator('#guest-code').fill(await guest.locator('#own-code').input_value())
            await host.locator('#add-button').click()
            await expect(guest.locator('.badge.connected')).to_be_visible(timeout=15000)
            await expect(guest.locator('#game-address')).to_have_value(f'127.0.0.1:{second_guest_port}')
            await expect(guest.locator('#guide-steps')).to_contain_text(str(second_guest_port))
            await expect(guest.locator('#guide-steps')).not_to_contain_text(str(first_guest_port))
            await stop_session(guest)
            await stop_session(host)
            await host.locator('#quit-app').click()
            await assert_no_overflow(host, 'quit dialog 320px')
            await host.locator('#cancel-quit').click()
            await expect(host.locator('#quit-app')).to_be_focused()
            await expect(host.locator('#setup')).to_be_visible()
            await host.locator('#quit-app').click()
            await host.locator('#confirm-quit').click()
            await expect(host.get_by_text('FreeP2P가 종료되었습니다.', exact=True)).to_be_visible()
            assert not errors, errors
            print('PASS: native validation, folded settings, code exchange, connection recovery, '
                  'clipboard fallback, keyboard focus, mobile dialogs, session restart, app exit')
            print(output)
            await browser.close()
    except BaseException:
        if errors:
            print('Browser errors:', errors, flush=True)
        raise
    finally:
        for runner in runners:
            await runner.cleanup()
        if game_server:
            game_server.close()
            await game_server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
