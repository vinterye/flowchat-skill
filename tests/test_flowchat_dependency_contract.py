"""Regression tests for causal edges versus shared context references."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
import flowchat_local_harness as harness  # noqa: E402


class DependencyContractTest(unittest.TestCase):
    def setUp(self):
        self.nodes = {
            "a": {"id": "a", "output_refs": ["result:a"], "input_refs": [], "context_refs": ["run:1"]},
            "b": {"id": "b", "output_refs": [], "input_refs": ["result:a"], "context_refs": ["run:1"]},
        }
        self.edges = {
            "e": {
                "id": "e", "source": "a", "target": "b", "type": "handoff",
                "dependency": {"kind": "input", "output_ref": "result:a", "input_ref": "result:a"},
            }
        }

    def check(self, graph=None, edges=None):
        failures = []
        metrics = harness._dependency_contract_checks(
            graph or {"dependency_contract": "causal-v1"},
            self.nodes,
            edges or self.edges,
            lambda check, **extra: failures.append({"check": check, **extra}),
        )
        return failures, metrics

    def test_real_output_to_input_dependency_passes(self):
        failures, metrics = self.check()
        self.assertEqual(failures, [])
        self.assertEqual(metrics["dependency_edges_checked"], 1)
        self.assertEqual(metrics["context_refs_checked"], 2)

    def test_missing_dependency_is_rejected(self):
        failures, _ = self.check(edges={"e": {"id": "e", "source": "a", "target": "b"}})
        self.assertIn("edge_dependency_missing", {item["check"] for item in failures})

    def test_shared_context_edge_is_rejected(self):
        edge = dict(self.edges["e"])
        edge["type"] = "shared-context"
        failures, _ = self.check(edges={"e": edge})
        self.assertIn("shared_context_must_use_context_refs", {item["check"] for item in failures})


if __name__ == "__main__":
    unittest.main()
