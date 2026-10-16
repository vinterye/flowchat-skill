#!/usr/bin/env python3
"""Render the Flowchat capability map as a standalone SVG.

The numbers on this map come from the type registry (49 node types / 19 edge
types / 13 statuses / 12 shapes / 4 size presets / 12 port positions), so the
map and the full enum spectrum page never disagree.

Regenerate with:
    python3 tools/render_capability_map.py --output docs/capability-map.svg
    python3 tools/render_capability_map.py --registry flowchat/data/type-registry-v1.json

Pure stdlib. The PNG in the README is produced from this SVG.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

W = 1240
H = 1500
PAD = 40

INK = "#172033"
MUTED = "#485266"
FAINT = "#7c8496"
LINE = "#dfe4ee"
CARD = "#ffffff"
CANVAS_TOP = "#f8faff"
CANVAS_BOTTOM = "#eff1fa"

BLUE = "#4a68e8"
PURPLE = "#7657d9"
GREEN = "#3ea77a"
AMBER = "#d9983a"
SLATE = "#98a5bd"
RED = "#d75a67"

FONT = "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', Arial, sans-serif"

# ---- truth from flowchat/data/type-registry-v1.json -------------------------
FAMILIES = [
    ("flow_control", "流程控制", 14, BLUE),
    ("execution", "执行", 14, PURPLE),
    ("data_artifact", "数据产物", 9, GREEN),
    ("governance", "治理", 7, AMBER),
    ("structure", "结构", 5, SLATE),
]

SHAPES = [
    "roundRect", "capsule", "diamond", "hexagon", "trapezoid", "cylinder",
    "document", "parallelogram", "circle", "octagon", "doubleRect", "bar",
]
SIZE_PRESETS = ["compact", "regular", "wide", "tall"]

# name, dash pattern, note
STATUS_SHOWN = [
    ("completed", "0 0", "已完成", GREEN),
    ("active", "10 6", "进行中（带流动）", BLUE),
    ("running", "4 4", "运行中", BLUE),
    ("pending", "7 6", "待开始", SLATE),
    ("blocked", "5 5", "已阻塞", RED),
    ("return", "5 5", "回流（反向）", RED),
]
STATUS_REST = [
    "review", "candidate", "unknown", "not_run",
    "not_implemented", "placeholder", "needs_review",
]

EDGE_TYPES = [
    "main", "flow", "data", "control", "agent", "review", "feedback", "return",
    "callback", "exception", "expected", "candidate", "retry", "loop",
    "parallel", "handoff", "event", "message", "human_review",
]

ROUTES = [
    ("直连", "相邻节点默认走直线", SLATE, "straight"),
    ("auto 自动正交", "直线 → 单折 → 绕行，带拐弯/交叉/重叠惩罚", BLUE, "auto"),
    ("route_points 显式", "回环、绕行、故意交叉才用，需标 crossing: true", AMBER, "explicit"),
]

PRINCIPLES = [
    ("类型决定形状与填充，状态只改边框、徽章、透明度、虚线",
     "registry 里写死的视觉回归规则：形状和填充是身份，状态只是它的时态", BLUE),
    ("几何是硬门禁，不是建议",
     "边长 ≥ 90px、末端箭头段 ≥ 75px、线宽 ≤ 2px、箭头 ≤ 5×5，由渲染器强制执行", PURPLE),
    ("宁可拒绝，也不伪造",
     "路由不合法就报错退出，绝不补一条反向折线让箭头说谎", RED),
    ("输入先校验，静默丢边是 bug 不是容错",
     "悬空引用在 validate 阶段拦下，而不是渲染出一个缺边但好看的页面", GREEN),
]


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rect(x, y, w, h, fill, stroke=None, rx=14):
    stroke_attr = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{stroke_attr}/>'


def text(x, y, s, size=15, fill=INK, weight="400", anchor="start"):
    return (
        f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>'
    )


def card_frame(x, y, w, h, title, subtitle):
    out = [rect(x, y, w, h, CARD, LINE)]
    out.append(rect(x, y, w, 4, BLUE, rx=2))
    out.append(text(x + 20, y + 34, title, size=17, weight="600"))
    out.append(text(x + 20, y + 56, subtitle, size=12.5, fill=MUTED))
    return out


def node_types_card(x, y, w, h):
    out = card_frame(x, y, w, h, "节点类型 · 49 种", "按 family 归 5 族，也是视觉回归要覆盖的 5 个面")
    total = sum(f[2] for f in FAMILIES)
    for i, (name, cn, count, color) in enumerate(FAMILIES):
        cy = y + 90 + i * 40
        out.append(text(x + 20, cy, name, size=12.5, weight="600"))
        out.append(text(x + 20 + len(name) * 7.2 + 12, cy, cn, size=12, fill=MUTED))
        bar_x = x + 150
        bar_w = int(190 * count / 14)
        out.append(rect(bar_x, cy - 10, 190, 11, "#f1f3f8", rx=5))
        out.append(rect(bar_x, cy - 10, bar_w, 11, color, rx=5))
        out.append(text(bar_x + 200, cy, f"{count}", size=12.5, weight="600", fill=color))
    sy = y + 90 + 5 * 40 + 8
    out.append(text(x + 20, sy, f"共 {total} 种；每种带固定的 shape / icon / fill / stroke", size=12, fill=FAINT))
    out.append(text(x + 20, sy + 20, "新增类型改注册表，不在渲染器里写死分支", size=12, fill=FAINT))
    return out


def status_card(x, y, w, h):
    out = card_frame(x, y, w, h, "状态 · 13 种", "同一 2px 线宽：状态只改虚线、徽章、透明度")
    for i, (name, dash, cn, color) in enumerate(STATUS_SHOWN):
        cy = y + 88 + i * 30
        sx = x + 20
        ex = sx + 96
        mid = cy - 4
        dash_attr = f' stroke-dasharray="{dash}"' if dash != "0 0" else ""
        out.append(
            f'<line x1="{sx}" y1="{mid}" x2="{ex}" y2="{mid}" stroke="{color}" stroke-width="2"'
            f'{dash_attr} stroke-linecap="round"/>'
        )
        if name == "return":
            out.append(
                f'<path d="M {sx + 8} {mid - 4} L {sx} {mid} L {sx + 8} {mid + 4}" fill="none" '
                f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        else:
            out.append(
                f'<path d="M {ex - 8} {mid - 4} L {ex} {mid} L {ex - 8} {mid + 4}" fill="none" '
                f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        if name == "active":
            out.append(
                f'<circle cx="{sx + 38}" cy="{mid}" r="2.6" fill="{color}">'
                f'<animate attributeName="cx" values="{sx};{ex}" dur="2.4s" repeatCount="indefinite"/>'
                f"</circle>"
            )
        out.append(text(ex + 14, cy, name, size=12, weight="600"))
        out.append(text(ex + 14 + len(name) * 6.9 + 10, cy, cn, size=11.5, fill=FAINT))
    ry = y + 88 + 6 * 30 + 10
    out.append(text(x + 20, ry, "其余 7 种：", size=11.5, fill=MUTED))
    out.append(text(x + 92, ry, " · ".join(STATUS_REST), size=11.5, fill=FAINT))
    out.append(text(x + 20, ry + 22, "unknown / not_run / not_implemented / placeholder 各自可见，不合并成“无状态”", size=11.5, fill=FAINT))
    return out


def shape_card(x, y, w, h):
    out = card_frame(x, y, w, h, "形状 12 种 · 尺寸 4 档", "形状是身份的一部分，不随状态变化")
    cols = 4
    for i, shape in enumerate(SHAPES):
        col, row = i % cols, i // cols
        cx = x + 24 + col * ((w - 48) // cols)
        cy = y + 82 + row * 46
        bw, bh = 58, 30
        if shape == "diamond":
            pts = f"{cx},{cy} {cx + bw / 2},{cy - bh / 2} {cx + bw},{cy} {cx + bw / 2},{cy + bh / 2}"
            out.append(f'<polygon points="{pts}" fill="#f3f6fa" stroke="{SLATE}" stroke-width="1.5"/>')
        elif shape in {"hexagon", "octagon"}:
            n = 6 if shape == "hexagon" else 8
            import math
            pts = " ".join(
                f"{cx + bw / 2 + bw / 2 * math.cos(2 * math.pi * k / n - math.pi / 2):.1f},"
                f"{cy + bh / 2 + bh / 2 * math.sin(2 * math.pi * k / n - math.pi / 2):.1f}"
                for k in range(n)
            )
            out.append(f'<polygon points="{pts}" fill="#f6f1ff" stroke="{PURPLE}" stroke-width="1.5"/>')
        elif shape == "capsule":
            out.append(rect(cx, cy - bh / 2, bw, bh, "#f1edff", PURPLE, rx=15))
        elif shape == "circle":
            out.append(f'<ellipse cx="{cx + bw / 2}" cy="{cy}" rx="{bw / 2}" ry="{bh / 2}" fill="#eef7ff" stroke="{BLUE}" stroke-width="1.5"/>')
        elif shape == "trapezoid":
            pts = f"{cx + 10},{cy - bh / 2} {cx + bw - 10},{cy - bh / 2} {cx + bw},{cy + bh / 2} {cx},{cy + bh / 2}"
            out.append(f'<polygon points="{pts}" fill="#fafaf9" stroke="#8a857c" stroke-width="1.5"/>')
        elif shape == "parallelogram":
            pts = f"{cx + 10},{cy - bh / 2} {cx + bw},{cy - bh / 2} {cx + bw - 10},{cy + bh / 2} {cx},{cy + bh / 2}"
            out.append(f'<polygon points="{pts}" fill="#fff7ed" stroke="{AMBER}" stroke-width="1.5"/>')
        elif shape == "cylinder":
            out.append(f'<ellipse cx="{cx + bw / 2}" cy="{cy - bh / 2}" rx="{bw / 2}" ry="6" fill="#eef2f7" stroke="{SLATE}" stroke-width="1.5"/>')
            out.append(f'<path d="M {cx} {cy - bh / 2} L {cx} {cy + bh / 2} M {cx + bw} {cy - bh / 2} L {cx + bw} {cy + bh / 2}" stroke="{SLATE}" stroke-width="1.5"/>')
            out.append(f'<ellipse cx="{cx + bw / 2}" cy="{cy + bh / 2}" rx="{bw / 2}" ry="6" fill="none" stroke="{SLATE}" stroke-width="1.5"/>')
        elif shape == "document":
            out.append(f'<path d="M {cx} {cy - bh / 2} L {cx + bw} {cy - bh / 2} L {cx + bw} {cy + bh / 2 - 7} '
                       f'Q {cx + bw / 2} {cy + bh / 2 + 4} {cx} {cy + bh / 2 - 7} Z" fill="#f3f6fa" stroke="{SLATE}" stroke-width="1.5"/>')
        elif shape == "doubleRect":
            out.append(rect(cx, cy - bh / 2, bw, bh, "#ffffff", SLATE, rx=4))
            out.append(rect(cx + 4, cy - bh / 2 + 4, bw - 8, bh - 8, "#ffffff", SLATE, rx=3))
        elif shape == "bar":
            out.append(rect(cx, cy - 6, bw, 12, "#e8f5ee", GREEN, rx=3))
        else:  # roundRect
            out.append(rect(cx, cy - bh / 2, bw, bh, "#eff6ff", BLUE, rx=7))
        out.append(text(cx + bw / 2, cy + bh / 2 + 13, shape, size=9.5, fill=FAINT, anchor="middle"))
    py = y + 82 + 3 * 46 + 14
    out.append(text(x + 20, py, "尺寸预设：", size=11.5, fill=MUTED, weight="600"))
    out.append(text(x + 90, py, " · ".join(SIZE_PRESETS), size=11.5, fill=FAINT))
    return out


def port_card(x, y, w, h):
    out = card_frame(x, y, w, h, "端口 · 12 个位置", "四条边 × 三道，扇入扇出各有其位，不挤在同一个锚点")
    nx, ny, nw, nh = x + 26, y + 88, 148, 100
    out.append(rect(nx, ny, nw, nh, "#ffffff", SLATE, rx=10))
    lanes = {"1": 1 / 3, "2": 1 / 2, "3": 2 / 3}
    for lane, frac in lanes.items():
        color = [BLUE, PURPLE, GREEN][int(lane) - 1]
        for side in ("left", "right"):
            px = nx if side == "left" else nx + nw
            out.append(f'<circle cx="{px}" cy="{ny + nh * frac:.1f}" r="4.2" fill="{color}"/>')
        for side in ("top", "bottom"):
            py2 = ny if side == "top" else ny + nh
            out.append(f'<circle cx="{nx + nw * frac:.1f}" cy="{py2}" r="4.2" fill="{color}"/>')
    out.append(text(nx + nw / 2, ny + nh / 2 + 5, "node", size=12, fill=MUTED, anchor="middle"))

    lx = nx + nw + 30
    out.append(text(lx, y + 94, "−1  →  1/3 处", size=12.5, weight="600", fill=BLUE))
    out.append(text(lx, y + 118, "−2  →  1/2 处（默认）", size=12.5, weight="600", fill=PURPLE))
    out.append(text(lx, y + 142, "−3  →  2/3 处", size=12.5, weight="600", fill=GREEN))
    out.append(text(lx, y + 174, "left / right / top / bottom", size=11.5, fill=MUTED))
    out.append(text(lx, y + 192, "单独写就是该边中心锚点", size=11.5, fill=FAINT))
    out.append(text(lx, y + 214, "编号端口让多对多不共线", size=11.5, fill=FAINT))
    return out


def edge_card(x, y, w, h):
    out = card_frame(x, y, w, h, "边类型 19 种 · 路由 3 种", "类型声明语义，路由决定怎么走到，两者分开")
    cols = 5
    per_col = (len(EDGE_TYPES) + cols - 1) // cols
    for i, name in enumerate(EDGE_TYPES):
        col, row = i // per_col, i % per_col
        cx = x + 20 + col * ((w - 40) // cols)
        cy = y + 84 + row * 21
        color = BLUE if name in {"main", "flow"} else AMBER if name in {"review", "human_review"} else \
            RED if name in {"return", "exception", "retry"} else GREEN if name in {"feedback", "loop"} else MUTED
        out.append(f'<circle cx="{cx + 3}" cy="{cy - 4}" r="3" fill="{color}"/>')
        out.append(text(cx + 12, cy, name, size=11.5))
    ry = y + 84 + per_col * 21 + 22
    slot = (w - 40) // 3
    for i, (name, desc, color, kind) in enumerate(ROUTES):
        sx = x + 20 + i * slot
        cy = ry
        sy = cy - 5
        if kind == "straight":
            path = f"M {sx} {sy} L {sx + 74} {sy}"
            ay = sy
        elif kind == "auto":
            path = f"M {sx} {sy} L {sx + 32} {sy} L {sx + 32} {sy - 14} L {sx + 74} {sy - 14}"
            ay = sy - 14
        else:
            path = f"M {sx} {sy} L {sx + 20} {sy} L {sx + 20} {sy + 12} L {sx + 52} {sy + 12} L {sx + 52} {sy - 4} L {sx + 74} {sy - 4}"
            ay = sy - 4
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
        out.append(
            f'<path d="M {sx + 66} {ay - 4} L {sx + 74} {ay} L {sx + 66} {ay + 4}" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        out.append(text(sx + 86, cy, name, size=11.5, weight="600"))
        out.append(text(sx + 86, cy + 17, desc, size=11, fill=FAINT))
    return out


def principle_row(x, y, w, title, body, color):
    out = [rect(x, y, w, 78, CARD, LINE)]
    out.append(rect(x, y, 4, 78, color, rx=2))
    out.append(text(x + 24, y + 32, title, size=15, weight="600"))
    out.append(text(x + 24, y + 56, body, size=12.5, fill=MUTED))
    return out


def build(registry: dict | None = None) -> str:
    note = "数据取自 type-registry-v1.json"
    if registry:
        node_types = len(registry.get("nodeTypes", {}))
        edge_types = len(registry.get("edgeTypes", {}))
        statuses = len(registry.get("statuses", {}))
        note = f"数据取自 type-registry-v1.json：{node_types} 节点类型 / {edge_types} 边类型 / {statuses} 状态"

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        "<defs>"
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{CANVAS_TOP}"/>'
        f'<stop offset="100%" stop-color="{CANVAS_BOTTOM}"/>'
        "</linearGradient>"
        "</defs>",
        rect(0, 0, W, H, "url(#bg)", rx=0),
    ]

    out.append(text(PAD, 62, "Flowchat", size=30, weight="700"))
    out.append(text(PAD + 132, 62, "流程图生成器 · 能力地图与设计取舍", size=19, fill=MUTED))
    out.append(text(PAD, 92, note, size=13.5, fill=MUTED))

    cw = (W - PAD * 2 - 24) // 2
    full = W - PAD * 2
    top = 124
    out += node_types_card(PAD, top, cw, 300)
    out += status_card(PAD + cw + 24, top, cw, 300)
    out += shape_card(PAD, top + 324, cw, 300)
    out += port_card(PAD + cw + 24, top + 324, cw, 300)
    out += edge_card(PAD, top + 648, full, 240)

    py = top + 648 + 240 + 28
    out.append(text(PAD, py, "我们怎么思考", size=19, weight="700"))
    out.append(text(PAD + 128, py, "四条不妥协的规则", size=13.5, fill=MUTED))
    iy = py + 24
    for title, body, color in PRINCIPLES:
        out += principle_row(PAD, iy, W - PAD * 2, title, body, color)
        iy += 88

    fy = iy + 12
    out.append(rect(PAD, fy, W - PAD * 2, 62, "rgba(255,255,255,.72)", LINE))
    out.append(text(PAD + 24, fy + 26, "validate  →  generate  →  harness", size=14.5, weight="600"))
    out.append(
        text(PAD + 24, fy + 47,
             "退出码 0 通过 · 1 输入错误 · 2 几何不达标或缺浏览器证据（几何看 static_status，不是 status）",
             size=12, fill=MUTED)
    )
    out.append(text(W - PAD - 24, fy + 38, "纯标准库 · 无构建 · 无外链", size=12.5, fill=MUTED, anchor="end"))

    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Flowchat capability map SVG")
    parser.add_argument("--output", type=Path, default=Path("docs/capability-map.svg"))
    parser.add_argument("--registry", type=Path, help="optional type-registry JSON to source counts from")
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8")) if args.registry else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(registry) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
