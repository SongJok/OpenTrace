from __future__ import annotations

from pathlib import Path
import json

from skills.runtime.manifest import SkillManifest
from skills.runtime.verifier import verifier


class SkillLoader:
    def load_manifest(self, skill_dir: Path) -> SkillManifest:
        path_json = skill_dir / "skill.json"
        path_yaml = skill_dir / "skill.yaml"

        if path_json.exists():
            data = json.loads(path_json.read_text(encoding="utf-8"))
        elif path_yaml.exists():
            # minimal yaml support without extra dependency (very constrained)
            data: dict[str, str] = {}
            for line in path_yaml.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.strip().startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
        else:
            raise FileNotFoundError("skill.json or skill.yaml not found")

        manifest = SkillManifest(**data)
        root = skill_dir.resolve()
        entrypoint = (root / manifest.entrypoint).resolve()
        if root not in entrypoint.parents:
            raise ValueError("skill entrypoint escapes skill directory")
        if not verifier.verify(manifest):
            raise ValueError("skill signature verification failed")
        return manifest


skill_loader = SkillLoader()
