#!/usr/bin/env python3
"""Generate a self-contained Flowchat HTML document from graph and theme JSON."""

from __future__ import annotations

import argparse
import heapq
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


# The edge id currently being rendered, so geometry failures can name it.
_CURRENT_EDGE: list[str] = []


DEFAULT_THEME: dict[str, str] = {
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


def _normalize(graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[float]]:
    nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(graph.get("nodes", [])):
        node = dict(raw)
        node.setdefault("id", f"node-{index + 1}")
        node.setdefault("label", node["id"])
        node.setdefault("shape", "rect")
        node.setdefault("width", 156 if node["shape"] != "diamond" else 150)
        node.setdefault("height", 88 if node["shape"] != "diamond" else 106)
        node.setdefault("x", 80 + index * 240)
        node.setdefault("y", 220)
        node.setdefault("status", "pending")
        node.setdefault("kind", "node")
        node.setdefault("order", index)
        nodes.append(node)
    edges = [dict(edge) for edge in graph.get("edges", [])]
    view_box = list(graph.get("viewBox", [0, 0, 1200, 620]))
    if len(view_box) != 4:
        view_box = [0, 0, 1200, 620]
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


def _node_svg(node: dict[str, Any], theme: dict[str, str]) -> str:
    node_id, label = _esc(node["id"]), _esc(node["label"])
    x, y = float(node["x"]), float(node["y"])
    width, height = float(node["width"]), float(node["height"])
    cx, cy = x + width / 2, y + height / 2
    shape = node.get("shape", "rect")
    status = str(node.get("status", "pending"))
    kind = str(node.get("kind", "node"))
    if status == "blocked":
        fill = theme.get("blocked_fill", theme["node_fill"])
    elif kind in {"agent", "dispatch"}:
        fill = theme.get(f"{kind}_fill", theme.get("agent_fill", theme["square_fill"]))
    elif kind == "review" or shape == "circle":
        fill = theme.get("review_fill", theme["diamond_fill"])
    elif kind == "feedback":
        fill = theme.get("feedback_fill", theme["node_fill"])
    else:
        fill = theme["diamond_fill"] if shape == "diamond" else theme["node_fill"]
    if shape == "diamond":
        points = f"{cx},{y} {x + width},{cy} {cx},{y + height} {x},{cy}"
        body = f'<polygon points="{points}" fill="{fill}" />'
    elif shape == "circle":
        body = f'<circle cx="{cx}" cy="{cy}" r="{min(width, height) / 2}" fill="{fill}" />'
    else:
        body = f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="{fill}" />'
    lines = _lines(str(node["label"]), max(6, int(width // 13)))
    line_height = 18
    start = cy - (len(lines) - 1) * line_height / 2
    text = "".join(f'<tspan class="flowchat-node-line line-{i}" x="{cx}" dy="{0 if i == 0 else line_height}">{_esc(line)}</tspan>' for i, line in enumerate(lines))
    status = _esc(status)
    kind_class = _esc(kind.replace("_", "-"))
    phase_class = _esc(str(node.get("phase", "unknown")).replace("_", "-"))
    readiness_class = _esc(str(node.get("readiness", "needs_review")).replace("_", "-"))
    diamond_marker = ' data-diamond-text="centered"' if shape == "diamond" else ''
    stage_attr = f' data-flow-stage="{node_id}"' if kind == "stage" else ''
    details_attr = ''
    if node.get("details"):
        details_attr = f' data-details="{_esc(json.dumps(node["details"], ensure_ascii=False, separators=(",", ":")))}"'
    return f'<g class="flowchat-node kind-{kind_class} phase-{phase_class} readiness-{readiness_class} status-{status}" data-node="{node_id}" data-status="{status}" data-kind="{_esc(kind)}" data-shape="{_esc(shape)}"{stage_attr}{details_attr} tabindex="0" role="button" aria-label="{label}">{body}<text x="{cx}" y="{start}" text-anchor="middle" dominant-baseline="middle" data-text-region="node" data-text-align="center"{diamond_marker} fill="{theme["text"]}">{text}</text></g>'


def _edge_color(edge: dict[str, Any], theme: dict[str, str]) -> str:
    """Keep the edge palette neutral; status is carried by dash/animation/width."""
    return theme.get("edge", theme["edge_pending"])


def _edge_marker(edge: dict[str, Any]) -> str:
    status = str(edge.get("status", "pending"))
    kind = str(edge.get("kind", "main"))
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
    return "pending"


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
    if source.get("shape", "rect") != "rect" or target.get("shape", "rect") != "rect":
        return None

    start, end = _port_point(source, source_port), _port_point(target, target_port)
    if target_side in {"left", "right"} and edge.get("target_port_y") is not None:
        end[1] = float(edge["target_port_y"])
    if target_side in {"top", "bottom"} and edge.get("target_port_x") is not None:
        end[0] = float(edge["target_port_x"])
    min_segment = 8.0
    min_arrow = float(edge.get("min_arrow_segment", 75))
    padding = 12.0
    nodes_list = list(nodes.values())
    x_values = {start[0], end[0]}
    y_values = {start[1], end[1]}
    for node in nodes_list:
        left, top = float(node["x"]), float(node["y"])
        right, bottom = left + float(node["width"]), top + float(node["height"])
        x_values.update({left - padding, left - min_arrow, right + padding, right + min_arrow, left, right})
        y_values.update({top - padding, top - min_arrow, bottom + padding, bottom + min_arrow, top, bottom})
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
            if distance < min_segment or not clear(a, b):
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
            lane_penalty = 0.0
            for occupied_a, occupied_b in occupied_segments or []:
                overlap = segment_overlap_length(a, b, occupied_a, occupied_b)
                if overlap:
                    lane_penalty += overlap * 300.0
                elif segment_crosses(a, b, occupied_a, occupied_b):
                    lane_penalty += 100.0
            next_cost = cost + distance + (22.0 if incoming not in {-1, direction} else 0.0) + lane_penalty
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
    if port_side in {"left", "right", "top", "bottom"} and shape == "rect":
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
        if port_side in {"left", "right", "top", "bottom"}:
            # 明确 side 时返回轴对齐端点，保证 route 正交
            if port_side == "left":   return [left, cy]
            if port_side == "right":  return [left + width, cy]
            if port_side == "top":    return [cx, top]
            return [cx, top + height]
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


def _edge_svg(
    edge: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    theme: dict[str, str],
    occupied_segments: list[tuple[list[float], list[float]]] | None = None,
) -> str:
    source, target = nodes.get(str(edge.get("source"))), nodes.get(str(edge.get("target")))
    if not source or not target:
        return ""
    _CURRENT_EDGE.clear()
    _CURRENT_EDGE.append(str(edge.get("id", "<unnamed>")))
    auto_route = _auto_orthogonal_route(edge, nodes, occupied_segments) if edge.get("routing") == "auto" else None
    if auto_route:
        points = auto_route
        points[0] = _snap_to_node_edge(source, points[0], points[1], _edge_port(edge, "source"))
        points[-1] = _snap_to_node_edge(target, points[-1], points[-2], _edge_port(edge, "target"))
        points = _ensure_orthogonal_route(points)
        points = _ensure_min_edge_length(points, float(edge.get("min_length", 90)))
        points = _ensure_min_arrow_segment(points, float(edge.get("min_arrow_segment", 75)))
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
        points = _ensure_min_arrow_segment(points, float(edge.get("min_arrow_segment", 75)))
        d = "M " + " L ".join(f"{x} {y}" for x, y in points)
        label_x = edge.get("label_x", sum(p[0] for p in points) / len(points))
        label_y = edge.get("label_y", sum(p[1] for p in points) / len(points))
    else:
        sx = float(source["x"]) + float(source["width"])
        sy = float(source["y"]) + float(source["height"]) / 2
        tx = float(target["x"])
        ty = float(target["y"]) + float(target["height"]) / 2
        if float(target["x"]) < float(source["x"]):
            sx = float(source["x"])
            tx = float(target["x"]) + float(target["width"])
        inferred = dict(edge)
        inferred.setdefault("source_side", "right" if tx >= sx else "left")
        inferred.setdefault("target_side", "left" if tx >= sx else "right")
        auto_route = _auto_orthogonal_route(inferred, nodes, occupied_segments)
        points = auto_route or [[sx, sy], [tx, ty]]
        points = _ensure_orthogonal_route(points)
        points = _ensure_min_direct_edge_length(points, float(edge.get("min_length", 90))) if len(points) == 2 else _ensure_min_edge_length(points, float(edge.get("min_length", 90)))
        points = _ensure_min_arrow_segment(points, float(edge.get("min_arrow_segment", 75)))
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
    truth_type = str(edge.get("truth_type", "")).strip().lower().replace("_", "-")
    truth_class = f" truth-{_esc(truth_type)}" if truth_type else ""
    truth_attr = f' data-truth-type="{_esc(truth_type)}"' if truth_type else ""
    edge_details = edge.get("details") or {key: edge.get(key) for key in ("reason", "expected", "actual", "run_id", "stage_run_id", "agent_run_id") if edge.get(key) is not None}
    details_attr = f' data-details="{_esc(json.dumps(edge_details, ensure_ascii=False, separators=(",", ":")))}"' if edge_details else ""
    stroke_width = _esc(theme.get("edge_stroke_width", "2"))
    return f'<g class="flowchat-edge-group kind-{kind}{truth_class} status-{status}" data-edge="{_esc(edge.get("id", ""))}" data-status="{status}"{truth_attr}{details_attr}{crossing_attr}><path class="flowchat-edge" d="{d}" stroke="{color}" data-stroke-width="{stroke_width}" marker-end="url(#flowchat-arrow-{marker})" />{label_markup}</g>'


def _subflow_node_svg(node: dict[str, Any], theme: dict[str, str]) -> str:
    """Compact node renderer for the stage-local map."""
    x, y, width, height = (float(node[key]) for key in ("x", "y", "width", "height"))
    cx, cy = x + width / 2, y + height / 2
    status = _esc(node.get("status", "pending"))
    label = _esc(node.get("label", node.get("id", "step")))
    fill = "#fff5f5" if status == "blocked" else "#fffaf0" if status in {"review", "return"} else "#ffffff"
    lines = _lines(str(node.get("label", "")), max(7, int(width // 13)))
    line_height = 18
    start = cy - (len(lines) - 1) * line_height / 2
    text = "".join(f'<tspan x="{cx}" dy="{0 if i == 0 else line_height}">{_esc(line)}</tspan>' for i, line in enumerate(lines))
    kind = _esc(node.get("kind", "subflow-step").replace("_", "-"))
    return f'<g class="flowchat-subflow-node kind-{kind} status-{status}" data-subflow-node="{_esc(node.get("id", ""))}" data-subflow-kind="{kind}" data-status="{status}" tabindex="0" role="button" aria-label="{label}"><rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="{fill}"/><text x="{cx}" y="{start}" text-anchor="middle" dominant-baseline="middle" data-text-region="subflow" fill="{theme["text"]}">{text}</text></g>'


def _subflow_edge_svg(edge: dict[str, Any], nodes: dict[str, dict[str, Any]], theme: dict[str, str]) -> str:
    source, target = nodes.get(str(edge.get("source"))), nodes.get(str(edge.get("target")))
    if not source or not target:
        return ""
    points = [[float(p[0]), float(p[1])] for p in edge.get("route_points", [])]
    if len(points) < 2:
        points = [[source["x"] + source["width"], source["y"] + source["height"] / 2], [target["x"], target["y"] + target["height"] / 2]]
    points[0] = _snap_to_node_edge(source, points[0], points[1], "right")
    points[-1] = _snap_to_node_edge(target, points[-1], points[-2], "left")
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    status = _esc(edge.get("status", "pending"))
    marker = _edge_marker(edge)
    dash = ' stroke-dasharray="10 8"' if status in {"return", "review"} else ""
    return f'<g class="flowchat-subflow-edge-group status-{status}" data-subflow-edge="{_esc(edge.get("id", ""))}"><path class="flowchat-subflow-edge" d="{d}" stroke="{theme.get("edge", theme["edge_pending"])}"{dash} marker-end="url(#flowchat-arrow-{marker})" /></g>'


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
    """Render optional white swimlane scaffolding behind graph edges and nodes."""
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
            f'<g class="flowchat-lane" data-lane="{_esc(lane.get("id", ""))}">'
            f'<rect x="0" y="{y}" width="{canvas_width}" height="{height}" fill="{_esc(fill)}"/>'
            f'<line x1="0" y1="{y}" x2="{canvas_width}" y2="{y}"/>'
            f'<line x1="218" y1="{y}" x2="218" y2="{y + height}" class="flowchat-lane-divider"/>'
            f'{label_markup}</g>'
        )
    return "".join(markup)


def render_html(graph: dict[str, Any], theme: dict[str, str], title: str) -> str:
    nodes, edges, view_box = _normalize(graph)
    by_id = {str(node["id"]): node for node in nodes}
    node_markup = "".join(_node_svg(node, theme) for node in nodes)
    edge_markup_parts: list[str] = []
    occupied_segments: list[tuple[list[float], list[float]]] = []
    for edge in edges:
        markup = _edge_svg(edge, by_id, theme, occupied_segments)
        edge_markup_parts.append(markup)
        path_match = re.search(r'<path class="flowchat-edge" d="([^"]+)"', markup)
        if path_match:
            path_points = [[float(x), float(y)] for x, y in re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path_match.group(1))]
            occupied_segments.extend(zip(path_points, path_points[1:]))
    edge_markup = "".join(edge_markup_parts)
    subflows = graph.get("subflows", {})
    subflow_markup = _subflow_layer_markup(subflows, theme)
    architecture = graph.get("architecture", {})
    architecture_markup = _architecture_markup(architecture, theme) if architecture else ""
    lane_markup = _lane_markup(graph.get("lanes", []), float(view_box[2])) if graph.get("lanes") else ""
    event_rows = "".join(f'<li><strong>{_esc(edge.get("id", "edge"))}</strong> · {_esc(edge.get("status", "pending"))}{(" · " + _esc(edge.get("label"))) if edge.get("label") else ""}</li>' for edge in edges)
    sequence_rows = "".join(f'<div class="flowchat-sequence-row"><span class="flowchat-sequence-index">{i + 1}</span><span>{_esc(node["label"])}</span><span class="flowchat-sequence-state">{_esc(node.get("status", "pending"))}</span></div>' for i, node in enumerate(sorted(nodes, key=lambda item: item.get("order", 0))))
    theme_json = json.dumps(theme, ensure_ascii=False)
    graph_json = json.dumps({"viewBox": view_box, "nodes": nodes, "edges": edges, "lanes": graph.get("lanes", []), "subflows": subflows, "architecture": architecture}, ensure_ascii=False)
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
.flowchat-node,.flowchat-subflow-node,.flowchat-architecture-node{{cursor:pointer;outline:none}}.flowchat-node>rect,.flowchat-node>polygon,.flowchat-node>circle,.flowchat-subflow-node>rect,.flowchat-architecture-node>rect{{stroke:{theme["node_stroke"]};stroke-width:1.5;filter:drop-shadow(0 10px 24px rgba(71,88,137,.09))}}.flowchat-node.kind-orchestrator>rect{{fill:#eef2ff;stroke:#4a68e8;stroke-width:2.8}}.flowchat-node.kind-control>rect{{fill:#eef7ff;stroke:#4a68e8;stroke-width:2.2}}.flowchat-node.kind-review-center>rect{{fill:#fffaf0;stroke:#d9983a;stroke-width:2.2}}.flowchat-node.kind-stage>rect{{fill:#fff;stroke-width:2}}.flowchat-node.kind-stage .line-0{{font-size:11px;font-weight:750;fill:#7657d9}}.flowchat-node.kind-stage .line-1{{font-size:14px;font-weight:700}}.flowchat-node.kind-dispatch>rect{{fill:#f5f3ff;stroke:#7657d9;stroke-width:2}}.flowchat-node.kind-agent>rect{{fill:#fff;stroke-width:2.2}}.flowchat-node.kind-summary>rect{{fill:#eef7ff;stroke:#4a68e8;stroke-width:2}}.flowchat-node.kind-gate>rect{{fill:#fffaf0;stroke:#d9983a;stroke-width:2}}.flowchat-node.kind-issue>rect{{fill:#fff5f5;stroke:#d75a67;stroke-width:2}}.flowchat-node.kind-feedback>rect{{fill:#f2fbf6;stroke:#3ea77a;stroke-width:1.5;opacity:.86}}.flowchat-node.status-completed{{opacity:.58}}.flowchat-node.status-completed>rect,.flowchat-node.status-completed>polygon,.flowchat-node.status-completed>circle{{fill:#f1f3f6!important;stroke:#9aa3b2!important}}.flowchat-node.status-pending>rect,.flowchat-node.status-pending>polygon,.flowchat-node.status-pending>circle{{fill:#f5f6f8!important;stroke:#a8b0bd!important;opacity:.78}}.flowchat-node.status-active>rect,.flowchat-node.status-active>polygon{{stroke:var(--fc-accent);animation:flowchat-node-pulse 2s ease-in-out infinite}}.flowchat-node.status-blocked>rect,.flowchat-node.status-blocked>polygon,.flowchat-node.status-blocked>circle{{stroke:{theme.get("blocked_stroke", theme["edge_blocked"])} }}.flowchat-node:hover>rect,.flowchat-node:hover>polygon,.flowchat-node:hover>circle,.flowchat-node.selected>rect,.flowchat-node.selected>polygon,.flowchat-subflow-node:hover>rect,.flowchat-subflow-node.selected>rect,.flowchat-architecture-node:hover>rect,.flowchat-architecture-node.selected>rect{{stroke:var(--fc-accent);filter:drop-shadow(0 14px 26px rgba(71,88,137,.15))}}.flowchat-node text,.flowchat-subflow-node text,.flowchat-architecture-node text{{fill:{theme["text"]}}}
.flowchat-side{{padding:18px;background:var(--fc-panel);backdrop-filter:blur(22px);border-left:1px solid rgba(222,227,239,.72);box-shadow:0 8px 20px rgba(91,91,145,.09);overflow:auto}}.flowchat-side h2{{font-size:14px;margin:0 0 8px}}.flowchat-detail{{padding:13px;border:1px solid #e3e8f2;border-radius:12px;background:rgba(255,255,255,.88);box-shadow:0 8px 20px rgba(91,91,145,.09);min-height:68px;margin-bottom:16px;white-space:pre-line}}.flowchat-log{{margin:0;padding-left:20px;color:var(--fc-muted);font-size:12px;max-height:290px;overflow:auto}}.flowchat-sequence{{display:none;padding:24px;overflow:auto}}.flowchat-sequence-row{{display:grid;grid-template-columns:32px 1fr auto;gap:10px;align-items:center;padding:11px 12px;border:1px solid #e3e8f2;border-radius:12px;margin-bottom:8px;background:rgba(255,255,255,.88);box-shadow:0 8px 20px rgba(91,91,145,.06)}}.flowchat-sequence-index{{color:var(--fc-accent);font-weight:700}}.flowchat-shell[data-view=sequence] .flowchat-stage{{display:none}}.flowchat-shell[data-view=sequence] .flowchat-sequence{{display:block}}@keyframes flowchat-flow{{to{{stroke-dashoffset:-40}}}}@keyframes flowchat-node-pulse{{0%,100%{{filter:drop-shadow(0 0 0 rgba(77,139,255,0))}}50%{{filter:drop-shadow(0 0 12px rgba(77,139,255,.35))}}}}@media(max-width:640px){{.flowchat-layout{{grid-template-columns:1fr}}.flowchat-side{{max-height:260px;border-left:0;border-top:1px solid #d8e0ea}}.flowchat-legend{{margin-left:0;width:100%}}}}
</style></head><body>
<div class="flowchat-shell" data-view="flow" data-flowchat-root>
<div class="flowchat-toolbar"><h1 data-flowchat-title>{_esc(title)}</h1><button type="button" data-view-button="flow" aria-pressed="true">流程视图</button><button type="button" data-view-button="architecture" aria-pressed="false">架构视图</button><button type="button" data-view-button="sequence" aria-pressed="false">时序视图</button><button type="button" data-action="overview" hidden>返回总览</button><button type="button" data-action="fit">适应视图</button><button type="button" data-action="demo">动态演示</button><div class="flowchat-legend"><span class="legend-completed">已完成</span><span class="legend-active">进行中</span><span class="legend-pending">待流转</span><span class="legend-blocked">阻塞</span><span class="legend-return">返工</span></div></div>
<div class="flowchat-layout"><div class="flowchat-stage" data-flowchat-stage><svg viewBox="{viewbox_text}" preserveAspectRatio="xMidYMid meet" aria-label="Flowchat 实时执行拓扑图"><defs>{marker_defs}</defs><g class="flowchat-world" data-flowchat-world>{lane_markup}{edge_markup}{node_markup}</g>{subflow_markup}{architecture_markup}</svg></div><div class="flowchat-sequence">{sequence_rows}</div><aside class="flowchat-side"><h2>节点详情</h2><div class="flowchat-detail" data-flowchat-detail>点击节点查看 Run、Stage、来源与执行原因。</div><h2>阶段转场</h2><div class="flowchat-detail" data-flowchat-transition>点击节点查看它的真实执行上下文。</div><h2>连线与事件</h2><ol class="flowchat-log" data-flowchat-log>{event_rows}</ol></aside></div></div>
<script>window.__FLOWCHAT_GRAPH__={graph_json};window.__FLOWCHAT_THEME__={theme_json};window.__FLOWCHAT_VIEWBOX__={json.dumps(view_box)};</script>
<script>
(()=>{{const root=document.querySelector('[data-flowchat-root]'),stage=root.querySelector('[data-flowchat-stage]'),overview=root.querySelector('[data-flowchat-world]'),layers=[...root.querySelectorAll('[data-flowchat-subflow]')],architectureLayer=root.querySelector('[data-flowchat-architecture]'),architectureWorld=architectureLayer?.querySelector('.flowchat-architecture-world'),detail=root.querySelector('[data-flowchat-detail]'),transition=root.querySelector('[data-flowchat-transition]'),log=root.querySelector('[data-flowchat-log]'),titleNode=root.querySelector('[data-flowchat-title]'),back=root.querySelector('[data-action=overview]'),vb=window.__FLOWCHAT_VIEWBOX__||[0,0,1600,960],vw=vb[2],vh=vb[3],subflows=window.__FLOWCHAT_GRAPH__.subflows||{{}},architecture=window.__FLOWCHAT_GRAPH__.architecture||{{}};let scale=1,panX=0,panY=0,drag=null,activeStage=null;const activePointers=new Map();const viewportPoint=(clientX,clientY)=>{{const rect=stage.getBoundingClientRect(),svgScale=Math.min(rect.width/vw,rect.height/vh),offsetX=(rect.width-vw*svgScale)/2,offsetY=(rect.height-vh*svgScale)/2;return {{x:(clientX-rect.left-offsetX)/svgScale,y:(clientY-rect.top-offsetY)/svgScale}}}};let pinchStart=0,pinchScale=1;const pinchDistance=()=>{{const p=[...activePointers.values()];return p.length===2?Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y):0}};const visibleLayer=()=>activeStage?root.querySelector(`[data-flowchat-subflow="${{activeStage}}"]`):root.dataset.view==='architecture'?architectureWorld:overview;const apply=()=>[overview,...layers.map(x=>x.querySelector('.flowchat-subflow-world')),architectureWorld].forEach(world=>world&&world.setAttribute('transform',`translate(${{panX}} ${{panY}}) scale(${{scale}})`));const fit=()=>{{scale=1;panX=0;panY=0;apply()}};const addLog=(text)=>{{const li=document.createElement('li');li.textContent=text;log.prepend(li);while(log.children.length>20)log.lastElementChild.remove()}};const formatDetails=(element)=>{{let data={{}};try{{data=JSON.parse(element.dataset.details||'{{}}')}}catch{{data={{}}}}const rows=Object.entries(data).filter(([,value])=>value!==null&&value!==undefined&&value!=='').map(([key,value])=>`${{key}}：${{Array.isArray(value)?value.join('、'):typeof value==='object'?JSON.stringify(value):value}}`);return rows.length?`${{element.getAttribute('aria-label')||element.dataset.edge||''}} · ${{rows.join(' / ')}}`:`${{element.getAttribute('aria-label')||element.dataset.edge||''}} · 状态：${{element.dataset.status||'unknown'}}`}};const showOverview=()=>{{activeStage=null;root.dataset.view='flow';overview.style.display='';layers.forEach(layer=>layer.style.display='none');if(architectureLayer)architectureLayer.style.display='none';back.hidden=true;titleNode.textContent={json.dumps(title, ensure_ascii=False)};transition.textContent='点击节点查看它的真实执行上下文。';fit();addLog('返回阶段总览')}};const showSubflow=(id)=>{{const meta=subflows[id];if(!meta)return;activeStage=id;root.dataset.view='flow';overview.style.display='none';layers.forEach(layer=>layer.style.display=layer.dataset.flowchatSubflow===id?'':'none');if(architectureLayer)architectureLayer.style.display='none';back.hidden=false;titleNode.textContent=meta.title;transition.textContent=`${{meta.entry}}\n${{meta.next}}\n${{meta.loop}}\n审核策略：${{meta.review_policy||'AI + 人工'}}`;fit();addLog(`打开子流程：${{meta.title}}`)}};const showArchitecture=()=>{{activeStage=null;root.dataset.view='architecture';overview.style.display='none';layers.forEach(layer=>layer.style.display='none');if(architectureLayer)architectureLayer.style.display='';back.hidden=true;titleNode.textContent=architecture.title||'Agent 工程分层架构';transition.textContent='每层只承担一个职责：说明项目、控制权限、加载规则、触发命令、复用技能、执行 Agent、统一 Harness 门禁、连接 Tool / MCP，并把结果沉淀为证据。';fit();addLog('打开架构视图')}};root.querySelectorAll('[data-view-button]').forEach(b=>b.addEventListener('click',()=>{{if(b.dataset.viewButton==='architecture'){{showArchitecture();}}else if(b.dataset.viewButton==='flow'){{showOverview();}}else{{root.dataset.view='sequence';activeStage=null;overview.style.display='';layers.forEach(layer=>layer.style.display='none');if(architectureLayer)architectureLayer.style.display='none';back.hidden=true;}}root.querySelectorAll('[data-view-button]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));addLog(`切换到 ${{b.textContent}}`)}}));back.addEventListener('click',showOverview);root.querySelector('[data-action=fit]').addEventListener('click',()=>{{fit();addLog('已适应视图')}});root.querySelector('[data-action=demo]').addEventListener('click',()=>{{visibleLayer()?.querySelectorAll('.status-active .flowchat-edge,.status-return .flowchat-edge,.status-active .flowchat-subflow-edge,.status-return .flowchat-subflow-edge,.status-active .flowchat-architecture-edge,.status-return .flowchat-architecture-edge').forEach(e=>e.classList.toggle('demo-highlight'));addLog('动态演示已更新')}});root.querySelectorAll('.flowchat-node').forEach(node=>node.addEventListener('click',()=>{{if(node.dataset.flowStage){{showSubflow(node.dataset.flowStage);return}}root.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));node.classList.add('selected');detail.textContent=formatDetails(node);addLog(`点击节点：${{node.getAttribute('aria-label')}}`)}}));root.querySelectorAll('.flowchat-edge-group').forEach(edge=>edge.addEventListener('click',()=>{{root.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));edge.classList.add('selected');detail.textContent=formatDetails(edge);addLog(`点击连线：${{edge.dataset.edge}}`)}}));root.querySelectorAll('.flowchat-subflow-node').forEach(node=>node.addEventListener('click',()=>{{root.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));node.classList.add('selected');detail.textContent=`步骤：${{node.getAttribute('aria-label')}} · 状态：${{node.dataset.status}}`;addLog(`点击子流程步骤：${{node.getAttribute('aria-label')}}`)}}));root.querySelectorAll('.flowchat-architecture-node').forEach(node=>node.addEventListener('click',()=>{{root.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));node.classList.add('selected');detail.textContent=`架构层：${{node.getAttribute('aria-label')}} · 状态：${{node.dataset.status}}`;addLog(`点击架构层：${{node.getAttribute('aria-label')}}`)}}));stage.addEventListener('pointerdown',e=>{{activePointers.set(e.pointerId,{{x:e.clientX,y:e.clientY}});if(e.pointerType==='touch'&&activePointers.size===2){{pinchStart=pinchDistance();pinchScale=scale;return}}if(e.target.closest('.flowchat-node,.flowchat-subflow-node,.flowchat-architecture-node'))return;const point=viewportPoint(e.clientX,e.clientY);drag={{x:point.x,y:point.y,panX,panY}};stage.setPointerCapture?.(e.pointerId)}});stage.addEventListener('pointermove',e=>{{if(activePointers.has(e.pointerId))activePointers.set(e.pointerId,{{x:e.clientX,y:e.clientY}});if(e.pointerType==='touch'&&activePointers.size===2&&pinchStart){{scale=Math.max(.35,Math.min(2.4,pinchScale*pinchDistance()/pinchStart));apply();return}}if(!drag)return;const point=viewportPoint(e.clientX,e.clientY);panX=drag.panX+(point.x-drag.x);panY=drag.panY+(point.y-drag.y);apply()}});stage.addEventListener('pointerup',e=>{{activePointers.delete(e.pointerId);if(activePointers.size<2)pinchStart=0;drag=null}});stage.addEventListener('pointercancel',e=>{{activePointers.delete(e.pointerId);pinchStart=0;drag=null}});stage.addEventListener('wheel',e=>{{e.preventDefault();const point=viewportPoint(e.clientX,e.clientY),worldX=(point.x-panX)/scale,worldY=(point.y-panY)/scale,nextScale=Math.max(.35,Math.min(2.4,scale*Math.exp(-e.deltaY*.0015)));scale=nextScale;panX=point.x-worldX*scale;panY=point.y-worldY*scale;apply()}},{{passive:false}});new ResizeObserver(fit).observe(stage);fit()}})();
</script></body></html>'''

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
    try:
        document = render_html(graph, theme, args.title)
    except ValueError as exc:
        edge_id = _CURRENT_EDGE[0] if _CURRENT_EDGE else None
        where = f" (edge `{edge_id}`)" if edge_id else ""
        print(
            "FAIL: geometry could not be satisfied, so no page was written.\n"
            f"  reason{where}: {exc}\n"
            "  The renderer refuses to emit a misleading arrow instead of faking a route.\n"
            "  How to fix:\n"
            "    1. increase the distance between the two nodes (edge >= 90px, final arrow segment >= 75px)\n"
            "    2. move the edge to a different port, or let auto-routing pick the path\n"
            "       by removing `route_points` / adding `\"routing\": \"auto\"`\n"
            "    3. check that declared ports face each other for the direction you intend",
            file=sys.stderr,
        )
        return 2
    args.output.write_text(document, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
