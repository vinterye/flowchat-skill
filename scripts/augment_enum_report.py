#!/usr/bin/env python3
"""Add the node-port/lane matrix to a generated Flowchat enum report.

The WorkBuddy enumeration generator renders the node and edge tiles.  This
small post-processor keeps the report reproducible while making the routing
contract visible for every registered node type.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


SIDES = ("left", "right", "top", "bottom")
LANES = ("1/3", "1/2", "2/3")


def _semantic_profile(kind: str, family: str) -> tuple[str, str, str]:
    """Return ingress, egress, and a short semantic note for a type."""
    if kind in {"start", "input"}:
        return "—", "right / bottom", "起点或输入只提供出线端"
    if kind in {"end", "output"}:
        return "left / top", "—", "终点或输出只提供入线端"
    if kind in {"artifact", "document", "database", "queue"}:
        return "left / top", "right / bottom", "数据/产物默认从主流程入线，也可继续传递"
    if kind in {"fork", "dispatch", "parallel_group"}:
        return "left / top", "right / bottom", "同组扇出共用 trunk，再按 1/2/3 分配分支"
    if kind in {"join", "merge", "summary"}:
        return "left / top", "right / bottom", "同组扇入先合并 corridor，再进入目标"
    if kind in {"decision", "gate", "rule", "checkpoint", "milestone"}:
        return "left / top", "right / bottom", "判断/治理节点按语义侧选择端口"
    if kind in {"retry", "loop", "fallback", "issue", "feedback"}:
        return "left / top", "right / bottom", "回环或返工边使用独立 lane，避免与主线重叠"
    if family == "structure":
        return "left / top", "right / bottom", "容器/引用节点保留四侧边界端口"
    return "left / top", "right / bottom", "普通处理节点按相对位置选择最短正交路径"


def _port_text() -> str:
    groups = []
    for side in SIDES:
        groups.append(f"<span class=port-chip>{side} · center</span>")
        groups.extend(f"<span class=port-chip>{side}-{lane}</span>" for lane in LANES)
    return "".join(groups)


def _compact_port_set() -> str:
    return " · ".join(f"{side}[1/3 · 1/2 · 2/3]" for side in SIDES)


def _extract_real_node_svgs(report_html: str) -> dict[str, str]:
    """Read the real node SVG tiles already emitted by WorkBuddy's generator."""
    found: dict[str, str] = {}
    pattern = re.compile(
        r'<div class="tile">(?P<body>.*?)<p class="tname">\d+\.\s*(?P<label>[^<]+)</p>',
        re.S,
    )
    for match in pattern.finditer(report_html):
        candidates = re.findall(r'<svg\b[^>]*>.*?</svg>', match.group("body"), re.S)
        svg = next((candidate for candidate in candidates if 'data-type="' in candidate and 'flowchat-node' in candidate), None)
        if not svg:
            continue
        kind = match.group("label").strip()
        found.setdefault(kind, svg)
    return found


def _node_dimensions(spec: dict) -> tuple[float, float]:
    shape = spec["shape"]
    if shape in {"diamond", "hexagon", "octagon"}:
        return 150.0, 106.0
    if shape == "bar":
        return 132.0, 42.0
    size = spec.get("size", "regular")
    return {"compact": (132.0, 56.0), "wide": (220.0, 88.0), "tall": (180.0, 120.0)}.get(size, (156.0, 88.0))


