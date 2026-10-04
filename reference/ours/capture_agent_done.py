"""Replay the completed local event stream and capture actual tool results."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


root = Path(__file__).resolve().parent / "agent-real"
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
    page.wait_for_function("document.querySelectorAll('.tool-card').length >= 1 && !document.querySelector('.agent-working')", timeout=30000)
    page.wait_for_timeout(500)
    tools = page.locator(".tool-card")
    names = [tools.nth(i).locator("summary").inner_text() for i in range(tools.count())]
    page.screenshot(path=str(root / "10-completed-tool-collapsed.png"), animations="disabled")
    tools.first.locator("summary").click()
    assert tools.first.get_attribute("open") is not None
    page.screenshot(path=str(root / "11-completed-tool-expanded.png"), animations="disabled")
    report = {"toolCount": tools.count(), "toolNames": names, "completed": True}
    (root / "completed-results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    browser.close()
