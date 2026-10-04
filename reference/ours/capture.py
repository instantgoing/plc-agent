"""Capture PLC-Agent states at the same CSS viewport as CortexIDE."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent


def capture(page, folder, name):
    folder.mkdir(exist_ok=True)
    page.screenshot(path=str(folder / f"{name}.png"), animations="disabled")
    data = page.evaluate("""() => Object.fromEntries(
      ['.topbar', '.activity-rail', '.sidebar', '.editor-zone', '.agent-panel',
       '.statusbar', '.bottom-dock', '.composer-shell', '.agent-compose textarea',
       '.side-head', '.tabbar', '.editor-toolbar']
      .map(selector => {
        const element = document.querySelector(selector);
        if (!element) return [selector, null];
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return [selector, {x: rect.x, y: rect.y, width: rect.width, height: rect.height,
          display: style.display, background: style.backgroundColor, color: style.color,
          fontSize: style.fontSize, padding: style.padding, border: style.border,
          borderRadius: style.borderRadius}];
      }))""")
    (folder / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pass_name")
    args = parser.parse_args()
    folder = ROOT / args.pass_name
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('.statusbar')?.textContent?.includes('MCP READY')", timeout=20000)
        # A prior real-agent run is replayed on a new connection. Start a fresh
        # UI session so the empty-state captures match the golden references.
        page.get_by_role("button", name="New agent session").click()
        page.locator(".agent-empty").wait_for(timeout=15000)
        page.wait_for_timeout(300)
        capture(page, folder, "01-main-shell")
        page.locator(".file-explorer summary").filter(has_text="examples").first.click()
        capture(page, folder, "02-sidebar")
        page.locator(".tree-file").filter(has_text="motor_start_stop.st").first.click()
        page.locator(".tab.active").wait_for(timeout=15000)
        page.wait_for_timeout(300)
        capture(page, folder, "03-editor")
        capture(page, folder, "04-agent-empty")
        page.locator(".agent-compose textarea").fill("Inspect motor_start_stop.st and explain the start/stop interlock.")
        capture(page, folder, "05-agent-typing")
        page.locator(".agent-compose textarea").fill("")
        page.locator(".tree-file").filter(has_text="motor_start_stop.st").first.hover()
        capture(page, folder, "12-hover")
        page.locator(".agent-compose textarea").focus()
        capture(page, folder, "13-focus")
        page.keyboard.press("Control+Shift+p")
        page.get_by_role("dialog", name="Command palette").wait_for()
        capture(page, folder, "14-command-palette")
        page.keyboard.press("Escape")
        page.keyboard.press("Control+Shift+m")
        capture(page, folder, "09-bottom-panel")
        page.keyboard.press("Control+b")
        capture(page, folder, "10-sidebar-collapsed")
        print(folder)
        browser.close()


if __name__ == "__main__":
    main()
