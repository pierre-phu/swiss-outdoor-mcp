"""The one HTTP helper both clients share: GET, decode, and map every failure the same way."""

from __future__ import annotations

from typing import Any

import httpx2

from swiss_outdoor_mcp.errors import UpstreamUnavailableError

__all__ = ["get_json"]


async def get_json(
    client: httpx2.AsyncClient, service: str, path: str, params: dict[str, Any]
) -> dict[str, Any]:
    """GET and decode, mapping every possible failure onto `UpstreamUnavailableError`.

    A timeout, a refused connection, a 500 and a body that is not JSON are all the same thing
    to the caller: we could not get an answer, and it says nothing about the question asked. The
    error message says exactly that, so the model does not report "no trains" or "not flyable".
    """
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx2.HTTPStatusError as exc:
        raise UpstreamUnavailableError(service, f"HTTP {exc.response.status_code}") from exc
    except httpx2.TimeoutException as exc:
        raise UpstreamUnavailableError(service, "timed out") from exc
    except httpx2.HTTPError as exc:
        raise UpstreamUnavailableError(service, type(exc).__name__) from exc
    except ValueError as exc:  # json() on a non-JSON body
        raise UpstreamUnavailableError(service, "malformed response") from exc

    if not isinstance(payload, dict):
        raise UpstreamUnavailableError(service, "malformed response")
    return payload
