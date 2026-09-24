"""Turn raw transport.opendata.ch JSON into our models.

Pure functions on plain dicts: no network, no clock. Every awkward part of the upstream format
lives here rather than in the client, so it can be tested without a transport at all.

The three traps this module exists to absorb, all documented in `docs/api-notes.md` section 3.2:

1. `duration` is a string, `"00d04:41:00"`, not a number of minutes.
2. A section's endpoints are called `departure` / `arrival`, not `from` / `to`.
3. A checkpoint carries both a `station` and a `location` key holding the same object;
   `station` is the legacy alias, so we read `location`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from swiss_outdoor_mcp.models import Connection, Section, SectionMode, Station

__all__ = [
    "parse_duration_minutes",
    "to_connection",
    "to_section",
    "to_station",
]

# "00d04:41:00" -> 0 days, 4 hours, 41 minutes, 0 seconds.
_DURATION = re.compile(r"^(?P<days>\d+)d(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})$")

_CATEGORY_TO_MODE: dict[str, SectionMode] = {
    # Deliberately short. Each entry below is backed by something we have actually observed;
    # anything else falls through to "other" with the raw code preserved on Section.category,
    # because the API's category vocabulary is open-ended and guessing at it would be inventing
    # API facts. Extend this table when a fixture shows a new code — never from memory.
    #
    # Seen in tests/fixtures/connections_lausanne_leysin.json, operator SBB:
    "R": "train",
    "IR": "train",
    # docs/api-notes.md 3.2: "EV" is a rail-replacement bus.
    "EV": "bus",
    # docs/api-notes.md 3.3: "PB" was the Wengen-Maennlichen aerial cableway (operator LWM).
    "PB": "cableway",
    # docs/api-notes.md 3.3: "CC" was the WAB cog railway - rack rail, so a train.
    "CC": "train",
}


def parse_duration_minutes(raw: str) -> int:
    """Convert the API's `"DDdHH:MM:SS"` duration into whole minutes.

    Raises `ValueError` on anything that does not match, rather than silently returning 0 — a
    duration we cannot read is a shape change we want to hear about.
    """
    match = _DURATION.match(raw.strip())
    if match is None:
        raise ValueError(f"unrecognised duration {raw!r}, expected a 'DDdHH:MM:SS' string")
    parts = {key: int(value) for key, value in match.groupdict().items()}
    total_seconds = (
        parts["days"] * 86_400 + parts["hours"] * 3_600 + parts["minutes"] * 60 + parts["seconds"]
    )
    # Half-up, written out rather than via round(), which is banker's rounding: round(0.5) is 0,
    # so a 30-second leg would come back as 0 minutes. Timetables always report whole minutes, so
    # this only matters if the upstream format ever changes — which is exactly when we want it
    # to behave predictably.
    return (total_seconds + 30) // 60


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse the API's ISO timestamps, which carry a `+0200`-style offset (no colon)."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _checkpoint_name(checkpoint: dict[str, Any] | None) -> str:
    """Name of the stop at a checkpoint, preferring `location` over the legacy `station` alias."""
    if not checkpoint:
        return ""
    for key in ("location", "station"):
        value = checkpoint.get(key)
        if isinstance(value, dict) and value.get("name"):
            return str(value["name"])
    return ""


def _line_name(category: str | None, number: object) -> str | None:
    """Build the line label a timetable would print, e.g. `"IR 95"`.

    `journey.name` is an internal code such as `"024211"`, so the label comes from category plus
    number instead. Some categories already repeat themselves in the number (`EV` + `EV1`), so the
    prefix is dropped when it would only be duplicated.
    """
    if not category:
        return None
    if number is None or str(number).strip() == "":
        return category
    text = str(number).strip()
    if text.upper().startswith(category.upper()):
        return text
    return f"{category} {text}"


def to_station(raw: dict[str, Any]) -> Station:
    """Map one `/locations` entry.

    Note the axis order: `coordinate.x` is the **latitude** and `coordinate.y` the **longitude**.
    Getting this backwards puts Swiss stops in Somalia (`docs/api-notes.md` section 3.1).
    """
    coordinate = raw.get("coordinate") or {}
    raw_id = raw.get("id")
    return Station(
        id=str(raw_id) if raw_id is not None else None,
        name=str(raw.get("name") or ""),
        lat=coordinate.get("x"),
        lon=coordinate.get("y"),
    )


def to_section(raw: dict[str, Any]) -> Section:
    """Map one section. A section with no `journey` is a walking leg."""
    journey = raw.get("journey")
    departure = raw.get("departure") or {}
    arrival = raw.get("arrival") or {}

    if not isinstance(journey, dict):
        mode: SectionMode = "walk"
        category: str | None = None
        line: str | None = None
    else:
        category = journey.get("category") or None
        mode = _CATEGORY_TO_MODE.get(category or "", "other")
        line = _line_name(category, journey.get("number"))

    return Section(
        mode=mode,
        category=category,
        line=line,
        from_stop=_checkpoint_name(departure),
        to_stop=_checkpoint_name(arrival),
        # A checkpoint holds both keys; only the relevant one is populated.
        departure=_parse_dt(departure.get("departure")),
        arrival=_parse_dt(arrival.get("arrival")),
    )


def to_connection(raw: dict[str, Any]) -> Connection:
    """Map one connection, including every section."""
    origin = raw.get("from") or {}
    destination = raw.get("to") or {}
    sections = [to_section(section) for section in raw.get("sections") or []]
    return Connection(
        departure=_parse_dt(origin.get("departure")),
        arrival=_parse_dt(destination.get("arrival")),
        duration_min=parse_duration_minutes(str(raw.get("duration", ""))),
        transfers=int(raw.get("transfers") or 0),
        sections=sections,
    )
