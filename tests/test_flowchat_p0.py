import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_flowchat as generator


class FlowchatP0ContractTest(unittest.TestCase):
    def test_registry_contains_five_families_and_reference_types(self):
        types = generator.NODE_TYPE_REGISTRY
        families = {spec["family"] for spec in types.values()}
        self.assertTrue({"flow_control", "execution", "data_artifact", "governance", "structure"} <= families)
        self.assertIn("reference", types)
        self.assertIn("exception", generator.EDGE_TYPE_REGISTRY)

    def test_normalize_preserves_raw_status_and_adds_visual_status(self):
        nodes, edges, _ = generator._normalize({
            "nodes": [{"id": "candidate", "type": "agent", "status": "candidate"}],
            "edges": [{"id": "e", "source": "candidate", "target": "candidate", "type": "callback", "status": "not_run"}],
        })
        self.assertEqual(nodes[0]["raw_status"], "candidate")
        self.assertEqual(nodes[0]["visual_status"], "candidate")
        self.assertEqual(edges[0]["edge_family"], "callback")
        self.assertEqual(edges[0]["raw_status"], "not_run")

    def test_shape_factory_keeps_edge_editing_hidden_by_default(self):
        html = generator.render_html({
            "viewBox": [0, 0, 500, 300],
            "nodes": [
                {"id": "start", "type": "start", "label": "开始", "x": 30, "y": 80, "width": 120, "height": 56, "status": "completed"},
                {"id": "ref", "type": "reference", "label": "子流程", "x": 320, "y": 80, "width": 120, "height": 56, "status": "unknown", "target_flow": "child"},
            ],
            "edges": [{"id": "e", "source": "start", "target": "ref", "type": "flow", "status": "active", "route_points": [[150, 108], [320, 108]]}],
            "subflows": {"child": {"title": "子流程", "entry": "进入", "next": "退出", "loop": "返工", "nodes": [], "edges": []}},
        }, dict(generator.DEFAULT_THEME), "P0")
        self.assertIn("data-target-flow=\"child\"", html)
        self.assertIn("flowchat-edge-hit", html)
        self.assertIn('data-edge-editing="disabled"', html)
        self.assertNotIn('<g class="flowchat-edge-endpoint-layer"', html)
        self.assertIn("data-raw-status=\"unknown\"", html)
        self.assertIn('rx="28.0"', html)
        json.loads(json.dumps(generator.TYPE_REGISTRY))

    def test_legacy_endpoint_layer_requires_explicit_opt_in(self):
        graph = {
            "viewBox": [0, 0, 500, 300],
            "edge_editing": True,
            "nodes": [
                {"id": "a", "type": "process", "label": "A", "x": 30, "y": 80, "width": 120, "height": 56},
                {"id": "b", "type": "process", "label": "B", "x": 320, "y": 80, "width": 120, "height": 56},
            ],
            "edges": [{"id": "e", "source": "a", "target": "b", "type": "flow", "route_points": [[150, 108], [320, 108]]}],
        }
        html = generator.render_html(graph, dict(generator.DEFAULT_THEME), "legacy")
        self.assertIn('data-edge-editing="enabled"', html)
        self.assertIn("flowchat-edge-endpoint-layer", html)


if __name__ == "__main__":
    unittest.main()
