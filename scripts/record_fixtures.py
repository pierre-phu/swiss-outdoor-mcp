"""Record real API responses into `tests/fixtures/`, once, by hand.

The test suite must never reach the network (`CLAUDE.md`), so every client test replays one of
these files through an `httpx2.MockTransport`. Re-run this script only when an upstream response
shape changes, and read the diff before committing it: a fixture is the only thing standing
between us and a silent upstream change.

    uv run python scripts/record_fixtures.py            # the unit-test fixtures
    uv run python scripts/record_fixtures.py --offline  # the offline-mode set, for the evals

Each transport fixture is written pretty-printed so that `git diff` on it is readable.

The offline set (`tests/fixtures/offline/`) is what `SWISS_OUTDOOR_OFFLINE=1` replays. It covers a
fixed window, OFFLINE_START to OFFLINE_END, whatever day it is recorded on: both APIs accept
past dates (docs/api-notes.md sections 2.7 and 3.8). That keeps "Saturday" answerable in the
evals, which tell the agent that today is EVAL_TODAY. It loops over the sites once, by hand;
the server's own one-call rule is about answering a question, not about recording.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import httpx2

from swiss_outdoor_mcp.clients.offline import MANIFEST
from swiss_outdoor_mcp.data_loader import load_sites
from swiss_outdoor_mcp.domain.openmeteo import MODELS, VARIABLES

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OFFLINE = FIXTURES / "offline"

# The offline window. EVAL_TODAY is a Friday, so the evals' "Saturday" is OFFLINE_SATURDAY.
OFFLINE_START = date(2026, 9, 25)
OFFLINE_END = date(2026, 9, 29)
EVAL_TODAY = date(2026, 9, 25)
OFFLINE_SATURDAY = date(2026, 9, 26)
ORIGIN = "Lausanne"

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
    directory: Path = FIXTURES,
) -> None:
    # transport.opendata.ch has dropped a pooled connection mid-run before, so retry a transport
    # failure a couple of times, pausing first. HTTP error statuses are never retried.
    for attempt in range(3):
        try:
            response = await client.get(base + path, params=params)
            break
        except httpx2.TransportError:
            if attempt == 2:
                raise
            await asyncio.sleep(2.0 * (attempt + 1))
    response.raise_for_status()
    target = directory / name
    body = json.dumps(response.json(), indent=2 if pretty else None, ensure_ascii=False)
    target.write_text(body + "\n")
    print(f"  {name:40s} {response.status_code}  {target.stat().st_size:>8,d} bytes")


def slug(text: str) -> str:
    """ASCII file-name form of a stop name: "Verbier, Médran" -> "verbier-medran"."""
    ascii_only = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")


def offline_recordings() -> list[tuple[str, str, str, dict[str, Any], bool, dict[str, str]]]:
    """Every request the offline set needs, each with the parameters offline mode matches on.

    Matching keys must agree with `clients.offline.MATCH_KEYS`; the offline tests check that
    every tool finds its recording.
    """
    recordings: list[tuple[str, str, str, dict[str, Any], bool, dict[str, str]]] = []
    stops = [ORIGIN]
    for site in load_sites():
        recordings.append(
            (
                f"ensemble_{site.id}.json",
                ENSEMBLE_URL,
                "",
                {
                    "latitude": site.lat,
                    "longitude": site.lon,
                    "hourly": ",".join(VARIABLES),
                    "models": ",".join(MODELS),
                    "start_date": OFFLINE_START.isoformat(),
                    "end_date": OFFLINE_END.isoformat(),
                    "timezone": "Europe/Zurich",
                },
                False,
                {"latitude": str(site.lat), "longitude": str(site.lon)},
            )
        )
        recordings.append(
            (
                f"connections_{slug(ORIGIN)}_{slug(site.nearest_stop)}.json",
                TRANSPORT_BASE,
                "/connections",
                {
                    "from": ORIGIN,
                    "to": site.nearest_stop,
                    "date": OFFLINE_SATURDAY.isoformat(),
                    "time": "08:00",
                    "limit": 3,
                },
                True,
                {"from": ORIGIN, "to": site.nearest_stop},
            )
        )
        if site.nearest_stop not in stops:
            stops.append(site.nearest_stop)
    for stop in stops:
        recordings.append(
            (
                f"locations_{slug(stop)}.json",
                TRANSPORT_BASE,
                "/locations",
                {"query": stop},
                True,
                {"query": stop},
            )
        )
    return recordings


def endpoint_of(base: str, path: str) -> str:
    return path or "/" + base.rstrip("/").rsplit("/", 1)[-1]


async def main(offline: bool, force: bool) -> None:
    if not offline:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        print(f"Recording {len(RECORDINGS)} fixtures into {FIXTURES}")
        async with httpx2.AsyncClient(timeout=30.0) as client:
            for name, base, path, params, pretty in RECORDINGS:
                await record_one(client, name, base, path, params, pretty)
        print("Done. Read the diff before committing.")
        return

    OFFLINE.mkdir(parents=True, exist_ok=True)
    recordings = offline_recordings()
    print(f"Recording {len(recordings)} offline fixtures into {OFFLINE}")
    manifest: list[dict[str, Any]] = []
    async with httpx2.AsyncClient(timeout=30.0) as client:
        for name, base, path, params, pretty, match in recordings:
            if (OFFLINE / name).exists() and not force:
                print(f"  {name:40s} kept (pass --force to re-record)")
            else:
                await record_one(client, name, base, path, params, pretty, OFFLINE)
                await asyncio.sleep(1.0)  # one request a second: the API states no limit
            manifest.append({"endpoint": endpoint_of(base, path), "match": match, "file": name})
    body = {
        "recorded_on": date.today().isoformat(),
        "window": {"start": OFFLINE_START.isoformat(), "end": OFFLINE_END.isoformat()},
        "eval_today": EVAL_TODAY.isoformat(),
        "note": (
            "Replayed by SWISS_OUTDOOR_OFFLINE=1. Matched on place only; dates, times and "
            "limits in a request are ignored. Written by scripts/record_fixtures.py --offline."
        ),
        "recordings": manifest,
    }
    (OFFLINE / MANIFEST).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    print("Done. Read the diff before committing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="record the offline-mode set")
    parser.add_argument(
        "--force", action="store_true", help="with --offline, re-record files that already exist"
    )
    args = parser.parse_args()
    asyncio.run(main(args.offline, args.force))
