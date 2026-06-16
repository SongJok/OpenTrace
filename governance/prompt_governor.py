"""Re-export prompt governor from kernel control plane."""

from kernel.governance.prompt_governor import PromptGovernanceResult, PromptGovernor

PromptGovernanceDecision = PromptGovernanceResult

__all__ = ["PromptGovernor", "PromptGovernanceResult", "PromptGovernanceDecision"]