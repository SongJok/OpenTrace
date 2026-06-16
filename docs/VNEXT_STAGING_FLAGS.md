# vNext staging / production flags

Copy relevant lines into `.env` for staging validation.

```bash
# Cognitive Runtime V2 (default on in settings.py)
KERNEL_ORCHESTRATOR_V4_ENABLED=false

# Optional: abort execute when RuntimePhase transition is invalid
KERNEL_RUNTIME_PHASE_TRANSITION_STRICT=false

# Multi-question + multi-goal
KERNEL_MULTI_QUESTION_RUNTIME_V2_ENABLED=true
KERNEL_MULTI_GOAL_SEQUENTIAL_ENABLED=true

# Data path via services layer (not external product)
KERNEL_DATA_INTELLIGENCE_ROUTING_ENABLED=true

# Governance gates on executive path
KERNEL_GOVERNANCE_EVIDENCE_GATE_ENABLED=true
KERNEL_GOVERNANCE_RISK_GATE_ENABLED=true
```

After changing `.env`, restart API: `bash restart.sh`.

**Regression (no Docker):**

```bash
bash scripts/run_vnext_final_tests.sh
```