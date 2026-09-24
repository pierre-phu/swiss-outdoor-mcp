"""Transport client tests. Offline: every response comes from a recorded fixture.

The unrouted-path guard in `mock_transport` means a test that accidentally reaches the real
network fails instead of quietly going online.
"""

from datetime import date, time

import httpx2
import pytest

from conftest import load_fixture, mock_transport
from swiss_outdoor_mcp.clients.transport import TransportClient
from swiss_outdoor_mcp.errors import StopNotFoundError, UpstreamUnavailableError
from swiss_outdoor_mcp.models import ConnectionQuery

pytestmark = pytest.mark.anyio

QUERY = ConnectionQuery(origin="Lausanne", destination="Leysin-Feydey", date=date(2026, 9, 25))


async def test_find_connections_maps_the_recorded_response() -> None:
    transport = mock_transport({"/connections": "connections_lausanne_leysin.json"})

    async with TransportClient(transport=transport) as client:
        connections = await client.find_connections(QUERY)

    assert len(connections) == 2
    assert connections[0].duration_min == 75
    assert connections[0].sections[0].from_stop == "Lausanne"


async def test_search_locations_drops_entries_without_an_id() -> None:
    """`/locations` mixes in addresses and POIs, which have a null id and cannot be routed to."""
    raw = load_fixture("locations_leysin_feydey.json")
    assert any(entry["id"] is None for entry in raw["stations"]), "fixture should contain a POI"
    transport = mock_transport({"/locations": "locations_leysin_feydey.json"})

    async with TransportClient(transport=transport) as client:
        stations = await client.search_locations("Leysin Feydey")

    assert stations, "the real stops should survive the filter"
    assert all(station.id for station in stations)
    assert stations[0].name == "Leysin-Feydey"


async def test_an_unknown_stop_names_the_bad_one_and_suggests_alternatives() -> None:
    """The API will not say which side failed, so the client resolves each stop itself."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/connections"):
            return httpx2.Response(200, json=load_fixture("connections_unknown_stop.json"))
        # Origin resolves exactly; the destination is the near miss.
        query = request.url.params["query"]
        name = "locations_lausanne.json" if query == "Lausanne" else "locations_leysin_feydey.json"
        return httpx2.Response(200, json=load_fixture(name))

    query = ConnectionQuery(origin="Lausanne", destination="Leysin Feydey", date=date(2026, 9, 25))

    async with TransportClient(transport=mock_transport(handler=handler)) as client:
        with pytest.raises(StopNotFoundError) as caught:
            await client.find_connections(query)

    assert caught.value.stop == "Leysin Feydey", "must blame the destination, not the origin"
    assert "Leysin-Feydey" in caught.value.suggestions
    assert "Did you mean" in str(caught.value)


async def test_an_unknown_stop_with_no_candidates_still_names_it() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/connections"):
            return httpx2.Response(200, json=load_fixture("connections_unknown_stop.json"))
        query = request.url.params["query"]
        name = "locations_lausanne.json" if query == "Lausanne" else "locations_unknown.json"
        return httpx2.Response(200, json=load_fixture(name))

    query = ConnectionQuery(
        origin="Lausanne", destination="NotARealStopXYZ", date=date(2026, 9, 25)
    )

    async with TransportClient(transport=mock_transport(handler=handler)) as client:
        with pytest.raises(StopNotFoundError) as caught:
            await client.find_connections(query)

    assert caught.value.stop == "NotARealStopXYZ"
    assert caught.value.suggestions == []
    assert "exact stop name" in str(caught.value)


async def test_no_service_is_an_empty_list_not_an_error() -> None:
    """Both stops resolved but nothing runs: a real answer, and it must not look like a failure."""
    payload = load_fixture("connections_lausanne_leysin.json")
    payload["connections"] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with TransportClient(transport=mock_transport(handler=handler)) as client:
        assert await client.find_connections(QUERY) == []


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_http_failures_become_upstream_unavailable(status: int) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={})

    async with TransportClient(transport=mock_transport(handler=handler)) as client:
        with pytest.raises(UpstreamUnavailableError) as caught:
            await client.find_connections(QUERY)

    assert str(status) in str(caught.value)
    # The model must not read an outage as "there are no trains".
    assert "do not treat this as a negative answer" in str(caught.value)


async def test_a_timeout_becomes_upstream_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("too slow", request=request)

    async with TransportClient(transport=mock_transport(handler=handler)) as client:
        with pytest.raises(UpstreamUnavailableError, match="timed out"):
            await client.find_connections(QUERY)


async def test_a_non_json_body_becomes_upstream_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>maintenance</html>")

    async with TransportClient(transport=mock_transport(handler=handler)) as client:
        with pytest.raises(UpstreamUnavailableError, match="malformed"):
            await client.find_connections(QUERY)


class TestRequestParameters:
    """What we put on the wire. `isArrivalTime` is the flag that flips the whole search."""

    async def _capture(self, query: ConnectionQuery) -> httpx2.QueryParams:
        seen: list[httpx2.QueryParams] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request.url.params)
            return httpx2.Response(200, json=load_fixture("connections_lausanne_leysin.json"))

        async with TransportClient(transport=mock_transport(handler=handler)) as client:
            await client.find_connections(query)
        return seen[0]

    async def test_defaults_send_no_time_anchor(self) -> None:
        params = await self._capture(QUERY)

        assert params["from"] == "Lausanne"
        assert params["date"] == "2026-09-25"
        assert params["limit"] == "3"
        assert "time" not in params
        assert "isArrivalTime" not in params

    async def test_arrive_before_sets_the_arrival_flag(self) -> None:
        params = await self._capture(QUERY.model_copy(update={"arrive_before": time(9, 30)}))

        assert params["time"] == "09:30"
        assert params["isArrivalTime"] == "1"

    async def test_depart_after_clears_the_arrival_flag(self) -> None:
        params = await self._capture(QUERY.model_copy(update={"depart_after": time(7, 5)}))

        assert params["time"] == "07:05"
        assert params["isArrivalTime"] == "0"
