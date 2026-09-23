"""Shared fixtures.

Async tests run through anyio's pytest plugin, which is what the MCP SDK's own testing docs use
(`docs/api-notes.md` section 1.4). We pin the backend to asyncio; there is no reason to pay for a
trio run as well.
"""

from collections.abc import AsyncIterator

import pytest
from mcp import Client

from swiss_outdoor_mcp.server import mcp


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
