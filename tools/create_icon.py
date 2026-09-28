"""Developer-only: render the vector icon and write a Windows multi-size ICO."""
import asyncio
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1024, 'height': 1024})
        await page.goto((ROOT / 'assets/icon.svg').as_uri())
        await page.screenshot(path=str(ROOT / 'assets/icon.png'), omit_background=True)
        await browser.close()
    Image.open(ROOT / 'assets/icon.png').save(ROOT / 'assets/icon.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])

if __name__ == '__main__':
    asyncio.run(main())
