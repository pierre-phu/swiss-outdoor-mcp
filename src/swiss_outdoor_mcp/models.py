"""Pydantic models for tool inputs, tool outputs and the YAML data files."""

from datetime import date, datetime, time
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

__all__ = [
    "CompassSector",
    "Connection",
    "ConnectionQuery",
    "EmissionFactor",
    "EmissionFactorsFile",
    "EnsembleModel",
    "Flyability",
    "FlyabilityCriteria",
    "HourlyFlyability",
    "Section",
    "SectionMode",
    "Site",
    "SitesFile",
    "Station",
    "TransportMode",
    "WindSpread",
]

# fmt: off
CompassSector = Literal[
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]
# fmt: on
"""A 16-point compass sector. A launch site's `orientations` list the directions it faces."""

TransportMode = Literal["train", "bus", "car"]
"""A mode we hold an emission factor for. Unrelated to `SectionMode`."""

SectionMode = Literal["train", "tram", "ship", "bus", "cableway", "walk", "other"]
"""How one leg of a journey is travelled.

The five vehicle values are the transport API's own documented `transportations` vocabulary
(`docs/api-notes.md` section 3.2), rather than a set we invented. `walk` is a leg with no vehicle,
and `other` is the deliberate escape hatch: the API's raw category codes are open-ended, so an
unrecognised one becomes `other` while `Section.category` keeps the code verbatim.
"""


class _Strict(BaseModel):
    """Reject unknown keys, so a typo in the YAML fails loudly instead of being ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Site(_Strict):
    """A paragliding launch site. Content is hand-written by Pierre in `data/sites.yaml`."""

    id: Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", min_length=2, max_length=64)]
    name: Annotated[str, Field(min_length=1)]
    region: Annotated[str, Field(min_length=1)]
    lat: Annotated[float, Field(ge=45.8, le=47.9, description="WGS84 latitude, Switzerland only")]
    lon: Annotated[float, Field(ge=5.9, le=10.6, description="WGS84 longitude, Switzerland only")]
    altitude_m: Annotated[int, Field(ge=0, le=4700)]
    orientations: Annotated[list[CompassSector], Field(min_length=1)]
    nearest_stop: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Stop name exactly as the Swiss timetable knows it. Verify it resolves via "
                "transport.opendata.ch /locations before adding a site."
            ),
        ),
    ]
    access_notes: str = ""

    @model_validator(mode="after")
    def _no_duplicate_orientations(self) -> Self:
        if len(set(self.orientations)) != len(self.orientations):
            raise ValueError(f"site {self.id!r} lists the same orientation twice")
        return self


class SitesFile(_Strict):
    """Top level of `data/sites.yaml`."""

    sites: list[Site]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        seen: set[str] = set()
        for site in self.sites:
            if site.id in seen:
                raise ValueError(f"duplicate site id {site.id!r}")
            seen.add(site.id)
        return self


class Station(_Strict):
    """A stop as the transport API knows it.

    `id` is `None` for the addresses and points of interest that `/locations` mixes into its
    results; those are not stops and cannot be routed to (`docs/api-notes.md` section 3.5).
    """

    id: str | None
    name: Annotated[str, Field(min_length=1)]
    lat: float | None = None
    lon: float | None = None


class Section(_Strict):
    """One leg of a journey: a single vehicle, or a walk between two stops."""

    mode: SectionMode
    category: str | None = Field(
        default=None,
        description="Raw category code from the API, e.g. 'R', 'IR', 'PB'. None on a walking leg.",
    )
    line: str | None = Field(
        default=None,
        description="Human-readable line, e.g. 'IR 95'. None on a walking leg.",
    )
    from_stop: str
    to_stop: str
    departure: datetime | None = None
    arrival: datetime | None = None


class Connection(_Strict):
    """One end-to-end journey option."""

    departure: datetime | None = None
    arrival: datetime | None = None
    duration_min: Annotated[int, Field(ge=0)]
    transfers: Annotated[int, Field(ge=0)]
    sections: list[Section]


class ConnectionQuery(_Strict):
    """A validated `get_connections` request.

    Carries the SPEC rule that a caller may anchor the search to an arrival time or a departure
    time, but not both — the API has a single `time` parameter plus an `isArrivalTime` flag, so
    asking for both is meaningless rather than merely redundant.
    """

    origin: Annotated[str, Field(min_length=1)]
    destination: Annotated[str, Field(min_length=1)]
    date: date
    arrive_before: time | None = None
    depart_after: time | None = None
    limit: Annotated[int, Field(ge=1, le=16)] = 3

    @model_validator(mode="after")
    def _at_most_one_time_anchor(self) -> Self:
        if self.arrive_before is not None and self.depart_after is not None:
            raise ValueError(
                "Set at most one of arrive_before or depart_after, not both. "
                "Use arrive_before to be somewhere by a time, depart_after to leave after one."
            )
        return self


EnsembleModel = Literal["icon_d2_eps", "icon_eu_eps"]
"""The two Open-Meteo ensembles `get_flyability` reads, in order of preference.

