"""Regression tests for the routing fixes.

Each test below corresponds to a defect that was reproduced against the real
generator before the fix: two of them crashed the renderer outright, the rest
produced geometrically wrong but silently accepted output.
"""
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_flowchat as generator  # noqa: E402


def node(node_id, cx, cy, width=120.0, height=88.0, **extra):
    payload = {
        "id": node_id, "label": node_id, "type": "process",
        "x": cx - width / 2, "y": cy - height / 2,
        "width": width, "height": height,
    }
    payload.update(extra)
    return payload


def edge(edge_id, source, target, **extra):
    payload = {"id": edge_id, "source": source, "target": target, "type": "main"}
    payload.update(extra)
    return payload


def points_of(edge_obj, nodes_by_id):
    markup = generator._edge_svg(edge_obj, nodes_by_id, dict(generator.DEFAULT_THEME))
    match = re.search(r'data-points="([^"]+)"', markup)
    assert match, "edge markup did not carry data-points"
    import json
    return json.loads(match.group(1).replace("&quot;", '"'))


def assert_orthogonal(case, points):
    for index, (first, second) in enumerate(zip(points, points[1:])):
        case.assertTrue(
            abs(first[0] - second[0]) <= 0.01 or abs(first[1] - second[1]) <= 0.01,
            f"segment {index} is diagonal: {first} -> {second}",
        )


