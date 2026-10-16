#!/usr/bin/env python3
"""Adapt the fact-backed TopologyProjection to the standalone Flowchat graph contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from generate_v2_topology import build_overview_projection  # noqa: E402


STAGE_IDS = (
    ("competitor", "01", "竞品分析"),
    ("requirement", "02", "需求文档"),
    ("interaction", "03", "交互设计"),
    ("prototype", "04", "原型"),
    ("ui_design", "05", "UI 设计"),
    ("development", "06", "开发"),
    ("testing", "07", "测试验收"),
)


def _safe(value: Any, fallback: str = "Unknown") -> str:
    return fallback if value in (None, "") else str(value)


def _status(value: Any, fallback: str = "pending") -> str:
    text = _safe(value, fallback).lower()
    return {
        "not_run": "pending",
        "unknown": "pending",
        "running": "active",
        "active": "active",
        "waiting_review": "review",
        "needs_human": "review",
        "review": "review",
        "blocked": "blocked",
        "completed": "completed",
        "verified": "completed",
    }.get(text, fallback)


def _label(value: Any, fallback: str = "Unknown") -> str:
    return _safe(value, fallback).replace("\n", " ")


def _runtime_edge_status(overview: Mapping[str, Any], source: str, target: str) -> str:
    """Read edge state only from the explicit runtime edge projection."""
    for edge in overview.get("runtime", {}).get("active_edges", []):
        if edge.get("from") == source and edge.get("to") == target:
            return _status(edge.get("runtime_status"), "pending")
    return "pending"


def _node(
    node_id: str,
    label: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    status: str = "pending",
    kind: str = "node",
    phase: str = "unknown",
    readiness: str = "needs_review",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "shape": "rect",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "status": status,
        "kind": kind,
        "phase": phase,
        "readiness": readiness,
    }


def _edge(edge_id: str, source: str, target: str, status: str, source_side: str, target_side: str) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "status": status,
        "kind": "main",
        "routing": "auto",
        "source_side": source_side,
        "target_side": target_side,
    }


def build_graph(projection: Mapping[str, Any]) -> dict[str, Any]:
    overview = build_overview_projection(projection)
    systems = overview["systems"]
    runtime_state = overview["runtime"].get("state", "idle")
    stage_rows = {stage["id"]: stage for stage in overview["stages"]}
    nodes: list[dict[str, Any]] = []

    nodes.append(_node(
        "rules", f"规则与治理\nRules / Governance\n{systems['rules']['registered_count']} Registered · {systems['rules']['conflict_count']} Conflicts",
        70, 40, 280, 112, status="active", kind="control", readiness="ready",
    ))
    nodes.append(_node(
        "brain", f"◎ 总控大脑\nOrchestrator Hub\n当前阶段：{overview['brain']['current_stage']}\n{overview['brain']['status']} · {overview['brain']['summary']}",
        950, 40, 480, 136, status="active" if runtime_state != "idle" else "pending", kind="orchestrator", readiness="ready",
    ))
    nodes.append(_node(
        "review", f"审核与门禁\nReview / Gate\n{systems['review']['human_count']} Human Waiting · {systems['review']['gate_count']} Gates",
        1790, 40, 280, 112, status="review" if systems["review"]["waiting"] else "pending", kind="gate", phase="post", readiness="needs_review",
    ))

    for index, (stage_id, number, name) in enumerate(STAGE_IDS):
        stage = stage_rows[stage_id]
        status = _status(stage.get("status"))
        phase = _safe(stage.get("phase"), "unknown").lower()
        nodes.append(_node(
            f"stage-{stage_id}",
            f"{number}\n{name}\n{_label(stage.get('phase'), '—')} · {_label(stage.get('activity'), '未运行')}",
            70 + index * 300, 280, 180, 104,
            status=status, kind="stage", phase=phase, readiness="ready" if status == "completed" else "candidate",
        ))

    worker_label = " · ".join(systems["agents"]["runtime_workers"]) if systems["agents"]["runtime_workers"] else "Registry / Runtime 分离"
    nodes.append(_node(
        "agents", f"执行能力\nAgent / Capability\n{systems['agents']['registry_agent_count']} Registered Agents · {systems['agents']['runtime_worker_count']} Runtime Workers\n{worker_label}",
        850, 540, 300, 112, status="active" if runtime_state != "idle" else "pending", kind="agent", phase="mid", readiness="candidate",
    ))
    nodes.append(_node(
        "harness", f"运行保障\nHarness / Runtime\nPreflight {systems['harness']['preflight']}\n{systems['harness']['state']}",
        1270, 540, 300, 112, status="active" if runtime_state != "idle" else "pending", kind="harness", readiness="ready",
    ))
    artifact_state = f"{systems['artifacts']['count']} Artifacts" if systems["artifacts"]["count"] else "No Artifact Evidence"
    nodes.append(_node(
        "artifacts", f"产物与证据\nArtifact / Evidence\n{artifact_state}\nLatest · {_label(systems['artifacts']['latest'], '—')}",
        1690, 540, 300, 112, status="completed" if systems["artifacts"]["count"] else "pending", kind="feedback", phase="post", readiness="ready",
    ))

    edges: list[dict[str, Any]] = [
        _edge("rules-to-brain", "rules", "brain", "active", "right", "left"),
        _edge("review-to-brain", "review", "brain", "review" if systems["review"]["waiting"] else "pending", "left", "right"),
        _edge("brain-to-first-stage", "brain", "stage-competitor", "active" if runtime_state != "idle" else "pending", "bottom", "top"),
    ]
    for index in range(len(STAGE_IDS) - 1):
        source_id = STAGE_IDS[index][0]
        target_id = STAGE_IDS[index + 1][0]
        status = _status(_runtime_edge_status(overview, source_id, target_id), "pending")
        edges.append(_edge(f"stage-{index + 1}-to-{index + 2}", f"stage-{source_id}", f"stage-{target_id}", status, "right", "left"))
    edges.extend([
        _edge("stage-interaction-to-agents", "stage-interaction", "agents", "active" if runtime_state != "idle" else "pending", "bottom", "top"),
        _edge("agents-to-harness", "agents", "harness", "active" if runtime_state != "idle" else "pending", "right", "left"),
        _edge("harness-to-artifacts", "harness", "artifacts", "completed" if systems["artifacts"]["count"] else "pending", "right", "left"),
        _edge("review-to-prototype", "review", "stage-prototype", "review" if systems["review"]["waiting"] else "pending", "bottom", "top"),
        _edge("last-stage-to-artifacts", "stage-testing", "artifacts", "completed" if systems["artifacts"]["count"] else "pending", "bottom", "top"),
    ])
    for return_edge in overview.get("runtime", {}).get("return_edges", []):
        if return_edge.get("from") in stage_rows and return_edge.get("to") in stage_rows:
            edges.append({
                "id": return_edge.get("edge_id") or f"return-{return_edge['from']}-{return_edge['to']}",
                "source": f"stage-{return_edge['from']}",
                "target": f"stage-{return_edge['to']}",
                "status": _status(return_edge.get("runtime_status"), "blocked"),
                "kind": "return",
                "routing": "auto",
                "source_side": "bottom",
                "target_side": "top",
                "runtime_status": return_edge.get("runtime_status"),
                "source_ref": return_edge.get("source"),
                "evidence": return_edge.get("evidence"),
            })
    subflows: dict[str, dict[str, Any]] = {}
    for stage_id, number, name in STAGE_IDS:
        stage = stage_rows[stage_id]
        binding_state = _label(stage.get("binding_status"), "unbound")
        executor_ids = stage.get("executor_ids", [])
        subflows[f"stage-{stage_id}"] = {
            "title": f"{number} {name} · Stage Detail",
            "entry": f"StageBinding：{binding_state}",
            "next": f"运行状态：{_label(stage.get('status'), 'not_run')}",
            "loop": f"执行目标：{', '.join(executor_ids) if executor_ids else '暂无已绑定执行目标'}",
            "nodes": [],
            "edges": [],
        }
    architecture_nodes = [
        {"id": "arch-rules", "label": f"Rules / Governance\n{systems['rules']['registered_count']} registered · {systems['rules']['conflict_count']} conflicts", "x": 90, "y": 220, "width": 260, "height": 96, "kind": "architecture", "status": "active"},
        {"id": "arch-review", "label": f"Review / Gate\n{systems['review']['registered_count']} registered · {systems['review']['human_count']} human waiting", "x": 410, "y": 220, "width": 260, "height": 96, "kind": "architecture", "status": "review" if systems["review"]["waiting"] else "pending"},
        {"id": "arch-agents", "label": f"Agent / Capability\n{systems['agents']['registry_agent_count']} registered · {systems['agents']['runtime_worker_count']} runtime workers", "x": 730, "y": 220, "width": 260, "height": 96, "kind": "architecture", "status": "active" if runtime_state != "idle" else "pending"},
        {"id": "arch-harness", "label": f"Harness / Runtime\nPreflight {systems['harness']['preflight']} · {systems['harness']['state']}", "x": 1050, "y": 220, "width": 260, "height": 96, "kind": "architecture", "status": "active" if runtime_state != "idle" else "pending"},
        {"id": "arch-artifacts", "label": f"Artifact / Evidence\n{artifact_state}", "x": 1370, "y": 220, "width": 260, "height": 96, "kind": "architecture-output", "status": "completed" if systems['artifacts']['count'] else "pending"},
    ]
    architecture_edges = [
        {"id": "arch-rules-review", "source": "arch-rules", "target": "arch-review", "status": "active", "route_points": [[350, 268], [410, 268]]},
        {"id": "arch-review-agents", "source": "arch-review", "target": "arch-agents", "status": "pending", "route_points": [[670, 268], [730, 268]]},
        {"id": "arch-agents-harness", "source": "arch-agents", "target": "arch-harness", "status": "active" if runtime_state != "idle" else "pending", "route_points": [[990, 268], [1050, 268]]},
        {"id": "arch-harness-artifacts", "source": "arch-harness", "target": "arch-artifacts", "status": "completed" if systems['artifacts']['count'] else "pending", "route_points": [[1310, 268], [1370, 268]]},
    ]
    return {"viewBox": [0, 0, 2200, 820], "nodes": nodes, "edges": edges, "subflows": subflows, "architecture": {"title": "Fact-backed system layers", "nodes": architecture_nodes, "edges": architecture_edges}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a standalone Flowchat graph from TopologyProjection")
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    projection = json.loads(args.projection.read_text(encoding="utf-8"))
    graph = build_graph(projection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
