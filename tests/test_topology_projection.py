import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.topology_projection import FORBIDDEN_UI_IDS, build_projection


class TopologyProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projection = build_projection()

    def test_required_shape(self):
        self.assertEqual(
            set(self.projection),
            {"schema", "nodes", "edges", "groups", "stageBindings", "runtimeOverlay", "conflicts", "sources"},
        )
        self.assertEqual(self.projection["schema"], "topology-projection/v1")

    def test_no_ui_only_business_nodes(self):
        node_ids = {node["id"] for node in self.projection["nodes"]}
        self.assertTrue(FORBIDDEN_UI_IDS.isdisjoint(node_ids))

    def test_status_and_runtime_are_separate(self):
        self.assertTrue(self.projection["runtimeOverlay"]["projects"])
        runtime_nodes = [node for node in self.projection["nodes"] if node["kind"] == "runtime_task_node"]
        self.assertTrue(runtime_nodes)
        self.assertTrue(all(node["id"].startswith("runtime:") for node in runtime_nodes))

    def test_reverse_relationships_are_canonicalized(self):
        reverse = [edge for edge in self.projection["edges"] if len(edge.get("directions", [])) > 1]
        self.assertTrue(reverse)
        for edge in reverse:
            self.assertEqual(edge["canonical_key"], edge["id"])

    def test_locations_are_preserved(self):
        located = [node for node in self.projection["nodes"] if "location" in node]
        self.assertTrue(located)
        self.assertTrue(all(isinstance(node["location"], dict) for node in located))

    def test_json_serializable(self):
        json.dumps(self.projection, ensure_ascii=False)

    def test_edges_and_bindings_reference_fact_nodes(self):
        node_ids = {node["id"] for node in self.projection["nodes"]}
        edge_endpoints = {endpoint for edge in self.projection["edges"] for endpoint in (edge["from"], edge["to"])}
        binding_targets = {target for binding in self.projection["stageBindings"] for target in binding["target_ids"]}
        self.assertTrue(edge_endpoints <= node_ids)
        self.assertTrue(binding_targets <= node_ids)

    def test_raw_status_values_survive(self):
        statuses = {node["status"] for node in self.projection["nodes"]}
        self.assertIn("Unknown", statuses)
        self.assertIn("not_run", statuses)
        self.assertIn("candidate_projection", statuses)


if __name__ == "__main__":
    unittest.main()
