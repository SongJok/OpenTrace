import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SqlJoinPlannerContractTests(unittest.TestCase):
    def test_sql_planner_supports_join_metadata(self):
        txt = (ROOT / "kernel/data_cognition/sql_planner.py").read_text(encoding="utf-8")
        self.assertIn('class PlannedSQL', txt)
        self.assertIn('join_path', txt)
        self.assertIn('infer JOIN paths', txt)

    def test_table_graph_exists(self):
        txt = (ROOT / "kernel/data_cognition/table_graph.py").read_text(encoding="utf-8")
        self.assertIn('class TableRelationshipGraph', txt)
        self.assertIn('find_join_path', txt)


if __name__ == "__main__":
    unittest.main()
