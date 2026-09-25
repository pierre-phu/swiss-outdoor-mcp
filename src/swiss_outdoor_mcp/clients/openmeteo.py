"""Async client for the Open-Meteo Ensemble API.

I/O only: this module builds the request, handles failures and hands the JSON to
`domain.openmeteo` for model selection and shaping. It holds no business logic.

One HTTP call per forecast, asking for both ensembles at once (`docs/api-notes.md` section 2.5).
"""

from __future__ import annotations

from datetime import date, time
from types import TracebackType
from typing import Self

import httpx2

from swiss_outdoor_mcp.clients._http import get_json
from swiss_outdoor_mcp.domain.flyability import EnsembleForecast
from swiss_outdoor_mcp.domain.openmeteo import MODELS, SERVICE, VARIABLES, select_forecast
from swiss_outdoor_mcp.errors import UpstreamUnavailableError

__all__ = ["FORECAST_DAYS", "OpenMeteoClient"]

BASE_URL = "https://ensemble-api.open-meteo.com/v1"
DEFAULT_TIMEOUT = 15.0

# Today plus four: everything icon_eu_eps has answered for in our probes (api-notes.md 2.5-2.6).
# Asking for more buys no horizon, only a longer tail of nulls. Coverage inside these days is
# still read off the response, never assumed from this number.
FORECAST_DAYS = 5


class OpenMeteoClient:
    """Talks to the Open-Meteo Ensemble API.

    The `transport` argument is what makes the tests offline: they pass an
    `httpx2.MockTransport` serving recorded fixtures. Left as `None`, the client goes to the
    real network.
    """

    def __init__(
        self,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_forecast(
        self, lat: float, lon: float, day: date, window_start: time, window_end: time
    ) -> EnsembleForecast:
        """Return the ensemble that answers for `day`'s window at this point.

        Raises `DateOutOfRangeError` when neither model covers the window, and
        `UpstreamUnavailableError` when the service fails or answers in a shape we do not know.
        """
        payload = await get_json(
            self._client,
            SERVICE,
            "/ensemble",
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": ",".join(VARIABLES),
                "models": ",".join(MODELS),
                "forecast_days": FORECAST_DAYS,
                # Without it times come back as naive UTC (api-notes.md 2.3).
                "timezone": "Europe/Zurich",
            },
        )
        try:
            return select_forecast(payload, day, window_start, window_end)
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamUnavailableError(SERVICE, "unexpected response shape") from exc
