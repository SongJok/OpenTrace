import os
import unittest

from model.dashscope_utils import dashscope_proxy_allowlist, resolve_dashscope_api_key


class DashScopeUtilsTests(unittest.TestCase):
    def test_resolve_dashscope_api_key_prefers_first_non_empty(self):
        self.assertEqual(resolve_dashscope_api_key(None, "", "  ", "sk-test"), "sk-test")

    def test_dashscope_proxy_allowlist_adds_hosts_and_restores_env(self):
        original_no_proxy = os.environ.get("NO_PROXY")
        original_http_proxy = os.environ.get("HTTP_PROXY")
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"
        os.environ["HTTP_PROXY"] = "http://proxy.local:8080"

        try:
            with dashscope_proxy_allowlist():
                no_proxy = os.environ.get("NO_PROXY", "")
                self.assertIn("dashscope.aliyuncs.com", no_proxy)
                self.assertIn(".aliyuncs.com", no_proxy)
        finally:
            if original_no_proxy is None:
                os.environ.pop("NO_PROXY", None)
            else:
                os.environ["NO_PROXY"] = original_no_proxy
            if original_http_proxy is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = original_http_proxy

        self.assertEqual(os.environ.get("HTTP_PROXY"), original_http_proxy)


if __name__ == "__main__":
    unittest.main()
