---
name: flowchat
description: "Flowchat · 流程图生成器：从 graph JSON 生成单文件、自包含、可直接用浏览器打开的流程图 HTML 页面。Use when the user asks for a 流程图 / 流程可视化 / 流程页面 / flow diagram / process map / pipeline visualization, or provides nodes/edges JSON to render."
---

# Flowchat · 流程图渲染器

把 graph JSON 变成**单个自包含 HTML 文件**，浏览器直接打开即可。无 iframe、无 srcdoc、无外部资源、无网络请求、无构建步骤。

## When to use

- The user wants a flow / process / pipeline / architecture diagram as a browsable page.
- The user hands you `nodes` + `edges` data (or describes a process you can model as nodes + edges).
- The user wants to restyle an existing flow page with their own colors.

Do **not** use this to produce an image, a Mermaid snippet, or an embedded widget. The deliverable here is a standalone HTML file.

## Quick start

All paths below are relative to the skill directory. Python 3.10+ only, zero third-party dependencies.

```bash
# 1. validate input first (fails loudly on bad data)
python3 scripts/validate_graph.py examples/minimal.graph.json

# 2. render
python3 scripts/generate_flowchat.py \
  --graph examples/minimal.graph.json \
  --theme examples/theme.example.json \
  --title "交付流程" \
  --output out/flowchat.html

# 3. open out/flowchat.html in a browser
```

`--theme` is optional; omit it to use the built-in neutral light theme. `--graph` is optional too; omit it to render the built-in 22-node demo graph.

## Rules that govern generation

1. **Never invent visual facts.** If the user supplies a theme or design tokens, use them. If not, use the built-in defaults. Do not invent colors, node shapes, edge styles, or status mappings "because it looks better". If a required visual value is genuinely unknown, mark it `unknown` and ask instead of guessing.
2. **Validate before render.** Always run `validate_graph.py` first. A dangling `source`/`target` is an error, not something to silently drop.
3. **Never hand-edit the generated HTML.** Change the graph or the theme and regenerate.
4. **One file out.** The output must remain self-contained; do not add CDN links, fonts, or external images.

## Input contract

Graph JSON:

```json
{
  "viewBox": [0, 0, 1600, 900],
  "nodes": [
    {"id": "intake", "label": "需求接入", "kind": "stage", "status": "completed",
     "x": 80, "y": 120, "width": 200, "height": 90}
  ],
  "edges": [
    {"id": "e1", "source": "intake", "target": "design", "status": "active",
     "source_port": "right-1", "target_port": "left-1"}
  ],
  "subflows": {
    "design": {
      "title": "设计子流程", "entry": "d1", "next": "开发", "loop": "返工",
      "nodes": [{"id": "d1", "label": "草稿"}],
      "edges": [{"id": "s1", "source": "d1", "target": "d2"}]
    }
  }
}
```

Node fields: `id`, `label`, `shape`, `x`, `y`, `width`, `height`, `status`, `kind`, `order`.
Edge fields: `id`, `source`, `target`, `status`, `kind`, `route_points`, `routing`, `source_side`, `target_side`, `source_port`, `target_port`, `label`, `label_x`, `label_y`, `crossing`.

### Node `kind` (drives shape and color family)

`orchestrator` top control hub · `control` rules center · `review-center` review center · `stage` numbered main stage · `dispatch` parallel dispatch · `agent` worker card · `summary` completion check · `gate` acceptance/review gate · `issue` blocked-event card · `feedback` feedback rail.

### Node / edge `status`

`completed`, `active`, `pending`, `blocked`, `return`. Status is expressed with **dash and animation**, never with thicker lines or bigger arrows. Completed and pending nodes render dimmed neutral gray so the active path stays readable.

### Ports and routing

A port is a side plus an optional lane: `left-1`, `left-2`, `left-3` (same for `right`, `top`, `bottom`). The three lanes resolve to 1/3, 1/2, 2/3 along that side. Use numbered ports for fan-out and fan-in so edges land on stable, separate anchors; a plain side name (`left`) remains the center port.

- For ordinary neighbor-to-neighbor edges, **do not** supply `route_points`; let auto-routing choose a straight or one-bend path.
- Keep explicit `route_points` only for feedback loops, wrap-around, or deliberately crossing edges, and mark them `crossing: true` or explain with an edge label.
- `routing: "auto"` picks the shortest safe orthogonal path around other nodes and occupied lanes; it prefers straight, then one bend, then padded node-boundary lanes with bend/crossing/overlap penalties.
- When an edge is unrelated to the currently selected node, route it away from that node rather than through its visual neighborhood. Prefer an empty corridor, then the corridor with the fewest occupied lanes. This outranks minimizing bends or length, but must preserve declared anchors.

### Center alignment and hierarchy

Center alignment applies only to primary parent/child or stage-flow edges; feedback, return, auxiliary, and evidence edges keep their declared routing. In `TB`/`BT` a one-to-one pair shares an x-center; in `LR`/`RL` it shares a y-center. One-to-many: put the source center on the bounding-box center of its targets. Many-to-one: put the target center on the bounding-box center of its sources. Many-to-many: do not force a single centerline — distribute across numbered ports and route each relation independently.

Optional semantic fields pass through without being hardcoded into the renderer: `layout_group`, `layout_role`, `align_policy`, and edge `relation` / `route_policy`.

## Subflows

`subflows` is keyed by stage node ID. Each entry carries `title`, `entry`, `next`, `loop`, `nodes`, `edges`, so a stage can expose its own local topology plus its handoff condition to the next stage and its loop-back condition. Clicking a stage opens its process map.

## Theme

Optional JSON. Any subset of the tokens in [references/theme.md](references/theme.md); missing keys fall back to the built-in neutral light theme. Override tokens only — never rewrite the host page through global `.node` / `.edge` selectors.

## Geometry gate (optional quality check)

The renderer enforces geometry itself, and the Harness verifies it:

- total edge length ≥ 90 px, final arrow segment ≥ 75 px
- no near-zero, reverse, or diagonal segments
- every endpoint magnetized to the declared node side; aligned ports stay straight
- overlapping lines allowed only when direction and shared side agree; intentional crossings marked `crossing: true`
- edge stroke ≤ 2 px, arrow marker ≤ 5×5
- centered, non-overflowing text; diamond text centered
- no intermediate-node occlusion

The renderer **rejects** invalid routes rather than adding a reverse dogleg, so a bad route can never silently become a misleading arrow.

Run the static gate (no browser needed):

```bash
python3 harness/flowchat_local_harness.py out/flowchat.html --output out/harness-report.json
```

Read `static_status` in the report to know whether geometry and interaction hooks passed. `status` is `blocked` — and the process exits `2` — whenever no browser receipt is supplied; that means "no browser evidence", **not** "geometry failed".

Run the full gate only when you have real browser evidence for this exact artifact:

```bash
python3 scripts/self_check_flowchat.py out/flowchat.html \
  --browser-receipt out/browser-receipt.json \
  --output out/harness-report.json
```

A receipt for a different file, or a `file://` load instead of HTTP, is `blocked`. Missing evidence is never reported as `not_run` success.

## Acceptance check

The output exists, is a single file, contains one `[data-flowchat-root]` mount, opens directly in a browser with no console errors, and its visible topology matches the input graph (no dropped edges, no invented nodes).
