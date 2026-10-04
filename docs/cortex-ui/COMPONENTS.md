# CortexIDE component inventory

## Navigation and workspace

| Component | Structure and states | Evidence |
| --- | --- | --- |
| Activity rail | Icon-led view switching; active foreground/border; compact icon/rail option. | [activitybarPart.ts](../../../cortexide-reference/src/vs/workbench/browser/parts/activitybar/activitybarPart.ts#L48), [theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L389) |
| File explorer | 22px tree rows, twisties, file icons, clipped names, inline rename, faded cut/missing rows and highlighted drop target. It is native workbench UI, not React chat. | [explorerviewlet.css](../../../cortexide-reference/src/vs/workbench/contrib/files/browser/media/explorerviewlet.css#L19), [explorerView.ts](../../../cortexide-reference/src/vs/workbench/contrib/files/browser/views/explorerView.ts#L997) |
| Editor tabs | Theme-driven active/inactive/selected/unfocused states, scroll or wrap, hidden tab-strip scrollbar, distinct dirty marker. | [multieditortabscontrol.css](../../../cortexide-reference/src/vs/workbench/browser/parts/editor/media/multieditortabscontrol.css#L76), [theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L31) |
| Settings editor | Center editor tab; responsive vertical section navigation beside content, capped at 900px overall. | [cortexideSettingsPane.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/cortexideSettingsPane.ts#L62), [Settings.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/settings/Settings.tsx#L1758) |
| Empty editor | Workbench watermark with contextual open-folder/settings buttons rather than fake content. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L230) |

## Chat and composer

| Component | Structure and states | Evidence |
| --- | --- | --- |
| Chat shell | React root in auxiliary pane; tabs, header and body stacked; independent error boundaries. | [Sidebar.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/Sidebar.tsx#L14), [SidebarChat.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/SidebarChat.tsx#L307) |
| Thread tabs | At most 12 visible, max 160px each, truncated label, active bordered surface, spinner when running, hover close action, new-chat plus. | [ComposerTabs.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chrome/ComposerTabs.tsx#L11) |
| Thread header | Truncated title, history toggle, new chat and settings actions; minimum 32px. | [ThreadHeader.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chrome/ThreadHeader.tsx#L24) |
| Landing page | Logo/title, composer, context chips, quick actions, then suggested prompts or previous chats. | [LandingPage.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/landing/LandingPage.tsx#L37) |
| Message list | Scrolling timeline for prior messages, streamed response, tool output, loading and errors. | [ChatMessageList.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/ChatMessageList.tsx#L90) |
| User message | Compact rounded surface with edit action and explicit edit/close mode. | [UserMessageComponent.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chat/UserMessageComponent.tsx#L207) |
| Composer | Rounded shell with multiline input, image/PDF and selected-context chips, upload, send/stop, mode/model/thinking row. Thread variant adds changed-file command bar and context usage. | [VoidChatArea.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/VoidChatArea.tsx#L380), [ComposerInputSection.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/ComposerInputSection.tsx#L21) |
| Context meter | Tiny label plus 3px track; warning over 80%, danger at 100%; `progressbar` semantics. | [ContextUsageBar.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/ContextUsageBar.tsx#L17) |

## Tool calls and result cards

A tool call is usually a **compact expandable row**. The header has a chevron, verb/title, truncated target, and optional count, info, error or canceled indicator. Minimum header height is 24px. Click or Enter/Space expands a body; the chevron rotates and the body animates. Code/results remain selectable and scroll inside the available width ([ToolHeader.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/tools/ToolHeader.tsx#L59), [ToolPrimitives.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/tools/ToolPrimitives.tsx#L8)).

The renderer uses human verbs for proposed/running/done, such as *Read file / Reading file*, *Edited file / Editing file*, and *Ran terminal / Running terminal*. File, search, lint, command and MCP results reuse the frame but supply different bodies. Error and canceled states are separate ([ToolRenderers.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/tools/ToolRenderers.tsx#L102), [ToolHeader.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/tools/ToolHeader.tsx#L125)).

Large plan/task cards coexist with these dense rows and put progress/status badges in their headers. The plan card distinguishes running, failed, paused, skipped and done ([ChatBubble.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chat/ChatBubble.tsx#L198)).

## Bottom areas

The workbench lower panel has its own title/border theme tokens. The global status bar holds compact model, latency, privacy and free-tier entries. The composer has a separate local toolbar and context meter. Keep global health, local conversation state and tool progress distinct ([theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L480), [cortexideStatusBar.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/cortexideStatusBar.ts#L44), [VoidChatArea.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/VoidChatArea.tsx#L485)).
