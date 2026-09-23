"""End-to-end checks of the MCP wiring, through a real client session.

These are deliberately thin. Their job is to prove that the SDK's tool registration, stdio-free
in-process transport and error envelope behave the way `docs/api-notes.md` claims — so that when
the real tools land on days 2-4, a failure here means the SDK changed, not our logic.
"""

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from swiss_outdoor_mcp import __version__
from swiss_outdoor_mcp.errors import SiteNotFoundError
from swiss_outdoor_mcp.server import tool_errors

pytestmark = pytest.mark.anyio


async def test_ping_is_listed_with_its_docstring_as_description(client: Client) -> None:
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert "ping" in tools
    assert tools["ping"].description is not None
    assert "reachable" in tools["ping"].description


async def test_ping_returns_the_server_version(client: Client) -> None:
    result = await client.call_tool("ping", {})

    assert result.is_error is False
    assert __version__ in str(result.content[0].text)  # type: ignore[union-attr]


async def test_unknown_tool_is_an_error(client: Client) -> None:
    result = await client.call_tool("no_such_tool", {})

    assert result.is_error is True


async def test_tool_errors_maps_domain_exceptions_to_tool_error() -> None:
    """A domain exception must become a ToolError, keeping its recovery hint intact."""

    @tool_errors
    async def failing() -> str:
        raise SiteNotFoundError("nope")

    with pytest.raises(ToolError) as caught:
        await failing()

    assert "Unknown site_id 'nope'" in str(caught.value)
    assert "Call list_sites" in str(caught.value)


async def test_tool_errors_lets_successful_calls_through() -> None:
    @tool_errors
    async def succeeding() -> int:
        return 42

    assert await succeeding() == 42