def _port_overlay(svg: str, kind: str, spec: dict) -> str:
    view = re.search(r'viewBox="([^"]+)"', svg)
    if not view:
        return svg
    values = [float(v) for v in view.group(1).split()]
    min_x, min_y, view_w, view_h = values
    width, height = _node_dimensions(spec)
    cx, cy = min_x + view_w / 2, min_y + view_h / 2
    ingress, egress, _ = _semantic_profile(kind, spec["family"])
    ingress_sides = set() if ingress == "—" else set(ingress.split(" / "))
    egress_sides = set() if egress == "—" else set(egress.split(" / "))
    circles = []
    for side in SIDES:
        for index, ratio in enumerate((1 / 3, 1 / 2, 2 / 3), 1):
            if side == "left":
                x, y = cx - width / 2, cy - height / 2 + height * ratio
            elif side == "right":
                x, y = cx + width / 2, cy - height / 2 + height * ratio
            elif side == "top":
                x, y = cx - width / 2 + width * ratio, cy - height / 2
            else:
                x, y = cx - width / 2 + width * ratio, cy + height / 2
            role = "both" if side in ingress_sides and side in egress_sides else "in" if side in ingress_sides else "out" if side in egress_sides else "available"
            fill = {"in": "#2563eb", "out": "#7c3aed", "both": "#0f766e", "available": "#ffffff"}[role]
            stroke = {"in": "#1d4ed8", "out": "#6d28d9", "both": "#0f766e", "available": "#94a3b8"}[role]
            r = 5.2 if index == 2 else 4.2
            circles.append(f'<circle class="port-dot port-{role}" cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"><title>{side}-{index}: {role}</title></circle>')
    overlay = '<g class="port-overlay" aria-label="四侧端口：每侧 1/3、1/2、2/3">' + ''.join(circles) + '</g>'
    return svg.replace('</svg>', overlay + '</svg>', 1)


def _build_section(registry: dict, report_html: str) -> str:
    real_svgs = _extract_real_node_svgs(report_html)
    cards = []
    for index, (kind, spec) in enumerate(registry["nodeTypes"].items(), 1):
        ingress, egress, note = _semantic_profile(kind, spec["family"])
        svg = _port_overlay(real_svgs.get(kind, ""), kind, spec)
        if not svg:
            svg = '<svg viewBox="0 0 240 150" role="img"><text x="120" y="75" text-anchor="middle">missing real SVG</text></svg>'
        cards.append(
            '<article class="port-card">'
            f'<div class="port-card-head"><b>{index}. <code>{html.escape(kind)}</code></b><span>{html.escape(spec["family"])} · {html.escape(spec["shape"])}</span></div>'
            f'<div class="port-card-svg">{svg}</div>'
            f'<div class="port-card-meta"><span class="port-role-in">入：{html.escape(ingress)}</span><span class="port-role-out">出：{html.escape(egress)}</span></div>'
            f'<div class="port-card-lanes">四侧各 1/3 · 1/2 · 2/3 · {html.escape(note)}</div>'
            '</article>'
        )
    return f'''<div class="sec port-sec">
<h2>2. 节点类型 × 端口与车道全集</h2>
<p class="desc">每张卡都复用真实生成器产出的节点 SVG，再叠加四侧端口圆点：蓝色为默认入侧、紫色为默认出侧、青色为入出共用，灰色为空闲可用端口。每侧固定 1/3、1/2、2/3 三条车道。</p>
<div class="port-legend"><div><b>端口车道可视图例</b></div><div class="port-demo"><svg viewBox="0 0 420 150" role="img" aria-label="四侧端口与三条车道"><rect x="120" y="35" width="180" height="80" rx="14" fill="#fff" stroke="#334155" stroke-width="2"/><g class="port-demo-dots"><circle cx="120" cy="62" r="5" fill="#2563eb"/><circle cx="120" cy="75" r="6" fill="#0f766e"/><circle cx="120" cy="88" r="5" fill="#2563eb"/><circle cx="300" cy="62" r="5" fill="#7c3aed"/><circle cx="300" cy="75" r="6" fill="#7c3aed"/><circle cx="300" cy="88" r="5" fill="#7c3aed"/><circle cx="180" cy="35" r="5" fill="#fff" stroke="#94a3b8"/><circle cx="210" cy="35" r="6" fill="#fff" stroke="#94a3b8"/><circle cx="240" cy="35" r="5" fill="#fff" stroke="#94a3b8"/><circle cx="180" cy="115" r="5" fill="#fff" stroke="#94a3b8"/><circle cx="210" cy="115" r="6" fill="#fff" stroke="#94a3b8"/><circle cx="240" cy="115" r="5" fill="#fff" stroke="#94a3b8"/></g><text x="210" y="20" text-anchor="middle">top · 1/3 1/2 2/3</text><text x="210" y="143" text-anchor="middle">bottom · 1/3 1/2 2/3</text><text x="28" y="79">left</text><text x="392" y="79" text-anchor="end">right</text></svg></div><div class="port-chips"><span class=port-chip>蓝：入</span><span class=port-chip>紫：出</span><span class=port-chip>青：入出共用</span><span class=port-chip>灰：可用</span></div><div class="lane-note"><b>车道规则：</b>普通单边使用 center（等价于 1/2）；1→N 与 N→1 按稳定顺序使用 1/3、1/2、2/3；同一节点同时入/出时，入出保留不同 lane。</div></div>
<div class="port-card-grid">{''.join(cards)}</div>
</div>
'''


