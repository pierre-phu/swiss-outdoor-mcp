"""`estimate_trip_co2` through a real MCP client session, offline."""

import json

import httpx2
import pytest
from mcp import Client

import swiss_outdoor_mcp.server as server
from conftest import load_fixture, mock_transport
from swiss_outdoor_mcp.clients.transport import TransportClient

pytestmark = pytest.mark.anyio


def use_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx2.MockTransport) -> None:
    monkeypatch.setattr(server, "_transport_client", lambda: TransportClient(transport=transport))


def locations_by_query(request: httpx2.Request) -> httpx2.Response:
    query = request.url.params["query"]
    name = "locations_lausanne.json" if query == "Lausanne" else "locations_leysin_feydey.json"
    return httpx2.Response(200, json=load_fixture(name))


def text_of(result: object) -> str:
    return str(getattr(result, "content")[0].text)  # noqa: B009


async def test_is_listed_with_its_arguments(client: Client) -> None:
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert "estimate_trip_co2" in tools
    assert set(tools["estimate_trip_co2"].input_schema["properties"]) == {"origin", "destination"}


async def test_prices_every_mode(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, mock_transport(handler=locations_by_query))

    result = await client.call_tool(
        "estimate_trip_co2", {"origin": "Lausanne", "destination": "Leysin-Feydey"}
    )

    assert result.is_error is False
    estimate = json.loads(text_of(result))
    assert set(estimate["by_mode"]) == {"train", "bus", "public_transport", "car"}
    assert estimate["destination"] == "Leysin-Feydey"
    assert "mobitool" in estimate["factor_source"]


async def test_an_unknown_stop_reaches_the_model_with_suggestions(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_transport(monkeypatch, mock_transport(handler=locations_by_query))

    result = await client.call_tool(
        "estimate_trip_co2", {"origin": "Lausanne", "destination": "Leysin Feydey"}
    )

    assert result.is_error is True
    assert "Leysin-Feydey" in text_of(result), "the model needs the correct spelling to retry"


async def test_an_outage_is_a_recoverable_error(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_transport(
        monkeypatch, mock_transport(handler=lambda request: httpx2.Response(503, json={}))
    )

    result = await client.call_tool(
        "estimate_trip_co2", {"origin": "Lausanne", "destination": "Leysin-Feydey"}
    )

    assert result.is_error is True
    assert "do not treat this as a negative answer" in text_of(result)
