from __future__ import annotations

import hashlib

from skills.runtime.manifest import SkillManifest


class SkillSignatureVerifier:
    """Step2 skeleton verifier.

    Current policy:
    - if signature is empty -> allow in dev mode
    - otherwise compare sha256(name:version:entrypoint) prefix
    """

    def verify(self, manifest: SkillManifest) -> bool:
        if not manifest.signature:
            return True
        raw = f"{manifest.name}:{manifest.version}:{manifest.entrypoint}".encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        return digest.startswith(manifest.signature.lower())


verifier = SkillSignatureVerifier()
