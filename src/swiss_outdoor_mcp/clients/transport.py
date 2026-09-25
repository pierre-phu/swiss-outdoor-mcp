"""Async client for transport.opendata.ch.

I/O only: this module builds requests, handles failures and hands the JSON to
`domain.transport` for shaping. It holds no business logic.

Call budget matters here. The API states no rate limit and no licence, and self-describes as
"inofficial" (`docs/api-notes.md` section 3.4), so Pierre's rule is one call per user question and
never a loop over sites. The one place we spend more is the error path below, where two extra
lookups turn a dead end into something the model can recover from.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx2

from swiss_outdoor_mcp.domain.transport import to_connection, to_station
from swiss_outdoor_mcp.errors import StopNotFoundError, UpstreamUnavailableError
from swiss_outdoor_mcp.models import Connection, ConnectionQuery, Station

__all__ = ["TransportClient"]

SERVICE = "Swiss timetable (transport.opendata.ch)"
BASE_URL = "https://transport.opendata.ch/v1"
DEFAULT_TIMEOUT = 10.0

# How many alternative stop names to offer when a lookup fails.
MAX_SUGGESTIONS = 3


class TransportClient:
    """Talks to transport.opendata.ch.

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

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET and decode, mapping every possible failure onto `UpstreamUnavailableError`.

        A timeout, a refused connection, a 500 and a body that is not JSON are all the same thing
        to the caller: we could not get an answer, and it says nothing about whether a connection
        exists. The error message says exactly that, so the model does not report "no trains".
        """
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx2.HTTPStatusError as exc:
            raise UpstreamUnavailableError(SERVICE, f"HTTP {exc.response.status_code}") from exc
        except httpx2.TimeoutException as exc:
            raise UpstreamUnavailableError(SERVICE, "timed out") from exc
        except httpx2.HTTPError as exc:
            raise UpstreamUnavailableError(SERVICE, type(exc).__name__) from exc
        except ValueError as exc:  # json() on a non-JSON body
            raise UpstreamUnavailableError(SERVICE, "malformed response") from exc

        if not isinstance(payload, dict):
            raise UpstreamUnavailableError(SERVICE, "malformed response")
        return payload

    async def search_locations(self, query: str, *, stations_only: bool = True) -> list[Station]:
        """Look a stop name up. Fuzzy: "Leysin Feydey" finds "Leysin-Feydey".

        Entries with a `null` id are addresses and points of interest rather than stops, and
        cannot be routed to, so `stations_only` drops them by default
        (`docs/api-notes.md` section 3.5).
        """
        payload = await self._get("/locations", {"query": query})
        stations = [to_station(raw) for raw in payload.get("stations") or []]
        if stations_only:
            stations = [station for station in stations if station.id]
        return stations

    async def find_connections(self, query: ConnectionQuery) -> list[Connection]:
        """Return journey options, best first.

        An empty list means "nothing runs then", which is a real answer. An unrecognised stop is
        not — that raises `StopNotFoundError` naming the offending stop.
        """
        params: dict[str, Any] = {
            "from": query.origin,
            "to": query.destination,
            "date": query.date.isoformat(),
            "limit": query.limit,
        }
        if query.arrive_before is not None:
            params["time"] = query.arrive_before.strftime("%H:%M")
            params["isArrivalTime"] = 1
        elif query.depart_after is not None:
            params["time"] = query.depart_after.strftime("%H:%M")
            params["isArrivalTime"] = 0

        payload = await self._get("/connections", params)

        # The API answers an unknown stop with HTTP 200 and nulls, and does not say which side
        # failed even when only one is bad (docs/api-notes.md 3.6). Populated `from`/`to` mean
        # both stops resolved, so an empty list there is genuinely "no service".
        if payload.get("from") is None or payload.get("to") is None:
            await self._raise_for_unknown_stop(query)

        return [to_connection(raw) for raw in payload.get("connections") or []]

    async def _raise_for_unknown_stop(self, query: ConnectionQuery) -> None:
        """Work out which stop the API could not resolve, and suggest alternatives.

        Costs up to two extra calls, on the error path only. Worth it: without them the model is
        told that one of two names is wrong but not which, and has nothing to retry with.
        """
        for stop in (query.origin, query.destination):
            matches = await self.search_locations(stop)
            exact = any(station.name.casefold() == stop.casefold() for station in matches)
            if not exact:
                suggestions = [station.name for station in matches[:MAX_SUGGESTIONS]]
                raise StopNotFoundError(stop, suggestions=suggestions)

        # Both names resolve on their own, so the failure is not a spelling problem.
        raise UpstreamUnavailableError(
            SERVICE, "the timetable returned no route and did not say why"
        )
