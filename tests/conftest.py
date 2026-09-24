"""Shared fixtures.

Async tests run through anyio's pytest plugin, which is what the MCP SDK's own testing docs use
(`docs/api-notes.md` section 1.4). We pin the backend to asyncio; there is no reason to pay for a
trio run as well.
"""

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp import Client

from swiss_outdoor_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Read a recorded API response. Recorded by `scripts/record_fixtures.py`."""
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


def mock_transport(
    routes: dict[str, str] | None = None,
    *,
    handler: Callable[[httpx2.Request], httpx2.Response] | None = None,
) -> httpx2.MockTransport:
    """Serve recorded fixtures offline.

    `routes` maps an endpoint (`"/connections"`) to a fixture filename. Matching is on the end of
    the path, because the client's base URL already carries a `/v1` prefix. Pass `handler` instead
    for the cases that need to fail on purpose or to inspect the request. Any unrouted path
    raises, so a test that would have reached the network fails loudly rather than going online.
    """
    if handler is not None:
        return httpx2.MockTransport(handler)

    table = routes or {}

    def respond(request: httpx2.Request) -> httpx2.Response:
        for endpoint, name in table.items():
            if request.url.path.endswith(endpoint):
                return httpx2.Response(200, json=load_fixture(name))
        raise AssertionError(f"unrouted request in a test: {request.url}")

    return httpx2.MockTransport(respond)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    """An in-process MCP client talking to our server object. No subprocess, no sockets.

    `raise_exceptions=True` surfaces crashes that happen outside a tool body, which would
    otherwise be flattened into a generic error message.
    """
    async with Client(mcp, raise_exceptions=True) as connected:
        yield connected
