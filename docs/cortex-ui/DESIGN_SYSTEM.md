# CortexIDE UI/UX design system

## Scope

This is a static source audit of `../cortexide-reference`, not a visual or runtime acceptance test. It extracts design rules for PLC-Agent; it does not prescribe a code port. Some source identifiers still say `void`. The requested `voidSettingsPane.ts` is named `cortexideSettingsPane.ts` in this snapshot ([registration](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/cortexide.contribution.ts#L29)).

## Core rules

1. **Spatial ownership:** activity rail switches views; primary sidebar discovers files; center edits/inspects; auxiliary bar hosts the agent; lower panel shows supporting output; status bar carries global state. The grid manages these separately ([layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L1598), [sidebarPane.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/sidebarPane.ts#L105)).
2. **Theme boundary:** native editor, explorer, tabs and status use `--vscode-*`. CortexIDE defines `--cortex-*` for custom surfaces and aliases many as `--void-*`; chat's auxiliary bar then remaps most `--void-*` colors to current sidebar theme colors. Its declared dark palette is not necessarily the rendered chat palette ([cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L6), [auxiliary override](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L300)).
3. **Compact workbench, prominent input:** 22px explorer rows, 32px pane/chat header, 36px chat tabs; subdued small labels around a large rounded composer. Elevation and large radius are reserved for inputs/cards, not every row ([explorerviewlet.css](../../../cortexide-reference/src/vs/workbench/contrib/files/browser/media/explorerviewlet.css#L19), [ComposerTabs.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chrome/ComposerTabs.tsx#L24), [styles.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/styles.css#L411)).
4. **State is local and legible:** active items combine surface, border and text; tool verbs change with proposed/running/done; generation pairs a label with motion and a stop control; failures provide recovery ([ComposerTabs.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chrome/ComposerTabs.tsx#L38), [ToolRenderers.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/tools/ToolRenderers.tsx#L102), [ChatMessageList.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/ChatMessageList.tsx#L112)).
5. **Keyboard first:** selection-to-chat, new chat, send/newline/cancel and visible keyboard focus are built into the interaction model ([sidebarActions.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/sidebarActions.ts#L90), [SidebarChat.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/SidebarChat.tsx#L207), [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L365)).

## Visual grammar

| Element | Extracted rule | Evidence |
| --- | --- | --- |
| Surfaces | Steps for base, alternate, input/card, elevated and menu; chat also inherits active host theme. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L20) |
| Text | Strong, body, muted, subtle hierarchy; semantic success/warning/danger. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L33) |
| Borders | Weak hairline divisions, base control border, strong/focus border. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L48) |
| Shape | Small radius for dense tool rows/dropdowns, larger radius for cards/composer, circular send/stop. | [styles.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/styles.css#L376) |
| Motion | Short hover/focus transitions; loading and streaming animation only during activity. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L97), [styles.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/styles.css#L150) |
| Icons | Native workbench icons plus Lucide in React; icon buttons get labels or accessible names. | [sidebarPane.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/sidebarPane.ts#L120), [ThreadHeader.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chrome/ThreadHeader.tsx#L6) |

## PLC-Agent adaptation

Use the layout and interaction grammar while keeping PLC-Agent's data and safety model authoritative. Source context, agent/tool activity, and real Runtime observations need distinct states. Compilation success cannot be displayed as behavioral verification. Prefer a compact semantic token layer over reproducing CortexIDE's mixed `--cortex-*`, `--void-*`, Tailwind and `--vscode-*` implementation. See [LAYOUT.md](LAYOUT.md), [COMPONENTS.md](COMPONENTS.md), [INTERACTIONS.md](INTERACTIONS.md), and [TOKENS.md](TOKENS.md).
