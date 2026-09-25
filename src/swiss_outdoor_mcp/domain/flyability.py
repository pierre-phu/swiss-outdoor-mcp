"""Turn a weather ensemble into a flyability indicator. Pure: no network, no clock.

The idea, in one paragraph. An ensemble is the same weather model run many times from slightly
perturbed starting conditions; each run is a "member". Instead of trusting one forecast, we ask
every member the same yes/no question — is this hour flyable at this launch? — and report the
share of members that say yes. That share is not a calibrated probability, but it is an honest
measure of how much the model agrees with itself.

The rules, all in `FlyabilityCriteria` and all echoed back in the output (`docs/SPEC.md` §2):

- A member-hour is flyable when wind, gust, precipitation *and* direction are all within limits.
- Direction: the wind must come from within `direction_tolerance_deg` of one of the sectors the
  launch faces. Open-Meteo reports where the wind comes *from* (`docs/api-notes.md` §2.2), which
  is exactly what an upslope wind on a south-facing launch looks like: from the south.
- The day counts for a member when it has at least `min_consecutive_hours` flyable hours in a
  row inside the window. One good hour between two bad ones is not a flight.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from swiss_outdoor_mcp.models import (
    CompassSector,
    EnsembleModel,
    Flyability,
    FlyabilityCriteria,
    HourlyFlyability,
    Site,
    WindSpread,
)

__all__ = [
    "ATTRIBUTION",
    "DISCLAIMER",
    "ZURICH",
    "EnsembleForecast",
    "MemberForecast",
    "angular_distance_deg",
    "compute_flyability",
    "longest_run",
    "sector_bearing_deg",
    "window_hours",
]

ZURICH = ZoneInfo("Europe/Zurich")

DISCLAIMER = (
    "Indicator only, computed from a weather-model ensemble. It does not replace pilot judgment, "
    "an on-site assessment of conditions, or official aviation weather forecasts."
)

# Required by the CC BY 4.0 licence of the data (docs/api-notes.md section 2.4).
ATTRIBUTION = "Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0."

_SECTORS: tuple[CompassSector, ...] = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)  # fmt: skip


@dataclass(frozen=True)
class MemberForecast:
    """One ensemble member's hourly series. All four are the same length as the time axis."""

    wind_speed_kmh: tuple[float, ...]
    wind_gusts_kmh: tuple[float, ...]
    wind_direction_deg: tuple[float, ...]
    precipitation_mm: tuple[float, ...]


@dataclass(frozen=True)
class EnsembleForecast:
    """Members x hours, from one model, with no gaps.

    This is the input of `compute_flyability`, deliberately not an HTTP response: the Open-Meteo
    key grammar and its `null` padding are dealt with in `domain.openmeteo` before we get here.
    """

    model: EnsembleModel
    times: tuple[datetime, ...]
    members: tuple[MemberForecast, ...]
    grid_elevation_m: float | None = None

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("an ensemble needs at least one member")
        if any(t.tzinfo is None for t in self.times):
            raise ValueError("ensemble times must be timezone-aware")
        n = len(self.times)
        for index, member in enumerate(self.members):
            lengths = {
                len(member.wind_speed_kmh),
                len(member.wind_gusts_kmh),
                len(member.wind_direction_deg),
                len(member.precipitation_mm),
            }
            if lengths != {n}:
                raise ValueError(f"member {index} has series of length {lengths}, expected {n}")


def sector_bearing_deg(sector: CompassSector) -> float:
    """Centre bearing of a 16-point sector: N is 0, NNE 22.5, ..., NNW 337.5."""
    return _SECTORS.index(sector) * 22.5


def angular_distance_deg(a: float, b: float) -> float:
    """Smallest angle between two bearings, 0-180. Handles the wrap: 350 vs 10 is 20, not 340."""
    difference = abs(a - b) % 360
    return min(difference, 360 - difference)


def longest_run(flags: list[bool]) -> int:
    """Length of the longest stretch of consecutive `True` values."""
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


def window_hours(criteria: FlyabilityCriteria) -> list[time]:
    """The local hours the window covers, both ends included: 10:00-17:00 is eight steps."""
    return [time(hour) for hour in range(criteria.window_start.hour, criteria.window_end.hour + 1)]


def _share(count: int, total: int) -> float:
    return round(count / total, 3)


