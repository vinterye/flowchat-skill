#!/usr/bin/env python3
"""Render the Flowchat capability map as a standalone SVG.

Regenerate with:
    python3 tools/render_capability_map.py --output docs/capability-map.svg

Pure stdlib. The PNG shipped in the README is produced from this SVG.
"""
from __future__ import annotations

import argparse
from pathlib import Path

W = 1240
H = 1160
PAD = 40

INK = "#172033"
MUTED = "#485266"
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

KINDS = [
    ("orchestrator", "总控中枢", BLUE),
    ("control", "规则中心", BLUE),
    ("review-center", "评审中心", AMBER),
    ("stage", "主线阶段", PURPLE),
    ("dispatch", "并行派发", BLUE),
    ("agent", "执行单元", PURPLE),
    ("summary", "完成汇总", GREEN),
    ("gate", "准入门禁", AMBER),
    ("issue", "阻塞事件", RED),
    ("feedback", "反馈通道", GREEN),
]

STATUSES = [
    ("completed", "已完成", SLATE, "0 0", "none"),
    ("active", "进行中", BLUE, "0 0", "flow"),
    ("pending", "待开始", SLATE, "7 6", "none"),
    ("blocked", "已阻塞", RED, "5 5", "none"),
    ("return", "回流", RED, "5 5", "back"),
]

PRINCIPLES = [
    ("几何是硬门禁，不是建议", "边长 ≥ 90px、末端箭头段 ≥ 75px、线宽 ≤ 2px、箭头 ≤ 5×5 —— 由渲染器强制执行，不靠人自觉", BLUE),
    ("宁可拒绝，也不伪造", "路由不合法就报错退出，绝不补一条反向折线让箭头说谎", RED),
    ("状态靠虚线与动画，不靠加粗放大", "粗细是层级信号，不该被状态占用；重量留给结构，状态留给节奏", PURPLE),
    ("输入先校验，静默丢边是 bug 不是容错", "悬空引用在 validate 阶段拦下，而不是渲染出一个缺边但好看的页面", GREEN),
]

ROUTES = [
    ("直连", "相邻节点默认走直线，不需要任何声明", SLATE, "straight"),
    ("auto 自动正交", "先试直线 → 单折 → 绕行；带拐弯、交叉、重叠惩罚", BLUE, "auto"),
    ("route_points 显式", "回环、绕行、故意交叉才用；需标 crossing: true", AMBER, "explicit"),
]


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rect(x, y, w, h, fill, stroke=None, rx=14, opacity=1.0):
    stroke_attr = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'
        f'{stroke_attr} opacity="{opacity}"/>'
    )


def text(x, y, s, size=15, fill=INK, weight="400", anchor="start", spacing=None):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{extra}>{esc(s)}</text>'
    )


def card_frame(x, y, w, h, title, subtitle):
    out = [rect(x, y, w, h, CARD, LINE)]
    out.append(rect(x, y, w, 4, BLUE, rx=2))
    out.append(text(x + 20, y + 34, title, size=17, weight="600"))
    out.append(text(x + 20, y + 56, subtitle, size=12.5, fill=MUTED))
    return out


def kinds_card(x, y, w, h):
    out = card_frame(x, y, w, h, "节点 kind · 10 类", "语义决定形状与配色，不让使用者临场发挥")
    col_w = (w - 40) // 2
    for i, (name, cn, color) in enumerate(KINDS):
        col, row = i % 2, i // 2
        cx = x + 20 + col * col_w
        cy = y + 82 + row * 34
        out.append(rect(cx, cy - 9, 10, 10, color, rx=3))
        out.append(text(cx + 18, cy + 1, name, size=12.5, weight="600"))
        out.append(text(cx + 18 + len(name) * 7.2 + 10, cy + 1, cn, size=12, fill=MUTED))
    return out


