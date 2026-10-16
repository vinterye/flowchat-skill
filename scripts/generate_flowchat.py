#!/usr/bin/env python3
"""Generate a self-contained Flowchat HTML document from graph and theme JSON."""

from __future__ import annotations

import argparse
import heapq
import html
import json
import math
import re
from pathlib import Path
from typing import Any


# Routing contract constants. They mirror the harness thresholds: a route that
# violates them is rejected at generation time rather than in the browser.
MIN_EDGE_LENGTH = 90.0
MIN_ARROW_SEGMENT = 75.0
MIN_SEGMENT = 8.0
# Cost per pixel of distance between a bend and the midpoint of the gap. Small
# enough that it never buys an extra bend (a bend costs 22), large enough to
# pick the centred corner among equal-length candidates.
CENTRE_PENALTY = 0.06

DEFAULT_THEME: dict[str, Any] = {
    "canvas": "linear-gradient(135deg,#f8faff,#f1f2fb)",
    "panel": "rgba(255,255,255,.62)",
    "node_fill": "#ffffff",
    "node_stroke": "#dce2ee",
    "diamond_fill": "#ffffff",
    "square_fill": "#ffffff",
    "agent_fill": "#ffffff",
    "agent_stroke": "#7657d9",
    "dispatch_fill": "#ffffff",
    "dispatch_stroke": "#4a68e8",
    "review_fill": "#fffaf0",
    "review_stroke": "#d9983a",
    "feedback_fill": "#f2fbf6",
    "blocked_fill": "#fff5f5",
    "blocked_stroke": "#d75a67",
    "phase_pre_stroke": "#4a68e8",
    "phase_mid_stroke": "#7657d9",
    "phase_post_stroke": "#3ea77a",
    "phase_unknown_stroke": "#98a5bd",
    "ready_stroke": "#3ea77a",
    "candidate_stroke": "#d9983a",
    "needs_review_stroke": "#98a5bd",
    "edge": "#98a5bd",
    "edge_completed": "#72c3a2",
    "edge_active": "#4a68e8",
    "edge_pending": "#98a5bd",
    "edge_blocked": "#d75a67",
    "edge_return": "#d75a67",
    "edge_feedback": "#3ea77a",
    "edge_review": "#d9983a",
    "text": "#172033",
    "muted": "#7b8495",
    "accent": "#4a68e8",
    "edge_stroke_width": "2",
    "arrow_marker_width": "5",
    "arrow_marker_height": "5",
    "arrow_marker_ref_x": "4",
    "arrow_marker_ref_y": "2",
}


def _load_type_registry() -> dict[str, Any]:
    """Load the reusable node/edge/status contract shipped with the skill."""
    registry_path = Path(__file__).resolve().parents[1] / "data" / "type-registry-v1.json"
    try:
        return json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Keep the renderer usable when copied as a single script.  The normal
        # repository path always uses the checked-in registry file above.
        return {
            "schema": "flowchat-type-registry/v1",
            "nodeTypes": {},
            "edgeTypes": {},
            "statuses": {},
        }


