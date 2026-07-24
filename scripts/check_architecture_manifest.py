#!/usr/bin/env python3
"""校验在线运行时的路由、Worker、事件、模型、配置与文档单一真相。"""

from __future__ import annotations

import argparse
import ast
import importlib
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs" / "architecture" / "runtime_manifest.yaml"


def _load_symbol(reference: str) -> Any:
    module_name, symbol_name = reference.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name)


def _route_key(method: str, path: str) -> tuple[str, str]:
    return method.upper(), path


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def validate_manifest(manifest_path: Path = MANIFEST_PATH) -> list[str]:
    errors: list[str] = []
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("product", {}).get("maturity") not in {"Alpha", "Beta", "GA"}:
        errors.append("product.maturity 必须使用 Alpha/Beta/GA")

    runtime = manifest["online_runtime"]
    app = _load_symbol(runtime["api"]["application"])
    openapi_paths = app.openapi().get("paths", {})

    declared_routes = [runtime["api"]["command_route"], runtime["api"]["event_route"]]
    for spec in declared_routes:
        method = spec["method"].lower()
        if method not in openapi_paths.get(spec["path"], {}):
            errors.append(f"缺少在线路由: {spec['method']} {spec['path']}")

    for spec in runtime["api"]["retired_routes"]:
        method = spec["method"].lower()
        operation = openapi_paths.get(spec["path"], {}).get(method)
        if operation is None:
            errors.append(f"缺少退役路由墓碑: {spec['method']} {spec['path']}")
            continue
        responses = operation.get("responses", {})
        if str(spec["status_code"]) not in responses:
            errors.append(f"退役路由未返回 {spec['status_code']}: {spec['method']} {spec['path']}")

    worker = importlib.import_module(runtime["worker"]["execution_module"])
    for name in runtime["worker"]["required_callables"]:
        if not callable(getattr(worker, name, None)):
            errors.append(f"Worker 缺少可调用入口: {name}")
    _load_symbol(runtime["worker"]["process_entrypoint"])
    _load_symbol(runtime["worker"]["manager_loop"])

    models = importlib.import_module(runtime["persistence"]["models_module"])
    for name in runtime["persistence"]["required_models"]:
        if getattr(models, name, None) is None:
            errors.append(f"缺少 Responses 事实模型: {name}")

    event_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "gateway" / "api_gateway" / "routers" / "responses.py",
            *sorted((ROOT / "infra" / "responses").glob("*.py")),
        ]
    )
    for event_type in runtime["persistence"]["required_events"]:
        if event_type not in event_sources:
            errors.append(f"架构清单事件未在在线实现中找到: {event_type}")

    _load_symbol(runtime["model_gateway"]["entrypoint"])
    _load_symbol(runtime["model_gateway"]["gateway_class"])
    settings_class = _load_symbol(runtime["configuration"]["settings_class"])
    fields = settings_class.model_fields
    if "app_env" not in fields or "capability_profile" not in fields:
        errors.append("Settings 必须声明 app_env 与 capability_profile")
    else:
        app_env_values = set(fields["app_env"].annotation.__args__)
        expected_envs = set(runtime["configuration"]["environment_profiles"])
        if app_env_values != expected_envs:
            errors.append(f"环境 Profile 漂移: {sorted(app_env_values)} != {sorted(expected_envs)}")
        capability_values = set(fields["capability_profile"].annotation.__args__)
        expected_capabilities = set(runtime["configuration"]["capability_profiles"])
        if capability_values != expected_capabilities:
            errors.append(
                "能力 Profile 漂移: "
                f"{sorted(capability_values)} != {sorted(expected_capabilities)}"
            )

    api_imports = _imported_modules(ROOT / "gateway" / "api_gateway" / "routers" / "responses.py")
    forbidden_prefixes = (
        "infra.responses.worker",
        "kernel.agent_loop.runner",
        "model.model_gateway",
        "openai",
        "dashscope",
    )
    forbidden = sorted(module for module in api_imports if module.startswith(forbidden_prefixes))
    if forbidden:
        errors.append(f"Responses API 越界执行依赖: {', '.join(forbidden)}")

    for relative_path in ("docs/architecture_overview.md", "docs/PROJECT_SUMMARY.md"):
        path = ROOT / relative_path
        if not path.exists() or len(path.read_text(encoding="utf-8").strip()) < 200:
            errors.append(f"架构真相文档缺失或为空: {relative_path}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    errors = validate_manifest(args.manifest)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: Responses 在线架构清单与实现一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
