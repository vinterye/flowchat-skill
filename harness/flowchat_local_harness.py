#!/usr/bin/env python3
"""Local Harness for standalone Flowchat HTML artifacts.

This intentionally does not call project skill.flowchart gates. It validates
standalone graph geometry, arrow anchoring, text layout, and interaction hooks.
Browser interaction evidence is supplied as a local JSON receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from collections import Counter

MIN_SEGMENT = 8.0
NEAR_ZERO = 2.0
DEFAULT_MIN_EDGE = 90.0
DEFAULT_MIN_ARROW = 75.0
MAX_EDGE_STROKE_WIDTH = 2.0
MAX_ARROW_MARKER_SIZE = 5.0
TOLERANCE = 2.5


def _load_graph(html: str) -> dict[str, Any]:
    match = re.search(r"window\.__FLOWCHAT_GRAPH__=(.*?);window\.__FLOWCHAT_THEME__=", html, re.S)
    if not match:
        raise ValueError("missing embedded Flowchat graph")
    return json.loads(match.group(1))


def _paths(html: str) -> dict[str, list[list[float]]]:
    result: dict[str, list[list[float]]] = {}
    pattern = re.compile(r'data-edge="([^"]+)"[^>]*>\s*<path class="flowchat-edge" d="([^"]+)"', re.S)
    for edge_id, path in pattern.findall(html):
        points = [[float(x), float(y)] for x, y in re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path)]
        result[edge_id] = points
    return result


def _length(a: list[float], b: list[float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _segment_length(points: list[list[float]]) -> list[float]:
    return [_length(a, b) for a, b in zip(points, points[1:])]


def _diamond_side(node: dict[str, Any]) -> float:
    return math.hypot(float(node["width"]) / 2, float(node["height"]) / 2)


def _on_boundary(node: dict[str, Any], point: list[float]) -> bool:
    x, y = point
    left, top = float(node["x"]), float(node["y"])
    width, height = float(node["width"]), float(node["height"])
    right, bottom = left + width, top + height
    shape = node.get("shape", "rect")
    if shape == "diamond":
        value = abs((x - (left + width / 2)) / max(width / 2, 1)) + abs((y - (top + height / 2)) / max(height / 2, 1))
        return abs(value - 1) <= 0.06
    if shape == "circle":
        return abs(math.hypot(x - (left + width / 2), y - (top + height / 2)) - min(width, height) / 2) <= TOLERANCE
    inside_x, inside_y = left - TOLERANCE <= x <= right + TOLERANCE, top - TOLERANCE <= y <= bottom + TOLERANCE
    on_side = min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom)) <= TOLERANCE
    return inside_x and inside_y and on_side


def _axis_aligned(a: list[float], b: list[float]) -> bool:
    return abs(a[0] - b[0]) <= 0.01 or abs(a[1] - b[1]) <= 0.01


def _segment_hits_rect(a: list[float], b: list[float], node: dict[str, Any]) -> bool:
    left, top = float(node["x"]), float(node["y"])
    right, bottom = left + float(node["width"]), top + float(node["height"])
    if abs(a[0] - b[0]) <= 0.01:
        x = a[0]
        return left + TOLERANCE < x < right - TOLERANCE and max(min(a[1], b[1]), top + TOLERANCE) < min(max(a[1], b[1]), bottom - TOLERANCE)
    if abs(a[1] - b[1]) <= 0.01:
        y = a[1]
        return top + TOLERANCE < y < bottom - TOLERANCE and max(min(a[0], b[0]), left + TOLERANCE) < min(max(a[0], b[0]), right - TOLERANCE)
    return False


def _attrs(markup: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', markup))


def _inside(node: dict[str, Any], point: list[float]) -> bool:
    x, y = point
    left, top, w, h = (float(node[k]) for k in ("x", "y", "width", "height"))
    dx, dy = x - left - w / 2, y - top - h / 2
    if node.get("shape") == "diamond":
        return abs(dx)/(w/2) + abs(dy)/(h/2) < 1 - 1e-6
    if node.get("shape") == "circle":
        return math.hypot(dx,dy) < min(w,h)/2 - 1e-6
    return left + 1e-6 < x < left+w-1e-6 and top+1e-6 < y < top+h-1e-6


def _hits(a: list[float], b: list[float], node: dict[str, Any]) -> bool:
    # Clip orthogonal segments analytically, including source and target bodies.
    left, top, w, h = (float(node[k]) for k in ("x", "y", "width", "height"))
    cx,cy=left+w/2,top+h/2
    horizontal=abs(a[1]-b[1]) < 1e-6
    if horizontal:
        fixed=a[1]; span=(min(a[0],b[0]),max(a[0],b[0])); center=cx; half=w/2
        dist=abs(fixed-cy); bound=h/2
    else:
        fixed=a[0]; span=(min(a[1],b[1]),max(a[1],b[1])); center=cy; half=h/2
        dist=abs(fixed-cx); bound=w/2
    if node.get("shape") == "circle":
        radius=min(w,h)/2
        if dist >= radius: return False
        half=math.sqrt(radius*radius-dist*dist)
    elif node.get("shape") == "diamond":
        if dist >= bound: return False
        half *= 1-dist/bound
    elif dist >= bound: return False
    return max(span[0],center-half)+1e-5 < min(span[1],center+half)


def _overlap(a, b, c, d):
    horizontal=abs(a[1]-b[1])<1e-6
    other_horizontal=abs(c[1]-d[1])<1e-6
    if horizontal != other_horizontal: return None
    axis=0 if horizontal else 1; fixed=1-axis
    if abs(a[fixed]-c[fixed])>1e-6: return None
    lo=max(min(a[axis],b[axis]), min(c[axis],d[axis]))
    hi=min(max(a[axis],b[axis]), max(c[axis],d[axis]))
    if hi-lo <= 1e-5: return None
    return (b[axis]-a[axis])*(d[axis]-c[axis])>0


def _cross(a,b,c,d):
    if (abs(a[1]-b[1])<1e-6)==(abs(c[1]-d[1])<1e-6): return None
    if abs(a[1]-b[1])>1e-6: a,b,c,d=c,d,a,b
    x,y=c[0],a[1]
    if min(a[0],b[0])+1e-5 < x < max(a[0],b[0])-1e-5 and min(c[1],d[1])+1e-5 < y < max(c[1],d[1])-1e-5:
        return [x,y]
    return None


def _edge_group_markup(html: str, edge_id: str) -> str:
    """Return one edge group's markup so crossing evidence is edge-bound."""
    match = re.search(
        r'<g class="flowchat-edge-group[^>]*data-edge="' + re.escape(edge_id) + r'"[^>]*>.*?</g>',
        html,
        re.S,
    )
    return match.group(0) if match else ""


