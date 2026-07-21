import unittest

from connectors.builtin.github_connector import GitHubConnector
from connectors.registry import ConnectorRegistry
from connectors.sdk.protocol import CredentialRef


class ConnectorSDKTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_register_and_get(self):
        reg = ConnectorRegistry()
        gh = GitHubConnector(client_id="abc")
        reg.register("github", gh)
        got = reg.get("github")
        self.assertIs(got, gh)
        self.assertEqual(reg.list()[0]["name"], "github")

    async def test_github_authorize_and_exchange(self):
        gh = GitHubConnector(client_id="cid")
        url = await gh.authorize_url(user_id="u1", redirect_uri="http://localhost/cb", state="s1")
        self.assertIn("github.com/login/oauth/authorize", url)
        self.assertIn("client_id=cid", url)

        cred = await gh.exchange_code(user_id="u1", code="code123", redirect_uri="http://localhost/cb")
        self.assertIsInstance(cred, CredentialRef)
        self.assertEqual(cred.provider, "github")
        self.assertTrue(cred.access_token.startswith("gho_mock_"))

    async def test_github_list_and_sync(self):
        gh = GitHubConnector()
        cred = CredentialRef(provider="github", account_id="u1", access_token="t")
        items = await gh.list_resources(cred)
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0].metadata.get("provider"), "github")

        rs = await gh.sync(cred)
        self.assertFalse(rs.has_more)
        self.assertGreaterEqual(len(rs.items), 1)


if __name__ == "__main__":
    unittest.main()