`icon_d2_eps` is the 2 km grid with 20 members, reaching about two days out; `icon_eu_eps` is the
13 km grid with 40 members, reaching about five (`docs/api-notes.md` sections 2.1 and 2.6).
"""

Probability = Annotated[float, Field(ge=0, le=1)]


class FlyabilityCriteria(_Strict):
    """The thresholds a member-hour must meet to count as flyable.

    Every limit is inclusive: a wind of exactly `max_wind_kmh` passes. The window is inclusive
    at both ends too, so the default 10:00-17:00 is eight hourly steps. The whole object is
    echoed in every `Flyability`, so the answer always says what it assumed.
    """

    max_wind_kmh: Annotated[float, Field(gt=0, description="Mean wind at 10 m, at most.")] = 20.0
    max_gust_kmh: Annotated[
        float, Field(gt=0, description="Strongest gust in the preceding hour, at most.")
    ] = 30.0
    max_precip_mm_h: Annotated[
        float, Field(ge=0, description="Precipitation in the preceding hour, at most.")
    ] = 0.1
    direction_tolerance_deg: Annotated[
        float,
        Field(
            ge=0,
            le=180,
            description="How far the wind may come from off one of the launch's orientations.",
        ),
    ] = 45.0
    window_start: time = Field(default=time(10), description="Local time, Europe/Zurich.")
    window_end: time = Field(default=time(17), description="Local time, Europe/Zurich, inclusive.")
    min_consecutive_hours: Annotated[int, Field(ge=1)] = 3

    @model_validator(mode="after")
    def _window_is_whole_hours_and_long_enough(self) -> Self:
        for bound in (self.window_start, self.window_end):
            if (bound.minute, bound.second, bound.microsecond) != (0, 0, 0):
                raise ValueError(f"window bounds must be whole hours, got {bound.isoformat()}")
        if self.window_start >= self.window_end:
            raise ValueError("window_start must be before window_end")
        steps = self.window_end.hour - self.window_start.hour + 1
        if self.min_consecutive_hours > steps:
            raise ValueError(
                f"min_consecutive_hours={self.min_consecutive_hours} can never be met "
                f"in a {steps}-step window"
            )
        return self


class WindSpread(_Strict):
    """How much the ensemble members disagree about the wind at one hour, in km/h."""

    median: float
    p10: float
    p90: float


class HourlyFlyability(_Strict):
    """One hour of the window: the share of members meeting each criterion, then all of them."""

    time: datetime
    p_wind_ok: Probability
    p_gust_ok: Probability
    p_dry: Probability
    p_direction_ok: Probability
    p_flyable: Probability
    wind_kmh: WindSpread


class Flyability(_Strict):
    """The answer of `get_flyability`: an ensemble-based indicator for one site and one day."""

    site_id: str
    date: date
    p_flyable: Probability = Field(
        description=(
            "Share of ensemble members with at least min_consecutive_hours consecutive "
            "flyable hours inside the window."
        )
    )
    hourly: list[HourlyFlyability]
    model: EnsembleModel = Field(
        description="Which ensemble answered: icon_d2_eps is the 2 km grid, icon_eu_eps 13 km."
    )
    n_members: Annotated[int, Field(ge=1)]
    grid_elevation_m: float | None = Field(
        default=None,
        description=(
            "Terrain height of the model's grid cell. Winds are 10 m above this, "
            "which may be far from the launch altitude."
        ),
    )
    criteria: FlyabilityCriteria
    method: str
    generated_at: datetime
    disclaimer: str
    attribution: str


class EmissionFactor(_Strict):
    """One emission factor, with the source it came from. Values are Pierre's to fill."""

    value_kg_per_pkm: Annotated[float, Field(ge=0, description="kg CO2e per passenger-kilometre")]
    source_name: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    retrieved_on: date


class EmissionFactorsFile(_Strict):
    """Top level of `data/emission_factors.yaml`: one factor per transport mode."""

    factors: dict[TransportMode, EmissionFactor]
