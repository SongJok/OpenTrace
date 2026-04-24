from __future__ import annotations

from sandbox_runtime.providers.base import SandboxProvider, SandboxRequest, SandboxResult


class FirecrackerProvider(SandboxProvider):
    name = "firecracker"

    async def run(self, req: SandboxRequest) -> SandboxResult:
        # Step5 skeleton: runtime wiring placeholder
        return SandboxResult(
            stdout="",
            stderr="Firecracker provider not enabled yet; fallback required",
            returncode=127,
            output_files=[],
            provider=self.name,
            metadata={"network": "isolated", "microvm": True},
        )
