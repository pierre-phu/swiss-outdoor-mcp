"""`get_flyability` through a real MCP client session, served from the Fiesch fixture.

This is the "done when" of day 3: a sensible result for a real site, offline.
"""

from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from mcp import Client

import swiss_outdoor_mcp.server as server
from conftest import mock_transport
from swiss_outdoor_mcp.clients.openmeteo import OpenMeteoClient

pytestmark = pytest.mark.anyio


def use_weather(monkeypatch: pytest.MonkeyPatch, transport: httpx2.MockTransport) -> None:
    monkeypatch.setattr(server, "_weather_client", lambda: OpenMeteoClient(transport=transport))


@pytest.fixture
def offline_weather(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    use_weather(monkeypatch, mock_transport({"/ensemble": "ensemble_two_models.json"}))
    yield


def text_of(result: object) -> str:
    return str(getattr(result, "content")[0].text)  # noqa: B009


async def test_is_listed_with_its_two_arguments(client: Client) -> None:
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert "get_flyability" in tools
    schema = tools["get_flyability"].input_schema
    assert set(schema["properties"]) == {"site_id", "date"}
    assert set(schema["required"]) == {"site_id", "date"}


async def test_scores_a_real_site_from_the_fixture(client: Client, offline_weather: None) -> None:
    result = await client.call_tool("get_flyability", {"site_id": "fiesch", "date": "2026-09-26"})

    assert result.is_error is False
    body: dict[str, Any] = result.structured_content or {}
    assert body["site_id"] == "fiesch"
    assert body["model"] == "icon_d2_eps"
    assert body["n_members"] == 20
    assert 0.0 <= body["p_flyable"] <= 1.0
    assert [h["time"][11:16] for h in body["hourly"]][0::7] == ["10:00", "17:00"]
    assert body["hourly"][0]["time"].endswith("+02:00"), "hours are Europe/Zurich, summer time"
    assert body["criteria"]["max_wind_kmh"] == 20
    assert "does not replace pilot judgment" in body["disclaimer"]
    assert "Open-Meteo" in body["attribution"]


async def test_switches_to_the_13km_model_further_out(
    client: Client, offline_weather: None
) -> None:
    result = await client.call_tool("get_flyability", {"site_id": "fiesch", "date": "2026-09-28"})

    body: dict[str, Any] = result.structured_content or {}
    assert (body["model"], body["n_members"]) == ("icon_eu_eps", 40)


async def test_an_unknown_site_points_the_model_at_list_sites(client: Client) -> None:
    result = await client.call_tool("get_flyability", {"site_id": "chamonix", "date": "2026-09-26"})

    assert result.is_error is True
    assert "Call list_sites" in text_of(result)


async def test_a_date_beyond_the_horizon_says_which_dates_work(
    client: Client, offline_weather: None
) -> None:
    result = await client.call_tool("get_flyability", {"site_id": "fiesch", "date": "2026-10-03"})

    assert result.is_error is True
    assert "cover 2026-09-25 to 2026-09-29" in text_of(result)


async def test_an_outage_is_not_reported_as_unflyable(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_weather(monkeypatch, mock_transport(handler=lambda _: httpx2.Response(502, json={})))

    result = await client.call_tool("get_flyability", {"site_id": "fiesch", "date": "2026-09-26"})

    assert result.is_error is True
    assert "do not treat this as a negative answer" in text_of(result)