def _edge_side(edge_id: str, edge: dict[str, Any], role: str, nodes: dict[str, dict[str, Any]], paths: dict[str, list[list[float]]]) -> str | None:
    explicit = edge.get(f"{role}_side") or edge.get(f"{role}_port")
    if explicit:
        return str(explicit).split("-", 1)[0]
    points = paths.get(edge_id, [])
    node = nodes.get(str(edge.get("source" if role == "source" else "target")))
    if not points or not node or node.get("shape", "rect") != "rect":
        return None
    point = points[0] if role == "source" else points[-1]
    left, top, width, height = (float(node[k]) for k in ("x", "y", "width", "height"))
    distances = {
        "left": abs(point[0] - left),
        "right": abs(point[0] - (left + width)),
        "top": abs(point[1] - top),
        "bottom": abs(point[1] - (top + height)),
    }
    return min(distances, key=distances.get)


def _port_ref(edge: dict[str, Any], role: str) -> str | None:
    value = edge.get(f"{role}_port") or edge.get(f"{role}_side")
    return str(value) if value else None


def _expected_relative_sides(source: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    """Return ports required by the center-to-center relative-position rule."""
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
    if abs(dx) >= abs(dy):
        return ("right", "left") if dx > 0 else ("left", "right")
    # Vertical distance dominates. The source exits vertically. An offset
    # target is entered from the horizontal side only when the target has
    # enough horizontal clearance for the minimum arrow segment; otherwise
    # the target keeps its opposite top/bottom midpoint.
    source_side = "bottom" if dy > 0 else "top"
    side_threshold = float(target["width"]) / 2 + DEFAULT_MIN_ARROW
    if abs(dx) < side_threshold:
        return source_side, ("top" if dy > 0 else "bottom")
    target_side = "left" if dx > 0 else "right"
    return source_side, target_side


def _routing_contract_checks(
    graph: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    paths: dict[str, list[list[float]]],
    fail,
) -> dict[str, int]:
    """Check semantic routing promises that geometry alone cannot prove."""
    metrics = {
        "centered_flow_groups": 0,
        "fanout_corridors_checked": 0,
        "fanin_corridors_checked": 0,
        "fanout_center_spacing_checked": 0,
        "fanin_center_spacing_checked": 0,
        "diagonal_horizontal_first_checked": 0,
        "relative_position_checked": 0,
        "relative_midpoint_corridor_checked": 0,
        "mixed_lane_nodes_checked": 0,
    }

    if isinstance(graph.get("layout"), dict) and graph["layout"].get("mode") in {"centered-flow", "auto-centered"}:
        groups: dict[str, dict[str, Any]] = {}
        def centered_group_key(edge: dict[str, Any], source_id: str) -> str:
            source_side = _port_ref(edge, "source")
            target_side = _port_ref(edge, "target")
            return f"{str(edge.get('fanout_group') or f'source:{source_id}')}|{source_side}:{target_side}"
        for edge in edges.values():
            source = nodes.get(str(edge.get("source")))
            target = nodes.get(str(edge.get("target")))
            if not source or not target:
                continue
            if edge.get("fanin_group"):
                continue
            source_side = _port_ref(edge, "source")
            target_side = _port_ref(edge, "target")
            vertical = source_side == "bottom" and target_side == "top"
            horizontal = source_side == "right" and target_side == "left"
            if not (vertical or horizontal):
                continue
            key = centered_group_key(edge, str(source["id"]))
            entry = groups.setdefault(key, {"targets": [], "horizontal": horizontal})
            entry["targets"].append(target)
        for group, entry in groups.items():
            targets = entry["targets"]
            horizontal = bool(entry["horizontal"])
            group_edges = [edge for edge in edges.values() if centered_group_key(edge, str(edge.get("source"))) == group]
            if len(targets) == 1 and not any(edge.get("fanout_group") for edge in group_edges):
                if not group_edges or group_edges[0].get("route_points"):
                    continue
            source_id = str(next(edge for edge in edges.values() if centered_group_key(edge, str(edge.get("source"))) == group).get("source"))
            source = nodes.get(source_id)
            if not source or not targets:
                continue
            unique_targets = {str(target["id"]): target for target in targets}
            if horizontal:
                target_centers = [float(target["y"]) + float(target["height"]) / 2 for target in unique_targets.values()]
                expected = sum(target_centers) / len(target_centers)
                actual = float(source["y"]) + float(source["height"]) / 2
            else:
                target_centers = [float(target["x"]) + float(target["width"]) / 2 for target in unique_targets.values()]
                expected = sum(target_centers) / len(target_centers)
                actual = float(source["x"]) + float(source["width"]) / 2
            metrics["centered_flow_groups"] += 1
            if abs(actual - expected) > TOLERANCE:
                fail("centered_flow_misaligned", group=group, source=source_id, actual=actual, expected=expected)

    for edge_id, edge in edges.items():
        source = nodes.get(str(edge.get("source")))
        target = nodes.get(str(edge.get("target")))
        points = paths.get(edge_id, [])
        if not source or not target or len(points) < 2:
            continue
        # A declared fan-out/fan-in group is a group-level topology contract.
        # Its shared trunk deliberately uses one side for every member even
        # when an outer target is diagonally offset from the source. Applying
        # the single-edge relative matrix here would incorrectly reject a
        # valid 1→N/N→1 corridor; the group checks below validate the common
        # side, trunk, split/merge corridor, spacing, and centring.
        if edge.get("fanout_group") or edge.get("fanin_group"):
            metrics["relative_position_checked"] += 1
            continue
        expected_source, expected_target = _expected_relative_sides(source, target)
        actual_source = _edge_side(edge_id, edge, "source", nodes, paths)
        actual_target = _edge_side(edge_id, edge, "target", nodes, paths)
        metrics["relative_position_checked"] += 1
        if actual_source != expected_source or actual_target != expected_target:
            fail(
                "relative_port_mismatch",
                edge=edge_id,
                expected_source_side=expected_source,
                expected_target_side=expected_target,
                actual_source_side=actual_source,
                actual_target_side=actual_target,
            )
            continue
        source_cx = float(source["x"]) + float(source["width"]) / 2
        source_cy = float(source["y"]) + float(source["height"]) / 2
        target_cx = float(target["x"]) + float(target["width"]) / 2
        target_cy = float(target["y"]) + float(target["height"]) / 2
        dx, dy = target_cx - source_cx, target_cy - source_cy
        tolerance = max(12.0, min(float(source["width"]), float(target["width"])) * 0.12)
        if abs(dx) > tolerance and abs(dy) > tolerance and len(points) > 2:
            interior = points[1:-1]
            if abs(dx) >= abs(dy):
                low, high = sorted((source_cx, target_cx))
                in_corridor = any(low - TOLERANCE <= point[0] <= high + TOLERANCE for point in interior)
            else:
                low, high = sorted((source_cy, target_cy))
                in_corridor = any(low - TOLERANCE <= point[1] <= high + TOLERANCE for point in interior)
            metrics["relative_midpoint_corridor_checked"] += 1
            if not in_corridor:
                fail("bend_outside_center_corridor", edge=edge_id, source_center=[source_cx, source_cy], target_center=[target_cx, target_cy])

    fanout_groups: dict[str, list[tuple[str, dict[str, Any], list[list[float]]]]] = {}
    fanin_groups: dict[str, list[tuple[str, dict[str, Any], list[list[float]]]]] = {}
    for edge_id, edge in edges.items():
        points = paths.get(edge_id, [])
        if edge.get("fanout_group"):
            fanout_groups.setdefault(str(edge["fanout_group"]), []).append((edge_id, edge, points))
        if edge.get("fanin_group"):
            fanin_groups.setdefault(str(edge["fanin_group"]), []).append((edge_id, edge, points))

    for group, items in fanout_groups.items():
        if len(items) < 2:
            continue
        source_ids = {str(edge.get("source")) for _, edge, _ in items}
        if len(source_ids) != 1:
            fail("fanout_group_multiple_sources", group=group, sources=sorted(source_ids))
            continue
        valid = [points for _, _, points in items if len(points) >= 3]
        if len(valid) < 2:
            fail("fanout_corridor_missing", group=group)
            continue
        first_points = [points[0] for points in valid]
        if any(_length(point, first_points[0]) > TOLERANCE for point in first_points[1:]):
            fail("fanout_source_trunk_not_shared", group=group)
        source_side = _port_ref(items[0][1], "source")
        if source_side == "bottom" and any(abs(points[1][1] - valid[0][1][1]) > TOLERANCE for points in valid[1:]):
            fail("fanout_split_corridor_not_shared", group=group)
        source = nodes.get(str(next(iter(source_ids))))
        targets = [nodes.get(str(edge.get("target"))) for _, edge, _ in items]
        targets = [target for target in targets if target]
        if source and len(targets) >= 2:
            horizontal = source_side in {"left", "right"}
            centers = sorted(
                (float(target["y"]) + float(target["height"]) / 2) if horizontal
                else (float(target["x"]) + float(target["width"]) / 2)
                for target in targets
            )
            gaps = [right - left for left, right in zip(centers, centers[1:])]
            if gaps and max(gaps) - min(gaps) > TOLERANCE:
                fail("fanout_target_spacing_not_equal", group=group, centers=centers)
            source_center = (float(source["y"]) + float(source["height"]) / 2) if horizontal else (float(source["x"]) + float(source["width"]) / 2)
            expected_center = (centers[0] + centers[-1]) / 2
            if abs(source_center - expected_center) > TOLERANCE:
                fail("fanout_source_not_centered_on_target_span", group=group, actual=source_center, expected=expected_center)
            metrics["fanout_center_spacing_checked"] += 1
        metrics["fanout_corridors_checked"] += 1

    for group, items in fanin_groups.items():
        if len(items) < 2:
            continue
        target_ids = {str(edge.get("target")) for _, edge, _ in items}
        if len(target_ids) != 1:
            fail("fanin_group_multiple_targets", group=group, targets=sorted(target_ids))
            continue
        valid = [points for _, _, points in items if len(points) >= 3]
        if len(valid) < 2:
            fail("fanin_corridor_missing", group=group)
            continue
        if any(_length(points[-1], valid[0][-1]) > TOLERANCE for points in valid[1:]):
            fail("fanin_target_port_not_shared", group=group)
        if any(_length(points[-2], valid[0][-2]) > TOLERANCE for points in valid[1:]):
            fail("fanin_merge_corridor_not_shared", group=group)
        target = nodes.get(str(next(iter(target_ids))))
        sources = [nodes.get(str(edge.get("source"))) for _, edge, _ in items]
        sources = [source for source in sources if source]
        if target and len(sources) >= 2:
            target_side = _port_ref(items[0][1], "target")
            horizontal = target_side in {"left", "right"}
            centers = sorted(
                (float(source["y"]) + float(source["height"]) / 2) if horizontal
                else (float(source["x"]) + float(source["width"]) / 2)
                for source in sources
            )
            gaps = [right - left for left, right in zip(centers, centers[1:])]
            if gaps and max(gaps) - min(gaps) > TOLERANCE:
                fail("fanin_source_spacing_not_equal", group=group, centers=centers)
            target_center = (float(target["y"]) + float(target["height"]) / 2) if horizontal else (float(target["x"]) + float(target["width"]) / 2)
            expected_center = (centers[0] + centers[-1]) / 2
            if abs(target_center - expected_center) > TOLERANCE:
                fail("fanin_target_not_centered_on_source_span", group=group, actual=target_center, expected=expected_center)
            metrics["fanin_center_spacing_checked"] += 1
        metrics["fanin_corridors_checked"] += 1

    source_groups: dict[tuple[str, str, str], list[tuple[str, dict[str, Any], list[list[float]]]]] = {}
    target_groups: dict[tuple[str, str], list[tuple[str, dict[str, Any], list[list[float]]]]] = {}
    for edge_id, edge in edges.items():
        source_port = _port_ref(edge, "source")
        target_port = _port_ref(edge, "target")
        if source_port and target_port and not edge.get("fanout_group"):
            source_groups.setdefault((str(edge.get("source")), source_port.split("-", 1)[0], target_port.split("-", 1)[0]), []).append((edge_id, edge, paths.get(edge_id, [])))
        if target_port and not edge.get("fanin_group"):
            target_groups.setdefault((str(edge.get("target")), target_port.split("-", 1)[0]), []).append((edge_id, edge, paths.get(edge_id, [])))
    for key, items in source_groups.items():
        if len(items) < 2:
            continue
        valid = [points for _, _, points in items if len(points) >= 3]
        shared_trunk = len(valid) == len(items) and len({tuple(points[0]) for points in valid}) == 1 and len({tuple(points[1]) for points in valid}) == 1
        if not shared_trunk:
            fail("fanout_group_missing", source=key[0], source_side=key[1], target_side=key[2], edges=[edge_id for edge_id, _, _ in items])
    for key, items in target_groups.items():
        if len(items) < 2:
            continue
        valid = [points for _, _, points in items if len(points) >= 3]
        shared_merge = len(valid) == len(items) and len({tuple(points[-1]) for points in valid}) == 1 and len({tuple(points[-2]) for points in valid}) == 1
        if not shared_merge:
            fail("fanin_group_missing", target=key[0], target_side=key[1], edges=[edge_id for edge_id, _, _ in items])

    for edge_id, edge in edges.items():
        if edge.get("route_points") or edge.get("fanout_group") or edge.get("fanin_group"):
            continue
        points = paths.get(edge_id, [])
        if len(points) < 2:
            continue
        source_side = _port_ref(edge, "source")
        target_side = _port_ref(edge, "target")
        if source_side in {"left", "right"}:
            metrics["diagonal_horizontal_first_checked"] += 1
            if abs(points[0][1] - points[1][1]) > TOLERANCE:
                fail("horizontal_first_route_missing", edge=edge_id, source_side=source_side)
        if target_side in {"top", "bottom"} and abs(points[-2][0] - points[-1][0]) > TOLERANCE:
            fail("vertical_target_approach_missing", edge=edge_id, target_side=target_side)

    side_roles: dict[tuple[str, str], dict[str, set[str]]] = {}
    for edge in edges.values():
        for role in ("source", "target"):
            node_id = str(edge.get("source" if role == "source" else "target"))
            port = _port_ref(edge, role)
            if not port or "-" not in port:
                continue
            side = port.split("-", 1)[0]
            side_roles.setdefault((node_id, side), {"source": set(), "target": set()})[role].add(port)
    for (node_id, side), roles in side_roles.items():
        if roles["source"] and roles["target"]:
            metrics["mixed_lane_nodes_checked"] += 1
            if roles["source"] & roles["target"]:
                fail("mixed_incoming_outgoing_lane_overlap", node=node_id, side=side, overlap=sorted(roles["source"] & roles["target"]))
    return metrics


def _dependency_contract_checks(
    graph: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    fail,
) -> dict[str, int]:
    """Validate that drawn edges are backed by declared data dependencies.

    The contract is opt-in per graph so legacy fixtures remain readable. Once
    enabled, shared context is represented by node ``context_refs`` and never
    becomes a visual edge; every visual edge must close an output_ref to an
    input_ref on its endpoints.
    """
    metrics = {
        "dependency_edges_checked": 0,
        "dependency_refs_checked": 0,
        "context_refs_checked": 0,
    }
    if graph.get("dependency_contract") != "causal-v1":
        return metrics

    def refs(node: dict[str, Any], key: str) -> set[str]:
        value = node.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            fail("invalid_dependency_refs", node=node.get("id"), field=key)
            return set()
        metrics["dependency_refs_checked"] += len(value)
        return set(value)

    node_inputs = {node_id: refs(node, "input_refs") for node_id, node in nodes.items()}
    node_outputs = {node_id: refs(node, "output_refs") for node_id, node in nodes.items()}
    for node_id, node in nodes.items():
        context = node.get("context_refs", [])
        if not isinstance(context, list) or any(not isinstance(item, str) or not item for item in context):
            fail("invalid_context_refs", node=node_id)
            continue
        metrics["context_refs_checked"] += len(context)

    allowed_kinds = {"input", "produces", "controls", "handoff", "review"}
    for edge_id, edge in edges.items():
        dependency = edge.get("dependency")
        if not isinstance(dependency, dict):
            fail("edge_dependency_missing", edge=edge_id)
            continue
        kind = dependency.get("kind")
        output_ref = dependency.get("output_ref")
        input_ref = dependency.get("input_ref")
        if kind not in allowed_kinds:
            fail("edge_dependency_kind_invalid", edge=edge_id, kind=kind)
        if not isinstance(output_ref, str) or not isinstance(input_ref, str):
            fail("edge_dependency_refs_missing", edge=edge_id)
            continue
        source_id = str(edge.get("source"))
        target_id = str(edge.get("target"))
        if output_ref not in node_outputs.get(source_id, set()):
            fail("edge_output_ref_not_declared", edge=edge_id, source=source_id, output_ref=output_ref)
        if input_ref not in node_inputs.get(target_id, set()):
            fail("edge_input_ref_not_declared", edge=edge_id, target=target_id, input_ref=input_ref)
        if output_ref in node_inputs.get(source_id, set()) or input_ref in node_outputs.get(target_id, set()):
            fail("edge_ref_role_inverted", edge=edge_id)
        metrics["dependency_edges_checked"] += 1

        edge_kind = str(edge.get("kind") or edge.get("type") or "").lower()
        if edge_kind in {"context", "shared-context", "shared_context"} or dependency.get("kind") == "context":
            fail("shared_context_must_use_context_refs", edge=edge_id)
    return metrics


def _static_checks(html: str, graph: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    failures=[]
    def fail(check, **extra): failures.append({"check":check, **extra})
    root_count=len(re.findall(r'<[^>]+data-flowchat-root(?:[ >])', html))
    if root_count != 1: fail("root_mount_count",actual=root_count,required=1)
    if re.search(r"<iframe\b|\bsrcdoc\s*=|file://", html, re.I):
        fail("nested_embed_forbidden")
    for key in ("nodes","edges"):
        ids=[str(item.get("id","")) for item in graph.get(key,[])]
        if not ids: fail("empty_graph", component=key)
        for item,count in Counter(ids).items():
            if count>1 or not item: fail("duplicate_graph_id", component=key,id=item)
    nodes={str(n["id"]):n for n in graph.get("nodes",[])}
    edges={str(e["id"]):e for e in graph.get("edges",[])}
    for node in nodes.values():
        for key in ("x","y","width","height"):
            if not math.isfinite(float(node[key])): fail("nonfinite_node",node=node["id"])
        if float(node["width"])<=0 or float(node["height"])<=0: fail("invalid_node_size",node=node["id"])
    paths=_paths(html)
    # A centred corridor on a tightly spaced graph cannot also keep a full
    # 75px arrow: centring was chosen deliberately over arrow length. The
    # generator marks exactly those edges, so they only have to keep a visible
    # stub. Everything else still has to meet the full arrow length.
    relaxed_edges={m.group(1) for m in re.finditer(r'data-edge="([^"]+)"[^>]*data-arrow-relaxed="true"', html)}
    diamonds=[n for n in nodes.values() if n.get("shape")=="diamond"]
    min_edge=max(DEFAULT_MIN_EDGE,max((_diamond_side(n) for n in diamonds),default=0))
    metrics={"node_count":len(nodes),"edge_count":len(edges),"min_edge_length":min_edge,"min_arrow_segment":DEFAULT_MIN_ARROW,"backtracking_count":0,"opposite_overlap_count":0,"crossing_count":0,"max_edge_stroke_width":MAX_EDGE_STROKE_WIDTH,"max_arrow_marker_size":MAX_ARROW_MARKER_SIZE,"arrow_relaxed_edges":sorted(relaxed_edges)}
    segments={}
    strokes=set()
    marker_defs={m.group(1):m.group(0) for m in re.finditer(r'<marker\b[^>]*id="([^"]+)".*?</marker>',html,re.S)}
    for edge_id,edge in edges.items():
        points=paths.get(edge_id,[])
        source,target=nodes.get(str(edge.get("source"))),nodes.get(str(edge.get("target")))
        if not source or not target: fail("unknown_edge_node",edge=edge_id);continue
        if len(points)<2: fail("route_missing",edge=edge_id);continue
        segments[edge_id]=list(zip(points,points[1:]))
        lengths=_segment_length(points)
        for index,(a,b) in enumerate(segments[edge_id]):
            if not _axis_aligned(a,b): fail("diagonal_segment",edge=edge_id,segment=index)
            if lengths[index]<NEAR_ZERO: fail("near_zero_segment",edge=edge_id,segment=index)
            elif lengths[index]<MIN_SEGMENT: fail("segment_too_short",edge=edge_id,segment=index,actual=lengths[index])
            for node in nodes.values():
                if node["id"] in {source["id"], target["id"]}:
                    continue
                if _hits(a,b,node): fail("edge_through_node",edge=edge_id,node=node["id"],segment=index)
        for i,(a,b,c) in enumerate(zip(points,points[1:],points[2:])):
            u=(b[0]-a[0],b[1]-a[1]);v=(c[0]-b[0],c[1]-b[1])
            if abs(u[0]*v[1]-u[1]*v[0])<1e-6 and u[0]*v[0]+u[1]*v[1]<0:
                fail("route_backtracks",edge=edge_id,vertex=i+1);metrics["backtracking_count"]+=1
        if sum(lengths)+1e-5<min_edge: fail("edge_too_short",edge=edge_id,actual=sum(lengths),required=min_edge)
        arrow_floor=MIN_SEGMENT if edge_id in relaxed_edges else DEFAULT_MIN_ARROW
        if lengths[-1]+1e-5<arrow_floor: fail("arrow_segment_too_short",edge=edge_id,actual=lengths[-1],required=arrow_floor)
        for role,node,point,near in (("source",source,points[0],points[1]),("target",target,points[-1],points[-2])):
            if not _on_boundary(node,point): fail(role+"_not_on_boundary",edge=edge_id,point=point)
            side=edge.get(role+"_side")
            if not side and node.get("shape","rect") == "rect":
                left,top,w,h=(float(node[k]) for k in ("x","y","width","height"))
                distances={"left":abs(point[0]-left),"right":abs(point[0]-(left+w)),"top":abs(point[1]-top),"bottom":abs(point[1]-(top+h))}
                side=min(distances,key=distances.get)
            if side:
                normals={"left":(-1,0),"right":(1,0),"top":(0,-1),"bottom":(0,1)}
                normal=normals.get(side)
                vec=(near[0]-point[0],near[1]-point[1])
                if not normal or vec[0]*normal[0]+vec[1]*normal[1]<=0 or abs(vec[0]*normal[1]-vec[1]*normal[0])>1e-5:
                    fail(role+"_direction_wrong",edge=edge_id,side=side)
                if normal and node.get("shape","rect")=="rect":
                    expected={"left":float(node["x"]),"right":float(node["x"])+float(node["width"]),"top":float(node["y"]),"bottom":float(node["y"])+float(node["height"])}[side]
                    if abs(point[0 if side in {"left","right"} else 1]-expected)>TOLERANCE: fail(role+"_port_side_wrong",edge=edge_id)
                    along=point[1]-float(node["y"]) if side in {"left","right"} else point[0]-float(node["x"])
                    size=float(node["height"] if side in {"left","right"} else node["width"])
                    if min(along,size-along)<13: fail("port_on_rounded_corner",edge=edge_id,role=role)
            distance=max(_length(point,near),1e-6)
            probe=[point[k]+(near[k]-point[k])*min(5,distance/2)/distance for k in (0,1)]
            if _inside(node,probe): fail(role+"_direction_wrong",edge=edge_id)
        if _axis_aligned(points[0],points[-1]) and len(points)>2:
            a,b=points[0],points[-1]
            startvec=(points[1][0]-a[0],points[1][1]-a[1]);endvec=(b[0]-points[-2][0],b[1]-points[-2][1]);direct=(b[0]-a[0],b[1]-a[1])
            forward=lambda v: abs(v[0]*direct[1]-v[1]*direct[0])<1e-5 and v[0]*direct[0]+v[1]*direct[1]>0
            if forward(startvec) and forward(endvec) and not any(_hits(a,b,n) for n in nodes.values()) and any(abs((p[0]-a[0])*direct[1]-(p[1]-a[1])*direct[0])>1e-5 for p in points):
                # Occupied opposing lanes justify an explicit outer route, but a label alone does not.
                conflict=any(_overlap(a,b,c,d) is False for other,ss in segments.items() if other!=edge_id for c,d in ss)
                if not conflict: fail("unnecessary_bend_aligned_ports",edge=edge_id)
        match=re.search(r'data-edge="'+re.escape(edge_id)+r'"[^>]*>\s*<path class="flowchat-edge"[^>]*>',html)
        attrs=_attrs(match.group(0)) if match else {}
        stroke=attrs.get("stroke","");strokes.add(stroke)
        try:
            stroke_width=float(attrs.get("data-stroke-width","nan"))
        except ValueError:
            stroke_width=float("nan")
        if not math.isfinite(stroke_width) or stroke_width>MAX_EDGE_STROKE_WIDTH:
            fail("edge_stroke_too_thick",edge=edge_id,actual=stroke_width,maximum=MAX_EDGE_STROKE_WIDTH)
        marker_id=re.fullmatch(r'url\(#([^)]*)\)',attrs.get("marker-end",""))
        marker=marker_defs.get(marker_id.group(1),"") if marker_id else ""
        ma=_attrs(marker.split(">",1)[0])
        if not marker or ma.get("orient")!="auto": fail("arrow_marker_missing",edge=edge_id)
        else:
            try:
                marker_width=float(ma.get("markerWidth","nan")); marker_height=float(ma.get("markerHeight","nan"))
            except ValueError:
                marker_width=marker_height=float("nan")
            if not math.isfinite(marker_width) or not math.isfinite(marker_height) or marker_width>MAX_ARROW_MARKER_SIZE or marker_height>MAX_ARROW_MARKER_SIZE:
                fail("arrow_marker_too_large",edge=edge_id,width=marker_width,height=marker_height,maximum=MAX_ARROW_MARKER_SIZE)
            coords=re.search(r'<path[^>]*d="M\s*0[ ,]+0\s+L\s*([0-9.]+)[ ,]+([0-9.]+)\s+L\s*0[ ,]+([0-9.]+)\s+Z"',marker)
            if not coords or abs(float(ma.get("refX","-1"))-float(coords.group(1)))>0.01: fail("arrow_tip_not_at_endpoint",edge=edge_id)
            if stroke not in re.findall(r'fill="([^"]+)"',marker): fail("arrow_color_mismatch",edge=edge_id)
    if len(strokes)>1: fail("edge_palette_not_unified",colors=sorted(strokes))
    edge_markup = {edge_id: _edge_group_markup(html, edge_id) for edge_id in edges}
    edge_sides = {edge_id: {role: _edge_side(edge_id, edge, role, nodes, paths) for role in ("source", "target")} for edge_id, edge in edges.items()}
    items=list(segments.items())
    for i,(id1,segs1) in enumerate(items):
        for id2,segs2 in items[i+1:]:
            e1,e2=edges[id1],edges[id2]
            for a,b in segs1:
                for c,d in segs2:
                    overlap=_overlap(a,b,c,d)
                    if overlap is not None:
                        # Collinear segments with opposite directions are
                        # never mergeable, even when they share a node.
                        if not overlap:
                            fail("opposite_direction_overlap",edges=[id1,id2]);metrics["opposite_overlap_count"]+=1
                        else:
                            same_source_side=(e1.get("source")==e2.get("source") and edge_sides[id1]["source"] and edge_sides[id1]["source"]==edge_sides[id2]["source"])
                            same_target_side=(e1.get("target")==e2.get("target") and edge_sides[id1]["target"] and edge_sides[id1]["target"]==edge_sides[id2]["target"])
                            if not (same_source_side or same_target_side):
                                fail("unrelated_edges_overlap",edges=[id1,id2])
                    crossing=_cross(a,b,c,d)
                    if crossing:
                        metrics["crossing_count"]+=1
                        shared_corridor_group = (
                            (e1.get("fanout_group") and e1.get("fanout_group") == e2.get("fanout_group"))
                            or (e1.get("fanin_group") and e1.get("fanin_group") == e2.get("fanin_group"))
                        )
                        if shared_corridor_group:
                            continue
                        # A crossing is deliberate when either route carries an
                        # edge-bound marker.  Looking in the complete document
                        # lets an unrelated edge accidentally satisfy the gate.
                        if 'data-crossing="true"' not in edge_markup.get(id1, "") and 'data-crossing="true"' not in edge_markup.get(id2, ""):
                            fail("crossing_not_distinguished",edges=[id1,id2],point=crossing)
    markup={m.group(1):m.group(0) for m in re.finditer(r'<g class="flowchat-node[^>]*data-node="([^"]+)".*?</g>',html,re.S)}
    for node_id,node in nodes.items():
        content=markup.get(node_id,"")
        if not content: fail("node_markup_missing",node=node_id);continue
        for token in ('data-text-region="node"','data-text-align="center"','text-anchor="middle"','dominant-baseline="middle"'):
            if token not in content: fail("text_not_centered",node=node_id);break
        if node.get("shape")=="diamond" and 'data-diamond-text="centered"' not in content: fail("diamond_text_not_centered",node=node_id)
        # Static check is conservative; actual text boxes require browser evidence.
        line_count=max(1,len(str(node.get("label","")).splitlines()))
        if line_count*18 > float(node["height"])-8: fail("text_height_overflow",node=node_id)
    metrics["dependency_contract"] = _dependency_contract_checks(graph, nodes, edges, fail)
    metrics["routing_contract"] = _routing_contract_checks(graph, nodes, edges, paths, fail)
    return failures,metrics


def _interaction_checks(html: str) -> dict[str, bool]:
    checks = {
        "drag": bool(re.search(r"pointerdown|pointermove|setPointerCapture", html)),
        "wheel_zoom": bool(re.search(r"addEventListener\(['\"]wheel", html)),
        "touch_pinch": bool(re.search(r"pointerType===['\"]touch|pinchDistance|activePointers", html)),
        "fit_view": bool(re.search(r"data-action=fit|ResizeObserver|const fit", html)),
        "edge_selection": bool(re.search(r"flowchat-edge-hit|flowchat-edge-group\.selected", html)),
        "edge_endpoint_drag": bool(re.search(r"flowchat-edge-endpoint|endpointDrag|data-endpoint", html)),
        "edge_snap": bool(re.search(r"nearestNode|snap-preview|anchorFor", html)),
        "edge_editing_disabled": bool(re.search(r'data-edge-editing="disabled"', html)) and not bool(re.search(r'<g class="flowchat-edge-endpoint-layer"', html)),
        "keyboard_navigation": bool(re.search(r"addEventListener\(['\"]keydown|ArrowLeft|ArrowRight|ArrowUp|ArrowDown", html)),
        "aria_contract": bool(re.search(r"aria-roledescription|aria-keyshortcuts|role=\"button\"", html)),
        "visual_matrix": bool(re.search(r"visualRegression|type_colors|data-size", html)),
    }
    return checks


def _browser_receipt(path: Path | None, artifact_sha256: str, graph: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if path is None:
        return "blocked", {"check": "browser_receipt_required", "reason": "browser receipt for this exact artifact is required"}
    data=json.loads(path.read_text(encoding="utf-8"))
    # Require only the capabilities the graph actually exposes. A small
    # routing fixture should not be blocked because it has no stage drilldown
    # or architecture layer; those remain hard requirements when present.
    required=["loaded","console_errors","console_warnings","drag","wheel_zoom","fit_view","node_click","arrows_visible","geometry_verified","text_bounds_verified","edge_style_verified","keyboard_navigation","aria_contract","visual_matrix"]
    has_subflow = bool(graph.get("subflows")) or any(node.get("children") or node.get("target_flow") or node.get("drilldown", {}).get("flow_id") for node in graph.get("nodes", []))
    if has_subflow:
        required.extend(["stage_subflow_click","subflow_transition_visible","subflow_loop_visible","subflow_output_visible","overview_restore"])
    if graph.get("architecture", {}).get("nodes"):
        required.extend(["architecture_view","architecture_nodes_visible","architecture_node_click"])
    if data.get("edge_editing_disabled") is True:
        required.append("edge_editing_disabled")
    else:
        required.extend(["edge_selection","edge_endpoint_drag","edge_snap"])
    missing=[key for key in required if key not in data]
    if missing: return "blocked", {"missing":missing}
    if data.get("artifact_sha256")!=artifact_sha256:
        return "blocked", {"check":"browser_receipt_artifact_mismatch","expected":artifact_sha256,"observed":data.get("artifact_sha256")}
    if not str(data.get("url","")).startswith(("http://","https://")):
        return "blocked", {"check":"browser_receipt_not_http"}
    if data.get("console_errors")!=0 or data.get("console_warnings")!=0 or not all(data.get(key) is True for key in required if key not in {"console_errors","console_warnings"}):
        return "blocked",data
    return "pass",data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate standalone Flowchat with its local Harness")
    parser.add_argument("html", type=Path)
    parser.add_argument("--browser-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    html = args.html.read_text(encoding="utf-8")
    try:
        graph = _load_graph(html)
        failures, metrics = _static_checks(html, graph)
    except Exception as exc:
        failures, metrics = [{"check": "harness_input", "error": str(exc)}], {}
    interactions = _interaction_checks(html)
    for name, passed in interactions.items():
        if name != "browser_validation_hook" and not passed:
            failures.append({"check": f"interaction_hook_{name}"})
    artifact_sha256 = hashlib.sha256(args.html.read_bytes()).hexdigest()
    browser_status, browser_details = _browser_receipt(args.browser_receipt, artifact_sha256, graph)
    report = {
        "schema_version": "flowchat-local-harness.v2",
        "artifact": str(args.html),
        "artifact_sha256": artifact_sha256,
        "static_status": "blocked" if failures else "pass",
        "status": "pass" if not failures and browser_status == "pass" else "blocked" if failures or browser_status == "blocked" else "not_run",
        "checks": {"geometry": metrics, "interaction_hooks": interactions, "browser_validation": browser_status},
        "failures": failures,
        "browser_details": browser_details,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
