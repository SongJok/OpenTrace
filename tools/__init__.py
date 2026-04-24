"""Tool package bootstrap: ensure built-in tools are registered."""

# Import side-effects register tools into the global registry.
from tools.builtin_tools import builtins as _builtins  # noqa: F401
