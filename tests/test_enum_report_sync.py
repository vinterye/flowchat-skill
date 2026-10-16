import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "flowchat/data/screenshot-routing-test-graph.json"
REPORTS = [
    ROOT / "generated/flowchat-full-reports/flowchat-枚举全谱.html",
    ROOT / "generated/flowchat-枚举全谱.html",
]


class EnumReportSyncTests(unittest.TestCase):
    def test_causal_snapshot_contains_real_graph_objects(self):
        graph = json.loads(GRAPH.read_text(encoding="utf-8"))
        for report in REPORTS:
            content = report.read_text(encoding="utf-8")
            self.assertIn("当前因果拓扑同步", content)
            self.assertIn("真实生成器 SVG", content)
            for node in graph["nodes"]:
                self.assertIn(str(node["id"]), content)
                for ref in node.get("input_refs", []) + node.get("output_refs", []) + node.get("context_refs", []):
                    self.assertIn(str(ref), content)
            for edge in graph["edges"]:
                self.assertIn(str(edge["id"]), content)
                self.assertIn(str(edge["dependency"]["kind"]), content)


if __name__ == "__main__":
    unittest.main()
