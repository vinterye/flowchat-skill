#!/usr/bin/env python3
"""Validate a Flowchat graph JSON before rendering.

Fails loudly with a readable message instead of letting the renderer
silently produce a page with missing edges or nodes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SIDES = ("left", "right", "top", "bottom")
PORT_RE = re.compile(r"^(left|right|top|bottom)(-[123])?$")
STATUSES = {"completed", "active", "pending", "blocked", "return"}
KINDS = {
    "orchestrator", "control", "review-center", "stage", "dispatch",
    "agent", "summary", "gate", "issue", "feedback",
}


def _preview(ids: list[str], limit: int = 4) -> str:
    shown = ", ".join(ids[:limit])
    return shown if len(ids) <= limit else f"{shown}, +{len(ids) - limit} more"


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _validate(graph: Any, report: Report) -> None:
    if not isinstance(graph, dict):
        report.error("graph root must be a JSON object")
        return

    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        report.error("`nodes` is required and must be a non-empty array")
        return

    node_ids: set[str] = set()
    unknown_kinds: dict[str, list[str]] = {}
    unknown_statuses: dict[str, list[str]] = {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            report.error(f"nodes[{i}] must be an object")
            continue
        nid = node.get("id")
        if not nid:
            report.error(f"nodes[{i}] is missing `id`")
            continue
        if nid in node_ids:
            report.error(f"duplicate node id: {nid}")
        node_ids.add(nid)
        if not node.get("label"):
            report.warn(f"node {nid} has no `label`; it will render blank")
        kind = node.get("kind")
        if kind is not None and kind not in KINDS:
            unknown_kinds.setdefault(str(kind), []).append(str(nid))
        status = node.get("status")
        if status is not None and status not in STATUSES:
            unknown_statuses.setdefault(str(status), []).append(str(nid))

    for kind, ids in unknown_kinds.items():
        report.warn(
            f"unknown node kind `{kind}` on {len(ids)} node(s) ({_preview(ids)}); "
            f"expected one of {sorted(KINDS)}"
        )
    for status, ids in unknown_statuses.items():
        report.warn(
            f"unknown node status `{status}` on {len(ids)} node(s) ({_preview(ids)}); "
            f"expected one of {sorted(STATUSES)}; unknown statuses render with default styling"
        )

    edges = graph.get("edges", [])
    if not isinstance(edges, list):
        report.error("`edges` must be an array when present")
        return

    edge_ids: set[str] = set()
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            report.error(f"edges[{i}] must be an object")
            continue
        eid = edge.get("id")
        if not eid:
            report.error(f"edges[{i}] is missing `id`")
            eid = f"#{i}"
        elif eid in edge_ids:
            report.error(f"duplicate edge id: {eid}")
        edge_ids.add(eid)

        for role in ("source", "target"):
            ref = edge.get(role)
            if not ref:
                report.error(f"edge {eid} is missing `{role}`")
            elif ref not in node_ids:
                report.error(
                    f"edge {eid} `{role}` points to `{ref}`, which is not a declared node"
                )

        for field in ("source_port", "target_port"):
            port = edge.get(field)
            if port is not None and not PORT_RE.match(str(port)):
                report.error(
                    f"edge {eid} `{field}` is `{port}`; expected a side "
                    f"({', '.join(SIDES)}) optionally plus -1/-2/-3"
                )
        for field in ("source_side", "target_side"):
            side = edge.get(field)
            if side is not None and side not in SIDES:
                report.error(
                    f"edge {eid} `{field}` is `{side}`; expected one of {', '.join(SIDES)}"
                )

        routing = edge.get("routing")
        if routing is not None and routing not in ("auto",):
            report.warn(f"edge {eid} has unrecognized routing `{routing}`; only `auto` is defined")

    subflows = graph.get("subflows")
    if isinstance(subflows, dict):
        for stage_id, sub in subflows.items():
            if stage_id not in node_ids:
                report.error(
                    f"subflows key `{stage_id}` is not a declared node id"
                )
            if not isinstance(sub, dict):
                report.error(f"subflow `{stage_id}` must be an object")
                continue
            sub_nodes = sub.get("nodes", [])
            if not isinstance(sub_nodes, list) or not sub_nodes:
                report.error(f"subflow `{stage_id}` needs a non-empty `nodes` array")
                continue
            sub_ids = {n.get("id") for n in sub_nodes if isinstance(n, dict)}
            for e in sub.get("edges", []):
                if not isinstance(e, dict):
                    continue
                for role in ("source", "target"):
                    ref = e.get(role)
                    if ref and ref not in sub_ids:
                        report.error(
                            f"subflow `{stage_id}` edge {e.get('id', '?')} `{role}` "
                            f"points to `{ref}`, not declared in this subflow"
                        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Flowchat graph JSON file")
    parser.add_argument("graph", type=Path)
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args()

    try:
        graph = json.loads(args.graph.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"FAIL: graph file not found: {args.graph}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"FAIL: {args.graph} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    report = Report()
    _validate(graph, report)

    node_count = len(graph.get("nodes", [])) if isinstance(graph, dict) else 0
    edge_count = len(graph.get("edges", [])) if isinstance(graph, dict) else 0

    for w in report.warnings:
        print(f"WARN: {w}")
    for e in report.errors:
        print(f"ERROR: {e}", file=sys.stderr)

    failed = bool(report.errors) or (args.strict and report.warnings)
    if failed:
        print(
            f"FAIL: {len(report.errors)} error(s), {len(report.warnings)} warning(s). "
            "Fix the graph before rendering.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {node_count} nodes, {edge_count} edges, {len(report.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
