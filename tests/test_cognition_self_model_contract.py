import unittest

from kernel.cognition.self_model import SelfModel
from kernel.cognition.types import CapabilityLevel, TaskDomain


class SelfModelContractTests(unittest.TestCase):
    def test_general_qa_is_available(self):
        sm = SelfModel()
        assessment = sm.introspect("你好", TaskDomain.GENERAL_QA)
        self.assertIn(assessment.level, [CapabilityLevel.FULL, CapabilityLevel.PARTIAL, CapabilityLevel.UNAVAILABLE])
        self.assertIsInstance(assessment.reasoning, str)

    def test_identity_prompt_contains_kernel_identity(self):
        sm = SelfModel()
        p = sm.get_identity_prompt()
        self.assertIn("OpenTrace Cognitive Kernel", p)
        self.assertIn("能力边界", p)


if __name__ == "__main__":
    unittest.main()
