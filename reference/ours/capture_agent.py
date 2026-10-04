"""Capture real read-only PLC Agent event states from the local Web IDE."""

import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent / "agent-real"
ROOT.mkdir(exist_ok=True)
report = {}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page.goto("http://127.0.0.1:5173/", wait_until="domcontentloaded")
    page.wait_for_function("document.querySelector('.statusbar')?.textContent?.includes('AGENT READY')", timeout=30000)
    prompt = (
        "Read examples/motor_start_stop.st and find the declaration of Motor. "
        "Do not edit files, run shell commands, compile, start a PLC, or force variables."
    )
    page.locator(".agent-compose textarea").fill(prompt)
    page.locator(".composer-send").click()
    try:
        page.locator(".agent-working").wait_for(timeout=15000)
        page.screenshot(path=str(ROOT / "06-agent-running.png"), animations="disabled")
        report["runningCaptured"] = True
        print("running captured", flush=True)
    except PlaywrightTimeoutError:
        report["runningCaptured"] = False
    try:
        tool = page.locator(".tool-card").first
        tool.wait_for(timeout=120000)
        page.screenshot(path=str(ROOT / "07-tool-call-collapsed.png"), animations="disabled")
        report["toolCollapsedCaptured"] = True
        print("tool collapsed captured", flush=True)
        tool.locator("summary").click()
        assert tool.get_attribute("open") is not None
        page.screenshot(path=str(ROOT / "08-tool-call-expanded.png"), animations="disabled")
        report["toolExpandedCaptured"] = True
    except PlaywrightTimeoutError:
        report["toolCollapsedCaptured"] = False
        report["toolExpandedCaptured"] = False
    page.wait_for_timeout(500)
    report["agentText"] = page.locator(".agent-stream").inner_text()[:2000]
    page.screenshot(path=str(ROOT / "09-last-state.png"), animations="disabled")
    browser.close()

(ROOT / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, ensure_ascii=True), flush=True)