def _extract_overview_svg(graph_html: str) -> str:
    """Extract the overview SVG from a real generator output.

    The enum report must show the same geometry as the generated artifact.  We
    therefore copy the SVG emitted by ``generate_flowchat.py`` instead of
    rebuilding a second illustrative diagram here.
    """
    match = re.search(
        r'(<svg\b[^>]*aria-label="Flowchat 实时执行拓扑图"[^>]*>.*?</svg>)',
        graph_html,
        re.S,
    )
    if not match:
        return ""
    svg = match.group(1)
    # Avoid marker-id collisions with the other real SVGs already on the page.
    svg = re.sub(r'id="flowchat-', 'id="enum-causal-flowchat-', svg)
    svg = svg.replace('url(#flowchat-', 'url(#enum-causal-flowchat-')
    return svg


def _ref_list(values: list[str]) -> str:
    if not values:
        return '<span class="causal-muted">—</span>'
    return " ".join(f'<code class="ref-pill">{html.escape(str(value))}</code>' for value in values)


def _edge_port(edge: dict, side_key: str, port_key: str) -> str:
    side = edge.get(side_key) or "auto"
    port = edge.get(port_key) or "center"
    return f"{side} · {port}" if side != "auto" or port != "center" else "auto"


def _causal_section(graph: dict, graph_html: str, source_path: Path) -> str:
    """Render the current causal graph as a visual, evidence-bound enum section."""
    nodes = list(graph.get("nodes", []))
    edges = list(graph.get("edges", []))
    by_id = {str(node.get("id")): node for node in nodes}
    svg = _extract_overview_svg(graph_html)
    svg_block = (
        f'<div class="causal-preview"><div class="causal-preview-title">真实生成器 SVG · 当前因果拓扑</div>{svg}</div>'
        if svg
        else '<div class="causal-missing">未找到真实生成器 SVG，当前拓扑图无法宣称已同步。</div>'
    )

    contexts: dict[str, list[str]] = {}
    refs: dict[str, dict[str, list[str]]] = {}
    for node in nodes:
        node_id = str(node.get("id"))
        for context in node.get("context_refs", []) or []:
            contexts.setdefault(str(context), []).append(node_id)
        for output in node.get("output_refs", []) or []:
            refs.setdefault(str(output), {"producers": [], "consumers": []})["producers"].append(node_id)
        for input_ref in node.get("input_refs", []) or []:
            refs.setdefault(str(input_ref), {"producers": [], "consumers": []})["consumers"].append(node_id)

    node_cards = []
    for index, node in enumerate(nodes, 1):
        node_id = str(node.get("id"))
        incoming = [e for e in edges if str(e.get("target")) == node_id]
        outgoing = [e for e in edges if str(e.get("source")) == node_id]
        in_ports = "、".join(_edge_port(e, "target_side", "target_port") for e in incoming) or "—"
        out_ports = "、".join(_edge_port(e, "source_side", "source_port") for e in outgoing) or "—"
        label = html.escape(str(node.get("label", node_id))).replace("\\n", "<br>")
        node_cards.append(
            '<article class="causal-node-card">'
            f'<div class="causal-node-head"><b>{index}. <code>{html.escape(node_id)}</code></b>'
            f'<span class="causal-kind">{html.escape(str(node.get("type", node.get("kind", "unknown"))))}</span></div>'
            f'<div class="causal-node-label">{label}</div>'
            f'<div class="causal-port-row"><b>入端口</b> {html.escape(in_ports)} · <b>出端口</b> {html.escape(out_ports)}</div>'
            f'<div class="causal-ref-row"><b>输入</b> {_ref_list(node.get("input_refs", []) or [])}</div>'
            f'<div class="causal-ref-row"><b>输出</b> {_ref_list(node.get("output_refs", []) or [])}</div>'
            f'<div class="causal-ref-row"><b>共享上下文</b> {_ref_list(node.get("context_refs", []) or [])}</div>'
            '</article>'
        )

    edge_rows = []
    for edge in edges:
        dep = edge.get("dependency") or {}
        source = str(edge.get("source"))
        target = str(edge.get("target"))
        edge_rows.append(
            '<tr>'
            f'<td><code>{html.escape(str(edge.get("id", "")))}</code></td>'
            f'<td><code>{html.escape(source)}</code> → <code>{html.escape(target)}</code></td>'
            f'<td>{html.escape(_edge_port(edge, "source_side", "source_port"))} → {html.escape(_edge_port(edge, "target_side", "target_port"))}</td>'
            f'<td><span class="dep-kind">{html.escape(str(dep.get("kind", "untyped")))}</span><br>'
            f'<b>out</b> {_ref_list([str(dep.get("output_ref"))] if dep.get("output_ref") else [])}<br>'
            f'<b>in</b> {_ref_list([str(dep.get("input_ref"))] if dep.get("input_ref") else [])}</td>'
            '</tr>'
        )

    ref_rows = []
    for ref, owners in sorted(refs.items()):
        consumers = owners["consumers"]
        producers = owners["producers"]
        state = "可闭合" if producers and consumers else "缺生产者" if consumers else "仅输出"
        ref_rows.append(
            '<tr>'
            f'<td><code>{html.escape(ref)}</code></td>'
            f'<td>{"、".join(html.escape(v) for v in producers) or "—"}</td>'
            f'<td>{"、".join(html.escape(v) for v in consumers) or "—"}</td>'
            f'<td><span class="dep-state {"closed" if producers and consumers else "open"}">{state}</span></td>'
            '</tr>'
        )

    context_rows = []
    for context, owners in sorted(contexts.items()):
        context_rows.append(
            '<tr>'
            f'<td><code>{html.escape(context)}</code></td>'
            f'<td>{"、".join(html.escape(v) for v in owners)}</td>'
            '<td><span class="context-state">共享上下文引用</span></td>'
            '</tr>'
        )

    return f'''<div class="sec causal-sec">
<h2>10. 当前因果拓扑同步（节点 / 连线 / 端口 / 依赖 / 上下文）</h2>
<p class="desc">这一节不是示意图：节点和连线 SVG 直接来自真实生成器产物；端口来自真实边的 source/target side 与 port；输入输出依赖和共享上下文来自同一份 graph JSON。源文件：<code>{html.escape(str(source_path))}</code>；<code>dependency_contract</code>：<code>{html.escape(str(graph.get("dependency_contract", "unknown")))}</code>。</p>
<div class="causal-summary"><span><b>{len(nodes)}</b> 个真实节点</span><span><b>{len(edges)}</b> 条真实连线</span><span><b>{len(refs)}</b> 个数据引用</span><span><b>{len(contexts)}</b> 个共享上下文</span></div>
{svg_block}
<h3>新增/修改节点及其真实端口与引用</h3><div class="causal-node-grid">{"".join(node_cards)}</div>
<h3>真实连线、端口和输入输出依赖</h3><div class="causal-table-wrap"><table class="causal-table"><thead><tr><th>边</th><th>拓扑</th><th>实际端口</th><th>依赖契约</th></tr></thead><tbody>{"".join(edge_rows)}</tbody></table></div>
<h3>输入输出引用闭合情况</h3><div class="causal-table-wrap"><table class="causal-table"><thead><tr><th>引用</th><th>生产者</th><th>消费者</th><th>状态</th></tr></thead><tbody>{"".join(ref_rows)}</tbody></table></div>
<h3>共享上下文（不生成伪连线）</h3><div class="causal-table-wrap"><table class="causal-table"><thead><tr><th>context_ref</th><th>引用节点</th><th>语义</th></tr></thead><tbody>{"".join(context_rows)}</tbody></table></div>
</div>
'''


