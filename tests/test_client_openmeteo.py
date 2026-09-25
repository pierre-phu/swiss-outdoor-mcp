"""`OpenMeteoClient` against recorded fixtures. Never touches the network."""

from datetime import date, time

import httpx2
import pytest

from conftest import load_fixture, mock_transport
from swiss_outdoor_mcp.clients.openmeteo import FORECAST_DAYS, OpenMeteoClient
from swiss_outdoor_mcp.errors import DateOutOfRangeError, UpstreamUnavailableError

pytestmark = pytest.mark.anyio

FIESCH = (46.4048, 8.09598)
SATURDAY = date(2026, 9, 26)


async def forecast_with(handler: httpx2.MockTransport, day: date = SATURDAY) -> object:
    async with OpenMeteoClient(transport=handler) as client:
        return await client.get_forecast(*FIESCH, day, time(10), time(17))


async def test_one_call_asks_for_both_models_in_zurich_time() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=load_fixture("ensemble_two_models.json"))

    await forecast_with(mock_transport(handler=handler))

    assert len(requests) == 1, "one HTTP call per forecast, two models inside it"
    params = requests[0].url.params
    assert requests[0].url.path == "/v1/ensemble"
    assert params["models"] == "icon_d2_eps,icon_eu_eps"
    assert params["hourly"] == "wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation"
    assert params["timezone"] == "Europe/Zurich"
    assert params["forecast_days"] == str(FORECAST_DAYS)
    assert (float(params["latitude"]), float(params["longitude"])) == FIESCH


async def test_returns_the_selected_ensemble() -> None:
    forecast = await forecast_with(mock_transport({"/ensemble": "ensemble_two_models.json"}))

    assert getattr(forecast, "model") == "icon_d2_eps"  # noqa: B009


async def test_out_of_range_passes_through_untouched() -> None:
    """DateOutOfRangeError is an answer for the model, not a shape error to be swallowed."""
    with pytest.raises(DateOutOfRangeError):
        await forecast_with(
            mock_transport({"/ensemble": "ensemble_two_models.json"}), day=date(2026, 10, 3)
        )


async def test_an_http_error_is_an_outage() -> None:
    with pytest.raises(UpstreamUnavailableError, match="HTTP 503"):
        await forecast_with(mock_transport(handler=lambda _: httpx2.Response(503, json={})))


async def test_a_timeout_is_an_outage() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(UpstreamUnavailableError, match="timed out"):
        await forecast_with(mock_transport(handler=handler))


async def test_an_unknown_shape_is_an_outage_not_a_crash() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"error": True, "reason": "something changed"})

    with pytest.raises(UpstreamUnavailableError, match="unexpected response shape"):
        await forecast_with(mock_transport(handler=handler))
