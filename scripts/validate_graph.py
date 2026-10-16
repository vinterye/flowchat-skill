#!/usr/bin/env python3
"""Validate a Flowchat graph JSON before rendering.

Registry-driven: node types, edge types, and statuses come from
`data/type-registry-v1.json`, so the validator never drifts from the renderer.
Unknown values are reported once per distinct value instead of once per node,
and a dangling edge endpoint is an error because the renderer would silently
drop that edge and hand back a page that looks complete but is not.

Exit codes: 0 = ok, 1 = graph has errors (or --strict with warnings),
2 = file missing / not valid JSON.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "data" / "type-registry-v1.json"
SIDES = ("left", "right", "top", "bottom")
# A port is a side plus an optional lane: left, left-1, right-3, ...
PORT_RE = re.compile(r"^(left|right|top|bottom)(-[123])?$")
ROUTINGS = {"auto", "straight", "orthogonal"}
# Both spellings are accepted: the renderer reads snake_case, while Graph V2
# adapters emit camelCase. Validating both keeps one validator honest.
ALIASES = {
    "source_port": ("source_port", "sourcePort"),
    "target_port": ("target_port", "targetPort"),
    "source_side": ("source_side", "sourceSide"),
    "target_side": ("target_side", "targetSide"),
    "route_points": ("route_points", "routePoints", "path"),
    "edge_type": ("type", "edge_type", "edgeType", "kind"),
    "node_type": ("type", "node_type", "nodeType", "kind"),
    "status": ("status",),
    "raw_status": ("raw_status", "rawStatus"),
    "visual_status": ("visual_status", "visualStatus"),
}


def _first(record: dict[str, Any], key: str) -> Any:
    for field in ALIASES[key]:
        if record.get(field) is not None:
            return record.get(field)
    return None


def _preview(ids: list[str], limit: int = 4) -> str:
    shown = ", ".join(ids[:limit])
    return shown if len(ids) <= limit else f"{shown}, +{len(ids) - limit} more"


def _enum_preview(values: Any, limit: int = 10) -> str:
    """Keep registry-sized enums readable instead of dumping 49 type names."""
    vals = sorted(str(v) for v in values)
    if len(vals) <= limit:
        return str(vals)
    return f"{vals[:limit]}, ... ({len(vals)} total; see data/type-registry-v1.json)"


class Registry:
    def __init__(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SystemExit(f"FAIL: type registry not found: {path}")
        except json.JSONDecodeError as exc:
            raise SystemExit(f"FAIL: type registry is not valid JSON ({path}): {exc}")
        self.node_types: dict[str, Any] = data.get("nodeTypes", {})
        self.edge_types: dict[str, Any] = data.get("edgeTypes", {})
        self.statuses: dict[str, Any] = data.get("statuses", {})
        self.size_presets: dict[str, Any] = data.get("sizePresets", {})
        if not self.node_types:
            raise SystemExit(f"FAIL: registry {path} has no nodeTypes")

    @property
    def visuals(self) -> set[str]:
        return {
            str(entry.get("visual"))
            for entry in self.statuses.values()
            if isinstance(entry, dict) and entry.get("visual")
        }


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def warn_grouped(self, values: dict[str, list[str]], noun: str, suffix: str) -> None:
        for value, ids in values.items():
            self.warn(
                f"unknown {noun} `{value}` on {len(ids)} node(s) ({_preview(ids)}); {suffix}"
            )


def _validate(graph: Any, reg: Registry, report: Report) -> None:
    if not isinstance(graph, dict):
        report.error("graph root must be a JSON object")
        return

    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        report.error("`nodes` is required and must be a non-empty array")
        return

    node_ids: set[str] = set()
    unknown_types: dict[str, list[str]] = {}
    unknown_statuses: dict[str, list[str]] = {}
    unknown_visuals: dict[str, list[str]] = {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            report.error(f"nodes[{i}] must be an object")
            continue
        nid = node.get("id")
        if not nid:
            report.error(f"nodes[{i}] is missing `id`")
            continue
        nid = str(nid)
        if nid in node_ids:
            report.error(f"duplicate node id: {nid}")
        node_ids.add(nid)

        if not node.get("label"):
            report.warn(f"node {nid} has no `label`; it will render blank")

        ntype = _first(node, "node_type")
        if ntype is not None and str(ntype) not in reg.node_types:
            unknown_types.setdefault(str(ntype), []).append(nid)

        status = _first(node, "status")
        raw_status = _first(node, "raw_status")
        # Raw runtime values (unknown, candidate, not_run, not_implemented) are
        # deliberately preserved, so an unregistered status is a warning: the
        # renderer keeps the value instead of silently rewriting it.
        if status is not None and str(status) not in reg.statuses:
            unknown_statuses.setdefault(str(status), []).append(nid)
        visual = _first(node, "visual_status")
        if visual is not None and str(visual) not in reg.visuals:
            unknown_visuals.setdefault(str(visual), []).append(nid)
        if raw_status is not None and status is None:
            report.warn(
                f"node {nid} sets `raw_status` without `status`; "
                "runtime value is kept but has no visual class"
            )

    report.warn_grouped(
        unknown_types, "node type", f"expected one of {_enum_preview(reg.node_types)}"
    )
    report.warn_grouped(
        unknown_statuses,
        "node status",
        f"expected one of {_enum_preview(reg.statuses)}; unknown values render with default styling",
    )
    report.warn_grouped(
        unknown_visuals, "visual_status", f"expected one of {_enum_preview(reg.visuals)}"
    )

    edges = graph.get("edges", [])
    if not isinstance(edges, list):
        report.error("`edges` must be an array when present")
        return

    edge_ids: set[str] = set()
    unknown_edge_types: dict[str, list[str]] = {}
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            report.error(f"edges[{i}] must be an object")
            continue
        eid = edge.get("id")
        if not eid:
            report.error(f"edges[{i}] is missing `id`")
            eid = f"#{i}"
        else:
            eid = str(eid)
        if eid in edge_ids:
            report.error(f"duplicate edge id: {eid}")
        edge_ids.add(eid)

        for role in ("source", "target"):
            ref = edge.get(role)
            if not ref:
                report.error(f"edge {eid} is missing `{role}`")
            elif str(ref) not in node_ids:
                report.error(
                    f"edge {eid} `{role}` points to `{ref}`, which is not a declared node"
                )

        etype = _first(edge, "edge_type")
        if etype is not None and str(etype) not in reg.edge_types:
            unknown_edge_types.setdefault(str(etype), []).append(eid)

        for role in ("source", "target"):
            for field in ALIASES[f"{role}_port"]:
                port = edge.get(field)
                if port is None:
                    continue
                if not PORT_RE.match(str(port)):
                    report.error(
                        f"edge {eid} `{field}` is `{port}`; expected a side "
                        f"({', '.join(SIDES)}) optionally plus -1/-2/-3"
                    )
            for field in ALIASES[f"{role}_side"]:
                side = edge.get(field)
                if side is None:
                    continue
                if str(side) not in SIDES:
                    report.error(
                        f"edge {eid} `{field}` is `{side}`; expected one of {', '.join(SIDES)}"
                    )

        for route_field in ALIASES["route_points"]:
            route = edge.get(route_field)
            if route is None:
                continue
            if not isinstance(route, list) or len(route) < 2:
                report.error(
                    f"edge {eid} `{route_field}` must contain at least two [x, y] points"
                )
                continue
            for point_index, point in enumerate(route):
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    report.error(f"edge {eid} `{route_field}[{point_index}]` must be [x, y]")
                    continue
                if not all(isinstance(value, (int, float)) for value in point):
                    report.error(
                        f"edge {eid} `{route_field}[{point_index}]` must contain numeric coordinates"
                    )

        routing = edge.get("routing")
        if routing is not None and str(routing) not in ROUTINGS:
            report.warn(
                f"edge {eid} has unrecognized routing `{routing}`; "
                f"expected one of {sorted(ROUTINGS)}"
            )

        for group_field in ("fanout_group", "fanoutGroup", "fanin_group", "faninGroup"):
            group = edge.get(group_field)
            if group is not None and not str(group):
                report.error(f"edge {eid} `{group_field}` is empty; omit it instead")

    for etype, ids in unknown_edge_types.items():
        report.warn(
            f"unknown edge type `{etype}` on {len(ids)} edge(s) ({_preview(ids)}); "
            f"expected one of {_enum_preview(reg.edge_types)}"
        )

    _validate_dependency_contract(graph, node_ids, report)
    _validate_subflows(graph, node_ids, reg, report)


def _validate_dependency_contract(
    graph: dict[str, Any], node_ids: set[str], report: Report
) -> None:
    """Causal edges must close one output to one input; context is not an edge."""
    if graph.get("dependency_contract") != "causal-v1" and graph.get(
        "dependencyContract"
    ) != "causal-v1":
        return

    outputs: dict[str, set[str]] = {}
    inputs: dict[str, set[str]] = {}
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id", ""))
        outputs[nid] = {
            str(v) for v in (node.get("output_refs") or node.get("outputRefs") or [])
        }
        inputs[nid] = {
            str(v) for v in (node.get("input_refs") or node.get("inputRefs") or [])
        }

    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        eid = str(edge.get("id", "?"))
        dep = edge.get("dependency")
        if dep is None:
            report.error(
                f"edge {eid} has no `dependency`, but the graph declares "
                "`dependency_contract: causal-v1`"
            )
            continue
        if not isinstance(dep, dict):
            report.error(f"edge {eid} `dependency` must be an object")
            continue
        kind = str(dep.get("kind", ""))
        if kind in {"context", "shared-context", "shared_context"}:
            report.error(
                f"edge {eid} declares a `{kind}` dependency; shared context belongs in "
                "`context_refs`, not in an edge"
            )
            continue
        out_ref = dep.get("output_ref") or dep.get("outputRef")
        in_ref = dep.get("input_ref") or dep.get("inputRef")
        if not out_ref or not in_ref:
            report.error(
                f"edge {eid} `dependency` needs both `output_ref` and `input_ref`"
            )
            continue
        if str(out_ref) != str(in_ref):
            report.error(
                f"edge {eid} dependency does not close: output_ref `{out_ref}` "
                f"!= input_ref `{in_ref}`"
            )
            continue
        src, tgt = str(edge.get("source", "")), str(edge.get("target", ""))
        if src in outputs and str(out_ref) not in outputs[src]:
            report.error(
                f"edge {eid} output_ref `{out_ref}` is not produced by source `{src}`"
            )
        if tgt in inputs and str(in_ref) not in inputs[tgt]:
            report.error(
                f"edge {eid} input_ref `{in_ref}` is not consumed by target `{tgt}`"
            )


def _validate_subflows(
    graph: dict[str, Any], node_ids: set[str], reg: Registry, report: Report
) -> None:
    subflows = graph.get("subflows")
    if subflows is None:
        return
    if not isinstance(subflows, dict):
        report.error("`subflows` must be an object keyed by stage node id")
        return
    for stage_id, sub in subflows.items():
        if str(stage_id) not in node_ids:
            report.error(f"subflows key `{stage_id}` is not a declared node id")
        if not isinstance(sub, dict):
            report.error(f"subflow `{stage_id}` must be an object")
            continue
        sub_nodes = sub.get("nodes", [])
        if not isinstance(sub_nodes, list) or not sub_nodes:
            report.error(f"subflow `{stage_id}` needs a non-empty `nodes` array")
            continue
        sub_ids = {str(n.get("id")) for n in sub_nodes if isinstance(n, dict)}
        for e in sub.get("edges", []):
            if not isinstance(e, dict):
                continue
            for role in ("source", "target"):
                ref = e.get(role)
                if ref and str(ref) not in sub_ids:
                    report.error(
                        f"subflow `{stage_id}` edge {e.get('id', '?')} `{role}` points to "
                        f"`{ref}`, not declared in this subflow"
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Flowchat graph JSON file")
    parser.add_argument("graph", type=Path)
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help=f"type registry to validate against (default: {DEFAULT_REGISTRY})",
    )
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

    registry = Registry(args.registry)
    report = Report()
    _validate(graph, registry, report)

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

    node_count = len(graph.get("nodes", [])) if isinstance(graph, dict) else 0
    edge_count = len(graph.get("edges", [])) if isinstance(graph, dict) else 0
    print(
        f"OK: {node_count} nodes, {edge_count} edges, {len(report.warnings)} warning(s) "
        f"(registry: {len(registry.node_types)} node types / "
        f"{len(registry.edge_types)} edge types / {len(registry.statuses)} statuses)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
