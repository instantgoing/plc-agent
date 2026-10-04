# CortexIDE component mapping, before implementation

The live capture is installed CortexIDE 1.106.00200. The sibling source checkout is 1.118.1. The live shell is the visual reference for the photographed states. Later chat details absent from the installed build are documented from the source and must not be described as measured pixels.

| Reference part | Reference source | PLC-Agent counterpart | Semantics to retain |
| --- | --- | --- | --- |
| Title and command bar | `src/vs/workbench/browser/parts/titlebar/titlebarPart.ts`, `media/titlebarpart.css` | `frontend/src/WorkbenchPanels.tsx` `TopBar` | Workspace identity, simulation and connection status |
| Activity Bar | `src/vs/workbench/browser/parts/activitybar/activitybarPart.ts`, `media/activitybarpart.css` | `WorkbenchNavigation.tsx` `ActivityRail` | Project, PLC context, diagnostics, runtime, changes, agent navigation |
| Primary Sidebar / Explorer | `src/vs/workbench/browser/parts/sidebar/sidebarPart.ts`, `src/vs/workbench/contrib/files/browser/views/explorerView.ts`, `media/explorerviewlet.css` | `FileExplorer.tsx` and PLC context branch in `App.tsx` | File operations, ST file selection, symbol discovery |
| Editor and tabs | `src/vs/workbench/browser/parts/editor/editorPart.ts`, `media/multieditortabscontrol.css` | `App.tsx` Monaco and tab strip | ST editing, dirty and external change handling, diff view |
| Secondary Sidebar / Chat | `src/vs/workbench/browser/parts/auxiliarybar/auxiliaryBarPart.ts`, `contrib/cortexide/browser/sidebarPane.ts`, `react/src/sidebar-tsx/SidebarChat.tsx` | `WorkbenchPanels.tsx` `AgentPanel` | Agent sessions, streaming messages, interruption |
| Bottom Panel | `src/vs/workbench/browser/parts/panel/panelPart.ts`, `media/panelpart.css` | `App.tsx` `bottom-dock` and `Debugger.tsx` | Diagnostics, runtime, variables, trace, watch, forced values, ladder, changes |
| Status Bar | `src/vs/workbench/browser/parts/statusbar/statusbarPart.ts`, `media/statusbarpart.css`, `contrib/cortexide/browser/cortexideStatusBar.ts` | `App.tsx` status footer | Live PLC, MCP, Agent and connection state |
| Chat thread tabs / header | `react/src/sidebar-tsx/chrome/ComposerTabs.tsx`, `ThreadHeader.tsx` | `AgentPanel` session control | Switch, resume, create, close; running session state |
| Chat timeline | `react/src/sidebar-tsx/composer/ChatMessageList.tsx`, `chat/ChatBubble.tsx`, `chat/UserMessageComponent.tsx` | `AgentPanel` + `AgentActivity.tsx` | Messages and actual tool events |
| Composer | `react/src/sidebar-tsx/composer/VoidChatArea.tsx`, `ComposerInputArea.tsx`, `ComposerInputSection.tsx` | `AgentPanel` composer | Multiline text, Enter/Shift+Enter, send/interrupt |
| Tool call row | `react/src/sidebar-tsx/tools/ToolHeader.tsx`, `ToolPrimitives.tsx`, `ToolRenderers.tsx` | `AgentActivity.tsx` `AgentEvent` | Expand real tool results, expose running/error/completed state |
| Buttons / inputs / dropdowns | `react/src/styles.css`, `react/src/util/inputs.tsx`, `contrib/cortexide/browser/media/cortexide.css` | Existing buttons, textarea, select in frontend | Preserve actual commands and disabled rules |
| Scrollbars | `contrib/cortexide/browser/media/cortexide.css`, VS Code list/scrollable elements | File tree, editor, chat, dock | Independent scroll regions |
| Split views | `src/vs/workbench/browser/layout.ts`, `src/vs/base/browser/ui/grid/grid.ts` | `App.tsx` pointer and keyboard splitters | Persisted widths, collapse, minimum bounds |

## Architecture and visual assets

- CortexIDE reuses the VS Code workbench grid, theme registry, Explorer, Monaco editor, editor tabs, Problems/Output/Terminal panel, status bar, Codicon font, and native menus. Its chat is a React tree mounted in the VS Code auxiliary bar by `sidebarPane.ts`.
- CortexIDE chat source uses Tailwind utilities and `lucide-react` icons. The workbench uses Codicons. The live workbench font computes to `"Segoe WPC", "Segoe UI", sans-serif` at 13px; the ST editor uses its configured monospace font.
- Source-specific CortexIDE palette lives in `contrib/cortexide/browser/media/cortexide.css`; source React button/composer/tool rules live in `react/src/styles.css`. Native workbench colors come from selected VS Code theme variables. The installed capture resolves shell backgrounds to near-black custom overrides, despite theme variables such as `--vscode-editor-background: #1f1f1f`.
- The root `LICENSE.txt` is MIT. Some CortexIDE React files carry explicit Apache 2.0 headers from Glass Devtools; source is being measured and mapped, not copied into PLC-Agent.

## Source and capture boundaries

- `01-main-shell.json` and `04-agent-empty.json` contain exact computed rectangles and styles for the installed version.
- `tokens.json` keeps installed values and source 1.118 values in separate objects.
- No CortexIDE artwork, logo, or name is mapped to the product UI. PLC-Agent identity and PLC specific data remain.
