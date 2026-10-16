import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_flowchat as generator


def fan_graph(target_xs):
    nodes = [{"id": "source", "type": "process", "label": "Source", "x": 40, "y": 20, "width": 120, "height": 88, "status": "active"}]
    edges = []
    for index, x in enumerate(target_xs, 1):
        target_id = f"target-{index}"
        nodes.append({"id": target_id, "type": "process", "label": target_id, "x": x, "y": 300, "width": 120, "height": 88, "status": "pending"})
        edges.append({"id": f"edge-{index}", "source": "source", "target": target_id, "type": "parallel", "status": "pending", "fanout_group": "fan-1", "source_side": "bottom", "target_side": "top"})
    return {"layout": {"mode": "centered-flow"}, "viewBox": [0, 0, 800, 500], "nodes": nodes, "edges": edges}


class FlowchatRoutingContractTest(unittest.TestCase):
    def test_centered_flow_aligns_one_to_one(self):
        nodes, edges, _ = generator._normalize(fan_graph([500]))
        source = nodes[0]
        target = nodes[1]
        self.assertAlmostEqual(source["x"] + source["width"] / 2, target["x"] + target["width"] / 2)

    def test_centered_flow_uses_two_target_midpoint(self):
        nodes, _, _ = generator._normalize(fan_graph([100, 500]))
        source, first, second = nodes
        midpoint = ((first["x"] + first["width"] / 2) + (second["x"] + second["width"] / 2)) / 2
        self.assertAlmostEqual(source["x"] + source["width"] / 2, midpoint)

    def test_centered_flow_uses_middle_target_for_three(self):
        nodes, _, _ = generator._normalize(fan_graph([100, 300, 500]))
        source, _, middle, _ = nodes
        self.assertAlmostEqual(source["x"] + source["width"] / 2, middle["x"] + middle["width"] / 2)

    def test_centered_flow_rebalances_multi_target_spacing(self):
        graph = fan_graph([100, 260, 620])
        nodes, _, _ = generator._normalize(graph)
        targets = [node for node in nodes if node["id"].startswith("target-")]
        centers = [node["x"] + node["width"] / 2 for node in targets]
        self.assertAlmostEqual(centers[1] - centers[0], centers[2] - centers[1])
        self.assertAlmostEqual(nodes[0]["x"] + nodes[0]["width"] / 2, centers[1])

    def test_fanout_routes_share_trunk_and_split_at_one_corridor(self):
        graph = fan_graph([100, 500])
        nodes, edges, _ = generator._normalize(graph)
        by_id = {node["id"]: node for node in nodes}
        routes = generator._compute_fanout_routes(edges, by_id)
        self.assertEqual(set(routes), {"edge-1", "edge-2"})
        self.assertEqual(routes["edge-1"][0], routes["edge-2"][0])
        self.assertEqual(routes["edge-1"][1][1], routes["edge-2"][1][1])
        self.assertNotEqual(routes["edge-1"][2][0], routes["edge-2"][2][0])
        html = generator.render_html(graph, dict(generator.DEFAULT_THEME), "fanout")
        self.assertEqual(html.count('data-edge="edge-1"'), 1)
        self.assertNotIn('<g class="flowchat-edge-endpoint-layer"', html)
        self.assertIn('data-edge="edge-2"', html)
        json.loads(json.dumps(graph))

    def test_horizontal_fanout_and_fanin_share_corridors(self):
        graph = {
            "layout": {"mode": "centered-flow"},
            "viewBox": [0, 0, 1000, 700],
            "nodes": [
                {"id": "fork", "type": "process", "label": "Fork", "x": 40, "y": 250, "width": 120, "height": 88},
                {"id": "a", "type": "process", "label": "A", "x": 420, "y": 120, "width": 120, "height": 88},
                {"id": "b", "type": "process", "label": "B", "x": 420, "y": 380, "width": 120, "height": 88},
                {"id": "join", "type": "process", "label": "Join", "x": 760, "y": 250, "width": 120, "height": 88},
            ],
            "edges": [
                {"id": "fa", "source": "fork", "target": "a", "type": "parallel", "fanout_group": "fork-group", "source_side": "right", "target_side": "left"},
                {"id": "fb", "source": "fork", "target": "b", "type": "parallel", "fanout_group": "fork-group", "source_side": "right", "target_side": "left"},
                {"id": "aj", "source": "a", "target": "join", "type": "parallel", "fanin_group": "join-group", "source_side": "right", "target_side": "left"},
                {"id": "bj", "source": "b", "target": "join", "type": "parallel", "fanin_group": "join-group", "source_side": "right", "target_side": "left"},
            ],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {node["id"]: node for node in nodes}
        fanout = generator._compute_fanout_routes(edges, by_id)
        fanin = generator._compute_fanin_routes(edges, by_id)
        self.assertEqual(fanout["fa"][0], fanout["fb"][0])
        self.assertEqual(fanout["fa"][2][0], fanout["fb"][2][0])
        self.assertEqual(fanin["aj"][-1], fanin["bj"][-1])
        self.assertEqual(fanin["aj"][-2], fanin["bj"][-2])

    def test_semantic_bottom_to_top_edge_auto_routes_without_route_points(self):
        graph = fan_graph([500])
        graph["edges"][0].pop("fanout_group")
        nodes, edges, _ = generator._normalize(graph)
        by_id = {node["id"]: node for node in nodes}
        markup = generator._edge_svg(edges[0], by_id, dict(generator.DEFAULT_THEME))
        points_match = __import__("re").search(r'data-points="([^\"]+)"', markup)
        self.assertIsNotNone(points_match)
        points = json.loads(points_match.group(1))
        self.assertGreaterEqual(len(points), 2)
        self.assertEqual(points[0][0], points[-1][0])
        self.assertEqual(points[0][1], by_id["source"]["y"] + by_id["source"]["height"])
        self.assertEqual(points[-1][1], by_id["target-1"]["y"])

    def test_diagonal_relation_leaves_horizontally_before_turning_up(self):
        graph = {
            "viewBox": [0, 0, 900, 700],
            "nodes": [
                {"id": "a", "type": "process", "label": "A", "x": 80, "y": 420, "width": 140, "height": 88},
                {"id": "b", "type": "process", "label": "B", "x": 500, "y": 120, "width": 140, "height": 88},
            ],
            "edges": [{"id": "ab", "source": "a", "target": "b", "type": "flow"}],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {node["id"]: node for node in nodes}
        self.assertEqual(edges[0]["source_side"], "right")
        self.assertEqual(edges[0]["target_side"], "left")
        markup = generator._edge_svg(edges[0], by_id, dict(generator.DEFAULT_THEME))
        points = json.loads(__import__("re").search(r'data-points="([^\"]+)"', markup).group(1))
        self.assertGreater(points[1][0], points[0][0])
        self.assertEqual(points[0][1], points[1][1])
        self.assertEqual(points[-2][1], points[-1][1])

    def test_many_to_one_edges_share_target_corridor(self):
        graph = {
            "viewBox": [0, 0, 900, 700],
            "nodes": [
                {"id": "a", "type": "process", "label": "A", "x": 80, "y": 80, "width": 140, "height": 88},
                {"id": "b", "type": "process", "label": "B", "x": 500, "y": 80, "width": 140, "height": 88},
                {"id": "target", "type": "process", "label": "Target", "x": 290, "y": 360, "width": 140, "height": 88},
            ],
            "edges": [
                {"id": "at", "source": "a", "target": "target", "type": "flow"},
                {"id": "bt", "source": "b", "target": "target", "type": "flow"},
            ],
        }
        nodes, edges, _ = generator._normalize(graph)
        by_id = {node["id"]: node for node in nodes}
        routes = generator._compute_fanin_routes(edges, by_id)
        self.assertEqual(set(routes), {"at", "bt"})
        self.assertEqual(routes["at"][3], routes["bt"][3])
        self.assertEqual(routes["at"][-1], routes["bt"][-1])

    def test_mixed_incoming_and_outgoing_edges_use_separate_lanes(self):
        graph = {
            "viewBox": [0, 0, 900, 500],
            "nodes": [
                {"id": "left", "type": "process", "label": "Left", "x": 40, "y": 180, "width": 140, "height": 88},
                {"id": "center", "type": "process", "label": "Center", "x": 360, "y": 180, "width": 140, "height": 88},
                {"id": "right", "type": "process", "label": "Right", "x": 680, "y": 180, "width": 140, "height": 88},
            ],
            "edges": [
                {"id": "in", "source": "left", "target": "center", "type": "flow"},
                {"id": "out", "source": "center", "target": "right", "type": "flow"},
            ],
        }
        _, edges, _ = generator._normalize(graph)
        ports = {edge["id"]: (edge.get("target_port") or edge.get("target_side"), edge.get("source_port") or edge.get("source_side")) for edge in edges}
        self.assertNotEqual(ports["in"][0], ports["out"][1])


if __name__ == "__main__":
    unittest.main()
