"""Visual hard-gates shared by the standalone Flowchat Harness.

The legacy CLI remains in ``flowchat_local_harness.py``. Keeping these checks
separate makes it possible to add visual contracts without growing the routing
checker into a second renderer.
"""
from __future__ import annotations

import re
from typing import Any, Callable


def viewport_checks(
    graph: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    paths: dict[str, list[list[float]]],
    fail: Callable[..., None],
    tolerance: float = 1.0,
) -> dict[str, int]:
    """Prove that factual nodes and rendered edge points fit the SVG viewBox."""
    raw_view_box = graph.get("viewBox", [0, 0, 1200, 620])
    if not isinstance(raw_view_box, (list, tuple)) or len(raw_view_box) != 4:
        fail("invalid_viewbox", value=raw_view_box)
        return {"viewport_bounds_checked": 0, "edge_points_bounds_checked": 0}
    left, top, width, height = (float(value) for value in raw_view_box)
    right, bottom = left + width, top + height
    checked_nodes = 0
    for node in nodes.values():
        x, y = float(node["x"]), float(node["y"])
        node_right, node_bottom = x + float(node["width"]), y + float(node["height"])
        checked_nodes += 1
        if x < left - tolerance or y < top - tolerance or node_right > right + tolerance or node_bottom > bottom + tolerance:
            fail("node_outside_viewport", node=str(node["id"]), node_bounds=[x, y, node_right, node_bottom], view_box=list(raw_view_box))
    checked_points = 0
    for edge_id, points in paths.items():
        for point in points:
            checked_points += 1
            if point[0] < left - tolerance or point[0] > right + tolerance or point[1] < top - tolerance or point[1] > bottom + tolerance:
                fail("edge_point_outside_viewport", edge=str(edge_id), point=point, view_box=list(raw_view_box))
    return {"viewport_bounds_checked": checked_nodes, "edge_points_bounds_checked": checked_points}


def edge_style_checks(
    html: str,
    edges: dict[str, dict[str, Any]],
    fail: Callable[..., None],
) -> dict[str, int]:
    """Check the stable distinction between main-flow and return/crossing edges."""
    checked = 0
    for edge_id, edge in edges.items():
        match = re.search(
            r'<g class="flowchat-edge-group[^>]*data-edge="' + re.escape(edge_id) + r'"[^>]*>.*?</g>',
            html,
            re.S,
        )
        if not match:
            continue
        markup = match.group(0)
        checked += 1
        status = str(edge.get("status", "pending"))
        kind = str(edge.get("kind", edge.get("type", "main")))
        crossing = edge.get("crossing") is True
        truth_overlay = bool(re.search(r'\btruth-(?:expected|candidate|callback|exception)\b', markup))
        if status in {"pending", "completed"} and not crossing and not truth_overlay:
            if "status-active" in markup or "status-return" in markup or "stroke-dasharray" in markup:
                fail("main_edge_not_solid", edge=edge_id, status=status)
        if status == "return" or kind == "return":
            if "status-return" not in markup and "kind-return" not in markup:
                fail("return_edge_style_missing", edge=edge_id)
    return {"edge_style_checked": checked}

