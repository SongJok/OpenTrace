#!/usr/bin/env bash
# Static import boundary checks aligned with tests/test_kernel_import_boundaries.py
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

ROOT="$(pwd)"
fail=0

die() {
  echo "BOUNDARY FAIL: $*" >&2
  fail=1
}

echo "=== check_import_boundaries ==="

# vNext runtime path must not import orchestrator_v4
for rel in \
  kernel/runtime_gateway.py \
  kernel/runtime/runtime_turn_dispatcher.py \
  kernel/cognitive_supervisor/supervisor.py \
  kernel/cognitive_supervisor/dispatch_enrichment.py \
  kernel/cognitive_supervisor/run_outcomes.py; do
  path="$ROOT/$rel"
  if [[ -f "$path" ]] && grep -q 'orchestrator_v4' "$path"; then
    die "$rel must not reference orchestrator_v4"
  fi
done

# RuntimeGateway must stay slim
gw="$ROOT/kernel/runtime_gateway.py"
if [[ -f "$gw" ]]; then
  grep -q 'cognitive_executive' "$gw" && die "runtime_gateway.py must not import cognitive_executive"
  grep -q 'planner_facade' "$gw" && die "runtime_gateway.py must not import planner_facade"
  grep -q 'get_goal_planner' "$gw" && die "runtime_gateway.py must not import get_goal_planner"
fi

# Production modules: no kernel.orchestrator_v4
for rel in \
  agents/rag_agent.py \
  agents/skills_agent.py \
  agents/vision_agent.py \
  agents/rule_engine_agent.py \
  kernel/plan_agent.py \
  gateway/api_gateway/routers/chat.py; do
  path="$ROOT/$rel"
  if [[ -f "$path" ]]; then
    if grep -qE 'from kernel\.orchestrator_v4|import kernel\.orchestrator_v4' "$path"; then
      die "$rel must use legacy.v4, not kernel.orchestrator_v4"
    fi
  fi
done

# Agents must not import cognitive_kernel
while IFS= read -r path; do
  base="$(basename "$path")"
  [[ "$base" == "__init__.py" ]] && continue
  if grep -q 'cognitive_kernel' "$path" 2>/dev/null; then
    die "$path must not import cognitive_kernel"
  fi
done < <(find "$ROOT/agents" -name '*.py' 2>/dev/null)

# Agents must not import gateway API routers
while IFS= read -r path; do
  if grep -q 'gateway\.api_gateway' "$path" 2>/dev/null; then
    die "$path must not import gateway.api_gateway"
  fi
done < <(find "$ROOT/agents" -name '*.py' 2>/dev/null)

# kernel/orchestrator.py uses legacy
orch="$ROOT/kernel/orchestrator.py"
if [[ -f "$orch" ]]; then
  grep -q 'legacy.v4.orchestrator' "$orch" || die "kernel/orchestrator.py must import legacy.v4.orchestrator"
  grep -qE 'from kernel\.orchestrator_v4|import kernel\.orchestrator_v4' "$orch" && die "kernel/orchestrator.py must not import kernel.orchestrator_v4"
fi

# governance/*_governor.py must re-export kernel.governance (no duplicate class bodies)
for rel in \
  governance/runtime_governor.py \
  governance/audit_governor.py \
  governance/capability_governor.py \
  governance/evidence_governor.py \
  governance/memory_governor.py \
  governance/risk_governor.py \
  governance/policy_governor.py \
  governance/prompt_governor.py; do
  path="$ROOT/$rel"
  if [[ -f "$path" ]]; then
    if grep -qE '^class ' "$path"; then
      die "$rel must not define governor classes (re-export kernel.governance only)"
    fi
    grep -q 'kernel.governance' "$path" || die "$rel must import from kernel.governance"
  fi
done

python -m pytest -q tests/test_kernel_import_boundaries.py tests/test_agents_import_boundaries.py tests/test_governance_single_source_contract.py --tb=short

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "=== OK ==="