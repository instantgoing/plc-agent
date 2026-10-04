"""Capture safe interaction states from the installed CDP-enabled workbench."""

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent


def shot(page, name):
    page.screenshot(path=str(ROOT / f"{name}.png"), scale="css", animations="disabled")
    print(name)


with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]
    row = page.locator(".part.sidebar .monaco-list-row").filter(has_text="motor_start_stop.st").first
    row.hover()
    shot(page, "12-hover")
    page.locator(".part.auxiliarybar textarea").focus()
    shot(page, "13-focus")
    page.keyboard.press("Control+Shift+p")
    page.wait_for_timeout(200)
    shot(page, "14-command-palette")
    page.keyboard.press("Escape")
    page.get_by_text("File", exact=True).first.click()
    shot(page, "15-menu")
    page.keyboard.press("Escape")
    page.mouse.move(347, 400)
    page.mouse.down()
    page.mouse.move(390, 400, steps=6)
    page.mouse.up()
    page.wait_for_timeout(100)
    shot(page, "16-resized")
    print("sidebar width", page.locator(".part.sidebar").bounding_box())
    browser.close()
