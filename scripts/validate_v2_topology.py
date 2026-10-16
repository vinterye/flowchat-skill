#!/usr/bin/env python3
"""Validate an evidence-bound Flowchat V2 snapshot without a browser."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def load_model(html_path: Path) -> tuple[str, dict[str, Any]]:
    html = html_path.read_text(encoding="utf-8")
    marker = "window.__FLOWCHAT_V2_MODEL__="
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return html, json.loads(html[start:end].rstrip(";"))


def check(html_path: Path) -> dict[str, Any]:
    html, model = load_model(html_path)
    failures: list[dict[str, Any]] = []

    def require(condition: bool, name: str, **extra: Any) -> None:
        if not condition:
            failures.append({"check": name, **extra})

    require(model.get("schema") == "flowchat-v2/overview", "schema")
    overview = model.get("overviewProjection", {})
    require(overview.get("schema") == "overview-projection/v1", "overview_projection_schema")
    require(set(overview) >= {"brain", "stages", "systems", "runtime", "alerts", "sources"}, "overview_projection_shape")
    require(len(model.get("stages", [])) == 7, "stage_count", actual=len(model.get("stages", [])))
    require(len(model.get("systems", [])) == 5, "system_entry_count", actual=len(model.get("systems", [])))
    require(bool(model.get("sources")), "source_manifest")
    projection = model.get("candidate_projection")
    if projection:
        require(str(projection.get("status")) == "candidate_projection", "candidate_projection_status", actual=projection.get("status"))
        require("Candidate Projection" in html and "不是 Runtime Evidence" in html, "candidate_projection_label")
    require(all(isinstance(edge.get("evidence"), dict) and edge["evidence"].get("source")
                for edge in model.get("relationships", [])), "relationship_evidence")
    require("Inspector" in html and "TopologyProjection" in html, "inspector_contract")
    systems_projection = overview.get("systems", {})
    require(overview.get("runtime", {}).get("state") == "idle"
            and all(stage.get("activity") == "未运行" for stage in overview.get("stages", []))
            and "PROJECT CONTEXT" in html, "idle_context_and_stage_copy")
    require(systems_projection.get("rules", {}).get("registered_count") == 3
            and systems_projection.get("rules", {}).get("conflict_count") == 5
            and "Registered Rules" in html, "registered_rules_summary")
    require(systems_projection.get("review", {}).get("registered_count") == 66
            and not systems_projection.get("review", {}).get("waiting")
            and "Registered Gates" in html, "registered_gate_summary")
    require(systems_projection.get("agents", {}).get("registry_agent_count") == 20
            and systems_projection.get("agents", {}).get("runtime_worker_count") == 3
            and "Registered Agents" in html and "Runtime Workers" in html, "registry_runtime_agent_split")
    require("NO RUNTIME" not in html and "TopologyProjection · LEVEL 1" not in html, "legacy_idle_copy_removed")
    runtime = model.get("runtime", {})
    active_edges = runtime.get("active_edges", [])
    require(not active_edges or runtime.get("task_id"), "active_edge_requires_task", active_edges=active_edges)
    require("active-dots" in html and "FIXTURE-DEVELOPMENT-ONLY" in html, "active_edge_animation_contract")
    require("active_edges" in html and "return_edges" in html and "data-edge-id" in html and "data-from" in html and "data-to" in html, "explicit_runtime_edge_contract")
    require("return-arrow" in html and "return_stage_id" in html and "产品规划" not in html, "blocked_return_edge_contract")
    stale_sources = []
    source_records = model.get("sources", [])
    if isinstance(source_records, dict):
        source_records = list(source_records.values())
    for record in source_records:
        path = Path(str(record.get("path", "")))
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
            stale_sources.append(record.get("source_id") or record.get("path"))
    require(not stale_sources, "source_sha256", stale=stale_sources)
    return {
        "schema": "flowchat-v2-validation/v1",
        "artifact_sha256": hashlib.sha256(html_path.read_bytes()).hexdigest(),
        "status": "passed" if not failures else "blocked",
        "failures": failures,
        "metrics": {
            "stages": len(model.get("stages", [])),
            "systems": len(model.get("systems", [])),
            "agents": len(model.get("agents", [])),
            "verified_relationships": len(model.get("relationships", [])),
            "omitted_relationships": model.get("omitted_relationships", 0),
            "runtime_task_id": runtime.get("task_id"),
            "active_edges": len(active_edges),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check(args.html)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
