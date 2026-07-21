"""对外声明支持的数据源必须具备可安装的运行时驱动。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_clickhouse_async_dsn_has_dialect_and_driver_dependencies():
    router = (ROOT / "execution/data/db_router.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "clickhouse+asynch" in router
    for dependency in ("clickhouse-sqlalchemy", "asynch"):
        assert dependency in requirements
        assert dependency in pyproject


def test_doris_reuses_the_installed_async_mysql_driver():
    router = (ROOT / "execution/data/db_router.py").read_text(encoding="utf-8")
    assert 'if t in {"doris"}' in router
    assert "mysql+asyncmy" in router


def test_doris_does_not_receive_mysql_transaction_setup():
    from execution.data.sql_executor import SQLExecutor

    executor = SQLExecutor(timeout_ms=1000)
    dsn = "mysql+asyncmy://user:password@doris.example:9030/warehouse"

    assert executor._read_only_setup_statements(dsn, source_type="doris") == ()
    assert executor._read_only_setup_statements(dsn, source_type="mysql") == (
        "SET TRANSACTION READ ONLY",
        "SET SESSION MAX_EXECUTION_TIME = 1000",
    )
