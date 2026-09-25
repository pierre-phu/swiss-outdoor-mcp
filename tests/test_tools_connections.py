"""The two new tools, exercised through a real MCP client session.

This is the layer that matters for an LLM: it checks the tools are registered, that their schemas
carry the arguments, and above all that a failure arrives as `is_error=True` with a message
naming the recovery — not as a cheerful-looking string (`docs/api-notes.md` section 1.2).
"""

from collections.abc import Iterator

import httpx2
import pytest
from mcp import Client

import swiss_outdoor_mcp.server as server
from conftest import load_fixture, mock_transport
from swiss_outdoor_mcp.clients.transport import TransportClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def offline_transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the tools at fixtures instead of the network, via the server's one seam."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/connections"):
            return httpx2.Response(200, json=load_fixture("connections_lausanne_leysin.json"))
        return httpx2.Response(200, json=load_fixture("locations_lausanne.json"))

    monkeypatch.setattr(
        server,
        "_transport_client",
        lambda: TransportClient(transport=mock_transport(handler=handler)),
    )
    yield


def text_of(result: object) -> str:
    return str(getattr(result, "content")[0].text)  # noqa: B009


class TestListSites:
    async def test_is_listed_with_both_filters(self, client: Client) -> None:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        assert "list_sites" in tools
        properties = tools["list_sites"].input_schema["properties"]
        assert set(properties) == {"region", "orientation"}

    async def test_returns_the_packaged_sites(self, client: Client) -> None:
        result = await client.call_tool("list_sites", {})

        assert result.is_error is False
        assert "nearest_stop" in text_of(result)

    async def test_filters_by_region(self, client: Client) -> None:
        result = await client.call_tool("list_sites", {"region": "Valais"})

        assert result.is_error is False
        assert "Vaud" not in text_of(result)

    async def test_an_unknown_region_is_an_empty_result_not_an_error(self, client: Client) -> None:
        """No sites in Ticino is a fact, not a failure."""
        result = await client.call_tool("list_sites", {"region": "Ticino"})

        assert result.is_error is False


class TestGetConnections:
    async def test_is_listed_with_its_arguments(self, client: Client) -> None:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        assert "get_connections" in tools
        properties = tools["get_connections"].input_schema["properties"]
        assert {"origin", "destination", "date"} <= set(properties)

    async def test_returns_connections(self, client: Client, offline_transport: None) -> None:
        result = await client.call_tool(
            "get_connections",
            {"origin": "Lausanne", "destination": "Leysin-Feydey", "date": "2026-09-25"},
        )

        assert result.is_error is False
        assert "Leysin-Feydey" in text_of(result)

    async def test_setting_both_time_anchors_is_a_recoverable_error(self, client: Client) -> None:
        """The cross-field rule has no place in the JSON schema, so it must be a ToolError."""
        result = await client.call_tool(
            "get_connections",
            {
                "origin": "Lausanne",
                "destination": "Leysin-Feydey",
                "date": "2026-09-25",
                "arrive_before": "09:30",
                "depart_after": "07:00",
            },
        )

        assert result.is_error is True
        assert "at most one" in text_of(result)

    async def test_an_unknown_stop_reaches_the_model_as_an_error_with_suggestions(
        self, client: Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            if request.url.path.endswith("/connections"):
                return httpx2.Response(200, json=load_fixture("connections_unknown_stop.json"))
            query = request.url.params["query"]
            name = (
                "locations_lausanne.json" if query == "Lausanne" else "locations_leysin_feydey.json"
            )
            return httpx2.Response(200, json=load_fixture(name))

        monkeypatch.setattr(
            server,
            "_transport_client",
            lambda: TransportClient(transport=mock_transport(handler=handler)),
        )

        result = await client.call_tool(
            "get_connections",
            {"origin": "Lausanne", "destination": "Leysin Feydey", "date": "2026-09-25"},
        )

        assert result.is_error is True
        message = text_of(result)
        assert "Leysin Feydey" in message
        assert "Leysin-Feydey" in message, "the model needs the correct spelling to retry"

    async def test_an_outage_is_not_reported_as_no_trains(
        self, client: Client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(503, json={})

        monkeypatch.setattr(
            server,
            "_transport_client",
            lambda: TransportClient(transport=mock_transport(handler=handler)),
        )

        result = await client.call_tool(
            "get_connections",
            {"origin": "Lausanne", "destination": "Leysin-Feydey", "date": "2026-09-25"},
        )

        assert result.is_error is True
        assert "do not treat this as a negative answer" in text_of(result)
