from __future__ import annotations

import json
import shutil
import subprocess
import hashlib
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from skills.runtime.loader import skill_loader

ROOT = Path(__file__).resolve().parents[2]
INSTALLED_DIR = ROOT / "skills" / "installed"
TMP_DIR = ROOT / ".tmp" / "skills"

INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class InstalledSkill:
    skill_id: str
    name: str
    version: str
    entrypoint: str
    path: str
    description: str = ""
    skill_type: str = "generic"  # generic, data_query, text_analysis, etc.
    code: str = ""
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    data_source_id: str = ""
    instructions: str = ""
    source: dict[str, Any] = field(default_factory=dict)


def _compute_skill_id(name: str, version: str) -> str:
    return f"{name}@{version}"


def _skill_path(skill_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}@[A-Za-z0-9_.+-]{1,64}", skill_id or ""):
        raise ValueError("invalid skill_id")
    target = (INSTALLED_DIR / skill_id).resolve()
    if INSTALLED_DIR.resolve() not in target.parents:
        raise ValueError("invalid skill path")
    return target


def _generate_signature(name: str, version: str, entrypoint: str) -> str:
    raw = f"{name}:{version}:{entrypoint}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class SkillMarketplace:
    def install_instructional(
        self,
        *,
        skill_id: str,
        name: str,
        version: str,
        description: str,
        instructions: str,
        source: dict[str, Any],
    ) -> InstalledSkill:
        """Install reviewed SKILL.md content without executing third-party code."""
        target = _skill_path(skill_id)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        manifest_data = {
            "name": name,
            "version": version,
            "entrypoint": "SKILL.md",
            "required_connectors": [],
            "permissions": [],
            "signature": _generate_signature(name, version, "SKILL.md"),
            "public_key_id": "skillhub-instruction-only",
        }
        (target / "skill.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        (target / "SKILL.md").write_text(instructions, encoding="utf-8")
        (target / "skill_config.json").write_text(
            json.dumps(
                {
                    "description": description,
                    "skill_type": "instruction",
                    "test_cases": [],
                    "data_source_id": "",
                    "source": source,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return InstalledSkill(
            skill_id=skill_id,
            name=name,
            version=version,
            entrypoint="SKILL.md",
            path=str(target),
            description=description,
            skill_type="instruction",
            instructions=instructions,
            source=source,
        )

    def install_from_git(self, git_url: str, ref: str = "main") -> InstalledSkill:
        if not settings.skills_git_install_enabled:
            raise PermissionError("Git skill installation is disabled by policy")
        temp = TMP_DIR / f"skill_{abs(hash((git_url, ref)))}"
        if temp.exists():
            shutil.rmtree(temp)

        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, git_url, str(temp)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        manifest = skill_loader.load_manifest(temp)
        skill_id = _compute_skill_id(manifest.name, manifest.version)
        target = _skill_path(skill_id)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(temp), str(target))

        return InstalledSkill(
            skill_id=skill_id,
            name=manifest.name,
            version=manifest.version,
            entrypoint=manifest.entrypoint,
            path=str(target),
        )

    def create_local(
        self,
        name: str,
        version: str,
        entrypoint: str,
        code: str = "",
        description: str = "",
        skill_type: str = "generic",
        test_cases: list[dict[str, Any]] | None = None,
        data_source_id: str = "",
    ) -> InstalledSkill:
        if not settings.skills_local_create_enabled:
            raise PermissionError("Local skill creation is disabled by policy")
        skill_id = _compute_skill_id(name, version)
        target = _skill_path(skill_id)
        if target.exists():
            raise ValueError(f"skill {skill_id} already exists")

        target.mkdir(parents=True)

        # Create skill.json manifest
        signature = _generate_signature(name, version, entrypoint)
        manifest_data = {
            "name": name,
            "version": version,
            "entrypoint": entrypoint,
            "required_connectors": [],
            "permissions": [],
            "signature": signature,
            "public_key_id": "default",
        }
        (target / "skill.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        # Create code file if provided
        if code:
            code_file = target / entrypoint
            code_file.write_text(code, encoding="utf-8")

        # Create skill_config.json for extra metadata
        config_data = {
            "description": description,
            "skill_type": skill_type,
            "test_cases": test_cases or [],
            "data_source_id": data_source_id,
        }
        (target / "skill_config.json").write_text(json.dumps(config_data, indent=2), encoding="utf-8")

        return InstalledSkill(
            skill_id=skill_id,
            name=name,
            version=version,
            entrypoint=entrypoint,
            path=str(target),
            description=description,
            skill_type=skill_type,
            code=code,
            test_cases=test_cases or [],
            data_source_id=data_source_id,
        )

    def get_skill(self, skill_id: str) -> InstalledSkill | None:
        try:
            target = _skill_path(skill_id)
        except ValueError:
            return None
        if not target.exists():
            return None

        try:
            manifest = skill_loader.load_manifest(target)
            config_path = target / "skill_config.json"
            config = {}
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))

            code = ""
            entry_file = target / manifest.entrypoint
            if entry_file.exists():
                code = entry_file.read_text(encoding="utf-8")

            return InstalledSkill(
                skill_id=skill_id,
                name=manifest.name,
                version=manifest.version,
                entrypoint=manifest.entrypoint,
                path=str(target),
                description=config.get("description", ""),
                skill_type=config.get("skill_type", "generic"),
                code=code,
                test_cases=config.get("test_cases", []),
                data_source_id=config.get("data_source_id", ""),
                instructions=code if manifest.entrypoint.lower().endswith(".md") else "",
                source=dict(config.get("source") or {}),
            )
        except Exception:
            return None

    def test_skill(self, skill_id: str, test_input: dict[str, Any]) -> dict[str, Any]:
        skill = self.get_skill(skill_id)
        if not skill:
            return {"success": False, "error": f"skill {skill_id} not found"}

        result: dict[str, Any] = {"skill_id": skill_id, "input": test_input}

        # If skill has predefined test cases, run them
        if skill.test_cases:
            results = []
            for tc in skill.test_cases:
                tc_input = tc.get("input", test_input)
                expected = tc.get("expected")
                results.append({
                    "input": tc_input,
                    "expected": expected,
                    "status": "pending_execution",
                })
            result["test_cases"] = results

        # Try to execute the skill code if it's Python
        if skill.code and skill.entrypoint.endswith(".py"):
            if bool(getattr(settings, "skills_subprocess_execution_enabled", False)):
                from skills.runtime.executor import execute_python_skill

                return {
                    "skill_id": skill_id,
                    "input": test_input,
                    **execute_python_skill(Path(skill.path), skill.entrypoint, test_input),
                }
            if not settings.skills_inprocess_execution_enabled:
                return {
                    "success": False,
                    "error": "Python skill execution is disabled; enable the subprocess runner policy",
                    "skill_id": skill_id,
                }
            try:
                import importlib.util
                import sys

                code_path = str(Path(skill.path) / skill.entrypoint)
                spec = importlib.util.spec_from_file_location(skill.name, code_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[skill.name] = mod
                    spec.loader.exec_module(mod)

                    # Look for execute function
                    if hasattr(mod, "execute"):
                        output = mod.execute(test_input)
                        result["success"] = True
                        result["output"] = output
                    else:
                        result["success"] = True
                        result["output"] = f"Skill '{skill.name}' loaded successfully (no execute function found)"
                else:
                    result["success"] = False
                    result["error"] = "Could not load skill module"
            except Exception as exc:
                result["success"] = False
                result["error"] = str(exc)
        elif skill.instructions:
            result["success"] = True
            result["output"] = {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "instructions": skill.instructions[:16000],
                "input": test_input,
                "trust": "user_enabled_instruction_skill",
            }
        else:
            result["success"] = True
            result["output"] = f"Skill '{skill.name}' ({skill.skill_type}) received input: {json.dumps(test_input)}"

        return result

    def uninstall(self, skill_id: str) -> bool:
        try:
            target = _skill_path(skill_id)
        except ValueError:
            return False
        if not target.exists():
            return False
        shutil.rmtree(target)
        return True

    def list_installed(self) -> list[InstalledSkill]:
        items: list[InstalledSkill] = []
        for p in INSTALLED_DIR.iterdir():
            if not p.is_dir():
                continue
            try:
                manifest = skill_loader.load_manifest(p)
                config_path = p / "skill_config.json"
                config = {}
                if config_path.exists():
                    config = json.loads(config_path.read_text(encoding="utf-8"))

                code = ""
                entry_file = p / manifest.entrypoint
                if entry_file.exists():
                    code = entry_file.read_text(encoding="utf-8")

                items.append(
                    InstalledSkill(
                        skill_id=p.name,
                        name=manifest.name,
                        version=manifest.version,
                        entrypoint=manifest.entrypoint,
                        path=str(p),
                        description=config.get("description", ""),
                        skill_type=config.get("skill_type", "generic"),
                        code=code[:500] if code else "",  # truncate for listing
                        test_cases=config.get("test_cases", []),
                        data_source_id=config.get("data_source_id", ""),
                        instructions=code if manifest.entrypoint.lower().endswith(".md") else "",
                        source=dict(config.get("source") or {}),
                    )
                )
            except Exception:
                continue
        return items


marketplace = SkillMarketplace()
