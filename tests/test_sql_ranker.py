import unittest

from kernel.data_cognition.sql_ranker import SQLRanker
from kernel.data_cognition.types import CandidateSQL, SemanticContext


class TestSQLRanker(unittest.TestCase):
    def setUp(self):
        self.ranker = SQLRanker()

    def test_empty_candidates(self):
        result = self.ranker.rank([])
        self.assertEqual(result, [])

    def test_shorter_sql_ranks_higher(self):
        c1 = CandidateSQL(sql="SELECT COUNT(*) FROM users LIMIT 100")
        c2 = CandidateSQL(
            sql="SELECT COUNT(*) FROM users WHERE tier IN (SELECT tier FROM tiers WHERE level = 'TIAN_DI') AND created_at >= NOW() - INTERVAL '30 days' AND name LIKE '%test%' LIMIT 100"
        )
        result = self.ranker.rank([c1, c2])
        self.assertGreater(result[0].score, result[1].score)

    def test_semantic_match_bonus(self):
        ctx = SemanticContext(
            dimension_mappings={
                "等级": {"column": "tier", "table": "users", "conditions": ["tier = 'TIAN_DI'"]}
            },
            time_macros=[],
        )
        c1 = CandidateSQL(sql="SELECT COUNT(*) FROM users WHERE tier = 'TIAN_DI' LIMIT 100")
        c2 = CandidateSQL(sql="SELECT COUNT(*) FROM users LIMIT 100")
        result = self.ranker.rank([c1, c2], semantic_ctx=ctx)
        self.assertGreater(result[0].score, result[1].score)

    def test_select_star_penalty(self):
        c1 = CandidateSQL(sql="SELECT * FROM users WHERE name = 'test' AND email IS NOT NULL AND phone IS NOT NULL LIMIT 100")
        c2 = CandidateSQL(sql="SELECT COUNT(*) FROM users LIMIT 100")
        result = self.ranker.rank([c1, c2])
        # c1 has SELECT * penalty and more tokens; c2 should rank higher
        self.assertGreaterEqual(result[0].score, result[1].score)
        self.assertIn("COUNT", result[0].sql)

    def test_time_filter_bonus(self):
        ctx = SemanticContext(
            time_macros=[{"pattern": "最近一个月", "column": "created_at", "days": 30}],
        )
        c1 = CandidateSQL(sql="SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '30 days' LIMIT 100")
        c2 = CandidateSQL(sql="SELECT COUNT(*) FROM users LIMIT 100")
        result = self.ranker.rank([c1, c2], semantic_ctx=ctx)
        self.assertGreater(result[0].score, result[1].score)

    def test_returns_sorted_descending(self):
        candidates = [
            CandidateSQL(sql=f"SELECT {i} FROM t LIMIT 100")
            for i in range(5)
        ]
        result = self.ranker.rank(candidates)
        scores = [c.score for c in result]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
