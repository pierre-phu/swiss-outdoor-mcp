"""The MCP layer: declare tools, validate, delegate, map errors.

No business logic lives here. Anything that computes belongs in `domain/`, anything that talks to
the network belongs in `clients/`.
"""

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from swiss_outdoor_mcp import __version__
from swiss_outdoor_mcp.errors import SwissOutdoorError

__all__ = ["mcp", "tool_errors"]

P = ParamSpec("P")
R = TypeVar("R")

mcp = MCPServer(
    "swiss-outdoor-mcp",
    version=__version__,
    instructions=(
        "Deterministic facts for planning Swiss mountain outings by public transport. "
        "Compose the tools yourself: the server never calls a model and never decides for you. "
        "Always relay the disclaimer that comes with any flyability result."
    ),
)


def tool_errors(
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Turn our domain exceptions into `ToolError`.

    This matters more than it looks. A tool that *returns* an error string comes back with
    `is_error=False`, so the model reads the failure as a successful answer. Raising `ToolError`
    is what sets `is_error=True` and gives the model a chance to recover — see
    `docs/api-notes.md` section 1.2.
    """

    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except SwissOutdoorError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
@tool_errors
async def ping() -> str:
    """Check that the swiss-outdoor-mcp server is reachable and report its version."""
    return f"swiss-outdoor-mcp {__version__} ok"