def status_card(x, y, w, h):
    out = card_frame(x, y, w, h, "状态 status · 5 类", "同一个 2px 线宽，状态只改虚线与流动，不改粗细")
    for i, (name, cn, color, dash, kind) in enumerate(STATUSES):
        cy = y + 90 + i * 34
        sx = x + 20
        ex = sx + 108
        mid = cy - 5
        dash_attr = f' stroke-dasharray="{dash}"' if dash != "0 0" else ""
        if kind == "auto_flow" or kind == "flow":
            dash_attr += ' stroke-dasharray="10 6"'
        out.append(
            f'<line x1="{sx}" y1="{mid}" x2="{ex}" y2="{mid}" stroke="{color}" stroke-width="2"'
            f'{dash_attr} stroke-linecap="round"/>'
        )
        # arrow head
        if kind == "back":
            out.append(
                f'<path d="M {sx + 8} {mid - 4} L {sx} {mid} L {sx + 8} {mid + 4}" fill="none" '
                f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        else:
            out.append(
                f'<path d="M {ex - 8} {mid - 4} L {ex} {mid} L {ex - 8} {mid + 4}" fill="none" '
                f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        out.append(text(ex + 16, cy, name, size=12.5, weight="600"))
        out.append(text(ex + 16 + len(name) * 7.2 + 10, cy, cn, size=12, fill=MUTED))
        if kind == "flow":
            out.append(
                f'<circle cx="{sx + 40}" cy="{mid}" r="2.6" fill="{color}">'
                f'<animate attributeName="cx" values="{sx};{ex}" dur="2.4s" repeatCount="indefinite"/>'
                f"</circle>"
            )
    return out


def port_card(x, y, w, h):
    out = card_frame(x, y, w, h, "端口 port · 12 个锚点", "四条边 × 三道 = 1/3、1/2、2/3，扇入扇出各有其位")
    nx, ny, nw, nh = x + 28, y + 86, 150, 104
    out.append(rect(nx, ny, nw, nh, "#ffffff", SLATE, rx=10))
    lanes = {"1": 1 / 3, "2": 1 / 2, "3": 2 / 3}
    for lane, frac in lanes.items():
        color = [BLUE, PURPLE, GREEN][int(lane) - 1]
        for side in ("left", "right"):
            px = nx if side == "left" else nx + nw
            py = ny + nh * frac
            out.append(f'<circle cx="{px}" cy="{py:.1f}" r="4" fill="{color}"/>')
        for side in ("top", "bottom"):
            px = nx + nw * frac
            py = ny if side == "top" else ny + nh
            out.append(f'<circle cx="{px:.1f}" cy="{py}" r="4" fill="{color}"/>')
    out.append(text(nx + nw / 2, ny + nh / 2 + 5, "node", size=12, fill=MUTED, anchor="middle"))

    lx = nx + nw + 34
    out.append(text(lx, y + 92, "−1  →  1/3 处", size=12.5, weight="600", fill=BLUE))
    out.append(text(lx, y + 116, "−2  →  1/2 处（默认）", size=12.5, weight="600", fill=PURPLE))
    out.append(text(lx, y + 140, "−3  →  2/3 处", size=12.5, weight="600", fill=GREEN))
    out.append(text(lx, y + 172, "只写 left / right / top / bottom", size=12, fill=MUTED))
    out.append(text(lx, y + 190, "就是该边的中心锚点", size=12, fill=MUTED))
    return out


def route_card(x, y, w, h):
    out = card_frame(x, y, w, h, "路由 routing · 3 种策略", "相邻边交给自动路由，只有回环与绕行才显式声明")
    for i, (name, desc, color, kind) in enumerate(ROUTES):
        cy = y + 96 + i * 52
        sx, sy = x + 20, cy - 6
        if kind == "straight":
            path = f"M {sx} {sy} L {sx + 92} {sy}"
        elif kind == "auto":
            path = f"M {sx} {sy} L {sx + 40} {sy} L {sx + 40} {sy - 20} L {sx + 92} {sy - 20}"
        else:
            path = f"M {sx} {sy} L {sx + 26} {sy} L {sx + 26} {sy + 18} L {sx + 66} {sy + 18} L {sx + 66} {sy - 6} L {sx + 92} {sy - 6}"
        out.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        out.append(
            f'<path d="M {sx + 84} {sy - 6 - 4} L {sx + 92} {sy - 6} L {sx + 84} {sy - 6 + 4}" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            if kind == "explicit"
            else f'<path d="M {sx + 84} {sy - 4} L {sx + 92} {sy} L {sx + 84} {sy + 4}" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            if kind == "straight"
            else f'<path d="M {sx + 84} {sy - 20 - 4} L {sx + 92} {sy - 20} L {sx + 84} {sy - 20 + 4}" fill="none" '
            f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        out.append(text(sx + 108, cy, name, size=12.5, weight="600"))
        out.append(text(sx + 108, cy + 18, desc, size=11.5, fill=MUTED))
    return out


def principle_row(x, y, w, title, body, color):
    out = [rect(x, y, w, 78, CARD, LINE)]
    out.append(rect(x, y, 4, 78, color, rx=2))
    out.append(text(x + 24, y + 32, title, size=15.5, weight="600"))
    out.append(text(x + 24, y + 56, body, size=12.5, fill=MUTED))
    return out


def build() -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f"<defs>"
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{CANVAS_TOP}"/>'
        f'<stop offset="100%" stop-color="{CANVAS_BOTTOM}"/>'
        f"</linearGradient>"
        f"</defs>",
        rect(0, 0, W, H, "url(#bg)", rx=0),
    ]

    # header
    out.append(text(PAD, 62, "Flowchat", size=30, weight="700"))
    out.append(text(PAD + 132, 62, "功能地图与设计取舍", size=19, fill=MUTED))
    out.append(
        text(
            PAD,
            92,
            "一份 graph JSON → 一个自包含 HTML；配色、几何、状态语义全部由枚举收敛，而不是留给使用者临场发挥",
            size=13.5,
            fill=MUTED,
        )
    )

    # capability cards
    cw = (W - PAD * 2 - 24) // 2
    top = 128
    out += kinds_card(PAD, top, cw, 268)
    out += status_card(PAD + cw + 24, top, cw, 268)
    out += port_card(PAD, top + 292, cw, 268)
    out += route_card(PAD + cw + 24, top + 292, cw, 268)

    # principles
    py = top + 292 + 292
    out.append(text(PAD, py, "我们怎么思考", size=19, weight="700"))
    out.append(text(PAD + 128, py, "四条不妥协的规则", size=13.5, fill=MUTED))
    iy = py + 24
    for title, body, color in PRINCIPLES:
        out += principle_row(PAD, iy, W - PAD * 2, title, body, color)
        iy += 88

    # footer
    fy = iy + 12
    out.append(rect(PAD, fy, W - PAD * 2, 62, "rgba(255,255,255,.72)", LINE))
    out.append(text(PAD + 24, fy + 26, "validate  →  generate  →  harness", size=14.5, weight="600"))
    out.append(
        text(
            PAD + 24,
            fy + 47,
            "退出码 0 通过 · 1 输入错误 · 2 几何不达标或缺浏览器证据（几何看 static_status，不是 status）",
            size=12,
            fill=MUTED,
        )
    )
    out.append(text(W - PAD - 24, fy + 38, "纯标准库 · 无构建 · 无外链", size=12.5, fill=MUTED, anchor="end"))

    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Flowchat capability map SVG")
    parser.add_argument("--output", type=Path, default=Path("docs/capability-map.svg"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build() + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
