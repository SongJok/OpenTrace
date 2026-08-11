import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.api_gateway.routers.databases import _require_database_admin
from infra.errors import AppException, ErrorCodes

ROOT = Path(__file__).resolve().parents[1]


class DatabasesApiContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_databases_router_has_required_routes(self):
        txt = self._read("gateway/api_gateway/routers/databases.py")
        self.assertIn('@router.post("/databases")', txt)
        self.assertIn('@router.get("/databases")', txt)
        self.assertIn('@router.get("/databases/{database_id}")', txt)
        self.assertIn('@router.delete("/databases/{database_id}")', txt)
        self.assertIn('@router.post("/databases/{database_id}/test-connection")', txt)
        self.assertIn('@router.post("/databases/{database_id}/sync-schema")', txt)
        self.assertIn('@router.post("/databases/{database_id}/query")', txt)
        self.assertIn('return database or "*"', txt)
        self.assertIn("database_scope", txt)

    def test_databases_router_included_in_main(self):
        txt = self._read("gateway/api_gateway/main.py")
        self.assertIn("databases.router", txt)

    def test_only_enterprise_admin_can_create_database(self):
        with pytest.raises(AppException) as exc_info:
            _require_database_admin(SimpleNamespace(role="user", is_superuser=False))

        self.assertEqual(exc_info.value.code, ErrorCodes.PERMISSION_DENIED.code)
        self.assertEqual(exc_info.value.http_status, 403)
        _require_database_admin(SimpleNamespace(role="admin", is_superuser=False))
        _require_database_admin(SimpleNamespace(role="user", is_superuser=True))

        txt = self._read("gateway/api_gateway/routers/databases.py")
        create_body = txt.split("async def create_database(", 1)[1].split(
            '@router.patch("/databases/{database_id}")', 1
        )[0]
        self.assertIn("_require_database_admin(current_user)", create_body)

    def test_models_contain_data_tables(self):
        txt = self._read("infra/storage/models.py")
        self.assertIn("class DataSource(Base)", txt)
        self.assertIn('__tablename__ = "data_sources"', txt)
        self.assertIn("class DataSourceSchema(Base)", txt)
        self.assertIn('__tablename__ = "data_source_schemas"', txt)
        self.assertIn("class DataQueryLog(Base)", txt)
        self.assertIn('__tablename__ = "data_query_logs"', txt)


if __name__ == "__main__":
    unittest.main()
