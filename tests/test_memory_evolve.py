import unittest


class MemoryEvolveSmokeTests(unittest.TestCase):
    def test_script_importable(self):
        from scripts.memory_evolve import evolve_once  # noqa: F401
        self.assertTrue(callable(evolve_once))


if __name__ == "__main__":
    unittest.main()
