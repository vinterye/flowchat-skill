#!/usr/bin/env python3
"""Semantic gate for Execution Truth projections.

Geometry is handled by the standalone Flowchat harness. This gate checks that
truth claims are backed by the selected runtime round and that causal nodes do
not appear without their incoming evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _event_id(event: dict[str, Any]) -> str | None:
    return event.get("event_id") or event.get("id")


def _run_id(event: dict[str, Any]) -> str | None:
    return event.get("run_id") or event.get("execution_id")


def validate(graph: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    truth = graph.get("execution_truth", {})
    run_id = truth.get("run_id")
    if not run_id:
        failures.append({"check": "canonical_run_id_present", "actual": run_id})

    tasks = [task for project in runtime.get("projects", []) for task in project.get("tasks", [])]
    task = next((task for task in tasks if task.get("id") == truth.get("task_id")), None)
    if not task:
        failures.append({"check": "task_source_present", "task_id": truth.get("task_id")})
        events: list[dict[str, Any]] = []
    else:
        events = [event for event in task.get("events", []) if _run_id(event) == run_id]
    event_ids = {_event_id(event) for event in events if _event_id(event)}

    nodes = {str(node.get("id")): node for node in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    incoming = {node_id: [edge for edge in edges if str(edge.get("target")) == node_id] for node_id in nodes}
    current_stages = [node for node in nodes.values() if node.get("kind") == "stage" and node.get("details", {}).get("sequence_state") == "current"]
    if len(current_stages) != 1:
        failures.append({"check": "single_current_stage", "count": len(current_stages)})

    for edge in edges:
        truth_type = str(edge.get("truth_type", "")).lower()
        if truth_type in {"actual", "callback", "exception"}:
            ids = edge.get("details", {}).get("event_ids", [])
            if not ids:
                failures.append({"check": "truth_edge_has_event_ids", "edge": edge.get("id")})
            unknown = [event_id for event_id in ids if event_id not in event_ids]
            if unknown:
                failures.append({"check": "truth_edge_event_ids_in_selected_run", "edge": edge.get("id"), "unknown": unknown})

    if "change-request" in nodes and not any(edge.get("id") == "review-to-change-request" for edge in incoming.get("change-request", [])):
        failures.append({"check": "change_request_has_review_source"})
    for node in nodes.values():
        if node.get("kind") == "evidence-note":
            failures.append({"check": "evidence_note_is_not_business_node", "node": node.get("id")})
        if node.get("kind") == "issue" and not incoming.get(str(node.get("id"))):
            failures.append({"check": "issue_has_causal_incoming_edge", "node": node.get("id")})
        if node.get("kind") == "skill" and node.get("details", {}).get("policy_evidence") == "Unknown" and node.get("details", {}).get("expected") is True:
            failures.append({"check": "unknown_policy_cannot_be_expected", "node": node.get("id")})
        if node.get("kind") == "agent" and node.get("details", {}).get("stage_id") == truth.get("current_stage") and not incoming.get(str(node.get("id"))):
            failures.append({"check": "current_agent_has_incoming_edge", "node": node.get("id")})

    return {
        "schema_version": "execution-truth-semantic-harness.v1",
        "status": "pass" if not failures else "blocked",
        "task_id": truth.get("task_id"),
        "run_id": run_id,
        "selected_event_count": len(events),
        "failures": failures,
        "checks": {
            "canonical_run_id_present": bool(run_id),
            "single_current_stage": len(current_stages) == 1,
            "truth_edges_event_bound": not any(f["check"] == "truth_edge_has_event_ids" for f in failures),
            "change_request_causally_sourced": not any(f["check"] == "change_request_has_review_source" for f in failures),
            "candidate_policy_guard": not any(f["check"] == "unknown_policy_cannot_be_expected" for f in failures),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(_load(args.graph), _load(args.runtime))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
