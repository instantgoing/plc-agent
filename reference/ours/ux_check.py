"""Exercise the implemented workbench without starting PLC or agent actions."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


report = {}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
    page.wait_for_function("document.querySelector('.statusbar')?.textContent?.includes('MCP READY')", timeout=20000)

    assert not page.locator(".bottom-dock").is_visible()
    page.keyboard.press("Control+Shift+m")
    assert page.locator(".bottom-dock").is_visible()
    assert page.locator(".dock-tabs button.active").inner_text().startswith("PROBLEMS")
    before = page.locator(".bottom-dock").bounding_box()["height"]
    splitter = page.locator(".panel-splitter-dock").bounding_box()
    page.mouse.move(splitter["x"] + 200, splitter["y"] + 2)
    page.mouse.down()
    page.mouse.move(splitter["x"] + 200, splitter["y"] - 44, steps=5)
    page.mouse.up()
    after = page.locator(".bottom-dock").bounding_box()["height"]
    assert after > before + 25, (before, after)
    report["panelResizePx"] = [before, after]
    page.keyboard.press("Control+j")
    assert not page.locator(".bottom-dock").is_visible()

    width_before = page.locator(".sidebar").bounding_box()["width"]
    sidebar_splitter = page.locator(".panel-splitter-sidebar").bounding_box()
    page.mouse.move(sidebar_splitter["x"] + 2, 400)
    page.mouse.down()
    page.mouse.move(sidebar_splitter["x"] + 52, 400, steps=5)
    page.mouse.up()
    width_after = page.locator(".sidebar").bounding_box()["width"]
    assert width_after > width_before + 25, (width_before, width_after)
    report["sidebarResizePx"] = [width_before, width_after]
    page.keyboard.press("Control+b")
    assert not page.locator(".sidebar").is_visible()
    page.keyboard.press("Control+b")
    assert page.locator(".sidebar").is_visible()

    page.locator(".file-explorer summary").filter(has_text="examples").first.click()
    first = page.locator(".tree-file").filter(has_text="motor_start_stop.st").first
    first.click()
    page.locator(".tab.active").wait_for()
    page.locator(".tree-file").filter(has_text="minimal.st").first.click()
    report["tabLabels"] = page.locator(".tab").all_inner_texts()
    assert page.locator(".tab").count() == 2, report["tabLabels"]
    tab = page.locator(".tab[aria-selected=true]")
    report["tabCount"] = page.locator(".tab").count()

    first.click(button="right")
    report["fileContextMenuVisible"] = page.locator(".file-menu").is_visible()
    assert report["fileContextMenuVisible"]
    page.keyboard.press("Escape")

    composer = page.locator(".agent-compose textarea")
    composer.fill("line one")
    composer.press("Shift+Enter")
    composer.type("line two")
    assert composer.input_value() == "line one\nline two"
    report["multilineInput"] = True
    composer.fill("")
    assert page.locator(".composer-send").is_disabled()
    report["emptySendDisabled"] = True

    page.keyboard.press("Control+l")
    assert composer.evaluate("n => document.activeElement === n")
    report["focusShortcut"] = True

    page.keyboard.press("Control+Shift+p")
    palette = page.get_by_role("dialog", name="Command palette")
    assert palette.is_visible()
    page.get_by_role("textbox", name="Type a command").fill("Show PLC Project")
    page.keyboard.press("Enter")
    assert not palette.is_visible()
    assert page.locator(".side-head").inner_text().startswith("PLC PROJECT")
    report["commandPalette"] = True

    browser.close()

Path(__file__).with_name("ux-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
