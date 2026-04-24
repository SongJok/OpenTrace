import unittest

from kernel.epistemology.evidence import (
    AnnotatedContent,
    AnnotatedResponse,
    EvidenceAnnotation,
    EvidenceLevel,
    SourceType,
)
from kernel.epistemology.validator import OutputValidator


class EpistemologyValidatorContractTests(unittest.TestCase):
    def test_fact_without_citation_warns(self):
        v = OutputValidator()
        resp = AnnotatedResponse(
            fragments=[
                AnnotatedContent(
                    text="昨日销售额为 100 元",
                    annotation=EvidenceAnnotation(
                        level=EvidenceLevel.FACT,
                        source_type=SourceType.DATABASE,
                        citations=[],
                        confidence=0.9,
                    ),
                )
            ]
        )
        ok, issues, _ = v.validate_response(resp)
        self.assertTrue(ok)
        self.assertTrue(any("事实性断言缺少引用来源" in i for i in issues))

    def test_speculation_adds_disclaimer(self):
        v = OutputValidator()
        resp = AnnotatedResponse(
            fragments=[
                AnnotatedContent(
                    text="这个策略会提高转化率",
                    annotation=EvidenceAnnotation(
                        level=EvidenceLevel.SPECULATION,
                        source_type=SourceType.MODEL_INFERENCE,
                        citations=[],
                        confidence=0.5,
                    ),
                )
            ]
        )
        ok, _, fixed = v.validate_response(resp)
        self.assertTrue(ok)
        self.assertIn("推测性分析", fixed.fragments[0].text)


if __name__ == "__main__":
    unittest.main()
