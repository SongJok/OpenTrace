"""
Cognitive Planning Layer — The system's "thinking brain."

Separates cognitive reasoning (WHAT to solve) from execution planning (HOW to solve).
Produces CognitiveGraph (goal hierarchy, uncertainty model, reasoning chains, constraints)
before StrategyBuilder projects it into ExecutionPlan.

This is the missing layer between UnderstandingEngine and CognitivePlanner.
"""

from kernel.runtime.cognitive.cognitive_graph import (
    CognitiveConstraint,
    CognitiveGraph,
    CognitivePlan,
    GoalHierarchy,
    GoalNode,
    GoalType,
    InformationGap,
    ReasoningChain,
    ReasoningStep,
    RiskAnalysis,
    UncertaintyModel,
)
from kernel.runtime.cognitive.cognitive_planner_v2 import CognitivePlannerV2
from kernel.runtime.cognitive.decomposition_policy import (
    DecompositionPolicy,
    DecompositionStrategy,
    build_decomposition_policy,
)
from kernel.runtime.cognitive.execution_projection import (
    ExecutionProjection,
    ProjectedCapability,
    ProjectionGroup,
    build_execution_projection,
)
from kernel.runtime.cognitive.strategy_builder import (
    StrategyBuilder,
    StrategyProjection,
    build_strategy_projection,
)

__all__ = [
    # Cognitive Graph
    "CognitiveGraph",
    "CognitivePlan",
    "CognitiveConstraint",
    "GoalNode",
    "GoalType",
    "GoalHierarchy",
    "InformationGap",
    "ReasoningChain",
    "ReasoningStep",
    "RiskAnalysis",
    "UncertaintyModel",
    # Planner V2
    "CognitivePlannerV2",
    # Strategy
    "StrategyBuilder",
    "StrategyProjection",
    "build_strategy_projection",
    # Decomposition
    "DecompositionPolicy",
    "DecompositionStrategy",
    "build_decomposition_policy",
    # Execution Projection
    "ExecutionProjection",
    "ProjectedCapability",
    "ProjectionGroup",
    "build_execution_projection",
]
