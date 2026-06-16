"""
Memory Truth Maintenance — Prevents memory pollution in long-running cognitive systems.

Truth maintenance ensures that memories don't silently drift, contradict,
or decay into noise over extended operation. Core capabilities:

- confidence_decay: Time-based and usage-based confidence decay
- contradiction_resolution: Detect and resolve conflicting memories
- fact_supersession: Mark old facts as superseded when newer information arrives
- truth_maintenance: Orchestrator that runs all TMS checks
"""

from kernel.runtime.memory.confidence_decay import (
    ConfidenceDecayPolicy,
    apply_confidence_decay,
)
from kernel.runtime.memory.contradiction_resolution import (
    ContradictionDetector,
    MemoryContradiction,
    ResolutionAction,
)
from kernel.runtime.memory.fact_supersession import (
    FactSupersessionEngine,
    SupersessionRecord,
)
from kernel.runtime.memory.truth_maintenance import (
    TruthMaintenanceSystem,
    TMSReport,
    run_truth_maintenance,
)

__all__ = [
    "ConfidenceDecayPolicy",
    "apply_confidence_decay",
    "ContradictionDetector",
    "MemoryContradiction",
    "ResolutionAction",
    "FactSupersessionEngine",
    "SupersessionRecord",
    "TruthMaintenanceSystem",
    "TMSReport",
    "run_truth_maintenance",
]