TYPE_REGISTRY = _load_type_registry()
NODE_TYPE_REGISTRY = TYPE_REGISTRY.get("nodeTypes", {})
EDGE_TYPE_REGISTRY = TYPE_REGISTRY.get("edgeTypes", {})
STATUS_REGISTRY = TYPE_REGISTRY.get("statuses", {})
SIZE_PRESETS = TYPE_REGISTRY.get("sizePresets", {
    "compact": {"width": 132, "height": 56},
    "regular": {"width": 156, "height": 88},
    "wide": {"width": 220, "height": 88},
    "tall": {"width": 180, "height": 120},
})
ICON_GLYPHS = {
    "play": "▶", "stop": "■", "process": "•", "decision": "◇", "rule": "⚖", "gate": "◇",
    "hand": "☝", "agent": "◎", "controller": "◎", "expert": "✦", "skill": "✧", "harness": "✓",
    "tool": "⌘", "runtime": "◌", "api": "⌁", "database": "▤", "document": "▱", "artifact": "✓",
    "review": "✓", "input": "←", "output": "→", "event": "·", "error": "!", "wait": "◷",
    "subflow": "▣", "reference": "↗", "external": "↔", "stage": "01", "control": "◈", "dispatch": "⑂",
    "summary": "Σ", "issue": "!", "feedback": "↺", "fork": "⑂", "join": "⊔", "merge": "◇",
    "retry": "↻", "loop": "↺", "timer": "◷", "queue": "▤", "message": "✉", "webhook": "⌁",
    "checkpoint": "◆", "milestone": "◇", "parallel": "⑂", "human": "♙", "fallback": "!",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _load(path: Path | None, fallback: Any) -> Any:
    if path is None:
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _demo_graph() -> dict[str, Any]:
    """A layered topology sample for the reusable standalone Flowchat skill."""
    stages = [
        ("stage-research", "01\n竞品研究\n✓ 已完成", 20, "completed", "pre", "ready"),
        ("stage-requirements", "02\n需求整理\n✓ 已完成", 250, "completed", "pre", "ready"),
        ("stage-planning", "03\n产品规划\n● 进行中", 480, "active", "mid", "candidate"),
        ("stage-design", "04\n界面设计\n待审核", 710, "review", "mid", "needs_review"),
        ("stage-interaction", "05\n交互设计\n待流转", 940, "pending", "mid", "needs_review"),
        ("stage-development", "06\n开发实现\n阻塞", 1170, "blocked", "mid", "candidate"),
        ("stage-release", "07\n上线发布\n待流转", 1400, "pending", "post", "candidate"),
    ]
    nodes: list[dict[str, Any]] = [
        {"id": "rules-center", "label": "◈ 规则中心\nRules Center\n当前生效 12\n阶段 7 · 审核 3 · 安全 2\n常驻 · 按需", "shape": "rect", "x": 30, "y": 20, "width": 260, "height": 110, "status": "active", "kind": "control", "phase": "unknown", "readiness": "ready", "order": -2},
        {
            "id": "control-brain", "label": "◎ 总控大脑\nOrchestrator Hub\n当前：03 产品规划\n调度 3 Agents\n目标理解 · 任务拆解\n过程监控 · 结果汇总 · 反馈优化",
            "shape": "rect", "x": 430, "y": 20, "width": 760, "height": 156.25,
            "status": "active", "kind": "orchestrator", "phase": "unknown", "readiness": "ready", "order": -1,
        },
        {"id": "review-center", "label": "✓ 审核中心\nReview Center\n待审核 1 · 已通过 2 · 打回 1\nAI · 人工 · 混合审核", "shape": "rect", "x": 1310, "y": 20, "width": 260, "height": 110, "status": "review", "kind": "review-center", "phase": "unknown", "readiness": "needs_review", "order": -1},
        *({"id": node_id, "label": label, "shape": "rect", "x": x, "y": 185, "width": 130, "height": 86,
           "status": status, "kind": "stage", "phase": phase, "readiness": readiness, "order": i}
          for i, (node_id, label, x, status, phase, readiness) in enumerate(stages)),
        {"id": "agent-dispatch", "label": "⑂ Agent Dispatch\n并行调度 · 3 Agents\n分派 / 监控 / 回收", "shape": "rect", "x": 470, "y": 346, "width": 220, "height": 64, "status": "active", "kind": "dispatch", "phase": "mid", "readiness": "candidate", "order": 20},
        {"id": "research-agent", "label": "用户研究 Agent\nResearch / Ready", "shape": "rect", "x": 360, "y": 500, "width": 180, "height": 84, "status": "completed", "kind": "agent", "phase": "mid", "readiness": "ready", "order": 21},
        {"id": "ui-agent", "label": "UI 设计 Agent\nDesign / Running", "shape": "rect", "x": 570, "y": 500, "width": 180, "height": 84, "status": "active", "kind": "agent", "phase": "mid", "readiness": "candidate", "order": 22},
        {"id": "api-agent", "label": "接口分析 Agent\nAPI / Blocked", "shape": "rect", "x": 780, "y": 500, "width": 180, "height": 84, "status": "blocked", "kind": "agent", "phase": "mid", "readiness": "candidate", "order": 23},
        {"id": "stage-summary", "label": "◎ Summary Gate\n阶段汇总 · 执行完成度\n2 / 3 Agent Ready\nArtifact / 阻塞检查通过", "shape": "rect", "x": 500, "y": 665, "width": 300, "height": 95, "status": "active", "kind": "summary", "phase": "mid", "readiness": "ready", "order": 24},
        {"id": "blocked-event", "label": "⚠ Issue Event\n接口契约边界不完整\n来源：接口分析 Agent\n影响：开发实现\n返回：产品规划", "shape": "rect", "x": 1050, "y": 525, "width": 260, "height": 150, "status": "blocked", "kind": "issue", "phase": "unknown", "readiness": "needs_review", "order": 25},
        {"id": "design-review", "label": "◇ Review Gate\n当前阶段审核\n通过 → 交互设计\n打回 → 产品规划", "shape": "rect", "x": 760, "y": 330, "width": 220, "height": 90, "status": "review", "kind": "gate", "phase": "mid", "readiness": "needs_review", "order": 26},
        {"id": "execution-receipt", "label": "运行回执\nExecution Receipt", "shape": "rect", "x": 250, "y": 820, "width": 150, "height": 60, "status": "completed", "kind": "feedback", "phase": "post", "readiness": "ready", "order": 30},
        {"id": "quality-metrics", "label": "质量指标\nQuality Metrics", "shape": "rect", "x": 500, "y": 820, "width": 150, "height": 60, "status": "completed", "kind": "feedback", "phase": "post", "readiness": "ready", "order": 31},
        {"id": "rule-proposal", "label": "规则建议\nRule Proposal\n待审核后生效", "shape": "rect", "x": 760, "y": 810, "width": 180, "height": 80, "status": "active", "kind": "feedback", "phase": "post", "readiness": "candidate", "order": 32},
        {"id": "rule-review", "label": "规则审核\nRule Review\n批准后进入规则中心", "shape": "rect", "x": 1040, "y": 810, "width": 180, "height": 80, "status": "review", "kind": "gate", "phase": "post", "readiness": "needs_review", "order": 33},
        {"id": "next-plan", "label": "下一轮规划\nNext Plan", "shape": "rect", "x": 1320, "y": 820, "width": 150, "height": 60, "status": "pending", "kind": "feedback", "phase": "post", "readiness": "candidate", "order": 34},
    ]
    edges = [
        {"id": "rules-to-orchestrator", "source": "rules-center", "target": "control-brain", "status": "active", "kind": "control", "source_side": "right", "target_side": "left", "route_points": [[290, 75], [430, 75]]},
        {"id": "review-to-orchestrator", "source": "review-center", "target": "control-brain", "status": "active", "kind": "review", "source_side": "left", "target_side": "right", "route_points": [[1310, 75], [1190, 75]]},
        {"id": "rules-to-review-gate", "source": "rules-center", "target": "design-review", "status": "active", "kind": "control", "source_side": "bottom", "target_side": "right", "target_port": "right-1", "route_points": [[160, 130], [160, 300], [1055, 300], [1055, 360], [980, 360]], "label": "规则约束"},
        {"id": "review-center-to-gate", "source": "review-center", "target": "design-review", "status": "active", "kind": "review", "source_side": "right", "target_side": "right", "target_port": "right-3", "route_points": [[1570, 75], [1580, 75], [1580, 300], [1130, 300], [1130, 390], [980, 390]], "label": "发起审核"},
        {"id": "control-to-research", "source": "control-brain", "target": "stage-research", "status": "active", "kind": "control", "source_side": "left", "target_side": "left", "route_points": [[430, 100], [400, 100], [400, 150], [-55, 150], [-55, 228], [20, 228]]},
        {"id": "main-1", "source": "stage-research", "target": "stage-requirements", "status": "completed", "kind": "main"},
        {"id": "main-2", "source": "stage-requirements", "target": "stage-planning", "status": "active", "kind": "main", "label": "刚刚流转", "label_x": 365, "label_y": 160},
        {"id": "main-3", "source": "stage-design", "target": "stage-interaction", "status": "pending", "kind": "main", "source_side": "right", "target_side": "left"},
        {"id": "main-4", "source": "stage-interaction", "target": "stage-development", "status": "pending", "kind": "main"},
        {"id": "main-5", "source": "stage-development", "target": "stage-release", "status": "pending", "kind": "main"},
        {"id": "planning-dispatch", "source": "stage-planning", "target": "agent-dispatch", "status": "active", "kind": "agent", "source_side": "right", "target_side": "top", "route_points": [[610, 228], [625, 228], [625, 271], [650, 271], [650, 346]]},
        {"id": "dispatch-research", "source": "agent-dispatch", "target": "research-agent", "status": "completed", "kind": "agent", "source_side": "bottom", "source_port": "bottom-1", "target_side": "top", "route_points": [[543.3333333333333, 410], [543.3333333333333, 425], [450, 425], [450, 500]]},
        {"id": "dispatch-ui", "source": "agent-dispatch", "target": "ui-agent", "status": "active", "kind": "agent", "source_side": "bottom", "source_port": "bottom-2", "target_side": "top", "route_points": [[580, 410], [580, 425], [660, 425], [660, 500]]},
        {"id": "dispatch-api", "source": "agent-dispatch", "target": "api-agent", "status": "blocked", "kind": "agent", "source_side": "bottom", "source_port": "bottom-3", "target_side": "top", "route_points": [[616.6666666666666, 410], [616.6666666666666, 425], [870, 425], [870, 500]]},
        {"id": "research-result", "source": "research-agent", "target": "stage-summary", "status": "completed", "kind": "agent-result", "source_side": "bottom", "target_side": "left", "target_port": "left-1", "route_points": [[450, 584], [450, 592], [420, 592], [420, 696.6666666666666], [500, 696.6666666666666]]},
        {"id": "ui-result", "source": "ui-agent", "target": "stage-summary", "status": "active", "kind": "agent-result", "source_side": "bottom", "target_side": "left", "target_port": "left-2", "route_points": [[660, 584], [660, 592], [410, 592], [410, 712.5], [500, 712.5]]},
        {"id": "api-result", "source": "api-agent", "target": "blocked-event", "status": "blocked", "kind": "issue", "source_side": "bottom", "target_side": "left", "route_points": [[870, 584], [870, 620], [975, 620], [975, 600], [1050, 600]], "label": "接口边界问题", "label_x": 1010, "label_y": 610},
        {"id": "summary-to-review", "source": "stage-summary", "target": "design-review", "status": "active", "kind": "gate", "crossing": True, "source_side": "right", "target_side": "bottom", "target_port": "bottom-1", "route_points": [[800, 712.5], [1020, 712.5], [1020, 495], [833.3333333333334, 495], [833.3333333333334, 420]], "label": "Ready → Review", "label_x": 930, "label_y": 480},
        {"id": "design-to-review", "source": "stage-design", "target": "design-review", "status": "pending", "kind": "review", "source_side": "right", "target_side": "top", "route_points": [[840, 228], [870, 228], [870, 330]]},
        {"id": "review-pass-interaction", "source": "design-review", "target": "stage-interaction", "status": "pending", "kind": "review", "crossing": True, "source_side": "right", "target_side": "left", "target_port": "left-1", "route_points": [[980, 375], [1100, 375], [1100, 300], [865, 300], [865, 213.66666666666666], [940, 213.66666666666666]], "label": "通过", "label_x": 1020, "label_y": 195},
        {"id": "review-rework-planning", "source": "design-review", "target": "stage-planning", "status": "return", "kind": "return", "source_side": "left", "target_side": "right", "target_port": "right-1", "route_points": [[760, 375], [700, 375], [700, 213.66666666666666], [610, 213.66666666666666]], "label": "打回 · 返回产品规划", "label_x": 650, "label_y": 360},
        {"id": "issue-to-planning", "source": "blocked-event", "target": "stage-planning", "status": "return", "kind": "return", "crossing": True, "source_side": "left", "target_side": "left", "route_points": [[1050, 630], [1000, 630], [1000, 480], [200, 480], [200, 303], [405, 303], [405, 228], [480, 228]], "label": "返工：接口边界需重新确认", "label_x": 750, "label_y": 450},
        {"id": "release-receipt", "source": "stage-release", "target": "execution-receipt", "status": "pending", "kind": "feedback", "source_side": "bottom", "target_side": "top", "route_points": [[1465, 271], [1465, 790], [430, 790], [430, 745], [375, 745], [375, 820]]},
        {"id": "feedback-1", "source": "execution-receipt", "target": "quality-metrics", "status": "completed", "kind": "feedback"},
        {"id": "feedback-2", "source": "quality-metrics", "target": "rule-proposal", "status": "active", "kind": "feedback"},
        {"id": "feedback-3", "source": "rule-proposal", "target": "rule-review", "status": "pending", "kind": "feedback"},
        {"id": "rule-review-to-rules", "source": "rule-review", "target": "rules-center", "status": "pending", "kind": "feedback", "crossing": True, "source_side": "bottom", "target_side": "right", "target_port": "right-1", "route_points": [[1130, 890], [1130, 920], [1580, 920], [1580, 0], [365, 0], [365, 56.666666666666664], [290, 56.666666666666664]], "label": "审核通过 → 生效规则", "label_x": 1450, "label_y": 145},
        {"id": "rule-review-to-next", "source": "rule-review", "target": "next-plan", "status": "pending", "kind": "feedback", "source_side": "right", "target_side": "left", "route_points": [[1220, 850], [1320, 850]]},
        {"id": "feedback-loop", "source": "next-plan", "target": "control-brain", "status": "pending", "kind": "feedback", "source_side": "right", "target_side": "right", "route_points": [[1470, 850], [1595, 850], [1595, 160], [1265, 160], [1190, 160]], "label": "下一轮规划 → 总控大脑", "label_x": 1370, "label_y": 145},
    ]
    # Control centers govern the orchestrator and the active gate through their
    # node semantics; keep those policies in the detail panel instead of drawing
    # long cross-canvas rails that obscure the business topology.
    edges = [edge for edge in edges if edge.get("id") not in {"control-to-research", "rules-to-review-gate", "review-center-to-gate"}]
    return {"viewBox": [0, 0, 1600, 960], "nodes": nodes, "edges": edges, "subflows": _demo_subflows(), "architecture": _demo_architecture()}


def _demo_subflows() -> dict[str, dict[str, Any]]:
    """Stage-local process maps used when a stage card is opened."""
    specs = {
        "stage-research": {
            "title": "竞品研究 · 阶段流程",
            "entry": "进入条件：需求范围已确认",
            "next": "输出研究简报后进入需求整理",
            "loop": "资料缺口 → 返回资料检索",
            "handoff": "进入：需求整理",
            "nodes": [("research-input", "输入需求", 190, 300, "active"), ("research-search", "资料检索", 430, 300, "active"), ("research-matrix", "竞品矩阵", 670, 300, "pending"), ("research-output", "输出研究简报", 910, 300, "pending"), ("research-review", "资料缺口", 670, 520, "review")],
            "edges": [("research-input", "research-search", "active", [[320,343],[430,343]]), ("research-search", "research-matrix", "active", [[560,343],[670,343]]), ("research-matrix", "research-output", "pending", [[800,343],[910,343]]), ("research-review", "research-search", "return", [[670,565],[500,565],[500,386],[495,386]])],
        },
        "stage-requirements": {
            "title": "需求整理 · 阶段流程",
            "entry": "进入条件：研究结论已交接",
            "next": "正式需求包确认后进入产品规划",
            "loop": "评审不通过 → 返回需求归并",
            "handoff": "进入：产品规划",
            "nodes": [("req-input", "碎片需求", 190, 300, "active"), ("req-merge", "需求归并", 430, 300, "active"), ("req-review", "需求评审", 670, 300, "review"), ("req-output", "正式需求包", 910, 300, "pending"), ("req-rework", "补充需求", 670, 520, "return")],
            "edges": [("req-input", "req-merge", "active", [[320,343],[430,343]]), ("req-merge", "req-review", "active", [[560,343],[670,343]]), ("req-review", "req-output", "pending", [[800,343],[910,343]]), ("req-rework", "req-merge", "return", [[670,565],[500,565],[500,386],[495,386]])],
        },
        "stage-planning": {
            "title": "产品规划 · 阶段流程",
            "entry": "进入条件：正式需求包已确认",
            "next": "产品规划输出通过后进入界面设计",
            "loop": "方案评审不通过 → 返回目标拆解",
            "handoff": "进入：界面设计",
            "nodes": [("plan-goal", "目标拆解", 190, 300, "active"), ("plan-priority", "优先级排序", 430, 300, "active"), ("plan-review", "方案评审", 670, 300, "review"), ("plan-output", "产品规划输出", 910, 300, "pending"), ("plan-rework", "调整方案", 670, 520, "return")],
            "edges": [("plan-goal", "plan-priority", "active", [[320,343],[430,343]]), ("plan-priority", "plan-review", "active", [[560,343],[670,343]]), ("plan-review", "plan-output", "pending", [[800,343],[910,343]]), ("plan-rework", "plan-goal", "return", [[670,565],[500,565],[500,386],[255,386]])],
        },
        "stage-design": {
            "title": "界面设计 · 阶段流程",
            "entry": "进入条件：产品规划输出已通过",
            "next": "设计交付确认后进入交互设计",
            "loop": "视觉方向需调整 → 返回视觉探索",
            "handoff": "进入：交互设计",
            "nodes": [("design-check", "设计输入检查", 190, 300, "active"), ("design-explore", "视觉探索", 430, 300, "active"), ("design-build", "界面设计", 670, 300, "pending"), ("design-output", "设计交付", 910, 300, "pending"), ("design-rework", "方向调整", 670, 520, "return")],
            "edges": [("design-check", "design-explore", "active", [[320,343],[430,343]]), ("design-explore", "design-build", "active", [[560,343],[670,343]]), ("design-build", "design-output", "pending", [[800,343],[910,343]]), ("design-rework", "design-explore", "return", [[670,565],[500,565],[500,386],[495,386]])],
        },
        "stage-interaction": {
            "title": "交互设计 · 阶段流程",
            "entry": "进入条件：设计交付已确认",
            "next": "交互输出确认后进入开发实现",
            "loop": "可用性问题 → 返回原型串联",
            "handoff": "进入：开发实现",
            "nodes": [("interaction-input", "交互方案", 190, 300, "active"), ("interaction-prototype", "原型串联", 430, 300, "active"), ("interaction-check", "可用性检查", 670, 300, "review"), ("interaction-output", "交互输出", 910, 300, "pending"), ("interaction-rework", "体验问题", 670, 520, "return")],
            "edges": [("interaction-input", "interaction-prototype", "active", [[320,343],[430,343]]), ("interaction-prototype", "interaction-check", "active", [[560,343],[670,343]]), ("interaction-check", "interaction-output", "pending", [[800,343],[910,343]]), ("interaction-rework", "interaction-prototype", "return", [[670,565],[500,565],[500,386],[495,386]])],
        },
        "stage-development": {
            "title": "开发实现 · 阶段流程",
            "entry": "进入条件：交互输出已确认",
            "next": "联调验证通过后进入上线发布",
            "loop": "接口问题 → 返回接口实现",
            "handoff": "进入：上线发布",
            "nodes": [("dev-plan", "技术方案", 190, 300, "active"), ("dev-api", "接口实现", 430, 300, "active"), ("dev-test", "联调验证", 670, 300, "review"), ("dev-output", "开发输出", 910, 300, "pending"), ("dev-issue", "接口问题", 670, 520, "blocked")],
            "edges": [("dev-plan", "dev-api", "active", [[320,343],[430,343]]), ("dev-api", "dev-test", "active", [[560,343],[670,343]]), ("dev-test", "dev-output", "pending", [[800,343],[910,343]]), ("dev-issue", "dev-api", "return", [[670,565],[500,565],[500,386],[495,386]])],
        },
        "stage-release": {
            "title": "上线发布 · 阶段流程",
            "entry": "进入条件：开发输出已验收",
            "next": "运行回执回到总控并开启下一轮规划",
            "loop": "发布异常 → 返回灰度发布",
            "handoff": "回到：总控大脑",
            "nodes": [("release-check", "发布检查", 190, 300, "active"), ("release-gray", "灰度发布", 430, 300, "active"), ("release-receipt", "运行回执", 670, 300, "pending"), ("release-next", "下一轮规划", 910, 300, "pending"), ("release-rollback", "回滚处理", 670, 520, "blocked")],
            "edges": [("release-check", "release-gray", "active", [[320,343],[430,343]]), ("release-gray", "release-receipt", "active", [[560,343],[670,343]]), ("release-receipt", "release-next", "pending", [[800,343],[910,343]]), ("release-rollback", "release-gray", "return", [[670,565],[500,565],[500,386],[495,386]])],
        },
    }
    result: dict[str, dict[str, Any]] = {}
    for stage_id, spec in specs.items():
        nodes = [{"id": node_id, "label": label, "shape": "rect", "x": x, "y": y, "width": 190, "height": 86, "status": status, "kind": "subflow-step", "phase": "mid", "readiness": "candidate", "order": index} for index, (node_id, label, x, y, status) in enumerate(spec["nodes"])]
        output_id = spec["nodes"][3][0]
        handoff_id = f"{stage_id}-handoff"
        nodes.append({"id": handoff_id, "label": spec["handoff"], "shape": "rect", "x": 1240, "y": 300, "width": 240, "height": 86, "status": "pending", "kind": "handoff", "phase": "post", "readiness": "candidate", "order": 10})
        edges = [{"id": f"{stage_id}-{index}", "source": source, "target": target, "status": status, "kind": "subflow", "route_points": route} for index, (source, target, status, route) in enumerate(spec["edges"])]
        edges.append({"id": f"{stage_id}-handoff-edge", "source": output_id, "target": handoff_id, "status": "pending", "kind": "handoff", "route_points": [[1100, 343], [1240, 343]]})
        result[stage_id] = {"title": spec["title"], "entry": spec["entry"], "next": spec["next"], "loop": spec["loop"], "review_policy": "AI + 人工：Artifact 完整性、质量一致性、人工确认", "nodes": nodes, "edges": edges}
    return result


def _demo_architecture() -> dict[str, Any]:
    """High-level agent engineering layers; each capability stays one node."""
    nodes = [
        {"id": "arch-guide", "label": "项目说明\nAGENTS.md\n目标 / 入口 / 约定", "x": 90, "y": 160, "width": 220, "height": 90, "kind": "architecture", "status": "active"},
        {"id": "arch-permissions", "label": "权限设置\nSettings\n允许 / 禁止", "x": 350, "y": 160, "width": 220, "height": 90, "kind": "architecture", "status": "pending"},
        {"id": "arch-rules", "label": "规则\nRules\n常驻 / 按需", "x": 610, "y": 160, "width": 220, "height": 90, "kind": "architecture", "status": "active"},
        {"id": "arch-commands", "label": "命令\nCommands\n显式触发", "x": 870, "y": 160, "width": 220, "height": 90, "kind": "architecture", "status": "pending"},
        {"id": "arch-skills", "label": "技能\nSkills\n可复用方法", "x": 220, "y": 450, "width": 220, "height": 90, "kind": "architecture", "status": "active"},
        {"id": "arch-agents", "label": "子智能体\nAgents\n专职执行", "x": 500, "y": 450, "width": 220, "height": 90, "kind": "architecture", "status": "active"},
        {"id": "arch-harness", "label": "Harness / Hooks\n门禁与证据\n统一校验", "x": 780, "y": 450, "width": 220, "height": 90, "kind": "architecture", "status": "active"},
        {"id": "arch-tools", "label": "工具 / MCP\nTools\n连接外部系统", "x": 1060, "y": 450, "width": 220, "height": 90, "kind": "architecture", "status": "pending"},
        {"id": "arch-output", "label": "产出与回执\nOutput / Evidence\n可追溯", "x": 1340, "y": 450, "width": 210, "height": 90, "kind": "architecture-output", "status": "pending"},
    ]
    edges = [
        {"id": "arch-1", "source": "arch-guide", "target": "arch-permissions", "status": "active", "route_points": [[310,205],[350,205]]},
        {"id": "arch-2", "source": "arch-permissions", "target": "arch-rules", "status": "pending", "route_points": [[570,205],[610,205]]},
        {"id": "arch-3", "source": "arch-rules", "target": "arch-commands", "status": "active", "route_points": [[830,205],[870,205]]},
        {"id": "arch-4", "source": "arch-commands", "target": "arch-skills", "status": "pending", "route_points": [[980,250],[980,390],[330,390],[330,450]]},
        {"id": "arch-5", "source": "arch-skills", "target": "arch-agents", "status": "active", "route_points": [[440,495],[500,495]]},
        {"id": "arch-6", "source": "arch-agents", "target": "arch-harness", "status": "active", "route_points": [[720,495],[780,495]]},
        {"id": "arch-7", "source": "arch-harness", "target": "arch-tools", "status": "pending", "route_points": [[1000,495],[1060,495]]},
        {"id": "arch-8", "source": "arch-tools", "target": "arch-output", "status": "pending", "route_points": [[1280,495],[1340,495]]},
        {"id": "arch-feedback", "source": "arch-harness", "target": "arch-rules", "status": "return", "route_points": [[890,450],[890,350],[720,350],[720,250]]},
    ]
    return {"title": "Agent 工程分层架构", "nodes": nodes, "edges": edges}


def _centered_source_x(source: dict[str, Any], targets: list[dict[str, Any]]) -> float:
    """Return the x coordinate that keeps a source centered over its targets."""
    centers = sorted(float(target["x"]) + float(target["width"]) / 2 for target in targets)
    if not centers:
        return float(source["x"])
    # 1→1 uses the only target, 1→2 uses the two-target midpoint, and 1→3
    # (and larger fan-outs) uses the median target center as its visual axis.
    axis = centers[0] if len(centers) == 1 else (sum((centers[0], centers[-1])) / 2 if len(centers) == 2 else centers[len(centers) // 2])
    return axis - float(source["width"]) / 2


def _infer_semantic_sides(source: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    """Choose horizontal-first ports for diagonal relationships.

    A diagonal edge leaves the source through the side facing the target and
    enters the target through the vertical side that keeps the final segment
    vertical. This makes a lower-left source go right, then up, instead of
    drawing an illegal direct diagonal or leaving through its top edge.
    """
    source_cx = float(source["x"]) + float(source["width"]) / 2
    source_cy = float(source["y"]) + float(source["height"]) / 2
    target_cx = float(target["x"]) + float(target["width"]) / 2
    target_cy = float(target["y"]) + float(target["height"]) / 2
    dx, dy = target_cx - source_cx, target_cy - source_cy
    tolerance = max(12.0, min(float(source["width"]), float(target["width"])) * 0.12)
    if abs(dx) <= tolerance:
        return ("bottom", "top") if dy >= 0 else ("top", "bottom")
    if abs(dy) <= tolerance:
        return ("right", "left") if dx >= 0 else ("left", "right")
    # Diagonal links always travel horizontally first. The target receives
    # the vertical leg from below or above, which keeps the arrow readable.
    # For a diagonal relation choose the dominant axis. This keeps the first
    # leg in the direction of the larger center-to-center offset and leaves the
    # other axis for the corridor turn. A lower-left source therefore exits
    # right when the horizontal offset dominates, while an upper-left source
    # exits bottom when the vertical offset dominates.
    if abs(dx) >= abs(dy):
        source_side = "right" if dx > 0 else "left"
        target_side = "left" if dx > 0 else "right"
    else:
        source_side = "bottom" if dy > 0 else "top"
        # A vertical relation still enters through a vertical side once the
        # horizontal offset is wide enough for a readable horizontal arrow:
        # half the target width keeps the leg clear of the node it enters, and
        # MIN_ARROW_SEGMENT keeps the arrow itself away from the edge.
        # Below that threshold the line must enter the top/bottom midpoint,
        # because a side entry would collapse into the node border.
        side_threshold = float(target["width"]) / 2 + MIN_ARROW_SEGMENT
        if abs(dx) >= side_threshold:
            target_side = "left" if dx > 0 else "right"
        else:
            target_side = "top" if dy > 0 else "bottom"
    return source_side, target_side


def _bbox_gap(source: dict[str, Any], targets: list[dict[str, Any]]) -> tuple[float, float]:
    """Clearance between the source box and the target-group box on each axis."""
    s_left, s_top = float(source["x"]), float(source["y"])
    s_right, s_bottom = s_left + float(source["width"]), s_top + float(source["height"])
    t_left = min(float(target["x"]) for target in targets)
    t_top = min(float(target["y"]) for target in targets)
    t_right = max(float(target["x"]) + float(target["width"]) for target in targets)
    t_bottom = max(float(target["y"]) + float(target["height"]) for target in targets)
    gap_x = max(0.0, t_left - s_right, s_left - t_right)
    gap_y = max(0.0, t_top - s_bottom, s_top - t_bottom)
    return gap_x, gap_y


def _group_orientation(source: dict[str, Any], targets: list[dict[str, Any]]) -> tuple[str, str]:
    """Decide ONE orientation for a whole fan-out group.

    Per-edge inference splits a group whenever the widest target happens to sit
    on the other side of the 45-degree line, which silently destroys the shared
    trunk. The group orientation therefore comes from the source-to-group
    relation: the axis with the larger clearance wins, and the centroid decides
    when both axes are equally clear.
    """
    gap_x, gap_y = _bbox_gap(source, targets)
    centroid_x = sum(float(target["x"]) + float(target["width"]) / 2 for target in targets) / len(targets)
    centroid_y = sum(float(target["y"]) + float(target["height"]) / 2 for target in targets) / len(targets)
    dx = centroid_x - (float(source["x"]) + float(source["width"]) / 2)
    dy = centroid_y - (float(source["y"]) + float(source["height"]) / 2)
    if abs(gap_x - gap_y) > 1.0:
        vertical = gap_y > gap_x
    else:
        vertical = abs(dy) > abs(dx)
    if vertical:
        return ("bottom", "top") if dy >= 0 else ("top", "bottom")
    return ("right", "left") if dx >= 0 else ("left", "right")


def _infer_edge_sides(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Fill missing semantic sides and give each fan-out group ONE orientation.

    This only adds routing metadata to normalized edge copies. It never creates
    nodes or changes the business relationship. Explicit ports remain
    authoritative.

    The call is idempotent, so it can run again after a layout pass moved the
    nodes: inferred sides are recomputed against the final coordinates while
    explicit sides stay untouched.
    """
    by_id = {str(node["id"]): node for node in nodes}
    auto_edges: list[dict[str, Any]] = []
    auto_source: set[str] = set()
    auto_target: set[str] = set()
    for edge in edges:
        source = by_id.get(str(edge.get("source")))
        target = by_id.get(str(edge.get("target")))
        if not source or not target:
            continue
        explicit_source = edge.get("source_port") is not None or edge.get("source_side") is not None
        explicit_target = edge.get("target_port") is not None or edge.get("target_side") is not None
        source_side, target_side = _infer_semantic_sides(source, target)
        if not explicit_source:
            edge["source_side"] = source_side
            auto_source.add(str(edge.get("id")))
        if not explicit_target:
            edge["target_side"] = target_side
            auto_target.add(str(edge.get("id")))
        # A self loop has no meaningful direction and must never be pulled
        # into the orientation of the other edges leaving the same node.
        if not explicit_source and not explicit_target and source is not target:
            auto_edges.append(edge)

    def coherent(anchor: dict[str, Any], others: list[dict[str, Any]], side: str) -> bool:
        """True when every other node really lies in the direction of `side`."""
        anchor_x = float(anchor["x"]) + float(anchor["width"]) / 2
        anchor_y = float(anchor["y"]) + float(anchor["height"]) / 2
        axis_index = 1 if side in {"top", "bottom"} else 0
        sign = 1 if side in {"bottom", "right"} else -1
        deltas = [
            (float(other["x"]) + float(other["width"]) / 2 - anchor_x,
             float(other["y"]) + float(other["height"]) / 2 - anchor_y)
            for other in others
        ]
        return all(delta[axis_index] * sign > 0 for delta in deltas)

    by_source: dict[str, list[dict[str, Any]]] = {}
    by_target: dict[str, list[dict[str, Any]]] = {}
    by_source_all: dict[str, list[dict[str, Any]]] = {}
    for edge in auto_edges:
        by_source.setdefault(str(edge.get("source")), []).append(edge)
        by_target.setdefault(str(edge.get("target")), []).append(edge)
    # Every edge leaving a node counts for the arrival-side rule below, even
    # when its sides were declared explicitly: they still share the port.
    for edge in edges:
        if str(edge.get("source")) == str(edge.get("target")) or edge.get("fanin_group"):
            continue
        by_source_all.setdefault(str(edge.get("source")), []).append(edge)

    # Fan-out: one source, many targets. They share one trunk, so they must
    # share one orientation. Per-edge inference splits the group as soon as the
    # widest target crosses the 45-degree line, which silently destroys the
    # shared corridor.
    for source_id, group in by_source.items():
        if len(group) < 2:
            continue
        source = by_id.get(source_id)
        targets = [by_id[str(edge.get("target"))] for edge in group if str(edge.get("target")) in by_id]
        if not source or len(targets) < 2:
            continue
        source_side, target_side = _group_orientation(source, targets)
        # A node fanning out into opposite quadrants has no single trunk; those
        # edges keep their own per-edge direction instead of being dragged into
        # a corridor that would cross the source.
        if not coherent(source, targets, source_side):
            continue
        for edge in group:
            edge["source_side"] = source_side
            edge["target_side"] = target_side

    # Fan-in: many sources, one target. Same argument mirrored, and this is
    # also what keeps the side-entry threshold below from splitting a merge:
    # several sources arriving at one node enter through the midpoint of the
    # facing edge, not through whichever side each one happens to be nearest.
    for target_id, group in by_target.items():
        if len(group) < 2:
            continue
        target = by_id.get(target_id)
        sources = [by_id[str(edge.get("source"))] for edge in group if str(edge.get("source")) in by_id]
        if not target or len(sources) < 2:
            continue
        target_side, source_side = _group_orientation(target, sources)
        if not coherent(target, sources, target_side):
            continue
        for edge in group:
            edge["source_side"] = source_side
            edge["target_side"] = target_side

    # A fan-out group leaves through ONE port, so its members also have to
    # arrive on ONE side, otherwise the shared corridor is rejected and the
    # group silently falls apart into independent edges. This covers groups
    # whose source side was declared explicitly: the declared port wins, and
    # the arrival side is the one facing it.
    facing = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
    for source_id, group in by_source_all.items():
        if len(group) < 2:
            continue
        source_sides = {_port_ref(_edge_port(edge, "source"))[0] for edge in group}
        if len(source_sides) != 1:
            continue
        arrival = facing.get(next(iter(source_sides)))
        if not arrival:
            continue
        for edge in group:
            if str(edge.get("id")) in auto_target:
                edge["target_side"] = arrival


def _group_fanout_fanin(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Share one corridor per aligned one-to-many / many-to-one relationship."""
    by_id = {str(node["id"]): node for node in nodes}
    # Aligned one-to-many and many-to-one relationships share a corridor by
    # default. An explicit group name still wins and remains visible in data.
    fanout_candidates: dict[str, list[dict[str, Any]]] = {}
    fanin_candidates: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = by_id.get(str(edge.get("source")))
        target = by_id.get(str(edge.get("target")))
        if not source or not target:
            continue
        source_side, target_side = _port_ref(_edge_port(edge, "source"))[0], _port_ref(_edge_port(edge, "target"))[0]
        source_faces_target = (
            (source_side == "bottom" and target_side == "top" and float(target["y"]) > float(source["y"]))
            or (source_side == "top" and target_side == "bottom" and float(target["y"]) < float(source["y"]))
            or (source_side == "right" and target_side == "left" and float(target["x"]) > float(source["x"]))
            or (source_side == "left" and target_side == "right" and float(target["x"]) < float(source["x"]))
        )
        if source_faces_target:
            fanout_candidates.setdefault(str(edge.get("fanout_group") or f"auto-source:{source['id']}:{source_side}:{target_side}"), []).append(edge)
        target_is_below = target_side == "top" and float(target["y"]) > float(source["y"])
        target_is_above = target_side == "bottom" and float(target["y"]) < float(source["y"])
        target_is_right = target_side == "left" and float(target["x"]) > float(source["x"])
        target_is_left = target_side == "right" and float(target["x"]) < float(source["x"])
        if target_is_below or target_is_above or target_is_right or target_is_left:
            fanin_candidates.setdefault(str(edge.get("fanin_group") or f"auto-target:{target['id']}:{target_side}"), []).append(edge)
    for group, candidates in fanout_candidates.items():
        if len(candidates) >= 2:
            for edge in candidates:
                edge.setdefault("fanout_group", group)
    for group, candidates in fanin_candidates.items():
        if len(candidates) >= 2 and len({str(edge.get("target")) for edge in candidates}) == 1:
            for edge in candidates:
                edge.setdefault("fanin_group", group)


def _assign_lanes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Reserve one numbered lane per parallel edge leaving the same node side."""

    def assign_lanes(edges_for_side: list[dict[str, Any]], role: str, side: str, slots: list[int]) -> None:
        if len(edges_for_side) <= 1:
            return
        for index, edge in enumerate(edges_for_side):
            side_value = str(edge.get(f"{role}_side") or "")
            if edge.get(f"{role}_port") is None and not edge.get("route_points") and not side_value.endswith(tuple(f"-{slot}" for slot in (1, 2, 3))):
                edge[f"{role}_port"] = f"{side}-{slots[min(index, len(slots) - 1)]}"

    for node in nodes:
        node_id = str(node["id"])
        for side in ("left", "right", "top", "bottom"):
            outgoing = [edge for edge in edges if str(edge.get("source")) == node_id and _port_ref(_edge_port(edge, "source"))[0] == side and not edge.get("fanout_group")]
            incoming = [edge for edge in edges if str(edge.get("target")) == node_id and _port_ref(_edge_port(edge, "target"))[0] == side and not edge.get("fanin_group")]
            if outgoing and incoming:
                assign_lanes(outgoing, "source", side, [1, 2])
                assign_lanes(incoming, "target", side, [3, 2])
            else:
                assign_lanes(outgoing, "source", side, [1, 2, 3])
                assign_lanes(incoming, "target", side, [1, 2, 3])


def _annotate_semantic_ports(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """One-shot port annotation: infer sides, share corridors, reserve lanes."""
    _infer_edge_sides(nodes, edges)
    _group_fanout_fanin(nodes, edges)
    _assign_lanes(nodes, edges)


def _apply_centered_flow_layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], layout: Any) -> None:
    """Apply the centered-flow contract to explicit graph geometry.

    A centered-flow graph is a layout request, so it may normalize the authored
    target row (equal spacing) and then align the source to that span. It never
    creates nodes or changes graph relationships. This makes 1→1, 1→N and N→1
    deterministic instead of leaving each edge to choose a different port from
    its own pairwise geometry.

    All four cardinal directions are supported: a group approached vertically
    is centered on x, a group approached horizontally is centered on y.
    """
    if not isinstance(layout, dict) or layout.get("mode") not in {"centered-flow", "auto-centered"}:
        return
    by_id = {str(node["id"]): node for node in nodes}
    groups: dict[str, dict[str, Any]] = {}
    source_group_counts: dict[str, int] = {}
    def source_group_key(edge: dict[str, Any], source_id: str) -> str:
        return f"{str(edge.get('fanout_group') or f'source:{source_id}')}|{_edge_port(edge, 'source')}:{_edge_port(edge, 'target')}"
    for edge in edges:
        source, target = by_id.get(str(edge.get("source"))), by_id.get(str(edge.get("target")))
        if not source or not target:
            continue
        source_side = _edge_port(edge, "source")
        target_side = _edge_port(edge, "target")
        source_shape = str(source.get("shape", "rect"))
        target_shape = str(target.get("shape", "rect"))
        # A diamond exposes its four vertices exactly at the rectangle edge
        # midpoints, so rectangular centring is valid for it. A circle has no
        # semantic edge midpoint, so it keeps its authored position.
        if source_shape == "circle" or target_shape == "circle":
            continue
        if edge.get("fanin_group"):
            continue
        downward = source_side == "bottom" and target_side == "top" and float(target["y"]) > float(source["y"])
        upward = source_side == "top" and target_side == "bottom" and float(target["y"]) < float(source["y"])
        rightward = source_side == "right" and target_side == "left" and float(target["x"]) > float(source["x"])
        leftward = source_side == "left" and target_side == "right" and float(target["x"]) < float(source["x"])
        if not (downward or upward or rightward or leftward):
            continue
        # Direction is part of the group identity. A node can fan out to the
        # right and down at the same time; those are two independent layout
        # contracts and must never pull the source onto one averaged axis.
        key = source_group_key(edge, str(source["id"]))
        entry = groups.setdefault(key, {"source_id": str(source["id"]), "targets": []})
        # A fanout group is one source splitting to many targets. Do not let a
        # malformed group silently move a different source onto this axis.
        if entry["source_id"] == str(source["id"]):
            entry["targets"].append(target)
    for entry in groups.values():
        source_group_counts[entry["source_id"]] = source_group_counts.get(entry["source_id"], 0) + 1
    for group_key, entry in groups.items():
        unique_targets = {str(target["id"]): target for target in entry["targets"]}
        if len(unique_targets) < 2:
            continue
        targets = list(unique_targets.values())
        first_edge = next((edge for edge in edges if source_group_key(edge, entry["source_id"]) == group_key), None)
        source_side = _edge_port(first_edge, "source") if first_edge else "bottom"
        target_side = _edge_port(first_edge, "target") if first_edge else "top"
        horizontal = source_side in {"left", "right"} and target_side in {"left", "right"}
        if horizontal:
            ordered = sorted(targets, key=lambda target: float(target["y"]) + float(target["height"]) / 2)
            low = float(ordered[0]["y"]) + float(ordered[0]["height"]) / 2
            high = float(ordered[-1]["y"]) + float(ordered[-1]["height"]) / 2
            step = (high - low) / (len(ordered) - 1)
            for index, target in enumerate(ordered):
                target["y"] = low + step * index - float(target["height"]) / 2
        elif source_side in {"top", "bottom"} and target_side in {"top", "bottom"}:
            ordered = sorted(targets, key=lambda target: float(target["x"]) + float(target["width"]) / 2)
            low = float(ordered[0]["x"]) + float(ordered[0]["width"]) / 2
            high = float(ordered[-1]["x"]) + float(ordered[-1]["width"]) / 2
            step = (high - low) / (len(ordered) - 1)
            for index, target in enumerate(ordered):
                target["x"] = low + step * index - float(target["width"]) / 2
    for group_key, entry in groups.items():
        unique_targets = {str(target["id"]): target for target in entry["targets"]}
        if not unique_targets:
            continue
        source_id = str(entry["source_id"])
        if source_id and source_id in by_id:
            target_list = list(unique_targets.values())
            first_edge = next((edge for edge in edges if str(edge.get("source")) == source_id and source_group_key(edge, source_id) == group_key), None)
            # When the same source participates in multiple directional
            # groups, a singleton group must not overwrite the source position
            # selected by the other direction. Multi-target groups still get
            # centered as a real fan-out contract.
            if len(target_list) == 1 and source_group_counts.get(source_id, 1) > 1 and not first_edge.get("fanout_group"):
                continue
            source_node = by_id[source_id]
            source_side = _edge_port(first_edge, "source") if first_edge else "bottom"
            target_side = _edge_port(first_edge, "target") if first_edge else "top"
            if source_side in {"left", "right"} and target_side in {"left", "right"}:
                centers = [float(target["y"]) + float(target["height"]) / 2 for target in target_list]
                source_node["y"] = sum(centers) / len(centers) - float(source_node["height"]) / 2
            else:
                source_node["x"] = _centered_source_x(source_node, target_list)

    target_groups: dict[str, dict[str, Any]] = {}
    target_group_counts: dict[str, int] = {}
    for edge in edges:
        source, target = by_id.get(str(edge.get("source"))), by_id.get(str(edge.get("target")))
        if not source or not target:
            continue
        source_side = _edge_port(edge, "source")
        target_side = _edge_port(edge, "target")
        if edge.get("fanout_group"):
            continue
        rightward_fanin = source_side == "right" and target_side == "left" and float(target["x"]) > float(source["x"])
        leftward_fanin = source_side == "left" and target_side == "right" and float(target["x"]) < float(source["x"])
        downward_fanin = source_side == "bottom" and target_side == "top" and float(target["y"]) > float(source["y"])
        upward_fanin = source_side == "top" and target_side == "bottom" and float(target["y"]) < float(source["y"])
        if not (rightward_fanin or leftward_fanin or downward_fanin or upward_fanin):
            continue
        horizontal_fanin = rightward_fanin or leftward_fanin
        # Keep incoming groups separate by port direction for the same reason
        # as source groups above: left-to-right and top-to-bottom fan-ins have
        # different center axes.
        key = f"{str(edge.get('fanin_group') or f'target:{target['id']}')}|{source_side}:{target_side}"
        entry = target_groups.setdefault(key, {"target_id": str(target["id"]), "sources": [], "horizontal": horizontal_fanin})
        if entry["target_id"] == str(target["id"]):
            entry["sources"].append(source)
    for entry in target_groups.values():
        target_group_counts[entry["target_id"]] = target_group_counts.get(entry["target_id"], 0) + 1
    for entry in target_groups.values():
        unique_sources = {str(source["id"]): source for source in entry["sources"]}
        target_id = str(entry["target_id"])
        target_node = by_id.get(target_id)
        if not target_node or len(unique_sources) < 2:
            continue
        sources = list(unique_sources.values())
        if entry["horizontal"]:
            centers = [float(source["y"]) + float(source["height"]) / 2 for source in sources]
            target_node["y"] = sum(centers) / len(centers) - float(target_node["height"]) / 2
        else:
            centers = [float(source["x"]) + float(source["width"]) / 2 for source in sources]
            target_node["x"] = sum(centers) / len(centers) - float(target_node["width"]) / 2


def _route_clear_of_nodes(points: list[list[float]], nodes: dict[str, dict[str, Any]], excluded: set[str]) -> bool:
    """Keep every orthogonal segment outside all unrelated node boxes."""
    for first, second in zip(points, points[1:]):
        for node_id, node in nodes.items():
            if str(node_id) in excluded:
                continue
            if _route_segment_hits(first, second, node, 12.0):
                return False
    return True


def _corridor_routes(
    group_edges: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    corridor_side: str,
) -> dict[str, list[list[float]]]:
    """Build one shared trunk/corridor for vertical or horizontal groups."""
    if len(group_edges) < 2:
        return {}
    source_ids = {str(edge.get("source")) for edge in group_edges}
    target_ids = {str(edge.get("target")) for edge in group_edges}
    if len(source_ids) != 1 and len(target_ids) != 1:
        return {}
    source_nodes = [nodes.get(source_id) for source_id in source_ids]
    target_nodes = [nodes.get(target_id) for target_id in target_ids]
    if any(node is None for node in source_nodes + target_nodes):
        return {}
    source_points = {str(edge["id"]): _port_point(nodes[str(edge["source"])], _edge_port(edge, "source")) for edge in group_edges}
    target_points = {str(edge["id"]): _port_point(nodes[str(edge["target"])], _edge_port(edge, "target")) for edge in group_edges}
    # A one-source fanout has one physical trunk even when the input carried
    # numbered source lanes. A one-target fanin likewise merges at one target
    # port; the lane split belongs on the far side of the corridor.
    if len(source_ids) == 1:
        source = nodes[next(iter(source_ids))]
        source_side = _port_ref(_edge_port(group_edges[0], "source"))[0]
        shared_source = _port_point(source, source_side)
        source_points = {str(edge["id"]): shared_source[:] for edge in group_edges}
    if len(target_ids) == 1:
        target = nodes[next(iter(target_ids))]
        target_side = _port_ref(_edge_port(group_edges[0], "target"))[0]
        shared_target = _port_point(target, target_side)
        target_points = {str(edge["id"]): shared_target[:] for edge in group_edges}
    min_arrow = max(MIN_ARROW_SEGMENT, max(float(edge.get("min_arrow_segment", MIN_ARROW_SEGMENT)) for edge in group_edges))
    source_side = _port_ref(_edge_port(group_edges[0], "source"))[0]
    target_side = _port_ref(_edge_port(group_edges[0], "target"))[0]
    horizontal = source_side in {"left", "right"} or target_side in {"left", "right"}
    axis_index = 0 if horizontal else 1
    # The corridor belongs in the middle of the gap between the two boxes, not
    # glued to whichever node it happens to be measured from. Measuring from
    # the target edge put the turn ~75px from the targets; the geometric
    # midpoint is what the layout rule asks for. The outward steps below are
    # only fallbacks taken when a node blocks the centred corridor.
    if horizontal:
        if len(source_ids) == 1:
            source_edge = source_points[str(group_edges[0]["id"])][0]
            target_axis = [point[0] for point in target_points.values()]
            target_edge = min(target_axis) if source_side == "right" else max(target_axis)
        else:
            source_axis = [point[0] for point in source_points.values()]
            target_edge = target_points[str(group_edges[0]["id"])][0]
            source_edge = max(source_axis) if target_side == "left" else min(source_axis)
    else:
        if len(source_ids) == 1:
            source_edge = source_points[str(group_edges[0]["id"])][1]
            target_axis = [point[1] for point in target_points.values()]
            target_edge = min(target_axis) if source_side == "bottom" else max(target_axis)
        else:
            source_axis = [point[1] for point in source_points.values()]
            target_edge = target_points[str(group_edges[0]["id"])][1]
            source_edge = max(source_axis) if target_side == "top" else min(source_axis)
    base_axis = (source_edge + target_edge) / 2.0
    excluded = source_ids | target_ids
    for attempt in range(81):
        offset = ((attempt + 1) // 2) * 16.0
        corridor_axis = base_axis - offset if attempt % 2 == 0 else base_axis + offset
        candidate: dict[str, list[list[float]]] = {}
        for edge in group_edges:
            source_point = source_points[str(edge["id"])]
            target_point = target_points[str(edge["id"])]
            edge_source_side = _port_ref(_edge_port(edge, "source"))[0]
            edge_target_side = _port_ref(_edge_port(edge, "target"))[0]
            if horizontal:
                if len(source_ids) == 1:
                    # Never overshoot the corridor: a full min_arrow lead-in
                    # would walk past the turn and come back, which reads as a
                    # visible backtrack on tightly spaced graphs.
                    lead = min(min_arrow, max(0.0, abs(corridor_axis - source_point[0])))
                    outward_x = source_point[0] + lead if edge_source_side == "right" else source_point[0] - lead
                    outward = [outward_x, source_point[1]]
                    source_leg = [source_point[:], outward, [corridor_axis, source_point[1]]]
                    branch = [[corridor_axis, target_point[1]], target_point[:]]
                else:
                    source_leg = [source_point[:]]
                    branch = [[corridor_axis, source_point[1]], [corridor_axis, target_point[1]], target_point[:]]
                candidate[str(edge["id"])] = source_leg + branch
            else:
                if len(source_ids) == 1:
                    source_leg = [source_point[:], [source_point[0], corridor_axis]]
                    branch = [[target_point[0], corridor_axis], target_point[:]]
                else:
                    source_leg = [source_point[:], [source_point[0], corridor_axis]]
                    branch = [[target_point[0], corridor_axis], target_point[:]]
                candidate[str(edge["id"])] = source_leg + branch
        for edge_id, route in candidate.items():
            compact: list[list[float]] = []
            for point in route:
                if not compact or point != compact[-1]:
                    compact.append(point)
            candidate[edge_id] = compact
        if all(_route_clear_of_nodes(route, nodes, excluded) for route in candidate.values()):
            # A centred corridor on a tightly spaced graph cannot also keep a
            # full-length arrow. Centring wins here, and the edge is flagged so
            # the harness can tell "deliberately centred" from "silently short".
            for edge in group_edges:
                route = candidate[str(edge["id"])]
                arrow = math.hypot(route[-1][0] - route[-2][0], route[-1][1] - route[-2][1])
                edge["arrow_relaxed"] = arrow + 1e-5 < min_arrow
            return candidate
    return {}


def _compute_fanout_routes(edges: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> dict[str, list[list[float]]]:
    """Build shared-trunk, centered fan-out routes for any aligned side."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = nodes.get(str(edge.get("source")))
        target = nodes.get(str(edge.get("target")))
        source_side = _port_ref(_edge_port(edge, "source"))[0]
        target_side = _port_ref(_edge_port(edge, "target"))[0]
        if edge.get("fanout_group"):
            group = str(edge["fanout_group"])
        elif source and target and (
            (source_side == "bottom" and target_side == "top" and float(target["y"]) > float(source["y"]))
            or (source_side == "top" and target_side == "bottom" and float(target["y"]) < float(source["y"]))
            or (source_side == "right" and target_side == "left" and float(target["x"]) > float(source["x"]))
            or (source_side == "left" and target_side == "right" and float(target["x"]) < float(source["x"]))
        ):
            group = f"auto-source:{source['id']}"
        else:
            continue
        grouped.setdefault(group, []).append(edge)
    routes: dict[str, list[list[float]]] = {}
    for group_edges in grouped.values():
        if len(group_edges) < 2:
            continue
        source_ids = {str(edge.get("source")) for edge in group_edges}
        target_sides = {_port_ref(_edge_port(edge, "target"))[0] for edge in group_edges}
        if len(source_ids) != 1 or len(target_sides) != 1:
            continue
        source = nodes.get(next(iter(source_ids)))
        if not source:
            continue
        routes.update(_corridor_routes(group_edges, nodes, next(iter(target_sides))))
    return routes


def _compute_fanin_routes(edges: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> dict[str, list[list[float]]]:
    """Build a shared merge corridor for multiple edges entering one node."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = nodes.get(str(edge.get("source")))
        target = nodes.get(str(edge.get("target")))
        source_side = _port_ref(_edge_port(edge, "source"))[0]
        target_side = _port_ref(_edge_port(edge, "target"))[0]
        if edge.get("fanin_group"):
            group = str(edge["fanin_group"])
        elif source and target and (
            (target_side == "top" and float(target["y"]) > float(source["y"]))
            or (target_side == "bottom" and float(target["y"]) < float(source["y"]))
            or (target_side == "left" and float(target["x"]) > float(source["x"]))
            or (target_side == "right" and float(target["x"]) < float(source["x"]))
        ):
            group = f"auto-target:{target['id']}"
        else:
            continue
        grouped.setdefault(group, []).append(edge)
    routes: dict[str, list[list[float]]] = {}
    for group_edges in grouped.values():
        if len(group_edges) < 2:
            continue
        target_ids = {str(edge.get("target")) for edge in group_edges}
        target_sides = {_port_ref(_edge_port(edge, "target"))[0] for edge in group_edges}
        if len(target_ids) != 1 or len(target_sides) != 1:
            continue
        routes.update(_corridor_routes(group_edges, nodes, next(iter(target_sides))))
    return routes


def _normalize(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[float]]:
    nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(graph.get("nodes", [])):
        node = dict(raw)
        node.setdefault("id", f"node-{index + 1}")
        node.setdefault("label", node["id"])
        node.setdefault("kind", node.get("type", "process"))
        node.setdefault("type", node["kind"])
        type_spec = NODE_TYPE_REGISTRY.get(str(node["type"]), NODE_TYPE_REGISTRY.get("process", {}))
        node.setdefault("family", type_spec.get("family", "execution"))
        node.setdefault("shape", type_spec.get("shape", "rect"))
        node.setdefault("icon", type_spec.get("icon", "process"))
        size_name = str(node.get("size", type_spec.get("size", "regular")))
        size = SIZE_PRESETS.get(size_name, SIZE_PRESETS.get("regular", {"width": 156, "height": 88}))
        default_width = 150 if node["shape"] in {"diamond", "hexagon", "octagon"} else size.get("width", 156)
        default_height = 106 if node["shape"] in {"diamond", "hexagon", "octagon"} else size.get("height", 88)
        node.setdefault("size", size_name)
        node.setdefault("width", default_width)
        node.setdefault("height", default_height)
        node.setdefault("x", 80 + index * 240)
        node.setdefault("y", 220)
        node.setdefault("status", "pending")
        raw_status = str(node["status"])
        status_spec = STATUS_REGISTRY.get(raw_status, {})
        node.setdefault("raw_status", raw_status)
        node.setdefault("visual_status", status_spec.get("visual", raw_status.replace("_", "-")))
        node.setdefault("children", [])
        node.setdefault("drilldown", node.get("drilldown", {}))
        node.setdefault("group_id", node.get("group", None))
        node.setdefault("port_role", node.get("port", None))
        node.setdefault("accessibility_label", node.get("aria_label", node.get("label", node["id"])))
        node.setdefault("order", index)
        nodes.append(node)
    edges: list[dict[str, Any]] = []
    for index, raw in enumerate(graph.get("edges", [])):
        edge = dict(raw)
        edge.setdefault("id", f"edge-{index + 1}")
        edge.setdefault("kind", edge.get("type", "main"))
        edge.setdefault("type", edge["kind"])
        edge.setdefault("edge_type", edge["type"])
        edge_spec = EDGE_TYPE_REGISTRY.get(str(edge["edge_type"]), {})
        edge.setdefault("edge_family", edge_spec.get("family", "flow"))
        raw_status = str(edge.get("status", "pending"))
        edge.setdefault("raw_status", raw_status)
        edge.setdefault("visual_status", STATUS_REGISTRY.get(raw_status, {}).get("visual", raw_status.replace("_", "-")))
        edges.append(edge)
    # Order matters: infer the direction, let the layout move nodes onto the
    # group axis, then infer again against the FINAL coordinates. Inferring
    # once and then moving the nodes leaves every side pointing at where the
    # nodes used to be.
    _infer_edge_sides(nodes, edges)
    _apply_centered_flow_layout(nodes, edges, graph.get("layout"))
    _infer_edge_sides(nodes, edges)
    _group_fanout_fanin(nodes, edges)
    _assign_lanes(nodes, edges)
    view_box = list(graph.get("viewBox", [0, 0, 1200, 620]))
    if len(view_box) != 4:
        view_box = [0, 0, 1200, 620]
    # Keep an authored viewBox when it is already large enough, but expand it
    # around factual node bounds so the initial fit cannot clip a node.
    padding = 24.0
    old_left, old_top, old_width, old_height = map(float, view_box)
    min_x = min((float(node["x"]) for node in nodes), default=old_left) - padding
    min_y = min((float(node["y"]) for node in nodes), default=old_top) - padding
    max_x = max((float(node["x"]) + float(node["width"]) for node in nodes), default=old_left + old_width) + padding
    max_y = max((float(node["y"]) + float(node["height"]) for node in nodes), default=old_top + old_height) + padding
    left = min(old_left, min_x)
    top = min(old_top, min_y)
    right = max(old_left + old_width, max_x)
    bottom = max(old_top + old_height, max_y)
    view_box = [left, top, right - left, bottom - top]
    return nodes, edges, view_box


def _lines(label: str, max_chars: int = 10) -> list[str]:
    result: list[str] = []
    for part in str(label).splitlines() or [""]:
        if len(part) <= max_chars:
            result.append(part)
            continue
        # Keep Latin words intact so labels such as "Research / Ready" do
        # not render as "Rea" + "dy" inside a node. Chinese text still falls
        # back to deterministic character wrapping.
        if " " in part:
            words = part.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > max_chars:
                    result.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                result.append(current)
        else:
            while len(part) > max_chars:
                result.append(part[:max_chars])
                part = part[max_chars:]
            result.append(part)
    return result or [""]


def _shape_markup(shape: str, x: float, y: float, width: float, height: float, fill: str, stroke: str) -> str:
    """Render a type-registered shape while keeping a stable node body."""
    cx, cy = x + width / 2, y + height / 2
    shape = str(shape or "rect")
    if shape == "diamond":
        points = f"{cx},{y} {x + width},{cy} {cx},{y + height} {x},{cy}"
        return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" />'
    if shape == "circle":
        return f'<circle cx="{cx}" cy="{cy}" r="{min(width, height) / 2}" fill="{fill}" stroke="{stroke}" />'
    if shape == "bar":
        # Fork/join bars carry a two-line label. Keep the port at the node
        # center, and give the visible runway enough height that the boundary
        # port clearly belongs to the bar background rather than the text line.
        bar_height = min(height, 56)
        return f'<rect x="{x}" y="{cy - bar_height / 2}" width="{width}" height="{bar_height}" rx="{bar_height / 2}" fill="{fill}" stroke="{stroke}" />'
    if shape in {"capsule", "roundRect"}:
        return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{height / 2 if shape == "capsule" else 12}" fill="{fill}" stroke="{stroke}" />'
    if shape == "hexagon":
        inset = width * 0.16
        points = f"{x + inset},{y} {x + width - inset},{y} {x + width},{cy} {x + width - inset},{y + height} {x + inset},{y + height} {x},{cy}"
        return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" />'
    if shape == "octagon":
        inset = min(width, height) * 0.18
        points = f"{x + inset},{y} {x + width - inset},{y} {x + width},{y + inset} {x + width},{y + height - inset} {x + width - inset},{y + height} {x + inset},{y + height} {x},{y + height - inset} {x},{y + inset}"
        return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" />'
    if shape == "trapezoid":
        inset = width * 0.14
        points = f"{x + inset},{y} {x + width - inset},{y} {x + width},{y + height} {x},{y + height}"
        return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" />'
    if shape == "parallelogram":
        inset = width * 0.12
        points = f"{x + inset},{y} {x + width},{y} {x + width - inset},{y + height} {x},{y + height}"
        return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" />'
    if shape == "document":
        fold = min(width, height) * 0.22
        points = f"{x},{y} {x + width - fold},{y} {x + width},{y + fold} {x + width},{y + height} {x},{y + height}"
        return f'<path d="M {x} {y} H {x + width - fold} L {x + width} {y + fold} V {y + height} H {x} Z" fill="{fill}" stroke="{stroke}" />'
    if shape == "cylinder":
        ry = min(12, height * 0.18)
        return f'<path d="M {x} {y + ry} Q {cx} {y - ry} {x + width} {y + ry} V {y + height - ry} Q {cx} {y + height + ry} {x} {y + height - ry} Z" fill="{fill}" stroke="{stroke}" />'
    if shape == "doubleRect":
        return f'<rect x="{x + 4}" y="{y + 4}" width="{width - 8}" height="{height - 8}" rx="12" fill="{fill}" stroke="{stroke}" /><rect x="{x}" y="{y}" width="{width - 8}" height="{height - 8}" rx="12" fill="none" stroke="{stroke}" />'
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="{fill}" stroke="{stroke}" />'


def _node_svg(node: dict[str, Any], theme: dict[str, Any]) -> str:
    node_id, label = _esc(node["id"]), _esc(node["label"])
    x, y = float(node["x"]), float(node["y"])
    width, height = float(node["width"]), float(node["height"])
    cx, cy = x + width / 2, y + height / 2
    shape = str(node.get("shape", "rect"))
    kind = str(node.get("kind", node.get("type", "process")))
    type_spec = NODE_TYPE_REGISTRY.get(kind, NODE_TYPE_REGISTRY.get("process", {}))
    status = str(node.get("raw_status", node.get("status", "pending")))
    visual_status = str(node.get("visual_status", STATUS_REGISTRY.get(status, {}).get("visual", status.replace("_", "-"))))
    fill_token = type_spec.get("fill_token")
    themed_fill = theme.get("type_colors", {}).get(kind) if isinstance(theme.get("type_colors"), dict) else None
    themed_stroke = theme.get("type_strokes", {}).get(kind) if isinstance(theme.get("type_strokes"), dict) else None
    fill = themed_fill or (theme.get(fill_token, type_spec.get("fill", theme["node_fill"])) if fill_token else type_spec.get("fill", theme["node_fill"]))
    stroke = themed_stroke or theme.get(f"{kind}_stroke", type_spec.get("stroke", theme["node_stroke"]))
    body = _shape_markup(shape, x, y, width, height, fill, stroke)
    lines = _lines(str(node["label"]), max(6, int(width // 13)))
    line_height = 18
    start = cy - (len(lines) - 1) * line_height / 2
    text = "".join(f'<tspan class="flowchat-node-line line-{i}" x="{cx}" dy="{0 if i == 0 else line_height}">{_esc(line)}</tspan>' for i, line in enumerate(lines))
    status = _esc(status)
    visual_status = _esc(visual_status)
    kind_class = _esc(kind.replace("_", "-"))
    family_class = _esc(str(node.get("family", type_spec.get("family", "execution"))).replace("_", "-"))
    icon = _esc(str(node.get("icon", type_spec.get("icon", "process"))))
    icon_glyph = _esc(ICON_GLYPHS.get(str(node.get("icon", type_spec.get("icon", "process"))), "•"))
    phase_class = _esc(str(node.get("phase", "unknown")).replace("_", "-"))
    readiness_class = _esc(str(node.get("readiness", "needs_review")).replace("_", "-"))
    diamond_marker = ' data-diamond-text="centered"' if shape in {"diamond", "hexagon", "octagon"} else ''
    stage_attr = f' data-flow-stage="{node_id}"' if kind == "stage" else ''
    target_flow = node.get("target_flow") or node.get("drilldown", {}).get("flow_id")
    reference_attr = f' data-target-flow="{_esc(target_flow)}"' if target_flow else ''
    children_attr = f' data-children="{_esc(json.dumps(node.get("children", []), ensure_ascii=False, separators=(",", ":")))}"' if node.get("children") else ''
    group_attr = f' data-group-id="{_esc(node["group_id"])}"' if node.get("group_id") else ''
    container_attr = ' data-container="true"' if node.get("children") or kind in {"stage", "parallel_group", "subflow"} else ''
    details_attr = ''
    if node.get("details"):
        details_attr = f' data-details="{_esc(json.dumps(node["details"], ensure_ascii=False, separators=(",", ":")))}"'
    badge = f'<circle class="flowchat-node-status-badge" cx="{x + width - 13}" cy="{y + 13}" r="5" data-status-badge="{visual_status}" />'
    icon_markup = f'<text class="flowchat-node-icon" x="{x + 14}" y="{y + 19}" text-anchor="middle" dominant-baseline="middle" aria-hidden="true">{icon_glyph}</text>'
    aria_label = _esc(node.get("accessibility_label", node.get("label", node_id)))
    return f'<g class="flowchat-node kind-{kind_class} family-{family_class} phase-{phase_class} readiness-{readiness_class} status-{visual_status}" data-node="{node_id}" data-status="{status}" data-raw-status="{status}" data-visual-status="{visual_status}" data-kind="{_esc(kind)}" data-type="{_esc(node.get("type", kind))}" data-family="{family_class}" data-icon="{icon}" data-shape="{_esc(shape)}" data-size="{_esc(node.get("size", "regular"))}"{stage_attr}{reference_attr}{children_attr}{group_attr}{container_attr}{details_attr} tabindex="0" role="button" aria-roledescription="流程节点" aria-keyshortcuts="Enter Space" aria-label="{aria_label}">{body}{icon_markup}{badge}<text x="{cx}" y="{start}" text-anchor="middle" dominant-baseline="middle" data-text-region="node" data-text-align="center"{diamond_marker} fill="{theme["text"]}">{text}</text></g>'


def _edge_color(edge: dict[str, Any], theme: dict[str, str]) -> str:
    """Keep the base edge palette neutral; evidence classes may add a semantic overlay."""
    return theme.get("edge", theme["edge_pending"])


def _edge_marker(edge: dict[str, Any]) -> str:
    status = str(edge.get("status", "pending"))
    kind = str(edge.get("edge_type", edge.get("kind", "main")))
    if status == "completed":
        return "completed"
    if status == "active":
        return "active"
    if status == "blocked":
        return "blocked"
    if status == "return" or kind == "return":
        return "return"
    if kind == "feedback":
        return "feedback"
    if kind == "review":
        return "review"
    marker = EDGE_TYPE_REGISTRY.get(kind, {}).get("marker")
    return str(marker or "pending")


def _polyline_length(points: list[list[float]]) -> float:
    return sum(((points[i][0] - points[i - 1][0]) ** 2 + (points[i][1] - points[i - 1][1]) ** 2) ** 0.5 for i in range(1, len(points)))


def _port_ref(value: Any) -> tuple[str | None, int]:
    """Parse a side or a numbered port such as ``bottom-2``.

    Numbered ports use three stable lanes (1/3, 1/2, 2/3). Plain sides keep
    the historical center-port behavior so existing graphs remain compatible.
    """
    text = str(value or "").strip().lower()
    if not text:
        return None, 2
    side, _, suffix = text.partition("-")
    if side not in {"left", "right", "top", "bottom"}:
        return None, 2
    try:
        slot = int(suffix) if suffix else 2
    except ValueError:
        slot = 2
    return side, min(3, max(1, slot))


def _edge_port(edge: dict[str, Any], role: str) -> str | None:
    """Return the explicit numbered port, falling back to the old side key."""
    value = edge.get(f"{role}_port")
    if value is None:
        value = edge.get(f"{role}_side")
    raw = str(value or "").strip().lower()
    side, slot = _port_ref(value)
    if not side:
        return None
    return raw if "-" in raw else side


def _port_point(node: dict[str, Any], port: str | None) -> list[float]:
    """Return the exact point for a semantic side/slot port."""
    left, top = float(node["x"]), float(node["y"])
    width, height = float(node["width"]), float(node["height"])
    cx, cy = left + width / 2, top + height / 2
    side, slot = _port_ref(port)
    ratio = {1: 1 / 3, 2: 1 / 2, 3: 2 / 3}[slot] if "-" in str(port or "") else 1 / 2
    if side == "left":
        return [left, top + height * ratio]
    if side == "right":
        return [left + width, top + height * ratio]
    if side == "top":
        return [left + width * ratio, top]
    if side == "bottom":
        return [left + width * ratio, top + height]
    return [cx, cy]


def _route_segment_hits(a: list[float], b: list[float], node: dict[str, Any], padding: float) -> bool:
    """Check an orthogonal segment against a padded rectangular obstacle."""
    left = float(node["x"]) - padding
    top = float(node["y"]) - padding
    right = float(node["x"]) + float(node["width"]) + padding
    bottom = float(node["y"]) + float(node["height"]) + padding
    if abs(a[0] - b[0]) <= 0.01:
        x = a[0]
        return left < x < right and max(min(a[1], b[1]), top) < min(max(a[1], b[1]), bottom)
    if abs(a[1] - b[1]) <= 0.01:
        y = a[1]
        return top < y < bottom and max(min(a[0], b[0]), left) < min(max(a[0], b[0]), right)
    return True


def _auto_orthogonal_route(
    edge: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    occupied_segments: list[tuple[list[float], list[float]]] | None = None,
) -> list[list[float]] | None:
    """Find a short obstacle-aware orthogonal route for an explicitly auto-routed edge.

    The search follows the same contract used by the local Harness: ports are fixed,
    the first/last segment must leave/enter the declared side, and every segment is
    axis-aligned. A bend penalty makes a straight or one-bend route win over a large
    outer loop whenever both are geometrically safe.
    """
    source = nodes.get(str(edge.get("source")))
    target = nodes.get(str(edge.get("target")))
    source_port, target_port = _edge_port(edge, "source"), _edge_port(edge, "target")
    source_side, _ = _port_ref(source_port)
    target_side, _ = _port_ref(target_port)
    if not source or not target or source_side not in {"left", "right", "top", "bottom"} or target_side not in {"left", "right", "top", "bottom"}:
        return None
    # Round rectangles, capsules, hexagons and trapezoids expose rectangular
    # semantic ports. A diamond's four vertices sit exactly on the rectangle
    # edge midpoints, so its rectangular ports are already on the perimeter.
    # A circle has no edge midpoint, but routing to the bounding-box midpoint
    # and letting _snap_to_node_edge project the endpoint back onto the
    # circumference still leaves the first and last segments axis aligned.
    # Excluding either shape here used to force a straight two-point fallback,
    # which is a diagonal and therefore always rejected downstream.

    start, end = _port_point(source, source_port), _port_point(target, target_port)
    mid_x = (start[0] + end[0]) / 2
    mid_y = (start[1] + end[1]) / 2
    if target_side in {"left", "right"} and edge.get("target_port_y") is not None:
        end[1] = float(edge["target_port_y"])
    if target_side in {"top", "bottom"} and edge.get("target_port_x") is not None:
        end[0] = float(edge["target_port_x"])
    min_segment = MIN_SEGMENT
    min_arrow = float(edge.get("min_arrow_segment", MIN_ARROW_SEGMENT))
    padding = 12.0
    nodes_list = list(nodes.values())
    x_values = {start[0], end[0]}
    y_values = {start[1], end[1]}
    for node in nodes_list:
        left, top = float(node["x"]), float(node["y"])
        right, bottom = left + float(node["width"]), top + float(node["height"])
        x_values.update({left - padding, left - min_arrow, right + padding, right + min_arrow, left, right})
        y_values.update({top - padding, top - min_arrow, bottom + padding, bottom + min_arrow, top, bottom})
    # The grid above only contains node-derived lines, so the true midpoint of
    # the gap is almost never on it and the best available corner can sit ~90px
    # off centre. Seed the midpoints so a centred corner is actually reachable.
    x_values.add(mid_x)
    y_values.add(mid_y)
    # Keep the search inside a generous canvas around the graph.
    min_x, max_x = min(x_values) - 80, max(x_values) + 80
    min_y, max_y = min(y_values) - 80, max(y_values) + 80
    x_values = sorted(x for x in x_values if min_x <= x <= max_x)
    y_values = sorted(y for y in y_values if min_y <= y <= max_y)
    start_ix, start_iy = x_values.index(start[0]), y_values.index(start[1])
    end_ix, end_iy = x_values.index(end[0]), y_values.index(end[1])
    target_id, source_id = str(target["id"]), str(source["id"])
    normals = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}
    source_normal, target_normal = normals[source_side], normals[target_side]

    def clear(a: list[float], b: list[float]) -> bool:
        for node in nodes_list:
            if str(node["id"]) in {source_id, target_id}:
                continue
            if _route_segment_hits(a, b, node, padding):
                return False
        return True

    def segment_overlap_length(a: list[float], b: list[float], c: list[float], d: list[float]) -> float:
        horizontal = abs(a[1] - b[1]) <= 0.01
        other_horizontal = abs(c[1] - d[1]) <= 0.01
        if horizontal != other_horizontal:
            return 0.0
        fixed_axis, span_axis = (1, 0) if horizontal else (0, 1)
        if abs(a[fixed_axis] - c[fixed_axis]) > 0.01:
            return 0.0
        return max(0.0, min(max(a[span_axis], b[span_axis]), max(c[span_axis], d[span_axis])) - max(min(a[span_axis], b[span_axis]), min(c[span_axis], d[span_axis])))

    def segment_crosses(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
        if (abs(a[1] - b[1]) <= 0.01) == (abs(c[1] - d[1]) <= 0.01):
            return False
        if abs(a[1] - b[1]) > 0.01:
            a, b, c, d = c, d, a, b
        x, y = c[0], a[1]
        return min(a[0], b[0]) < x < max(a[0], b[0]) and min(c[1], d[1]) < y < max(c[1], d[1])

    def clear_of_occupied(a: list[float], b: list[float]) -> bool:
        """Do not let an automatically routed edge cross or share a lane."""
        for occupied_a, occupied_b in occupied_segments or []:
            if segment_overlap_length(a, b, occupied_a, occupied_b) > 0.01 or segment_crosses(a, b, occupied_a, occupied_b):
                return False
        return True

    # State carries the incoming direction so bend count can be priced.
    start_state = (start_ix, start_iy, -1)
    queue: list[tuple[float, int, tuple[int, int, int]]] = [(0.0, 0, start_state)]
    serial = 1
    distances: dict[tuple[int, int, int], float] = {start_state: 0.0}
    previous: dict[tuple[int, int, int], tuple[int, int, int] | None] = {start_state: None}
    finish: tuple[int, int, int] | None = None
    while queue:
        cost, _, state = heapq.heappop(queue)
        if cost != distances.get(state):
            continue
        ix, iy, incoming = state
        if (ix, iy) == (end_ix, end_iy):
            if previous[state] is not None:
                prev = previous[state]
                prev_point = [x_values[prev[0]], y_values[prev[1]]]
                incoming_vec = [prev_point[0] - end[0], prev_point[1] - end[1]]
                if incoming_vec[0] * target_normal[0] + incoming_vec[1] * target_normal[1] > 0 and math.dist(prev_point, end) >= min_arrow:
                    finish = state
                    break
        neighbors = [(nx, iy, 0 if nx > ix else 1) for nx in range(len(x_values)) if nx != ix]
        neighbors.extend((ix, ny, 2 if ny > iy else 3) for ny in range(len(y_values)) if ny != iy)
        for nx, ny, direction in neighbors:
            a, b = [x_values[ix], y_values[iy]], [x_values[nx], y_values[ny]]
            distance = _polyline_length([a, b])
            if distance < min_segment or not clear(a, b) or not clear_of_occupied(a, b):
                continue
            if (nx, ny) == (end_ix, end_iy):
                target_vec = [a[0] - b[0], a[1] - b[1]]
                if target_vec[0] * target_normal[0] + target_vec[1] * target_normal[1] <= 0 or distance < min_arrow:
                    continue
            if incoming == -1:
                first_vec = [b[0] - a[0], b[1] - a[1]]
                if first_vec[0] * source_normal[0] + first_vec[1] * source_normal[1] <= 0:
                    continue
            if (incoming, direction) in {(0, 1), (1, 0), (2, 3), (3, 2)}:
                continue
            next_state = (nx, ny, direction)
            # A bend fixes the axis of the leg that follows it. Every bend
            # position gives the SAME Manhattan length, so without a centring
            # term the search just takes whichever candidate was queued first
            # - which put every corner next to the source instead of halfway.
            centre_penalty = 0.0
            if incoming not in {-1, direction}:
                if direction in {2, 3}:
                    centre_penalty = CENTRE_PENALTY * abs(x_values[ix] - mid_x)
                else:
                    centre_penalty = CENTRE_PENALTY * abs(y_values[iy] - mid_y)
            next_cost = cost + distance + (22.0 if incoming not in {-1, direction} else 0.0) + centre_penalty
            if next_cost < distances.get(next_state, float("inf")):
                distances[next_state] = next_cost
                previous[next_state] = state
                heapq.heappush(queue, (next_cost, serial, next_state))
                serial += 1
    if finish is None:
        return None
    states = []
    cursor: tuple[int, int, int] | None = finish
    while cursor is not None:
        states.append(cursor)
        cursor = previous[cursor]
    states.reverse()
    points = [[x_values[ix], y_values[iy]] for ix, iy, _ in states]
    points = [point for index, point in enumerate(points) if index == 0 or point != points[index - 1]]
    # Remove collinear waypoints so the SVG does not expose needless micro-bends.
    simplified: list[list[float]] = []
    for point in points:
        if len(simplified) >= 2:
            first = [simplified[-1][0] - simplified[-2][0], simplified[-1][1] - simplified[-2][1]]
            second = [point[0] - simplified[-1][0], point[1] - simplified[-1][1]]
            collinear_forward = (first[0] * second[1] - first[1] * second[0] == 0) and (first[0] * second[0] + first[1] * second[1] > 0)
        else:
            collinear_forward = False
        if collinear_forward:
            simplified[-1] = point
        else:
            simplified.append(point)
    if _polyline_length(simplified) < float(edge.get("min_length", 90)):
        return None
    return simplified


def _snap_to_node_edge(node: dict[str, Any], point: list[float], neighbor: list[float], side: str | None = None) -> list[float]:
    """Magnetize a route endpoint to the nearest semantic edge of its node."""
    x, y = float(point[0]), float(point[1])
    nx, ny = float(neighbor[0]), float(neighbor[1])
    left, top = float(node["x"]), float(node["y"])
    width, height = float(node["width"]), float(node["height"])
    cx, cy = left + width / 2, top + height / 2
    dx, dy = nx - cx, ny - cy
    shape = str(node.get("shape", "rect"))
    port_side, slot = _port_ref(side)
    if port_side in {"left", "right", "top", "bottom"} and shape not in {"circle", "diamond"}:
        if "-" not in str(side or ""):
            if port_side == "left": return [left, min(max(y, top + 1), top + height - 1)]
            if port_side == "right": return [left + width, min(max(y, top + 1), top + height - 1)]
            if port_side == "top": return [min(max(x, left + 1), left + width - 1), top]
            return [min(max(x, left + 1), left + width - 1), top + height]
        return _port_point(node, str(side))
    if shape == "circle":
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        radius = min(width, height) / 2
        return [cx + dx / length * radius, cy + dy / length * radius]
    if shape == "diamond":
        half_w, half_h = width / 2, height / 2
        scale = max(abs(dx) / max(half_w, 1) + abs(dy) / max(half_h, 1), 1)
        return [cx + dx / scale, cy + dy / scale]
    if abs(dx) >= abs(dy):
        return [left + width if dx >= 0 else left, min(max(ny, top), top + height)]
    return [min(max(nx, left), left + width), top + height if dy >= 0 else top]


def _ensure_min_edge_length(points: list[list[float]], minimum: float = 90.0) -> list[list[float]]:
    """Reject short routes instead of inserting a visible reverse dogleg."""
    if len(points) < 2:
        raise ValueError("route requires at least two points")
    length = _polyline_length(points)
    if length < minimum:
        raise ValueError(f"route total length {length:.1f} is below {minimum:.1f}")
    return points


def _ensure_min_direct_edge_length(points: list[list[float]], minimum: float = 90.0) -> list[list[float]]:
    """Reject short direct routes; callers must provide a deliberate orthogonal route."""
    if len(points) != 2:
        return points
    length = _polyline_length(points)
    if length < minimum:
        raise ValueError(f"direct route length {length:.1f} is below {minimum:.1f}")
    return points


def _ensure_orthogonal_route(points: list[list[float]]) -> list[list[float]]:
    """Reject diagonal route segments at generation time, before browser checks."""
    if len(points) < 2:
        raise ValueError("route requires at least two points")
    for index, (first, second) in enumerate(zip(points, points[1:])):
        if abs(first[0] - second[0]) > 0.01 and abs(first[1] - second[1]) > 0.01:
            raise ValueError(f"route segment {index} must be axis aligned")
    return points


def _ensure_min_arrow_segment(points: list[list[float]], minimum: float = 75.0) -> list[list[float]]:
    """Reject short final arrow segments; never add a reverse segment at render time."""
    if len(points) < 2:
        raise ValueError("route requires an arrow segment")
    previous, end = points[-2], points[-1]
    length = math.hypot(end[0] - previous[0], end[1] - previous[1])
    if length < minimum:
        raise ValueError(f"arrow segment {length:.1f} is below {minimum:.1f}")
    if abs(end[0] - previous[0]) > 0.01 and abs(end[1] - previous[1]) > 0.01:
        raise ValueError("final arrow segment must be axis aligned")
    return points


def _orthogonal_fallback_route(
    start: list[float],
    end: list[float],
    source_side: str | None,
    target_side: str | None,
    min_arrow: float = MIN_ARROW_SEGMENT,
) -> list[list[float]]:
    """Build an axis-aligned route when the search router finds nothing.

    A direct two-point fallback is never acceptable: as soon as the two ports
    are not on one axis it produces a diagonal, and the renderer rejects every
    diagonal. This walks out of each port along its own normal and joins the
    two leads with a single elbow, so the result is always orthogonal.
    """
    normals = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "top": (0.0, -1.0), "bottom": (0.0, 1.0)}
    source_normal = normals.get(str(source_side), (1.0, 0.0))
    target_normal = normals.get(str(target_side), (-1.0, 0.0))
    # Keep the lead-in short when the ports are close, otherwise the outward
    # leg overshoots the elbow and the route visibly doubles back.
    span = abs(end[0] - start[0]) if source_normal[0] else abs(end[1] - start[1])
    lead = min(float(min_arrow), max(MIN_SEGMENT, span / 2))
    out = [start[0] + source_normal[0] * lead, start[1] + source_normal[1] * lead]
    inn = [end[0] + target_normal[0] * lead, end[1] + target_normal[1] * lead]
    points: list[list[float]] = [list(start), out]
    if abs(out[0] - inn[0]) > 0.01 and abs(out[1] - inn[1]) > 0.01:
        # Leave the source port along its own axis first, then turn once.
        points.append([inn[0], out[1]] if source_normal[0] else [out[0], inn[1]])
    points.append(inn)
    points.append(list(end))
    compact: list[list[float]] = []
    for point in points:
        if not compact or abs(compact[-1][0] - point[0]) > 0.01 or abs(compact[-1][1] - point[1]) > 0.01:
            compact.append(point)
    return compact


def _edge_svg(
    edge: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    theme: dict[str, str],
    occupied_segments: list[tuple[list[float], list[float]]] | None = None,
    precomputed_route: list[list[float]] | None = None,
) -> str:
    source, target = nodes.get(str(edge.get("source"))), nodes.get(str(edge.get("target")))
    if not source or not target:
        return ""
    # A centred corridor on a tightly spaced graph cannot keep a full-length
    # arrow. Centring was chosen deliberately, so those edges only have to keep
    # a visible stub instead of the full arrow length.
    arrow_min = MIN_SEGMENT if edge.get("arrow_relaxed") else float(edge.get("min_arrow_segment", MIN_ARROW_SEGMENT))
    auto_route = _auto_orthogonal_route(edge, nodes, occupied_segments) if edge.get("routing") == "auto" else None
    if precomputed_route:
        points = [[float(point[0]), float(point[1])] for point in precomputed_route]
        points[0] = _snap_to_node_edge(source, points[0], points[1], _edge_port(edge, "source"))
        points[-1] = _snap_to_node_edge(target, points[-1], points[-2], _edge_port(edge, "target"))
        points = _ensure_orthogonal_route(points)
        points = _ensure_min_edge_length(points, float(edge.get("min_length", 90)))
        points = _ensure_min_arrow_segment(points, arrow_min)
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        label_x = edge.get("label_x", sum(p[0] for p in points) / len(points))
        label_y = edge.get("label_y", sum(p[1] for p in points) / len(points))
    elif auto_route:
        points = auto_route
        points[0] = _snap_to_node_edge(source, points[0], points[1], _edge_port(edge, "source"))
        points[-1] = _snap_to_node_edge(target, points[-1], points[-2], _edge_port(edge, "target"))
        points = _ensure_orthogonal_route(points)
        points = _ensure_min_edge_length(points, float(edge.get("min_length", 90)))
        points = _ensure_min_arrow_segment(points, arrow_min)
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        label_x = edge.get("label_x", sum(p[0] for p in points) / len(points))
        label_y = edge.get("label_y", sum(p[1] for p in points) / len(points))
    elif edge.get("route_points"):
        points = [[float(p[0]), float(p[1])] for p in edge["route_points"]]
        if len(points) >= 2:
            points[0] = _snap_to_node_edge(source, points[0], points[1], _edge_port(edge, "source"))
            points[-1] = _snap_to_node_edge(target, points[-1], points[-2], _edge_port(edge, "target"))
        points = _ensure_orthogonal_route(points)
        points = _ensure_min_edge_length(points, float(edge.get("min_length", 90)))
        points = _ensure_min_arrow_segment(points, arrow_min)
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        label_x = edge.get("label_x", sum(p[0] for p in points) / len(points))
        label_y = edge.get("label_y", sum(p[1] for p in points) / len(points))
    else:
        inferred = dict(edge)
        source_side, target_side = _infer_semantic_sides(source, target)
        inferred.setdefault("source_side", source_side)
        inferred.setdefault("target_side", target_side)
        sx, sy = _port_point(source, _edge_port(inferred, "source"))
        tx, ty = _port_point(target, _edge_port(inferred, "target"))
        auto_route = _auto_orthogonal_route(inferred, nodes, occupied_segments)
        points = auto_route or _orthogonal_fallback_route(
            [sx, sy], [tx, ty], source_side, target_side,
            float(edge.get("min_arrow_segment", MIN_ARROW_SEGMENT)),
        )
        points = _ensure_orthogonal_route(points)
        points = _ensure_min_direct_edge_length(points, float(edge.get("min_length", 90))) if len(points) == 2 else _ensure_min_edge_length(points, float(edge.get("min_length", 90)))
        points = _ensure_min_arrow_segment(points, arrow_min)
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        label_x, label_y = (sx + tx) / 2, (sy + ty) / 2 - 10
    status = _esc(edge.get("status", "pending"))
    kind = _esc(edge.get("kind", "main"))
    color = _edge_color(edge, theme)
    marker = _edge_marker(edge)
    label_markup = ""
    if edge.get("label"):
        label_text = _esc(edge["label"])
        label_width = max(50, len(str(edge["label"])) * 6)
        label_markup = f'<g class="flowchat-edge-label"><rect x="{float(label_x) - label_width / 2}" y="{float(label_y) - 13}" width="{label_width}" height="20" rx="6" fill="#ffffff" fill-opacity=".92"/><text x="{label_x}" y="{label_y}" text-anchor="middle" fill="{theme["muted"]}">{label_text}</text></g>'
    crossing_attr = ' data-crossing="true"' if edge.get("crossing") else ""
    relaxed_attr = ' data-arrow-relaxed="true"' if edge.get("arrow_relaxed") else ""
    truth_type = str(edge.get("truth_type", "")).strip().lower().replace("_", "-")
    truth_class = f" truth-{_esc(truth_type)}" if truth_type else ""
    truth_attr = f' data-truth-type="{_esc(truth_type)}"' if truth_type else ""
    edge_details = edge.get("details") or {key: edge.get(key) for key in ("reason", "expected", "actual", "run_id", "stage_run_id", "agent_run_id") if edge.get(key) is not None}
    details_attr = f' data-details="{_esc(json.dumps(edge_details, ensure_ascii=False, separators=(",", ":")))}"' if edge_details else ""
    stroke_width = _esc(theme.get("edge_stroke_width", "2"))
    edge_type = _esc(str(edge.get("edge_type", edge.get("kind", "main"))).replace("_", "-"))
    edge_family = _esc(str(edge.get("edge_family", "flow")).replace("_", "-"))
    visual_status = _esc(str(edge.get("visual_status", str(edge.get("status", "pending")).replace("_", "-"))))
    points_attr = _esc(json.dumps(points, ensure_ascii=False, separators=(",", ":")))
    source_side = _esc(str(_edge_port(edge, "source") or ""))
    target_side = _esc(str(_edge_port(edge, "target") or ""))
    source_point, target_point = points[0], points[-1]
    hit = f'<path class="flowchat-edge-hit" d="{d}" pathLength="1" aria-hidden="true" />'
    aria_label = _esc(edge.get("accessibility_label", edge.get("label", edge.get("id", "连线"))))
    return f'<g class="flowchat-edge-group kind-{edge_type} edge-family-{edge_family}{truth_class} status-{visual_status}" data-edge="{_esc(edge.get("id", ""))}" data-source="{_esc(edge.get("source", ""))}" data-target="{_esc(edge.get("target", ""))}" data-status="{_esc(edge.get("status", "pending"))}" data-visual-status="{visual_status}" data-edge-type="{edge_type}" data-edge-family="{edge_family}" data-source-side="{source_side}" data-target-side="{target_side}" data-points="{points_attr}" tabindex="0" role="button" aria-roledescription="流程连线" aria-keyshortcuts="Enter Space Escape" aria-label="{aria_label}"{truth_attr}{details_attr}{crossing_attr}{relaxed_attr}><path class="flowchat-edge" d="{d}" stroke="{color}" data-stroke-width="{stroke_width}" marker-end="url(#flowchat-arrow-{marker})" />{hit}{label_markup}</g>'


def _edge_endpoint_layer_svg(markup: str) -> str:
    """Place endpoint handles above nodes while keeping the edge path below them."""
    edge_match = re.search(r'data-edge="([^"]+)"', markup)
    points_match = re.search(r'data-points="([^"]+)"', markup)
    source_side = re.search(r'data-source-side="([^"]*)"', markup)
    target_side = re.search(r'data-target-side="([^"]*)"', markup)
    if not edge_match or not points_match:
        return ""
    try:
        points = json.loads(html.unescape(points_match.group(1)))
    except json.JSONDecodeError:
        return ""
    if len(points) < 2:
        return ""
    edge_id = _esc(edge_match.group(1))
    source_point, target_point = points[0], points[-1]
    return (
        f'<g class="flowchat-edge-endpoint-layer" data-edge="{edge_id}" data-points="{_esc(json.dumps(points, separators=(",", ":")))}">'
        f'<circle class="flowchat-edge-endpoint" data-endpoint="source" cx="{source_point[0]}" cy="{source_point[1]}" r="8" data-side="{_esc(source_side.group(1) if source_side else "")}" tabindex="0" role="button" aria-roledescription="连线端点" aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Enter Escape" aria-label="拖动连线起点" />'
        f'<circle class="flowchat-edge-endpoint" data-endpoint="target" cx="{target_point[0]}" cy="{target_point[1]}" r="8" data-side="{_esc(target_side.group(1) if target_side else "")}" tabindex="0" role="button" aria-roledescription="连线端点" aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Enter Escape" aria-label="拖动连线终点" />'
        '</g>'
    )


def _subflow_node_svg(node: dict[str, Any], theme: dict[str, str]) -> str:
    """Compact node renderer for the stage-local map."""
    x, y, width, height = (float(node[key]) for key in ("x", "y", "width", "height"))
    cx, cy = x + width / 2, y + height / 2
    status = _esc(node.get("status", "pending"))
    label = _esc(node.get("label", node.get("id", "step")))
    shape = str(node.get("shape", "rect"))
    kind = str(node.get("kind", "subflow-step")).replace("_", "-")
    fill = "#fff5f5" if status == "blocked" else theme.get("diamond_fill", "#ffffff") if shape == "diamond" or kind == "gate" else "#fffaf0" if status in {"review", "return"} else "#ffffff"
    stroke = theme.get("review_stroke", "#d97706") if shape == "diamond" or kind == "gate" else theme.get("node_stroke", "#cbd5e1")
    lines = _lines(str(node.get("label", "")), max(7, int(width // 13)))
    line_height = 18
    start = cy - (len(lines) - 1) * line_height / 2
    text = "".join(f'<tspan x="{cx}" dy="{0 if i == 0 else line_height}">{_esc(line)}</tspan>' for i, line in enumerate(lines))
    body = _shape_markup(shape, x, y, width, height, fill, stroke)
    diamond_marker = ' data-diamond-text="centered"' if shape in {"diamond", "hexagon", "octagon"} else ""
    return f'<g class="flowchat-subflow-node kind-{_esc(kind)} status-{status}" data-subflow-node="{_esc(node.get("id", ""))}" data-subflow-kind="{_esc(kind)}" data-shape="{_esc(shape)}" data-status="{status}" tabindex="0" role="button" aria-label="{label}">{body}<text x="{cx}" y="{start}" text-anchor="middle" dominant-baseline="middle" data-text-region="subflow" data-text-align="center"{diamond_marker} fill="{theme["text"]}">{text}</text></g>'


def _subflow_edge_svg(edge: dict[str, Any], nodes: dict[str, dict[str, Any]], theme: dict[str, str]) -> str:
    source, target = nodes.get(str(edge.get("source"))), nodes.get(str(edge.get("target")))
    if not source or not target:
        return ""
    source_port = _edge_port(edge, "source") or "right"
    target_port = _edge_port(edge, "target") or "left"
    points = [[float(p[0]), float(p[1])] for p in edge.get("route_points", [])]
    if len(points) < 2:
        points = [[source["x"] + source["width"], source["y"] + source["height"] / 2], [target["x"], target["y"] + target["height"] / 2]]
    points[0] = _snap_to_node_edge(source, points[0], points[1], source_port)
    points[-1] = _snap_to_node_edge(target, points[-1], points[-2], target_port)
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    status = _esc(edge.get("status", "pending"))
    marker = _edge_marker(edge)
    dash = ' stroke-dasharray="10 8"' if status in {"return", "review"} else ""
    points_attr = _esc(json.dumps(points, ensure_ascii=False, separators=(",", ":")))
    return f'<g class="flowchat-subflow-edge-group status-{status}" data-subflow-edge="{_esc(edge.get("id", ""))}" data-source="{_esc(edge.get("source", ""))}" data-target="{_esc(edge.get("target", ""))}" data-source-side="{_esc(source_port)}" data-target-side="{_esc(target_port)}" data-points="{points_attr}"><path class="flowchat-subflow-edge" d="{d}" stroke="{theme.get("edge", theme["edge_pending"])}"{dash} marker-end="url(#flowchat-arrow-{marker})" /></g>'


def _subflow_layer_markup(subflows: dict[str, dict[str, Any]], theme: dict[str, str]) -> str:
    layers = []
    for stage_id, subflow in subflows.items():
        nodes = {str(node["id"]): node for node in subflow.get("nodes", [])}
        edge_markup = "".join(_subflow_edge_svg(edge, nodes, theme) for edge in subflow.get("edges", []))
        node_markup = "".join(_subflow_node_svg(node, theme) for node in subflow.get("nodes", []))
        layers.append(f'<g class="flowchat-subflow-layer" data-flowchat-subflow="{_esc(stage_id)}" style="display:none"><g class="flowchat-subflow-world">{edge_markup}{node_markup}</g></g>')
    return "".join(layers)


def _architecture_node_svg(node: dict[str, Any], theme: dict[str, str]) -> str:
    x, y, width, height = (float(node[key]) for key in ("x", "y", "width", "height"))
    cx, cy = x + width / 2, y + height / 2
    status = _esc(node.get("status", "pending"))
    kind = _esc(node.get("kind", "architecture").replace("_", "-"))
    label = _esc(node.get("label", node.get("id", "layer")))
    lines = _lines(str(node.get("label", "")), max(8, int(width // 13)))
    line_height = 18
    start = cy - (len(lines) - 1) * line_height / 2
    text = "".join(f'<tspan x="{cx}" dy="{0 if i == 0 else line_height}">{_esc(line)}</tspan>' for i, line in enumerate(lines))
    fill = "#eef2ff" if kind == "architecture" else "#eef7ff"
    return f'<g class="flowchat-architecture-node kind-{kind} status-{status}" data-architecture-node="{_esc(node.get("id", ""))}" data-status="{status}" tabindex="0" role="button" aria-label="{label}"><rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="{fill}"/><text x="{cx}" y="{start}" text-anchor="middle" dominant-baseline="middle" data-text-region="architecture" fill="{theme["text"]}">{text}</text></g>'


def _architecture_edge_svg(edge: dict[str, Any], nodes: dict[str, dict[str, Any]], theme: dict[str, str]) -> str:
    source, target = nodes.get(str(edge.get("source"))), nodes.get(str(edge.get("target")))
    if not source or not target:
        return ""
    points = [[float(p[0]), float(p[1])] for p in edge.get("route_points", [])]
    if len(points) < 2:
        return ""
    points[0] = _snap_to_node_edge(source, points[0], points[1], edge.get("source_side"))
    points[-1] = _snap_to_node_edge(target, points[-1], points[-2], edge.get("target_side"))
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    status = _esc(edge.get("status", "pending"))
    marker = _edge_marker(edge)
    dash = ' stroke-dasharray="10 8"' if status == "return" else ""
    return f'<g class="flowchat-architecture-edge-group status-{status}" data-architecture-edge="{_esc(edge.get("id", ""))}"><path class="flowchat-architecture-edge" d="{d}" stroke="{theme.get("edge", theme["edge_pending"])}"{dash} marker-end="url(#flowchat-arrow-{marker})" /></g>'


def _architecture_markup(architecture: dict[str, Any], theme: dict[str, str]) -> str:
    nodes = {str(node["id"]): node for node in architecture.get("nodes", [])}
    edges = "".join(_architecture_edge_svg(edge, nodes, theme) for edge in architecture.get("edges", []))
    node_markup = "".join(_architecture_node_svg(node, theme) for node in architecture.get("nodes", []))
    return f'<g class="flowchat-architecture-layer" data-flowchat-architecture style="display:none"><g class="flowchat-architecture-world">{edges}{node_markup}</g></g>'


def _lane_markup(lanes: list[dict[str, Any]], canvas_width: float) -> str:
    """Render optional white swimlane scaffolding without separator rules."""
    markup: list[str] = []
    for index, lane in enumerate(lanes):
        y = float(lane.get("y", 0))
        height = float(lane.get("height", 120))
        fill = lane.get("fill") or ("#ffffff" if index % 2 == 0 else "#f8fafc")
        label = _esc(lane.get("label", lane.get("id", "Lane")))
        subtitle = _esc(lane.get("subtitle", ""))
        label_markup = f'<text x="28" y="{y + 45}" class="flowchat-lane-title">{label}</text>'
        if subtitle:
            label_markup += f'<text x="28" y="{y + 69}" class="flowchat-lane-subtitle">{subtitle}</text>'
        if lane.get("badge"):
            label_markup += f'<text x="{canvas_width - 28}" y="{y + 45}" class="flowchat-lane-badge" text-anchor="end">{_esc(lane["badge"])}</text>'
        markup.append(
            f'<g class="flowchat-lane" data-lane="{_esc(lane.get("id", ""))}" data-layout="{_esc(lane.get("layout", "center_outward"))}" data-node-ids="{_esc(json.dumps(lane.get("node_ids", []), ensure_ascii=False, separators=(",", ":")))}">'
            f'<rect x="0" y="{y}" width="{canvas_width}" height="{height}" fill="{_esc(fill)}" stroke="none"/>'
            f'{label_markup}</g>'
        )
    return "".join(markup)


def _interaction_script() -> str:
    """Browser interaction contract for selection, endpoint editing, and pan/zoom."""
    return r'''(()=>{
const root=document.querySelector('[data-flowchat-root]'),stage=root.querySelector('[data-flowchat-stage]'),overview=root.querySelector('[data-flowchat-world]'),layers=[...root.querySelectorAll('[data-flowchat-subflow]')],architectureLayer=root.querySelector('[data-flowchat-architecture]'),architectureWorld=architectureLayer?.querySelector('.flowchat-architecture-world'),detail=root.querySelector('[data-flowchat-detail]'),transition=root.querySelector('[data-flowchat-transition]'),log=root.querySelector('[data-flowchat-log]'),titleNode=root.querySelector('[data-flowchat-title]'),back=root.querySelector('[data-action=overview]'),vb=window.__FLOWCHAT_VIEWBOX__||[0,0,1600,960],vw=vb[2],vh=vb[3],subflows=window.__FLOWCHAT_GRAPH__.subflows||{},architecture=window.__FLOWCHAT_GRAPH__.architecture||{},edgeEditing=Boolean(window.__FLOWCHAT_GRAPH__.edge_editing);
let scale=1,panX=0,panY=0,drag=null,endpointDrag=null,activeStage=null;const activePointers=new Map();
const viewportPoint=(clientX,clientY)=>{const rect=stage.getBoundingClientRect(),svgScale=Math.min(rect.width/vw,rect.height/vh),offsetX=(rect.width-vw*svgScale)/2,offsetY=(rect.height-vh*svgScale)/2;return{x:(clientX-rect.left-offsetX)/svgScale,y:(clientY-rect.top-offsetY)/svgScale}};
let pinchStart=0,pinchScale=1;const pinchDistance=()=>{const p=[...activePointers.values()];return p.length===2?Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y):0};
const visibleLayer=()=>activeStage?root.querySelector(`[data-flowchat-subflow="${activeStage}"]`):root.dataset.view==='architecture'?architectureWorld:overview;
const apply=()=>[overview,...layers.map(x=>x.querySelector('.flowchat-subflow-world')),architectureWorld].forEach(world=>world&&world.setAttribute('transform',`translate(${panX} ${panY}) scale(${scale})`));
const fit=()=>{scale=1;panX=0;panY=0;apply()};
const addLog=(text)=>{if(!log)return;const li=document.createElement('li');li.textContent=text;log.prepend(li);while(log.children.length>20)log.lastElementChild.remove()};
const formatDetails=(element)=>{let data={};try{data=JSON.parse(element.dataset.details||'{}')}catch{}const rows=Object.entries(data).filter(([,value])=>value!==null&&value!==undefined&&value!=='').map(([key,value])=>`${key}：${Array.isArray(value)?value.join('、'):typeof value==='object'?JSON.stringify(value):value}`);return rows.length?`${element.getAttribute('aria-label')||element.dataset.edge||''} · ${rows.join(' / ')}`:`${element.getAttribute('aria-label')||element.dataset.edge||''} · 状态：${element.dataset.status||'unknown'}`};
const clearSelected=()=>root.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));
const endpointLayerFor=(edge)=>root.querySelector(`.flowchat-edge-endpoint-layer[data-edge="${edge.dataset.edge}"]`);
const selectElement=(element)=>{clearSelected();element.classList.add('selected');if(element.classList.contains('flowchat-edge-group'))endpointLayerFor(element)?.classList.add('selected');detail.textContent=formatDetails(element)};
const showOverview=()=>{activeStage=null;root.dataset.view='flow';overview.style.display='';layers.forEach(layer=>layer.style.display='none');if(architectureLayer)architectureLayer.style.display='none';back.hidden=true;titleNode.textContent=root.dataset.initialTitle||'Flowchat';transition.textContent='点击节点查看它的真实执行上下文。';fit();addLog('返回阶段总览')};
const showSubflow=(id)=>{const meta=subflows[id];if(!meta)return;activeStage=id;root.dataset.view='flow';overview.style.display='none';layers.forEach(layer=>layer.style.display=layer.dataset.flowchatSubflow===id?'':'none');if(architectureLayer)architectureLayer.style.display='none';back.hidden=false;titleNode.textContent=meta.title;transition.textContent=`${meta.entry}\n${meta.next}\n${meta.loop}\n审核策略：${meta.review_policy||'AI + 人工'}`;fit();addLog(`打开子流程：${meta.title}`)};
const showArchitecture=()=>{activeStage=null;root.dataset.view='architecture';overview.style.display='none';layers.forEach(layer=>layer.style.display='none');if(architectureLayer)architectureLayer.style.display='';back.hidden=true;titleNode.textContent=architecture.title||'Agent 工程分层架构';transition.textContent='每层只承担一个职责：说明项目、控制权限、加载规则、触发命令、复用技能、执行 Agent、统一 Harness 门禁、连接 Tool / MCP，并把结果沉淀为证据。';fit();addLog('打开架构视图')};
root.querySelectorAll('[data-view-button]').forEach(b=>b.addEventListener('click',()=>{if(b.dataset.viewButton==='architecture')showArchitecture();else if(b.dataset.viewButton==='flow')showOverview();else{root.dataset.view='sequence';activeStage=null;overview.style.display='';layers.forEach(layer=>layer.style.display='none');if(architectureLayer)architectureLayer.style.display='none';back.hidden=true}root.querySelectorAll('[data-view-button]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));addLog(`切换到 ${b.textContent}`)}));
back.addEventListener('click',showOverview);root.querySelector('[data-action=fit]').addEventListener('click',()=>{fit();addLog('已适应视图')});root.querySelector('[data-action=demo]').addEventListener('click',()=>{visibleLayer()?.querySelectorAll('.status-active .flowchat-edge,.status-return .flowchat-edge,.status-active .flowchat-subflow-edge,.status-return .flowchat-subflow-edge,.status-active .flowchat-architecture-edge,.status-return .flowchat-architecture-edge').forEach(e=>e.classList.toggle('demo-highlight'));addLog('动态演示已更新')});
const getPoints=(edge)=>{try{return JSON.parse(edge.dataset.points||'[]')}catch{return[]}};const pathFor=(points)=>'M '+points.map(([x,y])=>`${x} ${y}`).join(' L ');
const pointSegmentDistance=(p,a,b)=>{const dx=b.x-a.x,dy=b.y-a.y,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy||1))),x=a.x+t*dx,y=a.y+t*dy;return Math.hypot(p.x-x,p.y-y)};
const nearestEdgeAt=(clientX,clientY,fallback)=>{const svg=document.querySelector('svg'),point={x:clientX,y:clientY};let best={edge:fallback,distance:Infinity};root.querySelectorAll('.flowchat-edge-group').forEach(edge=>{const ctm=svg?.getScreenCTM?.();const points=getPoints(edge);if(!ctm||points.length<2)return;const screen=points.map(([x,y])=>{const p=new DOMPoint(x,y).matrixTransform(ctm);return{x:p.x,y:p.y}});for(let i=0;i<screen.length-1;i++){const d=pointSegmentDistance(point,screen[i],screen[i+1]);if(d<best.distance)best={edge,distance:d}}});return best.distance<=16?best.edge:fallback};
const setEndpointVisual=(edge,role,point)=>{const endpoint=endpointLayerFor(edge)?.querySelector(`.flowchat-edge-endpoint[data-endpoint="${role}"]`);if(endpoint){endpoint.setAttribute('cx',point[0]);endpoint.setAttribute('cy',point[1])}};
const renderEdgePoints=(edge,points)=>{edge.dataset.points=JSON.stringify(points);const layer=endpointLayerFor(edge);if(layer)layer.dataset.points=JSON.stringify(points);const path=pathFor(points);edge.querySelector('.flowchat-edge')?.setAttribute('d',path);edge.querySelector('.flowchat-edge-hit')?.setAttribute('d',path);setEndpointVisual(edge,'source',points[0]);setEndpointVisual(edge,'target',points[points.length-1])};
const nodeBox=(node)=>({x:Number(node.dataset.x||0),y:Number(node.dataset.y||0),w:Number(node.dataset.w||0),h:Number(node.dataset.h||0)});
const getNodeBox=(node)=>{const body=node.querySelector('rect,polygon,circle,path');if(!body)return null;const box=body.getBBox();return{x:box.x,y:box.y,w:box.width,h:box.height}};
const distanceToBox=(p,b)=>{const dx=Math.max(b.x-p.x,0,p.x-(b.x+b.w)),dy=Math.max(b.y-p.y,0,p.y-(b.y+b.h));return Math.hypot(dx,dy)};
const anchorFor=(point,box)=>{const distances={left:Math.abs(point.x-box.x),right:Math.abs(point.x-(box.x+box.w)),top:Math.abs(point.y-box.y),bottom:Math.abs(point.y-(box.y+box.h))};const side=Object.keys(distances).sort((a,b)=>distances[a]-distances[b])[0];const pad=12;const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));if(side==='left'||side==='right')return{x:side==='left'?box.x:box.x+box.w,y:clamp(point.y,box.y+pad,box.y+box.h-pad),side};return{x:clamp(point.x,box.x+pad,box.x+box.w-pad),y:side==='top'?box.y:box.y+box.h,side}};
const nearestNode=(point,edge,role)=>{let best=null;root.querySelectorAll('.flowchat-node').forEach(node=>{const id=node.dataset.node;if(!id||id===edge.dataset[role==='source'?'target':'source'])return;const box=getNodeBox(node);if(!box)return;const distance=distanceToBox(point,box);if(distance<=24&&(!best||distance<best.distance))best={node,box,distance}});return best};
const updateEndpoint=(state,point)=>{const edge=state.edge,role=state.role,points=state.original.map(p=>[...p]);const match=nearestNode(point,edge,role);const endpoint=match?anchorFor(point,match.box):{x:point.x,y:point.y,side:''};if(role==='source')points[0]=[endpoint.x,endpoint.y];else points[points.length-1]=[endpoint.x,endpoint.y];renderEdgePoints(edge,points);edge.classList.toggle('snap-preview',Boolean(match));state.match=match;state.endpoint=endpoint};
const finishEndpoint=(cancel=false)=>{if(!endpointDrag)return;const state=endpointDrag,edge=state.edge,layer=endpointLayerFor(edge);edge.classList.remove('endpoint-dragging','snap-preview');layer?.classList.remove('endpoint-dragging','snap-preview');if(cancel||!state.match){renderEdgePoints(edge,state.original);addLog(`已取消拖动连线${state.role==='source'?'起点':'终点'}`)}else{const id=state.match.node.dataset.node;edge.dataset[state.role==='source'?'source':'target']=id;const side=state.endpoint.side;layer?.querySelector(`.flowchat-edge-endpoint[data-endpoint="${state.role}"]`)?.setAttribute('data-side',side);addLog(`连线${state.role==='source'?'起点':'终点'}已吸附到：${id}`)}endpointDrag=null};
root.querySelectorAll('.flowchat-node').forEach(node=>node.addEventListener('click',()=>{if(node.dataset.flowStage||node.dataset.targetFlow){showSubflow(node.dataset.flowStage||node.dataset.targetFlow);return}selectElement(node);addLog(`点击节点：${node.getAttribute('aria-label')}`)}));
root.querySelectorAll('.flowchat-edge-group').forEach(edge=>{edge.addEventListener('mouseenter',()=>edge.classList.add('hovered'));edge.addEventListener('mouseleave',()=>edge.classList.remove('hovered'));/* Legacy click-to-edit is kept behind the explicit edge_editing opt-in. */if(edgeEditing)edge.addEventListener('click',e=>{e.stopPropagation();const selectedEdge=nearestEdgeAt(e.clientX,e.clientY,edge);selectElement(selectedEdge);addLog(`点击连线：${selectedEdge.dataset.edge}`)})});
/* Legacy endpoint drag implementation is preserved and intentionally disabled by default. */if(edgeEditing)root.querySelectorAll('.flowchat-edge-endpoint-layer').forEach(layer=>{const edge=root.querySelector(`.flowchat-edge-group[data-edge="${layer.dataset.edge}"]`);if(!edge)return;layer.addEventListener('mouseenter',()=>edge.classList.add('hovered'));layer.addEventListener('mouseleave',()=>edge.classList.remove('hovered'));layer.querySelectorAll('.flowchat-edge-endpoint').forEach(endpoint=>endpoint.addEventListener('pointerdown',e=>{e.preventDefault();e.stopPropagation();selectElement(edge);const role=endpoint.dataset.endpoint;endpointDrag={edge,role,original:getPoints(edge).map(p=>[...p]),match:null,endpoint:null};edge.classList.add('endpoint-dragging');layer.classList.add('endpoint-dragging');stage.setPointerCapture?.(e.pointerId)}))});
root.querySelectorAll('.flowchat-subflow-node').forEach(node=>node.addEventListener('click',()=>{selectElement(node);detail.textContent=`步骤：${node.getAttribute('aria-label')} · 状态：${node.dataset.status}`;addLog(`点击子流程步骤：${node.getAttribute('aria-label')}`)}));const keyboardStep=8;
const moveEndpointByKey=(endpoint,e)=>{const layer=endpoint.closest('.flowchat-edge-endpoint-layer'),edge=layer&&root.querySelector(`.flowchat-edge-group[data-edge=\"${layer.dataset.edge}\"]`);if(!edge)return false;const points=getPoints(edge),role=endpoint.dataset.endpoint,index=role==='source'?0:points.length-1,point=[...points[index]];const delta={ArrowLeft:[-keyboardStep,0],ArrowRight:[keyboardStep,0],ArrowUp:[0,-keyboardStep],ArrowDown:[0,keyboardStep]}[e.key];if(!delta)return false;point[0]+=delta[0];point[1]+=delta[1];points[index]=point;renderEdgePoints(edge,points);selectElement(edge);addLog(`键盘移动连线${role==='source'?'起点':'终点'}`);return true};
root.querySelectorAll('.flowchat-node,.flowchat-subflow-node,.flowchat-architecture-node').forEach(node=>node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();node.dispatchEvent(new MouseEvent('click',{bubbles:true}));}else if(e.key==='Escape'){clearSelected();detail.textContent='已清除选择';}}));
root.querySelectorAll('.flowchat-edge-group').forEach(edge=>edge.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectElement(edge);addLog(`键盘选择连线：${edge.dataset.edge}`)}else if(e.key==='Escape'){clearSelected();endpointLayerFor(edge)?.classList.remove('selected');}}));
root.querySelectorAll('.flowchat-edge-endpoint').forEach(endpoint=>endpoint.addEventListener('keydown',e=>{if(moveEndpointByKey(endpoint,e)){e.preventDefault();}else if(e.key==='Enter'){e.preventDefault();endpoint.focus();addLog(`已聚焦连线${endpoint.dataset.endpoint==='source'?'起点':'终点'}`)}else if(e.key==='Escape'){e.preventDefault();const edge=endpoint.closest('.flowchat-edge-endpoint-layer')&&root.querySelector(`.flowchat-edge-group[data-edge=\"${endpoint.closest('.flowchat-edge-endpoint-layer').dataset.edge}\"]`);if(edge){renderEdgePoints(edge,getPoints(edge));selectElement(edge);}}}));
root.querySelectorAll('.flowchat-architecture-node').forEach(node=>node.addEventListener('click',()=>{selectElement(node);detail.textContent=`架构层：${node.getAttribute('aria-label')} · 状态：${node.dataset.status}`;addLog(`点击架构层：${node.getAttribute('aria-label')}`)}));
stage.addEventListener('pointerdown',e=>{activePointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(e.pointerType==='touch'&&activePointers.size===2){pinchStart=pinchDistance();pinchScale=scale;return}if(e.target.closest('.flowchat-node,.flowchat-subflow-node,.flowchat-architecture-node,.flowchat-edge,.flowchat-edge-hit,.flowchat-edge-endpoint'))return;const point=viewportPoint(e.clientX,e.clientY);drag={x:point.x,y:point.y,panX,panY};stage.setPointerCapture?.(e.pointerId)});
stage.addEventListener('pointermove',e=>{if(activePointers.has(e.pointerId))activePointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(endpointDrag){updateEndpoint(endpointDrag,viewportPoint(e.clientX,e.clientY));return}if(e.pointerType==='touch'&&activePointers.size===2&&pinchStart){scale=Math.max(.35,Math.min(2.4,pinchScale*pinchDistance()/pinchStart));apply();return}if(!drag)return;const point=viewportPoint(e.clientX,e.clientY);panX=drag.panX+(point.x-drag.x);panY=drag.panY+(point.y-drag.y);apply()});
stage.addEventListener('pointerup',e=>{activePointers.delete(e.pointerId);if(endpointDrag){finishEndpoint(false);return}if(activePointers.size<2)pinchStart=0;drag=null});stage.addEventListener('pointercancel',e=>{activePointers.delete(e.pointerId);if(endpointDrag)finishEndpoint(true);pinchStart=0;drag=null});stage.addEventListener('wheel',e=>{e.preventDefault();const point=viewportPoint(e.clientX,e.clientY),worldX=(point.x-panX)/scale,worldY=(point.y-panY)/scale,nextScale=Math.max(.35,Math.min(2.4,scale*Math.exp(-e.deltaY*.0015)));scale=nextScale;panX=point.x-worldX*scale;panY=point.y-worldY*scale;apply()},{passive:false});new ResizeObserver(fit).observe(stage);fit()
})();'''


def render_html(graph: dict[str, Any], theme: dict[str, str], title: str) -> str:
    theme = {**DEFAULT_THEME, **(theme or {})}
    nodes, edges, view_box = _normalize(graph)
    by_id = {str(node["id"]): node for node in nodes}
    fanout_routes = _compute_fanout_routes(edges, by_id)
    fanin_routes = _compute_fanin_routes(edges, by_id)
    special_routes = {**fanin_routes, **fanout_routes}
    edge_editing = bool(graph.get("edge_editing", False))
    node_markup = "".join(_node_svg(node, theme) for node in nodes)
    edge_markup_parts: list[str] = []
    edge_endpoint_parts: list[str] = []
    occupied_segments: list[tuple[list[float], list[float]]] = []
    for edge in edges:
        markup = _edge_svg(edge, by_id, theme, occupied_segments, special_routes.get(str(edge.get("id"))))
        edge_markup_parts.append(markup)
        # Endpoint editing is intentionally not mounted by default. Keep the
        # renderer and legacy markup available for an explicit host opt-in.
        if edge_editing:
            edge_endpoint_parts.append(_edge_endpoint_layer_svg(markup))
        path_match = re.search(r'<path class="flowchat-edge" d="([^"]+)"', markup)
        if path_match:
            path_points = [[float(x), float(y)] for x, y in re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path_match.group(1))]
            occupied_segments.extend(zip(path_points, path_points[1:]))
    edge_markup = "".join(edge_markup_parts)
    edge_endpoint_markup = "".join(edge_endpoint_parts)
    subflows = graph.get("subflows", {})
    subflow_markup = _subflow_layer_markup(subflows, theme)
    architecture = graph.get("architecture", {})
    architecture_markup = _architecture_markup(architecture, theme) if architecture else ""
    lane_markup = _lane_markup(graph.get("lanes", []), float(view_box[2])) if graph.get("lanes") else ""
    event_rows = "".join(f'<li><strong>{_esc(edge.get("id", "edge"))}</strong> · {_esc(edge.get("status", "pending"))}{(" · " + _esc(edge.get("label"))) if edge.get("label") else ""}</li>' for edge in edges)
    sequence_rows = "".join(f'<div class="flowchat-sequence-row"><span class="flowchat-sequence-index">{i + 1}</span><span>{_esc(node["label"])}</span><span class="flowchat-sequence-state">{_esc(node.get("status", "pending"))}</span></div>' for i, node in enumerate(sorted(nodes, key=lambda item: item.get("order", 0))))
    theme_json = json.dumps(theme, ensure_ascii=False)
    registry_json = json.dumps(TYPE_REGISTRY, ensure_ascii=False)
    graph_json = json.dumps({"viewBox": view_box, "nodes": nodes, "edges": edges, "lanes": graph.get("lanes", []), "layout": graph.get("layout", {}), "subflows": subflows, "architecture": architecture, "registry": TYPE_REGISTRY, "edge_editing": edge_editing, "dependency_contract": graph.get("dependency_contract")}, ensure_ascii=False)
    viewbox_text = " ".join(str(value) for value in view_box)
    marker_colors = {name: theme.get("edge", theme["edge_pending"]) for name in ("completed", "active", "pending", "blocked", "return", "feedback", "review")}
    marker_width = theme.get("arrow_marker_width", "5")
    marker_height = theme.get("arrow_marker_height", "5")
    marker_ref_x = theme.get("arrow_marker_ref_x", "4")
    marker_ref_y = theme.get("arrow_marker_ref_y", "2")
    marker_defs = "".join(f'<marker id="flowchat-arrow-{name}" markerWidth="{marker_width}" markerHeight="{marker_height}" refX="{marker_ref_x}" refY="{marker_ref_y}" orient="auto"><path d="M0,0 L{marker_ref_x},{marker_ref_y} L0,{marker_height} Z" fill="{color}"/></marker>' for name, color in marker_colors.items())
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)}</title>
<style>
:root{{--fc-canvas:{theme["canvas"]};--fc-panel:{theme["panel"]};--fc-text:{theme["text"]};--fc-muted:{theme["muted"]};--fc-accent:{theme["accent"]}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--fc-canvas);color:var(--fc-text);font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.flowchat-shell{{height:100vh;display:grid;grid-template-rows:auto 1fr;min-height:620px}}.flowchat-toolbar{{display:flex;gap:8px;align-items:center;padding:12px 16px;border-bottom:1px solid rgba(220,225,238,.85);background:rgba(255,255,255,.82);backdrop-filter:blur(18px);flex-wrap:wrap}}.flowchat-toolbar h1{{margin:0 16px 0 0;font-size:18px}}button{{border:1px solid #e3e8f2;border-radius:999px;background:#fff;padding:7px 11px;cursor:pointer;color:var(--fc-text)}}button:hover,button[aria-pressed=true]{{border-color:var(--fc-accent);color:var(--fc-accent)}}.flowchat-legend{{display:flex;gap:10px;margin-left:auto;color:var(--fc-muted);font-size:12px;flex-wrap:wrap}}.flowchat-legend span::before{{content:"";display:inline-block;width:18px;border-top:2px solid currentColor;margin-right:4px;vertical-align:middle}}.legend-completed,.legend-active,.legend-pending,.legend-blocked,.legend-return{{color:{theme["edge"]}!important}}
.flowchat-layout{{display:grid;grid-template-columns:minmax(0,1fr) 340px;min-height:0}}.flowchat-stage{{position:relative;overflow:hidden;background:transparent;touch-action:none}}svg{{width:100%;height:100%;display:block}}.flowchat-world,.flowchat-subflow-world,.flowchat-architecture-world{{transform-origin:0 0}}.flowchat-lane rect{{stroke:#e5e7eb;stroke-width:1}}.flowchat-lane line{{stroke:#e5e7eb;stroke-width:1}}.flowchat-lane-divider{{stroke:#d5dce7!important}}.flowchat-lane-title{{font-size:17px;font-weight:700;fill:#334155}}.flowchat-lane-subtitle{{font-size:11px;fill:#94a3b8}}.flowchat-lane-badge{{font-size:12px;fill:#64748b}}.flowchat-edge,.flowchat-subflow-edge,.flowchat-architecture-edge{{fill:none;stroke:{theme["edge"]};stroke-width:{theme.get("edge_stroke_width", "2")};stroke-linecap:round;stroke-linejoin:round}}.flowchat-edge-group[data-crossing="true"] .flowchat-edge{{stroke-dasharray:7 5!important}}.flowchat-edge-group.status-active .flowchat-edge,.flowchat-subflow-edge-group.status-active .flowchat-subflow-edge,.flowchat-architecture-edge-group.status-active .flowchat-architecture-edge{{stroke-dasharray:28 6;animation:flowchat-flow 1.35s linear infinite}}.flowchat-edge-group.status-return .flowchat-edge,.flowchat-edge-group.kind-return .flowchat-edge,.flowchat-architecture-edge-group.status-return .flowchat-architecture-edge{{stroke-dasharray:22 8;animation:flowchat-flow 1.05s linear infinite}}.flowchat-edge-group.truth-actual .flowchat-edge{{stroke:#2563eb;stroke-width:2}}.flowchat-edge-group.truth-expected .flowchat-edge{{stroke:#94a3b8;stroke-dasharray:9 8}}.flowchat-edge-group.truth-candidate .flowchat-edge{{stroke:#c0841a;stroke-dasharray:4 6}}.flowchat-edge-group.truth-callback .flowchat-edge{{stroke:#7c3aed;stroke-dasharray:18 6}}.flowchat-edge-group.truth-exception .flowchat-edge{{stroke:#dc2626;stroke-width:2;stroke-dasharray:7 5}}.flowchat-edge.demo-highlight,.flowchat-subflow-edge.demo-highlight,.flowchat-architecture-edge.demo-highlight{{stroke:var(--fc-accent)!important;stroke-width:2!important;filter:drop-shadow(0 0 5px rgba(74,104,232,.42))}}
.flowchat-edge-group{{cursor:pointer}}.flowchat-edge{{pointer-events:none}}.flowchat-edge-hit{{fill:none;stroke:transparent;stroke-width:14;stroke-linecap:round;stroke-linejoin:round;pointer-events:stroke;cursor:pointer}}.flowchat-edge-group:hover .flowchat-edge,.flowchat-edge-group.hovered .flowchat-edge{{filter:drop-shadow(0 0 3px rgba(74,104,232,.4))}}.flowchat-edge-group.selected .flowchat-edge{{stroke:var(--fc-accent)!important;stroke-width:2.5!important}}.flowchat-edge-endpoint{{display:none;fill:var(--fc-accent);stroke:#fff;stroke-width:2.5;cursor:crosshair;pointer-events:all}}.flowchat-edge-group.selected .flowchat-edge-endpoint,.flowchat-edge-endpoint-layer.selected .flowchat-edge-endpoint,.flowchat-edge-group.endpoint-dragging .flowchat-edge-endpoint,.flowchat-edge-endpoint-layer.endpoint-dragging .flowchat-edge-endpoint{{display:block}}.flowchat-edge-group.endpoint-dragging .flowchat-edge{{stroke:var(--fc-accent)!important;stroke-dasharray:none!important}}.flowchat-edge-group.snap-preview .flowchat-edge-endpoint,.flowchat-edge-endpoint-layer.snap-preview .flowchat-edge-endpoint{{r:10;stroke-width:3}}.flowchat-node,.flowchat-subflow-node,.flowchat-architecture-node{{cursor:pointer;outline:none}}.flowchat-node:focus-visible,.flowchat-subflow-node:focus-visible,.flowchat-architecture-node:focus-visible,.flowchat-edge-group:focus-visible,.flowchat-edge-endpoint:focus-visible{{outline:3px solid var(--fc-accent);outline-offset:4px}}.flowchat-node>rect,.flowchat-node>polygon,.flowchat-node>circle,.flowchat-node>path,.flowchat-subflow-node>rect,.flowchat-architecture-node>rect{{stroke:{theme["node_stroke"]};stroke-width:1.5;filter:drop-shadow(0 10px 24px rgba(71,88,137,.09))}}.flowchat-node.kind-orchestrator>rect{{fill:#eef2ff;stroke:#4a68e8;stroke-width:2.8}}.flowchat-node.kind-control>rect{{fill:#eef7ff;stroke:#4a68e8;stroke-width:2.2}}.flowchat-node.kind-review-center>rect{{fill:#fffaf0;stroke:#d9983a;stroke-width:2.2}}.flowchat-node.kind-stage>rect{{fill:#fff;stroke-width:2}}.flowchat-node.kind-stage .line-0{{font-size:11px;font-weight:750;fill:#7657d9}}.flowchat-node.kind-stage .line-1{{font-size:14px;font-weight:700}}.flowchat-node.kind-dispatch>rect{{fill:#f5f3ff;stroke:#7657d9;stroke-width:2}}.flowchat-node.kind-agent>rect{{fill:#fff;stroke-width:2.2}}.flowchat-node.kind-summary>rect{{fill:#eef7ff;stroke:#4a68e8;stroke-width:2}}.flowchat-node.kind-gate>rect{{fill:#fffaf0;stroke:#d9983a;stroke-width:2}}.flowchat-node.kind-issue>rect{{fill:#fff5f5;stroke:#d75a67;stroke-width:2}}.flowchat-node.kind-feedback>rect{{fill:#f2fbf6;stroke:#3ea77a;stroke-width:1.5;opacity:.86}}.flowchat-node.status-completed{{opacity:.72}}.flowchat-node.status-pending,.flowchat-node.status-not-run{{opacity:.78}}.flowchat-node.status-active{{animation:flowchat-node-pulse 2s ease-in-out infinite}}.flowchat-node.status-active>rect,.flowchat-node.status-active>polygon,.flowchat-node.status-active>circle,.flowchat-node.status-active>path{{stroke:var(--fc-accent)}}.flowchat-node.status-blocked>rect,.flowchat-node.status-blocked>polygon,.flowchat-node.status-blocked>circle,.flowchat-node.status-blocked>path{{stroke:{theme.get("blocked_stroke", theme["edge_blocked"])} }}.flowchat-node.status-review>rect,.flowchat-node.status-review>polygon,.flowchat-node.status-review>circle,.flowchat-node.status-review>path,.flowchat-node.status-needs-review>rect,.flowchat-node.status-needs-review>polygon,.flowchat-node.status-needs-review>circle,.flowchat-node.status-needs-review>path{{stroke:{theme.get("review_stroke", "#d9983a")} }}.flowchat-node.status-candidate>rect,.flowchat-node.status-candidate>polygon,.flowchat-node.status-candidate>circle,.flowchat-node.status-candidate>path{{stroke:{theme.get("candidate_stroke", "#d9983a")} }}.flowchat-node.status-unknown>rect,.flowchat-node.status-unknown>polygon,.flowchat-node.status-unknown>circle,.flowchat-node.status-unknown>path,.flowchat-node.status-not-implemented>rect,.flowchat-node.status-not-implemented>polygon,.flowchat-node.status-not-implemented>circle,.flowchat-node.status-not-implemented>path{{stroke:{theme.get("needs_review_stroke", "#98a5bd")};stroke-dasharray:5 4}}.flowchat-node-status-badge{{fill:#94a3b8;stroke:#fff;stroke-width:2}}.flowchat-node.status-completed .flowchat-node-status-badge{{fill:#16a34a}}.flowchat-node.status-active .flowchat-node-status-badge{{fill:#2563eb}}.flowchat-node.status-blocked .flowchat-node-status-badge{{fill:#dc2626}}.flowchat-node.status-review .flowchat-node-status-badge,.flowchat-node.status-needs-review .flowchat-node-status-badge{{fill:#d97706}}.flowchat-node.status-candidate .flowchat-node-status-badge{{fill:#d9983a}}.flowchat-node:hover>rect,.flowchat-node:hover>polygon,.flowchat-node:hover>circle,.flowchat-node:hover>path,.flowchat-node.selected>rect,.flowchat-node.selected>polygon,.flowchat-node.selected>circle,.flowchat-node.selected>path,.flowchat-subflow-node:hover>rect,.flowchat-subflow-node.selected>rect,.flowchat-architecture-node:hover>rect,.flowchat-architecture-node.selected>rect{{stroke:var(--fc-accent);filter:drop-shadow(0 14px 26px rgba(71,88,137,.15))}}.flowchat-node text,.flowchat-subflow-node text,.flowchat-architecture-node text{{fill:{theme["text"]}}}.flowchat-node-icon{{font-size:13px;font-weight:700;fill:currentColor;opacity:.72;pointer-events:none}}
.flowchat-side{{padding:18px;background:var(--fc-panel);backdrop-filter:blur(22px);border-left:1px solid rgba(222,227,239,.72);box-shadow:0 8px 20px rgba(91,91,145,.09);overflow:auto}}.flowchat-side h2{{font-size:14px;margin:0 0 8px}}.flowchat-detail{{padding:13px;border:1px solid #e3e8f2;border-radius:12px;background:rgba(255,255,255,.88);box-shadow:0 8px 20px rgba(91,91,145,.09);min-height:68px;margin-bottom:16px;white-space:pre-line}}.flowchat-log{{margin:0;padding-left:20px;color:var(--fc-muted);font-size:12px;max-height:290px;overflow:auto}}.flowchat-sequence{{display:none;padding:24px;overflow:auto}}.flowchat-sequence-row{{display:grid;grid-template-columns:32px 1fr auto;gap:10px;align-items:center;padding:11px 12px;border:1px solid #e3e8f2;border-radius:12px;margin-bottom:8px;background:rgba(255,255,255,.88);box-shadow:0 8px 20px rgba(91,91,145,.06)}}.flowchat-sequence-index{{color:var(--fc-accent);font-weight:700}}.flowchat-shell[data-view=sequence] .flowchat-stage{{display:none}}.flowchat-shell[data-view=sequence] .flowchat-sequence{{display:block}}@keyframes flowchat-flow{{to{{stroke-dashoffset:-40}}}}@keyframes flowchat-node-pulse{{0%,100%{{filter:drop-shadow(0 0 0 rgba(77,139,255,0))}}50%{{filter:drop-shadow(0 0 12px rgba(77,139,255,.35))}}}}@media(max-width:640px){{.flowchat-layout{{grid-template-columns:1fr}}.flowchat-side{{max-height:260px;border-left:0;border-top:1px solid #d8e0ea}}.flowchat-legend{{margin-left:0;width:100%}}}}
</style></head><body>
<div class="flowchat-shell" data-view="flow" data-edge-editing="{'enabled' if edge_editing else 'disabled'}" data-initial-title="{_esc(title)}" data-flowchat-root>
<div class="flowchat-toolbar"><h1 data-flowchat-title>{_esc(title)}</h1><button type="button" data-view-button="flow" aria-pressed="true">流程视图</button><button type="button" data-view-button="architecture" aria-pressed="false">架构视图</button><button type="button" data-view-button="sequence" aria-pressed="false">时序视图</button><button type="button" data-action="overview" hidden>返回总览</button><button type="button" data-action="fit">适应视图</button><button type="button" data-action="demo">动态演示</button><div class="flowchat-legend"><span class="legend-completed">已完成</span><span class="legend-active">进行中</span><span class="legend-pending">待流转</span><span class="legend-blocked">阻塞</span><span class="legend-return">返工</span></div></div>
<div class="flowchat-layout"><div class="flowchat-stage" data-flowchat-stage><svg viewBox="{viewbox_text}" preserveAspectRatio="xMidYMid meet" aria-label="Flowchat 实时执行拓扑图"><defs>{marker_defs}</defs><g class="flowchat-world" data-flowchat-world>{lane_markup}{edge_markup}{node_markup}{edge_endpoint_markup}</g>{subflow_markup}{architecture_markup}</svg></div><div class="flowchat-sequence">{sequence_rows}</div><aside class="flowchat-side"><h2>节点详情</h2><div class="flowchat-detail" data-flowchat-detail>点击节点查看 Run、Stage、来源与执行原因。</div><h2>阶段转场</h2><div class="flowchat-detail" data-flowchat-transition>点击节点查看它的真实执行上下文。</div><h2>连线与事件</h2><ol class="flowchat-log" data-flowchat-log>{event_rows}</ol></aside></div></div>
<script>window.__FLOWCHAT_GRAPH__={graph_json};window.__FLOWCHAT_THEME__={theme_json};window.__FLOWCHAT_REGISTRY__={registry_json};window.__FLOWCHAT_VIEWBOX__={json.dumps(view_box)};</script>
<script>{_interaction_script()}</script></body></html>'''

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a standalone Flowchat HTML page")
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--theme", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Flowchat")
    args = parser.parse_args()
    graph = _load(args.graph, _demo_graph())
    theme = dict(DEFAULT_THEME)
    theme.update(_load(args.theme, {}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(graph, theme, args.title), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