class CrashRegressionTest(unittest.TestCase):
    """Both of these raised ValueError before the fix and produced no HTML."""

    def test_same_row_link_to_diamond_no_longer_crashes(self):
        graph = {
            "viewBox": [0, 0, 1600, 900],
            "nodes": [node("a", 220, 300, type="process"), node("b", 700, 300, type="decision")],
            "edges": [edge("e", "a", "b")],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {item["id"]: item for item in nodes}
        points = points_of(edges[0], by_id)
        assert_orthogonal(self, points)

    def test_four_edges_per_side_no_longer_crashes(self):
        nodes = [node("hub", 660, 444)]
        edges = []
        for index in range(1, 5):
            nodes.append(node(f"u{index}", 160 + (index - 1) * 200, 124))
            nodes.append(node(f"b{index}", 160 + (index - 1) * 200, 804))
            edges.append(edge(f"in{index}", f"u{index}", "hub", target_side="left"))
            edges.append(edge(f"out{index}", "hub", f"b{index}", source_side="left"))
        normalized, normalized_edges, _ = generator._normalize(
            {"viewBox": [0, 0, 1400, 900], "nodes": nodes, "edges": edges})
        by_id = {item["id"]: item for item in normalized}
        for item in normalized_edges:
            assert_orthogonal(self, points_of(item, by_id))


class SideEntryThresholdTest(unittest.TestCase):
    """Vertical relations enter a vertical side only when the offset allows it."""

    def _sides(self, dx, dy, target_width=120.0):
        graph = {
            "viewBox": [0, 0, 1600, 1200],
            "nodes": [node("s", 160, 144), node("t", 160 + dx, 144 + dy, width=target_width)],
            "edges": [edge("e", "s", "t")],
        }
        nodes, edges, _ = generator._normalize(graph)
        return generator._edge_port(edges[0], "source"), generator._edge_port(edges[0], "target")

    def test_narrow_offset_enters_the_top_midpoint(self):
        self.assertEqual(self._sides(60, 420), ("bottom", "top"))

    def test_offset_at_threshold_enters_the_side(self):
        # 120/2 + 75 = 135
        self.assertEqual(self._sides(135, 420), ("bottom", "left"))

    def test_wide_offset_enters_the_side(self):
        self.assertEqual(self._sides(300, 420), ("bottom", "left"))

    def test_threshold_scales_with_target_width(self):
        # 200/2 + 75 = 175
        self.assertEqual(self._sides(174, 420, target_width=200), ("bottom", "top"))
        self.assertEqual(self._sides(175, 420, target_width=200), ("bottom", "left"))

    def test_mirrored_offset_enters_the_opposite_side(self):
        self.assertEqual(self._sides(-300, 420), ("bottom", "right"))


class CentredBendTest(unittest.TestCase):
    """A corner between two nodes belongs in the middle of the gap."""

    def test_auto_route_bend_sits_on_the_midpoint(self):
        graph = {
            "viewBox": [0, 0, 1600, 1200],
            "nodes": [node("s", 160, 144), node("t", 220, 564)],
            "edges": [edge("e", "s", "t")],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {item["id"]: item for item in nodes}
        points = points_of(edges[0], by_id)
        bends = [p for index, p in enumerate(points) if 0 < index < len(points) - 1]
        self.assertTrue(bends, "expected at least one bend")
        midpoint = (188.0 + 520.0) / 2
        for bend in bends:
            self.assertAlmostEqual(bend[1], midpoint, delta=1.0,
                                   msg=f"bend {bend} is not on the midpoint {midpoint}")

    def test_corridor_sits_in_the_middle_of_the_gap(self):
        graph = {
            "layout": {"mode": "centered-flow"},
            "viewBox": [0, 0, 1200, 900],
            "nodes": [node("src", 160, 144), node("t1", 160, 564), node("t2", 460, 564)],
            "edges": [edge("e1", "src", "t1", fanout_group="g", source_side="bottom", target_side="top"),
                      edge("e2", "src", "t2", fanout_group="g", source_side="bottom", target_side="top")],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {item["id"]: item for item in nodes}
        routes = generator._compute_fanout_routes(edges, by_id)
        self.assertEqual(set(routes), {"e1", "e2"})
        corridor_y = routes["e1"][1][1]
        self.assertEqual(corridor_y, routes["e2"][1][1])
        expected = (by_id["src"]["y"] + by_id["src"]["height"] + by_id["t1"]["y"]) / 2
        self.assertAlmostEqual(corridor_y, expected, delta=1.0)


class FanoutOrientationTest(unittest.TestCase):
    """All eight cardinal directions must behave like the two that worked."""

    CASES = {
        "down":   ((760, 744), [(660, 1244), (960, 1244), (1260, 1244)]),
        "up":     ((760, 1144), [(660, 644), (960, 644), (1260, 644)]),
        "right":  ((560, 344), [(1460, 344), (1460, 644), (1460, 944)]),
        "left":   ((1560, 344), [(460, 344), (460, 644), (460, 944)]),
    }

    def _normalize_case(self, source_center, target_centers):
        nodes = [node("src", *source_center)]
        edges = []
        for index, center in enumerate(target_centers, 1):
            nodes.append(node(f"t{index}", *center))
            edges.append(edge(f"e{index}", "src", f"t{index}"))
        normalized, normalized_edges, _ = generator._normalize(
            {"layout": {"mode": "centered-flow"}, "viewBox": [0, 0, 2200, 1800],
             "nodes": nodes, "edges": edges})
        return {item["id"]: item for item in normalized}, normalized_edges

    def test_every_direction_uses_one_orientation(self):
        for name, (source_center, targets) in self.CASES.items():
            by_id, edges = self._normalize_case(source_center, targets)
            pairs = {(generator._edge_port(e, "source"), generator._edge_port(e, "target")) for e in edges}
            self.assertEqual(len(pairs), 1, f"{name}: group split into {pairs}")

    def test_every_direction_centres_the_source(self):
        for name, (source_center, targets) in self.CASES.items():
            by_id, edges = self._normalize_case(source_center, targets)
            source = by_id["src"]
            source_side = generator._edge_port(edges[0], "source")
            if source_side in {"left", "right"}:
                got = source["y"] + source["height"] / 2
                want = sum(t[1] for t in targets) / len(targets)
            else:
                got = source["x"] + source["width"] / 2
                want = sum(t[0] for t in targets) / len(targets)
            self.assertAlmostEqual(got, want, delta=1.0, msg=f"{name}: source not centred")

    def test_every_direction_shares_one_trunk(self):
        for name, (source_center, targets) in self.CASES.items():
            by_id, edges = self._normalize_case(source_center, targets)
            routes = generator._compute_fanout_routes(edges, by_id)
            self.assertEqual(set(routes), {f"e{i}" for i in range(1, len(targets) + 1)},
                             f"{name}: no shared trunk")
            first_legs = {tuple(route[0]) for route in routes.values()}
            self.assertEqual(len(first_legs), 1, f"{name}: trunks diverge")

    def test_every_direction_renders(self):
        for name, (source_center, targets) in self.CASES.items():
            by_id, edges = self._normalize_case(source_center, targets)
            for item in edges:
                assert_orthogonal(self, points_of(item, by_id))


class FaninGroupTest(unittest.TestCase):
    """The side-entry threshold must not split a merge into separate corridors."""

    def test_merge_keeps_one_target_side(self):
        graph = {
            "viewBox": [0, 0, 900, 700],
            "nodes": [node("a", 150, 124), node("b", 570, 124), node("target", 360, 404)],
            "edges": [edge("at", "a", "target"), edge("bt", "b", "target")],
        }
        nodes, edges, _ = generator._normalize(graph)
        sides = {generator._edge_port(e, "target") for e in edges}
        self.assertEqual(len(sides), 1, f"merge split across target sides {sides}")

    def test_merge_shares_a_corridor(self):
        graph = {
            "viewBox": [0, 0, 900, 700],
            "nodes": [node("a", 150, 124), node("b", 570, 124), node("target", 360, 404)],
            "edges": [edge("at", "a", "target"), edge("bt", "b", "target")],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {item["id"]: item for item in nodes}
        routes = generator._compute_fanin_routes(edges, by_id)
        self.assertEqual(set(routes), {"at", "bt"})
        self.assertEqual(routes["at"][-1], routes["bt"][-1])

    def test_self_loop_is_not_pulled_into_the_group(self):
        graph = {
            "viewBox": [0, 0, 900, 900],
            "nodes": [node("self", 260, 244), node("other", 260, 504)],
            "edges": [edge("loop", "self", "self"), edge("e", "self", "other")],
        }
        nodes, edges, _ = generator._normalize(graph)
        loop = next(e for e in edges if e["id"] == "loop")
        straight = next(e for e in edges if e["id"] == "e")
        self.assertNotEqual(generator._edge_port(loop, "source"),
                            generator._edge_port(straight, "source"))


class ArrowRelaxationTest(unittest.TestCase):
    """Centring wins over arrow length, but the choice has to be declared."""

    def test_tight_corridor_is_marked_relaxed(self):
        graph = {
            "layout": {"mode": "centered-flow"},
            "viewBox": [0, 0, 1200, 900],
            "nodes": [node("src", 160, 144), node("t1", 160, 300), node("t2", 460, 300)],
            "edges": [edge("e1", "src", "t1", fanout_group="g", source_side="bottom", target_side="top"),
                      edge("e2", "src", "t2", fanout_group="g", source_side="bottom", target_side="top")],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {item["id"]: item for item in nodes}
        routes = generator._compute_fanout_routes(edges, by_id)
        self.assertTrue(routes, "expected a corridor route")
        for item in edges:
            route = routes[item["id"]]
            arrow = math.hypot(route[-1][0] - route[-2][0], route[-1][1] - route[-2][1])
            self.assertEqual(bool(item.get("arrow_relaxed")), arrow + 1e-5 < 75.0,
                             "arrow_relaxed flag does not match the real arrow length")


if __name__ == "__main__":
    unittest.main()
