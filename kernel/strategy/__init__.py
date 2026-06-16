"""
Strategy Domain facade — capability routing, policy, execution strategy.

Delegates to runtime cognitive modules; stable import surface for vNext six-domain layout.
"""

from kernel.runtime.cognitive.strategy_builder import StrategyBuilder
from kernel.runtime.policy import policy_engine

__all__ = ["StrategyBuilder", "policy_engine"]