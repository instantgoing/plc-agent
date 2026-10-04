# CortexIDE interaction measurements

## Captured on the installed 1.106 renderer

| State or action | Result | Evidence |
| --- | --- | --- |
| Explorer folder click | `examples` expands inline; each row remains 22px high. | `02-sidebar.png`, `02-sidebar.json` |
| Open ST file | An editor tab of 35px opens above a Monaco editor and breadcrumb row. The file was only read. | `03-editor.png`, `03-editor.json` |
| Composer focus and typing | Input is multiline and grows; the shell is 16px radius with 10px padding. | `05-agent-typing.png`, `13-focus.png`, `05-agent-typing.json` |
| `Ctrl+Shift+M` | Problems opens as a 300px bottom panel under the editor, leaving the Chat sidebar full height. | `09-bottom-panel.png`, `09-bottom-panel.json` |
| `Ctrl+B` | Primary sidebar is hidden; editor begins after the 48px activity rail. | `10-sidebar-collapsed.png`, `10-sidebar-collapsed.json` |
| Drag sidebar sash from x=347 to x=390 | Sidebar width changes from 300px to 343px; editor contracts. | `16-resized.png` |
| Explorer row hover | Native list hover state. | `12-hover.png` |
| `Ctrl+Shift+P` | Native command palette opens over the editor. | `14-command-palette.png` |
| File menu click | Native menu opens from the top title bar. | `15-menu.png` |
| Submit a read-only prompt with no configured model | The renderer shows a real no-model error. No running/tool-result state is available from this isolated profile. | `11-no-model-error.png`, `11-no-model-error.json` |

The isolated process used `--remote-debugging-port=9222` and its own user data directory. The prompt requested only a summary of `examples/motor_start_stop.st`; no file edit was requested. Screenshots are CSS-pixel 1440×900. The original installed build is 1.106.00200; the source checkout is 1.118.1.

## Source 1.118 interaction contract

- `layout.ts` owns a resizable grid. Sidebar and auxiliary bar minimum widths are 170px; panel minimum height is 77px and minimum width is 300px (`sidebarPart.ts`, `auxiliaryBarPart.ts`, `panelPart.ts`).
- `ComposerTabs.tsx` switches and closes chat tabs, shows a spinner for `LLM`, `tool`, and `preparing`, and offers a new-thread button. Each tab is at most 160px wide; the strip has a 36px minimum height.
- `ThreadHeader.tsx` toggles bounded history, creates a thread, and opens settings. Its minimum height is 32px.
- `VoidChatArea.tsx` places input and send/stop controls above a mode/model row. `inputs.tsx` caps textarea height at 500px, inserts a newline with Shift+Enter, and handles an `@` context picker.
- `ToolHeader.tsx` renders a header at least 24px high, toggles expanded content by click or Enter/Space, and rotates a 16px chevron. `ToolRenderers.tsx` provides bodies for read, edit, search, command, and MCP tools.
- `cortexide.css` declares 6px vertical and 4px horizontal chat scrollbars; workbench list and editor scrollbars use native VS Code rules.

## Uncaptured golden states

`06-agent-running.png`, `07-tool-call-collapsed.png`, and `08-tool-call-expanded.png` are intentionally absent. This isolated installed build has no configured model and therefore cannot produce real tool events. Inventing those screenshots would violate the golden-master requirement. The source gives their structure and state logic, but cannot establish exact rendered pixels for the newer build.
