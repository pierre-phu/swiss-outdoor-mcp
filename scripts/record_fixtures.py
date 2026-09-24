"""Record real API responses into `tests/fixtures/`, once, by hand.

The test suite must never reach the network (`CLAUDE.md`), so every client test replays one of
these files through an `httpx2.MockTransport`. Re-run this script only when an upstream response
shape changes, and read the diff before committing it: a fixture is the only thing standing
between us and a silent upstream change.

    uv run python scripts/record_fixtures.py

Each fixture is written pretty-printed so that `git diff` on it is readable.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

TRANSPORT_BASE = "https://transport.opendata.ch/v1"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

# (filename, base url, path, query, pretty) — one entry per recorded response.
# `pretty=False` is for the ensemble file: it is thousands of floats, so indenting it doubles the
# size without making any diff readable.
RECORDINGS: list[tuple[str, str, str, dict[str, Any], bool]] = [
    # Happy path: Lausanne to a real site stop. `limit=2` keeps the file small.
    (
        "connections_lausanne_leysin.json",
        TRANSPORT_BASE,
        "/connections",
        {"from": "Lausanne", "to": "Leysin-Feydey", "limit": 2},
        True,
    ),
    # Unknown stop: HTTP 200 with nulls, and no hint about which side failed.
    # See docs/api-notes.md section 3.6.
    (
        "connections_unknown_stop.json",
        TRANSPORT_BASE,
        "/connections",
        {"from": "Lausanne", "to": "NotARealStopXYZ", "limit": 1},
        True,
    ),
    # A near miss an LLM would plausibly produce: the real stop is hyphenated.
    # Drives the suggestions in StopNotFoundError.
    (
        "locations_leysin_feydey.json",
        TRANSPORT_BASE,
        "/locations",
        {"query": "Leysin Feydey"},
        True,
    ),
    (
        "locations_lausanne.json",
        TRANSPORT_BASE,
        "/locations",
        {"query": "Lausanne", "type": "station"},
        True,
    ),
    (
        "locations_unknown.json",
        TRANSPORT_BASE,
        "/locations",
        {"query": "NotARealStopXYZ"},
        True,
    ),
    # Day 3's fixture, recorded now: one call, both ensembles, so the null-padding that
    # decides model selection (docs/api-notes.md 2.5-2.6) is present in the file.
    (
        "ensemble_two_models.json",
        ENSEMBLE_URL,
        "",
        {
            "latitude": 46.4048,
            "longitude": 8.09598,
            "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation",
            "models": "icon_d2_eps,icon_eu_eps",
            "forecast_days": 5,
            "timezone": "Europe/Zurich",
        },
        False,
    ),
]


async def record_one(
    client: httpx2.AsyncClient,
    name: str,
    base: str,
    path: str,
    params: dict[str, Any],
    pretty: bool,
) -> None:
    response = await client.get(base + path, params=params)
    response.raise_for_status()
    target = FIXTURES / name
    body = json.dumps(response.json(), indent=2 if pretty else None, ensure_ascii=False)
    target.write_text(body + "\n")
    print(f"  {name:36s} {response.status_code}  {target.stat().st_size:>8,d} bytes")


async def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    print(f"Recording {len(RECORDINGS)} fixtures into {FIXTURES}")
    async with httpx2.AsyncClient(timeout=30.0) as client:
        for name, base, path, params, pretty in RECORDINGS:
            await record_one(client, name, base, path, params, pretty)
    print("Done. Read the diff before committing.")


if __name__ == "__main__":
    asyncio.run(main())
