"""Capture the installed CortexIDE renderer through its local CDP endpoint.

Run only against the separate --remote-debugging-port=9222 instance.
This script reads renderer state and screenshots; it never sends a chat prompt.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
SELECTORS = {
    "workbench": ".monaco-workbench",
    "titleBar": ".part.titlebar",
    "activityBar": ".part.activitybar",
    "primarySidebar": ".part.sidebar",
    "editor": ".part.editor",
    "secondarySidebar": ".part.auxiliarybar",
    "panel": ".part.panel",
    "statusBar": ".part.statusbar",
    "explorerHeader": ".part.sidebar .pane-header",
    "explorerRow": ".part.sidebar .monaco-list-row",
    "chatPane": ".part.auxiliarybar .pane-body",
    "chatComposer": ".cortex-composer-shell, .void-input:has(textarea)",
    "chatInput": ".part.auxiliarybar textarea",
    "chatToolHeader": ".cortex-tool-header",
    "editorTab": ".part.editor .tab",
    "statusItem": ".part.statusbar .statusbar-item",
}

STYLE_KEYS = [
    "minWidth", "maxWidth", "minHeight", "maxHeight", "padding", "margin", "gap",
    "fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "color",
    "backgroundColor", "border", "borderColor", "borderRadius", "boxShadow",
    "opacity", "display", "overflow", "scrollbarWidth", "cursor",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Screenshot basename, without .png")
    parser.add_argument("--no-shot", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = browser.contexts[0].pages[0]
        result = page.evaluate(
            """({selectors, keys}) => {
                const get = selector => {
                    const node = document.querySelector(selector);
                    if (!node) return null;
                    const rect = node.getBoundingClientRect();
                    const style = getComputedStyle(node);
                    const out = {
                        rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                        scrollWidth: node.scrollWidth, scrollHeight: node.scrollHeight,
                        text: (node.textContent || '').trim().slice(0, 160),
                    };
                    for (const key of keys) out[key] = style[key];
                    return out;
                };
                const items = Object.fromEntries(Object.entries(selectors).map(([key, selector]) => [key, get(selector)]));
                const rootStyle = getComputedStyle(document.querySelector('.monaco-workbench'));
                const vars = {};
                for (const key of ['--vscode-editor-background', '--vscode-sideBar-background', '--vscode-sideBar-foreground', '--vscode-sideBar-border', '--vscode-activityBar-background', '--vscode-activityBar-foreground', '--vscode-panel-background', '--vscode-statusBar-background', '--vscode-tab-activeBackground', '--vscode-tab-inactiveBackground', '--vscode-focusBorder', '--vscode-list-hoverBackground']) {
                    vars[key] = rootStyle.getPropertyValue(key).trim();
                }
                const composer = document.querySelector('.cortex-composer-shell, .void-input:has(textarea)');
                if (composer) {
                    const s = getComputedStyle(composer);
                    for (const key of ['--cortex-surface-1', '--cortex-surface-2', '--cortex-surface-3', '--cortex-text-base', '--cortex-text-muted', '--cortex-brand', '--cortex-border-weak', '--cortex-border-base', '--void-bg-1', '--void-bg-2']) vars[key] = s.getPropertyValue(key).trim();
                }
                return { viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio}, title: document.title, items, vars };
            }""",
            {"selectors": SELECTORS, "keys": STYLE_KEYS},
        )
        (ROOT / f"{args.name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        if not args.no_shot:
            page.screenshot(path=str(ROOT / f"{args.name}.png"), scale="css", animations="disabled")
        print(json.dumps({"name": args.name, "viewport": result["viewport"], "found": [k for k, v in result["items"].items() if v]}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
