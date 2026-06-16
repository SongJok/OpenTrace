# OpenTrace — 发布与合并门禁

> 与 `ARCHITECTURE_REQUIREMENTS_MATRIX.md`、`scripts/run_vnext_final_tests.sh` 联动。

## PR / 合并必需（无需 Docker LLM）

在已安装依赖的前提下：

```bash
pip install -e ".[dev]"
bash scripts/weekly_release_checklist.sh
# 或分项：
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
python -m pytest -q tests/test_architecture_requirements_alignment.py
bash scripts/check_import_boundaries.sh
bash scripts/check_gateway_silent_failures.sh
bash scripts/check_kernel_silent_failures.sh
PYTHONPATH=. python scripts/sync_env_example_to_docs.py
```

CI 工作流：`vnext-contract.yml`（仅契约）、`ci-fast.yml`（Docker + E2E + 契约）。

## 发布前（需运行中的 API）

```bash
export BASE_URL=http://127.0.0.1:14100
bash scripts/preflight_release.sh --quick   # 健康 + stage9
bash scripts/preflight_release.sh --full    # verify_all + stage6–9
```

默认 API 端口为 **14100**（与 `APP_PORT`、`docker-compose`、`VITE_API_URL` 一致）。

## 可选（Nightly / 大版本）

```bash
python -m pytest -q
bash scripts/verify_all_docker.sh
```

## 禁止项

- 提交 `.env`、真实 API Key、SMTP 密码。
- 在 vNext 主路径模块中新增 `orchestrator_v4` 导入（见 `tests/test_kernel_import_boundaries.py`）。
- 扩展 `kernel/orchestrator_v4.py`（仅 re-export `legacy.v4`）。

## 文档

| 文档 | 用途 |
|------|------|
| `docs/CONFIG_TRUTH.md` | 端口与 URL 真相表 |
| `docs/ENV_PROFILES.md` | dev / staging / production 推荐开关 |
| `docs/FEATURE_FLAG_REGISTRY.md` | 内核开关注册表 |
| `docs/CAPABILITY_MATURITY.md` | 模块成熟度 |
| `docs/adr/*.md` | 架构决策记录 |
| `docs/runbooks/evidence-gate-failure.md` | 证据门禁排障 |

## 架构债跟踪（不改代码）

```bash
bash scripts/report_v4_imports.sh
```