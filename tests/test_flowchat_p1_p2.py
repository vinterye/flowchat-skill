import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_flowchat as generator


class FlowchatP1P2ContractTest(unittest.TestCase):
    def test_advanced_control_and_execution_types_are_registered(self):
        required = {"fork", "join", "merge", "retry", "loop", "parallel_group", "human_review", "fallback"}
        self.assertTrue(required <= set(generator.NODE_TYPE_REGISTRY))
        self.assertTrue({"parallel", "handoff", "retry", "loop", "human_review"} <= set(generator.EDGE_TYPE_REGISTRY))
        self.assertIn("compact", generator.SIZE_PRESETS)

    def test_semantic_ports_are_honored_on_round_rect_nodes(self):
        node = {"id": "n", "type": "human_review", "x": 100, "y": 100, "width": 220, "height": 88}
        self.assertEqual(generator._snap_to_node_edge(node, [320, 144], [240, 144], "right"), [320.0, 144.0])
        self.assertEqual(generator._snap_to_node_edge(node, [210, 188], [210, 260], "bottom"), [210.0, 188.0])

    def test_keyboard_and_accessibility_contract_is_emitted(self):
        html = generator.render_html({
            "viewBox": [0, 0, 500, 300],
            "nodes": [
                {"id": "a", "type": "fork", "label": "Fork", "x": 30, "y": 100, "status": "active"},
                {"id": "b", "type": "human_review", "label": "人工审核", "x": 320, "y": 100, "status": "review"},
            ],
            "edges": [{"id": "e", "source": "a", "target": "b", "type": "handoff", "status": "pending", "route_points": [[162, 128], [320, 128]], "source_side": "right", "target_side": "left"}],
        }, dict(generator.DEFAULT_THEME), "P1/P2")
        self.assertIn('aria-roledescription="流程节点"', html)
        self.assertIn('aria-keyshortcuts="Enter Space"', html)
        self.assertIn('aria-roledescription="流程连线"', html)
        self.assertIn("moveEndpointByKey", html)

    def test_visual_matrix_preserves_type_fill_across_statuses(self):
        statuses = generator.TYPE_REGISTRY["visualRegression"]["statuses"]
        for kind, spec in generator.NODE_TYPE_REGISTRY.items():
            for status in statuses:
                html = generator.render_html({
                    "viewBox": [0, 0, 500, 300],
                    "nodes": [
                        {"id": "n", "type": kind, "label": kind, "x": 30, "y": 100, "status": status},
                        {"id": "t", "type": "process", "label": "target", "x": 320, "y": 100, "status": "pending"},
                    ],
                    "edges": [],
                }, dict(generator.DEFAULT_THEME), "matrix")
                self.assertIn(f'data-type="{kind}"', html)
                self.assertIn(f'data-raw-status="{status}"', html)
                self.assertIn(f'data-shape="{spec["shape"]}"', html)

    def test_high_contrast_theme_overrides_type_color_without_changing_status(self):
        theme = json.loads((ROOT / "data" / "theme-high-contrast.json").read_text())
        graph = {"viewBox": [0, 0, 500, 300], "nodes": [{"id": "a", "type": "agent", "label": "Agent", "x": 30, "y": 100, "status": "blocked"}, {"id": "b", "type": "process", "label": "Next", "x": 320, "y": 100, "status": "pending"}], "edges": [{"id": "e", "source": "a", "target": "b", "type": "flow", "route_points": [[186, 144], [320, 144]], "source_side": "right", "target_side": "left"}]}
        html = generator.render_html(graph, theme, "contrast")
        self.assertIn('fill="#dbeafe"', html)
        self.assertIn('status-blocked', html)


if __name__ == "__main__":
    unittest.main()
