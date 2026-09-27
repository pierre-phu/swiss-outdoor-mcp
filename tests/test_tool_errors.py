"""The error paths not covered elsewhere, and the map of all of them.

Every error a tool can raise must reach the model as `is_error=True` with a message it can act
on (`CLAUDE.md`, "Tool error messages are written for an LLM to recover"). Where each path is
tested:

- any tool
  - domain error becomes a `ToolError`: test_server.py, `..._maps_domain_exceptions_to_tool_error`
  - unknown tool: test_server.py, `test_unknown_tool_is_an_error`
- `list_sites`
  - orientation that is not a sector: here
  - unknown region is `[]`, not an error: test_tools_connections.py, `TestListSites`
- `get_flyability`
  - unknown `site_id`: test_tools_flyability.py, `test_an_unknown_site_points_...`
  - date beyond the horizon: test_tools_flyability.py, `test_a_date_beyond_the_horizon_...`
  - upstream down: test_tools_flyability.py, `test_an_outage_is_not_reported_as_unflyable`
  - date that is not a date: here
- `get_connections`
  - unknown stop, with suggestions: test_tools_connections.py, `TestGetConnections`
  - both time anchors set: test_tools_connections.py, `TestGetConnections`
  - upstream down: test_tools_connections.py, `test_an_outage_is_not_reported_as_no_trains`
  - `limit` out of range: here
- `estimate_trip_co2`
  - unknown stop, with suggestions: test_tools_co2.py
  - upstream down: test_tools_co2.py, `test_an_outage_is_a_recoverable_error`
  - stop without coordinates: test_client_transport.py, `TestResolveStop`
- offline mode
  - request with no recording: test_offline.py, `TestMisses`
  - fixtures directory missing: test_offline.py, `TestMisses`

Messages for schema violations (a bad date, `limit=0`) come from the MCP SDK, not from us, so
those tests only pin that they are errors rather than crashes or silent defaults.
"""

import pytest
from mcp import Client

pytestmark = pytest.mark.anyio


def text_of(result: object) -> str:
    return str(getattr(result, "content")[0].text)  # noqa: B009


async def test_an_unknown_orientation_lists_the_valid_ones(client: Client) -> None:
    """'south-west' used to filter everything out, reading as "no launch faces that way"."""
    result = await client.call_tool("list_sites", {"orientation": "south-west"})

    assert result.is_error is True
    message = text_of(result)
    assert "Unknown orientation 'south-west'" in message
    assert "SW" in message


async def test_a_lowercase_sector_is_still_fine(client: Client) -> None:
    result = await client.call_tool("list_sites", {"orientation": "sw"})

    assert result.is_error is False


async def test_a_date_in_words_is_rejected_not_guessed(client: Client) -> None:
    result = await client.call_tool(
        "get_flyability", {"site_id": "fiesch", "date": "next saturday"}
    )

    assert result.is_error is True


async def test_a_limit_out_of_range_is_rejected(client: Client) -> None:
    result = await client.call_tool(
        "get_connections",
        {"origin": "Lausanne", "destination": "Fiesch", "date": "2026-09-26", "limit": 0},
    )

    assert result.is_error is True
