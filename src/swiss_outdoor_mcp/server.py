"""The MCP layer: declare tools, validate, delegate, map errors.

No business logic lives here. Anything that computes belongs in `domain/`, anything that talks to
the network belongs in `clients/`.
"""

from collections.abc import Callable, Coroutine
from datetime import date as date_type
from datetime import time as time_type
from functools import wraps
from typing import Annotated, Any, ParamSpec, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from swiss_outdoor_mcp import __version__
from swiss_outdoor_mcp.clients.transport import TransportClient
from swiss_outdoor_mcp.data_loader import load_sites
from swiss_outdoor_mcp.domain.sites import filter_sites
from swiss_outdoor_mcp.errors import SwissOutdoorError
from swiss_outdoor_mcp.models import Connection, ConnectionQuery, Site

__all__ = ["mcp", "tool_errors"]

P = ParamSpec("P")
R = TypeVar("R")


def _transport_client() -> TransportClient:
    """Build the transport client used by the tools.

    A single seam, so tests can inject an `httpx2.MockTransport` serving fixtures without the
    tools taking a transport argument that would leak into their public JSON schema. This is also
    where `SWISS_OUTDOOR_OFFLINE` will hook in when offline mode lands.
    """
    return TransportClient()


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
        except ValidationError as exc:
            # Cross-field rules (such as "at most one time anchor") cannot be expressed in the
            # flat JSON schema the SDK derives, so they fail here instead. That is still a
            # caller mistake a better call would avoid, so it is a ToolError, not a crash.
            raise ToolError("; ".join(error["msg"] for error in exc.errors())) from exc

    return wrapper


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
@tool_errors
async def ping() -> str:
    """Check that the swiss-outdoor-mcp server is reachable and report its version."""
    return f"swiss-outdoor-mcp {__version__} ok"


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
@tool_errors
async def list_sites(
    region: Annotated[
        str | None,
        Field(default=None, description="Canton or region, e.g. 'Valais'. Case-insensitive."),
    ] = None,
    orientation: Annotated[
        str | None,
        Field(
            default=None,
            description="Compass sector the launch faces, e.g. 'SW'. 16-point, case-insensitive.",
        ),
    ] = None,
) -> list[Site]:
    """List the paragliding launch sites this server knows, optionally filtered.

    Use the returned `id` for get_flyability, and the returned `nearest_stop` as the destination
    for get_connections. `access_notes` covers the last leg from that stop, which the timetable
    often cannot route.
    """
    return filter_sites(load_sites(), region=region, orientation=orientation)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
@tool_errors
async def get_connections(
    origin: Annotated[
        str, Field(description="Departure stop, exactly as the timetable spells it.")
    ],
    destination: Annotated[
        str, Field(description="Arrival stop. For a launch site, use its nearest_stop.")
    ],
    date: Annotated[date_type, Field(description="Travel date, YYYY-MM-DD, Europe/Zurich.")],
    arrive_before: Annotated[
        time_type | None,
        Field(default=None, description="Be there by this local time, HH:MM."),
    ] = None,
    depart_after: Annotated[
        time_type | None,
        Field(default=None, description="Leave no earlier than this local time, HH:MM."),
    ] = None,
    limit: Annotated[int, Field(default=3, ge=1, le=16, description="How many options.")] = 3,
) -> list[Connection]:
    """Find public-transport connections between two Swiss stops on a given date.

    Set at most one of arrive_before / depart_after. An empty list means nothing runs at that
    time, which is a real answer, not a failure.
    """
    query = ConnectionQuery(
        origin=origin,
        destination=destination,
        date=date,
        arrive_before=arrive_before,
        depart_after=depart_after,
        limit=limit,
    )
    async with _transport_client() as client:
        return await client.find_connections(query)
