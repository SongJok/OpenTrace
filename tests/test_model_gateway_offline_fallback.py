import unittest


class ModelGatewayOfflineFallbackTests(unittest.TestCase):
    def test_complete_has_offline_fallback(self):
        with open('model/model_gateway/gateway.py', 'r', encoding='utf-8') as f:
            code = f.read()

        self.assertIn('_offline_fallback_response', code)
        self.assertIn('All LLM candidates failed; using offline fallback', code)
        self.assertIn('Circuit breaker open; using offline fallback', code)

    def test_stream_uses_fallback_text_when_open(self):
        with open('model/model_gateway/gateway.py', 'r', encoding='utf-8') as f:
            code = f.read()

        self.assertIn('yield fallback[i : i + step]', code)
        self.assertIn('LLM stream failed; using offline fallback', code)


if __name__ == '__main__':
    unittest.main()
