import unittest
from unittest.mock import patch

from execution.data.database_hosts import (
    is_allowed_database_host,
    is_docker_internal_database_host,
    resolve_database_host_for_runtime,
)
from execution.data.db_router import DBConnectionInfo, DBRouter


class DatabaseHostRulesTests(unittest.TestCase):
    def test_allows_resolvable_external_domain(self):
        self.assertTrue(is_allowed_database_host("analytics.example.com"))

    def test_rejects_docker_internal_service_name(self):
        self.assertTrue(is_docker_internal_database_host("mysql"))
        self.assertFalse(is_allowed_database_host("mysql"))

    def test_loopback_is_mapped_to_container_host_alias(self):
        self.assertEqual(
            resolve_database_host_for_runtime(
                "127.0.0.1",
                containerized=True,
                docker_host_alias="host.docker.internal",
            ),
            "host.docker.internal",
        )

    def test_db_router_uses_runtime_host_resolution(self):
        with patch(
            "execution.data.db_router.resolve_database_host_for_runtime",
            return_value="host.docker.internal",
        ) as resolve_host:
            dsn = DBRouter().build_dsn(
                DBConnectionInfo(
                    source_type="mysql",
                    host="127.0.0.1",
                    port=3306,
                    database="test_db",
                    username="root",
                    password="950514",
                )
            )

        resolve_host.assert_called_once_with("127.0.0.1")
        self.assertEqual(
            dsn,
            "mysql+asyncmy://root:950514@host.docker.internal:3306/test_db",
        )

    def test_docker_compose_exposes_host_gateway_alias(self):
        with open("docker-compose.yml", "r", encoding="utf-8") as f:
            compose = f.read()

        self.assertIn("host.docker.internal:host-gateway", compose)


if __name__ == "__main__":
    unittest.main()
