# CortexIDE reproduction verification

## Reference and scope

- Compared at 1440 × 900 CSS pixels. The running installed CortexIDE is 1.106.00200; `../cortexide-reference` source is 1.118.1. The rendered installed client takes priority where the two differ.
- Measured reference values and source mappings: `../cortexide/tokens.json`, `layout.json`, `components.md`, and `interactions.md`. Direct code from the reference was not copied. PLC-Agent branding and behavior were retained.
- The reference's 06–08 running/tool-call states could not be captured: the isolated client has no configured model and returned a real no-model error (`../cortexide/11-no-model-error.png`). These are intentionally absent as golden images.

## Capture and correction passes

- Local `pass1b` through `pass9` hold repeated 1440 × 900 captures; local `diff-pass*` hold generated pixel differences. Only `pass9` and `diff-pass9` are committed; intermediate captures remain local. `pass9` is the final empty-chat visual state and also captures hover, focus, and command palette. The intermediate `final` directory contains a replayed agent conversation and is therefore not paired with empty-chat goldens.
- The initial UI used a 48px title area, 260px primary sidebar, 360px Agent panel, green accents, and an always-open full-width bottom panel. Final measured boundaries are 35px title, 48px activity rail, 300px primary sidebar, 792px editor, 300px Agent panel, 22px status bar, and a 300px panel under only the editor when opened.
- Corrections included a 1px activity-rail overflow, 25px empty-Agent content offset, panel/sidebar resizing, composer height and focus treatment, editor tab/breadcrumb/minimap geometry, and tool-result disclosure.
- `diff-pass9/metrics.json`: raw threshold-20 mismatch is 4.53% on main shell, 6.37% on editor/empty Agent, and 6.92% on bottom panel. The directly comparable blank editor region is 1.43%. Raw whole-image mismatch includes different project tree contents, ST highlighting, PLC-specific status text, and omitted CortexIDE branding.

## UX and functional checks

- `ux-results.json` records successful sidebar and panel drag resize, panel toggle, sidebar collapse, two-file tab switching, file context menu, multiline composer, disabled empty send, focus shortcut, and a functional keyboard command palette. Keyboard resize handlers and tab arrow navigation were added.
- `agent-real/` contains a real read-only Agent execution with four completed tool calls, running and expanded/collapsed captures, and `completed-results.json`. No ST or Runtime mutation was requested.
- `npm run build` passed; `npm test` passed 6/6 frontend tests. `git diff --check` passed. Python `pytest` was unavailable in the existing interpreters, so the backend suite was not run for this frontend work.

## Remaining differences

- The live reference and source checkout are different versions; newer source chat details cannot be claimed as measured live pixels.
- No valid CortexIDE golden exists for running, collapsed tool, or expanded tool state without model configuration. PLC-Agent's real captures demonstrate the interactions but cannot establish a reference pixel percentage for them.
- The browser app does not have Electron's native File/Edit/View menus. Its keyboard command palette exposes only existing PLC-Agent actions. Product content, branding, status, editor syntax highlighting, and available commands necessarily differ.
- The reference shows a token usage value; PLC-Agent does not expose that data, so the UI says `Context usage unavailable` rather than inventing a value.
