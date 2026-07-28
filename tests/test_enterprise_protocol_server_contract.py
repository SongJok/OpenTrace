from fastapi.routing import APIRoute

from gateway.api_gateway.routers import interoperability
from gateway.api_gateway.routers.auth import get_current_user


def test_mcp_and_a2a_routes_require_authenticated_user():
    protected = [
        route
        for route in interoperability.router.routes
        if isinstance(route, APIRoute) and route.path != "/.well-known/agent-card.json"
    ]
    assert protected
    for route in protected:
        assert any(dep.call is get_current_user for dep in route.dependant.dependencies)


def test_mcp_tool_is_durable_response_adapter():
    source = __import__("inspect").getsource(interoperability.mcp_server)
    assert "create_response" in source
    assert "background=True" in source
    assert "idempotencyKey" in source
