"""Pydantic models for tool inputs, tool outputs and the YAML data files.

The forecast models arrive with `get_flyability` on day 3.
"""

from datetime import date, datetime, time
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

__all__ = [
    "CompassSector",
    "Connection",
    "ConnectionQuery",
    "EmissionFactor",
    "EmissionFactorsFile",
    "Section",
    "SectionMode",
    "Site",
    "SitesFile",
    "Station",
    "TransportMode",
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


class EmissionFactor(_Strict):
    """One emission factor, with the source it came from. Values are Pierre's to fill."""

    value_kg_per_pkm: Annotated[float, Field(ge=0, description="kg CO2e per passenger-kilometre")]
    source_name: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    retrieved_on: date


class EmissionFactorsFile(_Strict):
    """Top level of `data/emission_factors.yaml`: one factor per transport mode."""

    factors: dict[TransportMode, EmissionFactor]
