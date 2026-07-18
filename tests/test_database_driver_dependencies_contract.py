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
