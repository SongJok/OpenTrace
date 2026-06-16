"""Kernel routing facade — L0/L1/V5 tier entry (decoupled from CognitiveKernel)."""

from kernel.routing.v5_facade import V5RoutingFacade, get_v5_routing_facade

__all__ = ["V5RoutingFacade", "get_v5_routing_facade"]