def _spread(values: list[float]) -> WindSpread:
    if len(values) == 1:  # quantiles() needs two points; one member has no spread
        only = round(values[0], 1)
        return WindSpread(median=only, p10=only, p90=only)
    deciles = statistics.quantiles(values, n=10, method="inclusive")
    return WindSpread(
        median=round(statistics.median(values), 1),
        p10=round(deciles[0], 1),
        p90=round(deciles[-1], 1),
    )


def compute_flyability(
    forecast: EnsembleForecast,
    site: Site,
    day: date,
    criteria: FlyabilityCriteria,
    *,
    generated_at: datetime,
) -> Flyability:
    """Score one site on one day.

    Hours are matched on their Europe/Zurich wall-clock time, whatever timezone the forecast
    carries, and anything outside `day`'s window is ignored. The window must be complete —
    a missing hour would silently break a consecutive run — so a gap raises `ValueError`.
    That is a bug upstream of this function, never a user error: `domain.openmeteo` only hands
    over a model that covers the whole window.

    `generated_at` is passed in because this module does not read the clock.
    """
    local_hours = window_hours(criteria)
    by_local_time = {
        (t.astimezone(ZURICH).date(), t.astimezone(ZURICH).time()): i
        for i, t in enumerate(forecast.times)
    }
    missing = [h for h in local_hours if (day, h) not in by_local_time]
    if missing:
        raise ValueError(
            f"forecast does not cover {day} at " + ", ".join(h.strftime("%H:%M") for h in missing)
        )
    indices = [by_local_time[(day, h)] for h in local_hours]
    bearings = [sector_bearing_deg(sector) for sector in site.orientations]
    n = len(forecast.members)

    # flyable[m][k]: is member m flyable at the k-th hour of the window?
    flyable: list[list[bool]] = [[] for _ in forecast.members]
    hourly: list[HourlyFlyability] = []
    for hour, i in zip(local_hours, indices, strict=True):
        wind_ok = gust_ok = dry = direction_ok = all_ok = 0
        speeds: list[float] = []
        for m, member in enumerate(forecast.members):
            speeds.append(member.wind_speed_kmh[i])
            checks = (
                member.wind_speed_kmh[i] <= criteria.max_wind_kmh,
                member.wind_gusts_kmh[i] <= criteria.max_gust_kmh,
                member.precipitation_mm[i] <= criteria.max_precip_mm_h,
                min(angular_distance_deg(member.wind_direction_deg[i], b) for b in bearings)
                <= criteria.direction_tolerance_deg,
            )
            wind_ok += checks[0]
            gust_ok += checks[1]
            dry += checks[2]
            direction_ok += checks[3]
            all_ok += all(checks)
            flyable[m].append(all(checks))

        hourly.append(
            HourlyFlyability(
                time=datetime.combine(day, hour, tzinfo=ZURICH),
                p_wind_ok=_share(wind_ok, n),
                p_gust_ok=_share(gust_ok, n),
                p_dry=_share(dry, n),
                p_direction_ok=_share(direction_ok, n),
                p_flyable=_share(all_ok, n),
                wind_kmh=_spread(speeds),
            )
        )

    flyable_members = sum(longest_run(flags) >= criteria.min_consecutive_hours for flags in flyable)
    return Flyability(
        site_id=site.id,
        date=day,
        p_flyable=_share(flyable_members, n),
        hourly=hourly,
        model=forecast.model,
        n_members=n,
        grid_elevation_m=forecast.grid_elevation_m,
        criteria=criteria,
        method=_method(criteria, forecast.model, n),
        generated_at=generated_at,
        disclaimer=DISCLAIMER,
        attribution=ATTRIBUTION,
    )


def _method(criteria: FlyabilityCriteria, model: EnsembleModel, n: int) -> str:
    start = criteria.window_start.strftime("%H:%M")
    end = criteria.window_end.strftime("%H:%M")
    return (
        f"Each of the {n} members of the {model} ensemble is checked hour by hour against the "
        f"criteria (all limits inclusive; wind 10 m above the model's terrain). Hourly p_* values "
        f"are the share of members meeting each criterion. The day-level p_flyable is the share "
        f"of members with at least {criteria.min_consecutive_hours} consecutive flyable hours "
        f"between {start} and {end} Europe/Zurich, both ends included."
    )
