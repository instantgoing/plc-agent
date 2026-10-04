# CortexIDE token map

The custom palette is declared in [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L18). React components also use [Tailwind configuration](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/tailwind.config.js#L8) and [styles.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/styles.css#L310). Native workbench colors come from [theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L31) and the selected VS Code theme.

## Custom semantic palette

| Role | Dark default | Light default | Intended use |
| --- | --- | --- | --- |
| `surface-0` / `surface-1` | `#0a0a0d` / `#111116` | `#ffffff` / `#f7f7fa` | Deep overlay / base panel |
| `surface-1-alt` / `surface-2` | `#14141a` / `#18181f` | `#f1f1f6` / `#eaeaf1` | Alternate row / input or card |
| `surface-2-alt` / `surface-3` / `surface-4` | `#1e1e27` / `#242430` / `#2c2c3c` | `#e1e1ea` / `#d5d5e2` / `#c8c8d8` | Hover / raised card / menu |
| `text-strong` / `text-base` | `#f0f0f5` / `#d4d4e8` | `#0d0d18` / `#1a1a2e` | Heading or active / body |
| `text-muted` / `text-subtle` | `#9898b8` / `#6a6a88` | `#484868` / `#78789a` | Secondary / hint |
| `brand` / `brand-dim` | `#8b6fff` / `#6d52d4` | `#6340e0` / `#4f2fc0` | Accent / pressed accent |
| `success` / `warning` / `danger` | `#3dbf8e` / `#f5c842` / `#ff5c7a` | `#187a52` / `#a06a00` / `#c8001e` | Semantic feedback |
| `border-weak` / `base` / `strong` | `#22222e` / `#2e2e40` / `#3a3a52` | `#e2e2ee` / `#cecee0` / `#b8b8d0` | Divider / control / emphasis |
| Scrollbar thumb / hover | `#2e2e42` / `#3e3e58` | `#c4c4d8` / `#a8a8c4` | Quiet scroll affordance |

Dark values: [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L20). Light values: [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L595). Separate high-contrast light/dark overrides exist at [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L650).

## Geometry, typography and motion

| Family | Values and rule | Evidence |
| --- | --- | --- |
| Spacing | 2, 4, 8, 12, 16, 20, 24px; legacy alias adds 6px. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L80) |
| Radii | 3, 5, 8, 12, 16px; pills and circular controls use full radius. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L89) |
| Custom type roles | Title 14, subtitle 13, body 12, label 11, micro 10px. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L55) |
| React type scale | Tailwind maps `xs` 10, `sm` 11, `root` 13, `lg` 14, `xl` 16px. These overlap with custom roles, so there is no single global 12px body. | [tailwind.config.js](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/tailwind.config.js#L35) |
| Monospace | Cascadia Code/Mono, SF Mono, JetBrains Mono, Fira Code and system monospace fallbacks for code/pre/editor lines. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L66), [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L566) |
| Motion | Fast 120ms, base 180ms, slow 260ms; local 100–300ms animations for tabs, tools and messages. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L97), [styles.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/styles.css#L266) |
| Scrollbars | Scoped chat 6px vertical / 4px horizontal; legacy scroll element 10px/6px; Firefox `thin`. | [cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L325) |

## Resolution order and caveat

1. `--cortex-*` defines custom defaults on `.void-scope`, onboarding root and auxiliary content. Many `--void-*` values are aliases ([cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L18), [aliases](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L123)).
2. Inside `.part.auxiliarybar > .content`, most `--void-bg-*`, `--void-fg-*` and `--void-border-*` aliases are reassigned to `--vscode-sideBar-*` values. Components using direct `--cortex-*` retain the CortexIDE palette. This mixed resolution means a static hex list cannot fully predict a chat screenshot ([cortexide.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/media/cortexide.css#L300), [styles.css](../../../cortexide-reference/src/vs/workbench/contrib/cortexide/browser/react/src/styles.css#L411)).
3. Native tabs, activity rail, explorer, panel and status bar resolve host theme tokens. `theme.ts` registers defaults, but selected user themes may override them. For example, inactive tab defaults are `#2D2D2D` dark / `#ECECEC` light; activity rail defaults are `#333333` dark / `#2C2C2C` light. These are not guaranteed screen colors ([theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L35), [theme.ts](../../../cortexide-reference/src/vs/workbench/common/theme.ts#L389)).

## Later PLC-Agent semantic map

| PLC-Agent role | Reference concept |
| --- | --- |
| Shell/editor/sidebar surfaces | Active app theme surface tokens |
| Composer/cards | One stepped local surface scale |
| Dividers/control/focus | Weak, base, strong and one focus accent |
| Tool progress | Neutral, running, success, warning, error |
| PLC verification | Distinct pending/passed/failed state sourced from real verification |
| Source code and values | Readable monospace |

This vocabulary does not require adopting CortexIDE variable names or exact colors.
