# CortexIDE layout

```text
title / command area
activity rail | primary sidebar | editor groups + tabs | auxiliary chat
              |                 | optional lower panel  |
status bar
```

This is the default conceptual arrangement, not a fixed pixel template. Workbench `layout.ts` assembles title, activity bar, sidebar, editor, panel, auxiliary bar and status bar as independently managed grid views. Sidebar and activity bar can move; the panel can be horizontal or vertical ([layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L1598), [grid ordering](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L2508)).

| Region | Ownership and sizing | Evidence |
| --- | --- | --- |
| Activity rail | View switching; fixed 48px width or 36px compact, with 24px or 16px icons. | [activitybarPart.ts](../../../cortexide-reference/src/vs/workbench/browser/parts/activitybar/activitybarPart.ts#L48) |
| Primary sidebar | Native explorer/search; minimum width 170px. File rows are 22px, tree indented, icon led and ellipsized. | [sidebarPart.ts](../../../cortexide-reference/src/vs/workbench/browser/parts/sidebar/sidebarPart.ts#L44), [explorerviewlet.css](../../../cortexide-reference/src/vs/workbench/contrib/files/browser/media/explorerviewlet.css#L19) |
| Center workspace | Editor groups own file tabs, editor/diff content, empty editor and settings tab. Settings is a custom `EditorPane`, minimum width 700px. | [layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L1600), [cortexideSettingsPane.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/cortexideSettingsPane.ts#L62) |
| Auxiliary chat | Registered as one nonmovable view in `ViewContainerLocation.AuxiliaryBar`; opens after restore and mounts React. Minimum width 170px. | [sidebarPane.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/sidebarPane.ts#L64), [auxiliaryBarPart.ts](../../../cortexide-reference/src/vs/workbench/browser/parts/auxiliarybar/auxiliaryBarPart.ts#L53) |
| Lower panel | Native terminal/output/problems region; default bottom, movable and maximizable. | [layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L2330), [theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L480) |
| Status bar | Global compact strip; CortexIDE adds model, latency, privacy and free-tier entries near editor mode on the right. | [cortexideStatusBar.ts](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/cortexideStatusBar.ts#L44) |

## Chat interior

The panel fills its parent. Its stack is: scrollable thread tabs (minimum 36px), title/actions (minimum 32px), optional history (maximum 40% panel height), and either a landing page or thread. A thread is a flex column with an independently scrolling message list and composer below. The landing page scrolls as a unit and places the composer near the top, followed by context chips, quick actions and suggestions/history ([SidebarChat.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/SidebarChat.tsx#L276), [LandingPage.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/landing/LandingPage.tsx#L37)).

## Resizing and overflow

- Sidebar and auxiliary widths initialize near 300px, bounded by one quarter of window width, then restore saved dimensions. A bottom panel defaults near one third of height. The grid owns resize and stores the cached visible size even while a region is hidden ([layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L2792), [layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L2939), [layout.ts](../../../cortexide-reference/src/vs/workbench/browser/layout.ts#L1668)).
- Narrow regions retain usability through `min-width: 0`, title truncation, horizontal tab scroll and internal message/tool scroll. The composer caps at 80vh; its textarea caps at 500px and scrolls ([ComposerTabs.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/chrome/ComposerTabs.tsx#L31), [VoidChatArea.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/sidebar-tsx/composer/VoidChatArea.tsx#L380), [inputs.tsx](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/util/inputs.tsx#L845)).
- CSS declares 480px and 768px breakpoints and larger touch targets. Some selectors depend on classes being rendered, so this establishes intent, not proof of a fully mobile workbench ([cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L516)).

For PLC-Agent, retain left project navigation, center ST editor/debug workspace, right agent, lower diagnostics/runtime output, and bottom connection/run state. Existing frontend state already tracks sidebar, agent and dock dimensions; review it before later layout changes ([App.tsx](../../frontend/src/App.tsx#L18), [App.tsx](../../frontend/src/App.tsx#L72)).
