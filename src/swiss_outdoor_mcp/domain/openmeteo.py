"""Turn a raw two-model Open-Meteo ensemble response into an `EnsembleForecast`.

Pure functions on plain dicts: no network, no clock. The traps this module absorbs, all
documented in `docs/api-notes.md` sections 2.3-2.6:

1. Members are not an array. Each one is a sibling key of `hourly`, named
   `<variable>[_memberNN]_<model_id>`; the unsuffixed series is the control run and counts as a
   member, so the member count is read off the keys, never hard-coded.
2. Both models share one time axis. The shorter one is padded with `null` to the longer one's
   horizon, so "does this model cover the window" is a non-null test.
3. The horizon drifts with each model run, so which model answers — and which dates can be
   answered at all — is read off the `null`s, never computed from the lead time.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any

from swiss_outdoor_mcp.domain.flyability import ZURICH, EnsembleForecast, MemberForecast
from swiss_outdoor_mcp.errors import DateOutOfRangeError, UpstreamUnavailableError
from swiss_outdoor_mcp.models import EnsembleModel

__all__ = ["MODELS", "SERVICE", "VARIABLES", "member_keys", "select_forecast"]

SERVICE = "weather forecast (Open-Meteo)"

# Order is preference: the 2 km grid wins whenever it covers the window (api-notes.md 2.6).
MODELS: tuple[EnsembleModel, ...] = ("icon_d2_eps", "icon_eu_eps")

# The hourly variables we request, in the order MemberForecast stores them.
VARIABLES: tuple[str, ...] = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "precipitation",
)


def member_keys(hourly: dict[str, Any], variable: str, model: EnsembleModel) -> list[str]:
    """The keys holding `variable` for every member of `model`, control run first.

    Returns an empty list when the model is absent from the response.
    """
    pattern = re.compile(rf"^{variable}(?:_member(\d{{2}}))?_{model}$")
    found: list[tuple[int, str]] = []
    for key in hourly:
        match = pattern.match(key)
        if match:
            found.append((int(match.group(1) or 0), key))
    return [key for _, key in sorted(found)]


def _local_times(hourly: dict[str, Any]) -> list[datetime]:
    # The client asks for timezone=Europe/Zurich, so the times arrive as naive local wall-clock
    # strings (api-notes.md 2.3). Attaching the zone here keeps every later step unambiguous.
    return [datetime.fromisoformat(raw).replace(tzinfo=ZURICH) for raw in hourly["time"]]


def _covers(hourly: dict[str, Any], model: EnsembleModel, indices: list[int]) -> bool:
    """True when every series of `model` has a value at every index."""
    keys = [key for variable in VARIABLES for key in member_keys(hourly, variable, model)]
    return bool(keys) and all(hourly[key][i] is not None for key in keys for i in indices)


def _answering_model(
    hourly: dict[str, Any], times: list[datetime], day: date, start: time, end: time
) -> tuple[EnsembleModel, list[int]] | None:
    """The preferred model covering `day`'s whole window, with the window's indices, or None."""
    indices = [i for i, t in enumerate(times) if t.date() == day and start <= t.time() <= end]
    if len(indices) != end.hour - start.hour + 1:
        return None  # the date is not on the time axis at all
    for model in MODELS:
        if _covers(hourly, model, indices):
            return model, indices
    return None


def _build(
    payload: dict[str, Any], model: EnsembleModel, times: list[datetime], indices: list[int]
) -> EnsembleForecast:
    hourly = payload["hourly"]
    per_variable = [member_keys(hourly, variable, model) for variable in VARIABLES]
    counts = {len(keys) for keys in per_variable}
    if len(counts) != 1:
        raise ValueError(f"{model}: variables disagree on the member count: {sorted(counts)}")

    members = tuple(
        MemberForecast(*(tuple(float(hourly[key][i]) for i in indices) for key in member_series))
        for member_series in zip(*per_variable, strict=True)
    )
    elevation = payload.get("elevation")
    return EnsembleForecast(
        model=model,
        times=tuple(times[i] for i in indices),
        members=members,
        grid_elevation_m=float(elevation) if elevation is not None else None,
    )


def select_forecast(payload: dict[str, Any], day: date, start: time, end: time) -> EnsembleForecast:
    """Pick the model that answers for `day`'s window and return it, sliced to that window.

    The rule of `docs/api-notes.md` section 2.6: the first model in `MODELS` with no `null`
    anywhere in the window wins; the two ensembles are never pooled. If none covers it, raise
    `DateOutOfRangeError` quoting the dates that *can* be answered, found in this response.

    Raises `ValueError` or `KeyError` on a response whose shape we do not recognise.
    """
    hourly = payload["hourly"]
    times = _local_times(hourly)

    answer = _answering_model(hourly, times, day, start, end)
    if answer is not None:
        model, indices = answer
        return _build(payload, model, times, indices)

    covered = sorted(
        candidate
        for candidate in {t.date() for t in times}
        if _answering_model(hourly, times, candidate, start, end) is not None
    )
    if not covered:
        # Nothing answers for any date: that is the service failing, not a bad date.
        raise UpstreamUnavailableError(SERVICE, "no ensemble returned data for any date")
    raise DateOutOfRangeError(day, covered[0], covered[-1])