def augment(report: Path, registry_path: Path, graph_path: Path | None = None, graph_html_path: Path | None = None) -> None:
    content = report.read_text(encoding="utf-8")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    marker = '<div class="sec"><h2>2. '
    if marker not in content:
        raise SystemExit("cannot locate section 2 insertion point")
    if '<div class="sec port-sec">' in content:
        start = content.index('<div class="sec port-sec">')
        next_section = content.index('<div class="sec">', start + 1)
        content = content[:start] + content[next_section:]
    if '.port-legend{' not in content:
        content = content.replace('</style>', '''
.port-legend{background:#fff;border:1px solid #e4e4e8;border-radius:13px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.port-chips{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0 10px}.port-chip,.side-chip{display:inline-block;border:1px solid #d9e1f2;background:#f7f9ff;border-radius:999px;padding:2px 8px;font-size:11px;color:#3154a5}.lane-note{font-size:12px;color:#6b6b70}.port-demo{margin:10px 0 4px;border:1px solid #edf0f5;border-radius:10px;background:#fafcff;padding:8px}.port-demo svg{display:block;width:100%;max-height:170px}.port-demo text{font-size:11px;fill:#64748b}.port-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:14px;margin-top:14px}.port-card{background:#fff;border:1px solid #e4e4e8;border-radius:13px;padding:10px;box-shadow:0 1px 3px rgba(0,0,0,.06)}.port-card-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:12px}.port-card-head span{color:#8a8a90;font-size:10.5px;white-space:nowrap}.port-card-svg{margin-top:7px;border:1px solid #edf0f5;border-radius:9px;background:#fff;overflow:hidden}.port-card-svg svg{display:block;width:100%;height:150px}.port-card-svg .port-overlay{pointer-events:none}.port-card-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;font-size:11px}.port-role-in,.port-role-out{border-radius:999px;padding:2px 7px}.port-role-in{color:#1d4ed8;background:#eff6ff}.port-role-out{color:#6d28d9;background:#f5f3ff}.port-card-lanes{margin-top:7px;font-size:10.5px;line-height:1.45;color:#6b6b70}.port-table-wrap,.port-table{display:none}
.causal-summary{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.causal-summary span{border:1px solid #d9e1f2;background:#f7f9ff;border-radius:999px;padding:4px 10px;color:#3154a5;font-size:12px}.causal-summary b{font-size:15px}.causal-preview{background:#fff;border:1px solid #dfe5ef;border-radius:13px;padding:12px;overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.06)}.causal-preview-title{font-size:12px;font-weight:700;color:#3154a5;margin:0 0 8px}.causal-preview svg{display:block;width:100%;min-width:900px;max-height:620px;height:auto;background:#fbfcff}.causal-missing{padding:18px;border:1px solid #f2caca;background:#fff1f2;color:#a32b22;border-radius:10px}.causal-node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}.causal-node-card{background:#fff;border:1px solid #e4e4e8;border-radius:12px;padding:11px;box-shadow:0 1px 3px rgba(0,0,0,.05)}.causal-node-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.causal-kind,.dep-kind,.dep-state,.context-state{display:inline-block;border-radius:999px;padding:2px 7px;font-size:10.5px;background:#eef2ff;color:#3154a5}.causal-node-label{margin:8px 0;font-size:13px;line-height:1.45;color:#1d1d1f}.causal-port-row,.causal-ref-row{font-size:11px;line-height:1.65;color:#6b6b70}.causal-port-row b,.causal-ref-row b{color:#4a4a50}.ref-pill{display:inline-block;margin:1px 3px 1px 0;background:#f5f3ff;color:#5b36b8}.causal-table-wrap{overflow:auto;border:1px solid #e4e4e8;border-radius:12px;background:#fff}.causal-table{width:100%;border-collapse:collapse;min-width:880px;font-size:11.5px}.causal-table th,.causal-table td{padding:9px 10px;border-bottom:1px solid #ececf0;text-align:left;vertical-align:top}.causal-table th{background:#fafaff;color:#6b6b70;font-size:11px}.causal-table tr:last-child td{border-bottom:0}.dep-state.closed{background:#eaf8f0;color:#16723d}.dep-state.open{background:#fff6e8;color:#8a5a10}.context-state{background:#ecfeff;color:#0f766e}
 </style>''', 1)
    elif '.port-list{' not in content:
        content = content.replace('</style>', '.port-list{min-width:270px;color:#3154a5;font-size:11px;line-height:1.45}</style>', 1)
    if '.port-card-grid{' not in content:
        content = content.replace('</style>', '.port-demo{margin:10px 0 4px;border:1px solid #edf0f5;border-radius:10px;background:#fafcff;padding:8px}.port-demo svg{display:block;width:100%;max-height:170px}.port-demo text{font-size:11px;fill:#64748b}.port-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:14px;margin-top:14px}.port-card{background:#fff;border:1px solid #e4e4e8;border-radius:13px;padding:10px;box-shadow:0 1px 3px rgba(0,0,0,.06)}.port-card-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:12px}.port-card-head span{color:#8a8a90;font-size:10.5px;white-space:nowrap}.port-card-svg{margin-top:7px;border:1px solid #edf0f5;border-radius:9px;background:#fff;overflow:hidden}.port-card-svg svg{display:block;width:100%;height:150px}.port-card-svg .port-overlay{pointer-events:none}.port-card-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;font-size:11px}.port-role-in,.port-role-out{border-radius:999px;padding:2px 7px}.port-role-in{color:#1d4ed8;background:#eff6ff}.port-role-out{color:#6d28d9;background:#f5f3ff}.port-card-lanes{margin-top:7px;font-size:10.5px;line-height:1.45;color:#6b6b70}.port-table-wrap,.port-table{display:none}</style>', 1)
    
    content = content.replace(marker, _build_section(registry, content) + marker, 1)
    content = content.replace(
        '未改动 flowchat 项目任何文件（脚本只读取 + 调生成器，探针写在 /tmp）。',
        '节点与边图形来自真实生成器 SVG；端口/车道矩阵来自本地注册表与 SKILL 路由合同。',
    )
    if graph_path and graph_html_path:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph_html = graph_html_path.read_text(encoding="utf-8")
        if '<div class="sec causal-sec">' in content:
            start = content.index('<div class="sec causal-sec">')
            next_section = content.find('<div class="sec">', start + 1)
            if next_section == -1:
                next_section = content.find('<div class="foot">', start)
            content = content[:start] + (content[next_section:] if next_section != -1 else '')
        marker_10 = '<div class="sec"><h2>10. '
        causal = _causal_section(graph, graph_html, graph_path)
        if marker_10 in content:
            content = content.replace(marker_10, causal + marker_10, 1)
        elif '<div class="foot">' in content:
            content = content.replace('<div class="foot">', causal + '<div class="foot">', 1)
        else:
            content += causal
        # The causal snapshot occupies section 10; keep the pre-existing
        # probe findings as the following section instead of duplicating the
        # section number in the rendered report.
        content = content.replace(
            '<div class="sec"><h2>10. 枚举过程中实测暴露的缺口</h2>',
            '<div class="sec"><h2>11. 枚举过程中实测暴露的缺口</h2>',
            1,
        )
    report.write_text(content, encoding="utf-8")


