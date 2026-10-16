#!/usr/bin/env python3
"""Build an Execution Truth graph from the runtime event log and registries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


STAGES = (
    ("competitor", "01", "竞品"),
    ("requirement", "02", "需求"),
    ("product_definition", "03", "产品定义"),
    ("prototype", "04", "原型"),
    ("interaction", "05", "交互"),
    ("development", "06", "开发"),
    ("testing", "07", "测试 / 验收"),
    ("delivery", "08", "交付"),
)
STAGE_NAME = {stage_id: name for stage_id, _, name in STAGES}
ACTIVE_TASK_STATUSES = {"needs_human", "revision_required", "running"}
STATUS_MAP = {
    "completed": "completed",
    "present": "completed",
    "approved": "completed",
    "pass": "completed",
    "running": "active",
    "waiting_review": "review",
    "needs_human": "review",
    "revision_required": "blocked",
    "revise": "blocked",
    "blocked": "blocked",
    "pending": "pending",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe(value: Any, fallback: str = "Unknown") -> str:
    return fallback if value in (None, "") else str(value)


def _status(value: Any, fallback: str = "pending") -> str:
    return STATUS_MAP.get(str(value or fallback).lower(), fallback)


def _agent_name(projection: Mapping[str, Any], agent_id: str) -> str:
    for node in projection.get("nodes", []):
        if node.get("id") == agent_id and node.get("kind") == "agent":
            return str(node.get("label") or agent_id)
    return agent_id


def _choose_task(runtime: Mapping[str, Any], task_id: str | None) -> Mapping[str, Any]:
    tasks = [task for project in runtime.get("projects", []) for task in project.get("tasks", [])]
    if task_id:
        for task in tasks:
            if task.get("id") == task_id:
                return task
        raise ValueError(f"task not found: {task_id}")
    candidates = [task for task in tasks if task.get("status") in ACTIVE_TASK_STATUSES and task.get("events")]
    if not candidates:
        candidates = [task for task in tasks if task.get("events")]
    if not candidates:
        raise ValueError("runtime contains no task with events")
    priority = {"needs_human": 3, "revision_required": 2, "running": 1}
    return max(candidates, key=lambda task: (priority.get(str(task.get("status")), 0), int(str(task.get("id", "0")).split("-")[-1]) if str(task.get("id", "")).split("-")[-1].isdigit() else 0))


def _details(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def _event_run_id(event: Mapping[str, Any]) -> str | None:
    return event.get("run_id") or event.get("execution_id")


def _event_id(event: Mapping[str, Any]) -> str | None:
    return event.get("event_id") or event.get("id")


def _friendly_agent_name(agent_id: str, events: list[Mapping[str, Any]]) -> tuple[str, str]:
    if agent_id == "requirement-agent":
        return "Requirements Agent", "primary"
    if any("Controller" in str(event.get("message", "")) or "controller" in str(event.get("message", "")).lower() for event in events):
        return "Review Controller", "controller"
    return agent_id, "temporary"


def _edge(edge_id: str, source: str, target: str, *, truth_type: str, status: str, kind: str = "main", source_side: str, target_side: str, route_points: list[list[float]], label: str = "", details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    edge: dict[str, Any] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "status": status,
        "kind": kind,
        "truth_type": truth_type,
        "source_side": source_side,
        "target_side": target_side,
        "route_points": route_points,
        "expected": truth_type == "expected",
        "actual": truth_type in {"actual", "callback", "exception"},
    }
    if label:
        edge["label"] = label
    if details:
        edge["details"] = dict(details)
    return edge


def build_graph(projection: Mapping[str, Any], runtime: Mapping[str, Any], task_id: str | None = None) -> dict[str, Any]:
    task = _choose_task(runtime, task_id)
    all_events = sorted(task.get("events", []), key=lambda event: event.get("sequence", 0))
    run_id = next((_event_run_id(event) for event in reversed(all_events) if _event_run_id(event)), None)
    events = [event for event in all_events if _event_run_id(event) == run_id] if run_id else all_events
    project_id = next((project.get("id") for project in runtime.get("projects", []) if task in project.get("tasks", [])), "PROJECT-COCKPIT")
    current_stage = str(task.get("currentStage") or "unknown")
    stage_states = task.get("stages", {})
    by_agent: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        agent_id = event.get("agent_id") or event.get("controller_agent_id")
        if agent_id:
            by_agent.setdefault(str(agent_id), []).append(event)
    current_agent_ids = list(by_agent)
    current_agent = current_agent_ids[-1] if current_agent_ids else None
    latest_artifact = next((event for event in reversed(events) if event.get("type") == "artifact"), None)
    latest_change = next((event for event in reversed(events) if event.get("type") == "change_request"), None)
    latest_review = next((event for event in reversed(events) if event.get("type") in {"review", "status"} and event.get("decision")), None)
    event_ids = [event.get("event_id") or event.get("id") for event in events]
    runtime_source = "runtime/state.json"
    projection_source = "topology-projection.json"
    registered_rule_count = sum(1 for node in projection.get("nodes", []) if node.get("kind") == "rule")
    registry_conflict_count = len(projection.get("conflicts", []))

    lanes = [
        {"id": "governance", "label": "治理", "subtitle": "Governance", "y": 0, "height": 110, "fill": "#ffffff"},
        {"id": "brain", "label": "总控大脑", "subtitle": "Control Brain", "y": 110, "height": 150, "fill": "#f8fafc"},
        {"id": "stage", "label": "阶段", "subtitle": "Stage", "y": 260, "height": 180, "fill": "#ffffff"},
        {"id": "agent", "label": "Agent", "subtitle": "智能体执行", "y": 440, "height": 180, "fill": "#f8fafc"},
        {"id": "skill", "label": "Skill / Harness", "subtitle": "能力与执行容器", "y": 620, "height": 180, "fill": "#ffffff", "badge": "0 Actual Invocations · Unknown"},
        {"id": "runtime", "label": "Runtime / Tool", "subtitle": "运行时与工具", "y": 800, "height": 150, "fill": "#f8fafc"},
        {"id": "artifact", "label": "Artifact / Review", "subtitle": "产物与审核", "y": 950, "height": 150, "fill": "#ffffff"},
    ]
    nodes: list[dict[str, Any]] = []
    nodes.append({
        "id": "governance-registry", "label": f"治理与注册表\nRegistry evidence\n{registered_rule_count} Rules · {registry_conflict_count} Conflicts", "shape": "rect", "x": 280, "y": 22, "width": 360, "height": 70,
        "status": "completed", "kind": "control", "phase": "unknown", "readiness": "ready",
        "lane": "governance",
        "details": _details(type="governance", source=projection_source, registered_rules=registered_rule_count, registry_conflicts=registry_conflict_count, prefer_local_capability="Unknown", lane="governance"),
    })
    nodes.append({
        "id": "control-brain", "label": f"◎ 总控大脑\n{task.get('status', 'Unknown').upper()} · {task.get('id')}\n当前阶段：{STAGE_NAME.get(current_stage, current_stage)}", "shape": "rect", "x": 760, "y": 135, "width": 620, "height": 100,
        "status": "active" if task.get("status") == "running" else "review" if task.get("status") in {"needs_human", "revision_required"} else "completed", "kind": "orchestrator", "phase": "unknown", "readiness": "ready", "lane": "brain",
        "details": _details(type="brain", run_id=run_id, task_run_id=task.get("id"), project_id=project_id, current_stage=current_stage, status=task.get("status"), source=runtime_source, lane="brain", control_chain=["Planner", "Router", "Execute"], control_chain_evidence="no dedicated control events in this Run"),
    })

    stage_x: dict[str, float] = {}
    for index, (stage_id, number, name) in enumerate(STAGES):
        x = 270 + index * 300
        stage_x[stage_id] = x
        raw_status = stage_states.get(stage_id, "pending")
        status = _status(raw_status, "pending")
        if stage_id == current_stage and status == "pending":
            status = "active"
        sequence_state = "completed" if raw_status in {"completed", "done", "approved", "pass"} else "current" if stage_id == current_stage else "future"
        nodes.append({
            "id": f"stage-{stage_id}", "label": f"{number}\n{name}\n{str(raw_status).replace('_', ' ')}", "shape": "rect", "x": x, "y": 300, "width": 205, "height": 92,
            "status": status, "kind": "stage", "phase": "mid", "readiness": "ready" if status == "completed" else "candidate", "lane": "stage",
            "details": _details(type="stage", stage_id=stage_id, run_id=run_id, sequence_state=sequence_state, execution_status=_status(raw_status, "pending"), status=raw_status, source=runtime_source, current=stage_id == current_stage, lane="stage"),
        })

    agent_nodes = []
    agent_positions = [(560, "requirement-agent"), (1010, "agent-master-controller-v1-1-master-controller-worker--4e450eb4")]
    for x, agent_id in agent_positions:
        agent_events = by_agent.get(agent_id, [])
        if not agent_events:
            continue
        last = agent_events[-1]
        display_name, role = _friendly_agent_name(agent_id, agent_events)
        node_status = "review" if any(event.get("status") in {"needs_human", "waiting_review", "revision_required"} for event in agent_events) else "completed"
        node_id = f"agent-{agent_id}"
        agent_nodes.append(node_id)
        nodes.append({
            "id": node_id, "label": f"{display_name}\nActual · {role.upper()} · {('Review' if node_status == 'review' else 'Completed')}", "shape": "rect", "x": x, "y": 485, "width": 340, "height": 92,
            "status": node_status, "kind": "agent", "phase": "mid", "readiness": "ready", "lane": "agent",
            "details": _details(type="agent", agent_id=agent_id, role=role, run_id=run_id, agent_run_id=run_id, stage_id=last.get("stage_id"), status=node_status, source=runtime_source, lane="agent", event_ids=[_event_id(event) for event in agent_events], selection_reason=last.get("message")),
        })

    nodes.append({
        "id": "candidate-modify-requirement", "label": "modify-requirement\nCandidate · 未证明必需", "shape": "rect", "x": 590, "y": 668, "width": 300, "height": 88,
        "status": "pending", "kind": "skill", "phase": "mid", "readiness": "needs_review", "lane": "skill",
        "details": _details(type="skill", skill_id="modify-requirement", candidate=True, expected=False, actual=False, source="capability_registry", invocation_events=0, policy_evidence="Unknown", lane="skill", reason="存在注册能力匹配，但没有 Governance / Router 证据证明本轮必须调用"),
    })

    nodes.append({
        "id": "review-gate", "label": "Review Gate\n实际审核链\n" + _safe(latest_review.get("decision") if latest_review else task.get("status")), "shape": "rect", "x": 1260, "y": 965, "width": 330, "height": 88,
        "status": "blocked" if task.get("status") in {"needs_human", "revision_required"} else "review", "kind": "gate", "phase": "post", "readiness": "needs_review", "lane": "artifact",
        "details": _details(type="review", status=task.get("status"), decision=latest_review.get("decision") if latest_review else None, run_id=run_id, source=runtime_source, lane="artifact", event_ids=[_event_id(event) for event in events if event.get("type") == "review"]),
    })
    nodes.append({
        "id": "human-gate", "label": "Human Gate\n当前需要人工处理", "shape": "rect", "x": 1510, "y": 22, "width": 300, "height": 88,
        "status": "blocked" if task.get("status") == "needs_human" else "pending", "kind": "gate", "phase": "post", "readiness": "needs_review", "lane": "governance",
        "details": _details(type="human_gate", status=task.get("status"), source=runtime_source, run_id=run_id, lane="governance"),
    })
    if latest_artifact:
        nodes.append({
            "id": "artifact-latest", "label": "Artifact\nrequirements.md\n实际已生成", "shape": "rect", "x": 810, "y": 985, "width": 360, "height": 88,
            "status": "completed", "kind": "feedback", "phase": "post", "readiness": "ready", "lane": "artifact",
            "details": _details(type="artifact", artifact_id=latest_artifact.get("artifact_id") or latest_artifact.get("asset_id"), path=latest_artifact.get("path"), fingerprint=latest_artifact.get("fingerprint"), source=runtime_source, lane="artifact", event_id=_event_id(latest_artifact), run_id=run_id),
        })
    if latest_change:
        nodes.append({
            "id": "change-request", "label": "Modify / Retry\nChange Request\n" + _safe(latest_change.get("change_request_id") or latest_change.get("asset_id")), "shape": "rect", "x": 1680, "y": 985, "width": 360, "height": 88,
            "status": "blocked", "kind": "issue", "phase": "post", "readiness": "needs_review", "lane": "artifact",
            "details": _details(type="change_request", change_request_id=latest_change.get("change_request_id") or latest_change.get("asset_id"), base_artifact_id=latest_change.get("base_artifact_id"), required_changes=latest_change.get("required_changes"), source=runtime_source, lane="artifact", event_id=_event_id(latest_change), run_id=run_id),
        })

    edges: list[dict[str, Any]] = []
    edges.append(_edge("governance-to-brain", "governance-registry", "control-brain", truth_type="expected", status="pending", kind="control", source_side="right", target_side="left", route_points=[[640, 57], [680, 57], [680, 185], [760, 185]], label="Policy / Registry", details={"expected": True, "actual": False, "source": projection_source}))
    for index in range(len(STAGES) - 1):
        source_id, _, _ = STAGES[index]
        target_id, _, _ = STAGES[index + 1]
        source_x, target_x = stage_x[source_id], stage_x[target_id]
        source_status, target_status = stage_states.get(source_id, "pending"), stage_states.get(target_id, "pending")
        edges.append(_edge(f"stage-{source_id}-to-{target_id}", f"stage-{source_id}", f"stage-{target_id}", truth_type="expected", status="completed" if source_status == "completed" and target_status == "completed" else "pending", kind="stage-transition", source_side="right", target_side="left", route_points=[[source_x + 205, 346], [target_x, 346]], label="Stage flow" if index == 0 else "", details={"expected": True, "actual": False, "source": "stage-template"}))
    if "agent-requirement-agent" in agent_nodes:
        invocation = next((event for event in events if event.get("type") == "runtime" and event.get("agent_id") == "requirement-agent"), None)
        edges.append(_edge("stage-requirement-to-agent", "stage-requirement", "agent-requirement-agent", truth_type="actual", status="completed", kind="agent", source_side="bottom", target_side="top", route_points=[[stage_x["requirement"] + 102, 392], [stage_x["requirement"] + 102, 410], [730, 410], [730, 485]], label="Actual invocation", details={"event_ids": [_event_id(invocation)] if invocation else [], "event_type": invocation.get("type") if invocation else None, "source": runtime_source, "stage_id": "requirement", "run_id": run_id}))
        edges.append(_edge("agent-to-candidate-skill", "agent-requirement-agent", "candidate-modify-requirement", truth_type="candidate", status="pending", kind="candidate", source_side="bottom", target_side="top", route_points=[[730, 577], [730, 668]], label="Candidate · 未证明必需", details={"candidate": True, "expected": False, "actual": False, "reason": "Governance / Router policy evidence Unknown", "source": "capability_registry"}))
        if latest_artifact:
            edges.append(_edge("agent-to-artifact", "agent-requirement-agent", "artifact-latest", truth_type="actual", status="completed", kind="artifact-result", source_side="right", target_side="top", route_points=[[900, 531], [960, 531], [960, 985]], label="Artifact created", details={"event_ids": [_event_id(latest_artifact)], "event_type": latest_artifact.get("type"), "source": runtime_source, "run_id": run_id}))
    if "agent-agent-master-controller-v1-1-master-controller-worker--4e450eb4" in agent_nodes:
        controller_events = [event for event in events if event.get("controller_agent_id") == "agent-master-controller-v1-1-master-controller-worker--4e450eb4" or event.get("agent_id") == "agent-master-controller-v1-1-master-controller-worker--4e450eb4"]
        edges.append(_edge("review-to-controller", "review-gate", "agent-agent-master-controller-v1-1-master-controller-worker--4e450eb4", truth_type="callback", status="completed", kind="review", source_side="top", target_side="bottom", route_points=[[1500, 965], [1500, 652], [1325, 652], [1325, 577]], label="Review request", details={"callback_type": "controller_review", "event_ids": [_event_id(event) for event in controller_events if "requested" in str(event.get("message", "")).lower() or "called" in str(event.get("message", "")).lower()], "source": runtime_source, "run_id": run_id}))
        edges.append(_edge("controller-to-review", "agent-agent-master-controller-v1-1-master-controller-worker--4e450eb4", "review-gate", truth_type="actual", status="review", kind="review", source_side="bottom", target_side="top", route_points=[[1180, 577], [1180, 850], [1425, 850], [1425, 965]], label="Controller decision", details={"event_ids": [_event_id(event) for event in controller_events if event.get("decision")], "source": runtime_source, "run_id": run_id}))
    if latest_artifact:
        review_request = next((event for event in events if event.get("type") == "review" and "requested" in str(event.get("message", "")).lower()), None)
        edges.append(_edge("artifact-to-review", "artifact-latest", "review-gate", truth_type="actual", status="review", kind="review", source_side="right", target_side="left", route_points=[[1170, 1029], [1260, 1029]], label="Review requested", details={"event_ids": [_event_id(latest_artifact), _event_id(review_request)] if review_request else [_event_id(latest_artifact)], "source": runtime_source, "run_id": run_id}))
    if latest_change:
        decision_event = next((event for event in reversed(events) if event.get("decision") in {"revision_required", "needs_human", "revise"}), None)
        edges.append(_edge("review-to-change-request", "review-gate", "change-request", truth_type="callback", status="completed", kind="review-output", source_side="bottom", target_side="top", route_points=[[1425, 1053], [1425, 1070], [1860, 1070], [1860, 985]], label="Modify decision → Change Request", details={"event_ids": [_event_id(event) for event in (decision_event, latest_change) if event], "source": runtime_source, "run_id": run_id}))
    if "human-gate" in {node["id"] for node in nodes}:
        decision_event = next((event for event in reversed(events) if event.get("decision") == "needs_human"), None)
        edges.append(_edge("review-to-human", "review-gate", "human-gate", truth_type="exception", status="blocked", kind="return", source_side="right", target_side="right", route_points=[[1590, 1009], [1650, 1009], [1650, 1090], [2600, 1090], [2600, 66], [1810, 66]], label="Needs Human", details={"reason": "runtime status needs_human", "event_ids": [_event_id(decision_event)] if decision_event else [], "source": runtime_source, "run_id": run_id}))
    if latest_change and "agent-requirement-agent" in agent_nodes:
        edges.append(_edge("change-request-to-agent", "change-request", "agent-requirement-agent", truth_type="callback", status="return", kind="return", source_side="left", target_side="left", route_points=[[1680, 1029], [1600, 1029], [1600, 930], [470, 930], [470, 531], [560, 531]], label="Modify → Agent", details={"callback_type": "review_callback", "change_request_id": latest_change.get("change_request_id"), "event_ids": [_event_id(latest_change)], "source": runtime_source, "run_id": run_id}))

    subflows = {}
    if "agent-requirement-agent" in agent_nodes:
        subflows["stage-requirement"] = {
            "title": "需求阶段 · 真实执行链",
            "entry": "进入：需求阶段",
            "next": "下一步：审核结果决定是否返工",
            "loop": "返工：Change Request → Requirement Agent",
            "review_policy": "Expert Review + Controller Review",
            "nodes": [
                {"id": "sf-requirement-agent", "label": "Requirement Agent\n实际执行", "x": 260, "y": 360, "width": 260, "height": 90, "kind": "agent", "status": "active"},
                {"id": "sf-requirement-artifact", "label": "requirements.md\n实际产物", "x": 620, "y": 360, "width": 260, "height": 90, "kind": "artifact", "status": "completed"},
                {"id": "sf-requirement-review", "label": "Review Gate\n真实审核", "x": 980, "y": 360, "width": 260, "height": 90, "kind": "review", "status": "review"},
            ],
            "edges": [
                {"id": "sf-agent-artifact", "source": "sf-requirement-agent", "target": "sf-requirement-artifact", "status": "active", "route_points": [[520, 405], [620, 405]]},
                {"id": "sf-artifact-review", "source": "sf-requirement-artifact", "target": "sf-requirement-review", "status": "review", "route_points": [[880, 405], [980, 405]]},
            ],
        }
    architecture = {
        "title": "Execution Truth · Source Layers",
        "nodes": [
            {"id": "arch-projection", "label": "TopologyProjection\nRegistry facts", "x": 180, "y": 220, "width": 260, "height": 90, "kind": "architecture", "status": "completed"},
            {"id": "arch-runtime", "label": "Runtime state\nEvent evidence", "x": 560, "y": 220, "width": 260, "height": 90, "kind": "architecture", "status": "active"},
            {"id": "arch-graph", "label": "Flowchat graph\nTruth projection", "x": 940, "y": 220, "width": 260, "height": 90, "kind": "architecture", "status": "active"},
            {"id": "arch-harness", "label": "Harness\nGeometry + interaction", "x": 1320, "y": 220, "width": 260, "height": 90, "kind": "architecture-output", "status": "pending"},
        ],
        "edges": [
            {"id": "arch-projection-runtime", "source": "arch-projection", "target": "arch-runtime", "status": "active", "source_side": "right", "target_side": "left", "route_points": [[440, 265], [560, 265]]},
            {"id": "arch-runtime-graph", "source": "arch-runtime", "target": "arch-graph", "status": "active", "source_side": "right", "target_side": "left", "route_points": [[820, 265], [940, 265]]},
            {"id": "arch-graph-harness", "source": "arch-graph", "target": "arch-harness", "status": "pending", "source_side": "right", "target_side": "left", "route_points": [[1200, 265], [1320, 265]]},
        ],
    }
    return {
        "viewBox": [0, 0, 2650, 1100],
        "lanes": lanes,
        "nodes": nodes,
        "edges": edges,
        "subflows": subflows,
        "architecture": architecture,
        "execution_truth": {
            "schema": "execution-truth-graph/v1",
            "project_id": project_id,
            "task_id": task.get("id"),
            "run_id": run_id,
            "task_run_id": task.get("id"),
            "canonical_run_id_source": "runtime event execution_id" if run_id else "missing in runtime task",
            "task_status": task.get("status"),
            "current_stage": current_stage,
            "source": runtime_source,
            "event_count": len(events),
            "capability_invocation_count": sum(1 for event in events if event.get("type") in {"capability_invoked", "skill_invoked"}),
            "capability_evidence": "Unknown" if not any(event.get("type") in {"capability_invoked", "skill_invoked"} for event in events) else "Actual",
            "event_ids": event_ids,
            "all_event_count": len(all_events),
            "excluded_event_count": len(all_events) - len(events),
            "actual_edge_rule": "only event-backed relations are Actual / Callback / Exception",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    graph = build_graph(_load(args.projection), _load(args.runtime), args.task_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "task_id": graph["execution_truth"]["task_id"], "run_id": graph["execution_truth"]["run_id"], "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