def append_causal_snapshot(report: Path, graph_path: Path, graph_html_path: Path) -> None:
    """Append the same evidence-bound snapshot to the legacy compact enum page."""
    content = report.read_text(encoding="utf-8")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_html = graph_html_path.read_text(encoding="utf-8")
    if '<div class="sec causal-sec">' in content:
        start = content.index('<div class="sec causal-sec">')
        end = content.find('<h2>Harness 几何指标</h2>', start)
        if end != -1:
            content = content[:start] + content[end:]
    if '.causal-preview{' not in content:
        content = content.replace('</style>', '''
.causal-sec{margin-top:30px}.causal-summary{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.causal-summary span{border:1px solid #d9e1f2;background:#f7f9ff;border-radius:999px;padding:4px 10px;color:#3154a5;font-size:12px}.causal-summary b{font-size:15px}.causal-preview{background:#fff;border:1px solid #dfe5ef;border-radius:13px;padding:12px;overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.06)}.causal-preview-title{font-size:12px;font-weight:700;color:#3154a5;margin:0 0 8px}.causal-preview svg{display:block;width:100%;min-width:900px;max-height:620px;height:auto;background:#fbfcff}.causal-node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}.causal-node-card{background:#fff;border:1px solid #e4e4e8;border-radius:12px;padding:11px}.causal-node-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.causal-kind,.dep-kind,.dep-state,.context-state{display:inline-block;border-radius:999px;padding:2px 7px;font-size:10.5px;background:#eef2ff;color:#3154a5}.causal-node-label{margin:8px 0;font-size:13px;line-height:1.45}.causal-port-row,.causal-ref-row{font-size:11px;line-height:1.65;color:#6b6b70}.causal-port-row b,.causal-ref-row b{color:#4a4a50}.ref-pill{display:inline-block;margin:1px 3px 1px 0;background:#f5f3ff;color:#5b36b8}.causal-table-wrap{overflow:auto;border:1px solid #e4e4e8;border-radius:12px;background:#fff}.causal-table{width:100%;border-collapse:collapse;min-width:880px;font-size:11.5px}.causal-table th,.causal-table td{padding:9px 10px;border-bottom:1px solid #ececf0;text-align:left;vertical-align:top}.causal-table th{background:#fafaff;color:#6b6b70;font-size:11px}.causal-table tr:last-child td{border-bottom:0}.dep-state.closed{background:#eaf8f0;color:#16723d}.dep-state.open{background:#fff6e8;color:#8a5a10}.context-state{background:#ecfeff;color:#0f766e}
</style>''', 1)
    section = _causal_section(graph, graph_html, graph_path)
    marker = '<h2>Harness 几何指标</h2>'
    if marker in content:
        content = content.replace(marker, section + marker, 1)
    elif '</main>' in content:
        content = content.replace('</main>', section + '</main>', 1)
    else:
        content += section
    report.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--graph-html", type=Path)
    parser.add_argument("--append-only", action="store_true")
    args = parser.parse_args()
    if args.append_only:
        if not args.graph or not args.graph_html:
            parser.error("--append-only requires --graph and --graph-html")
        append_causal_snapshot(args.report, args.graph, args.graph_html)
    else:
        augment(args.report, args.registry, args.graph, args.graph_html)
    print(f"augmented {args.report}")


if __name__ == "__main__":
    main()
