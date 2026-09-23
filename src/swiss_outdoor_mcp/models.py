"""Pydantic models for tool inputs, tool outputs and the YAML data files.

Day 1 covers only what `data/` needs. The forecast and connection models arrive with their tools.
"""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

__all__ = [
    "CompassSector",
    "EmissionFactor",
    "EmissionFactorsFile",
    "Site",
    "SitesFile",
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


class EmissionFactor(_Strict):
    """One emission factor, with the source it came from. Values are Pierre's to fill."""

    value_kg_per_pkm: Annotated[float, Field(ge=0, description="kg CO2e per passenger-kilometre")]
    source_name: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    retrieved_on: date


class EmissionFactorsFile(_Strict):
    """Top level of `data/emission_factors.yaml`: one factor per transport mode."""

    factors: dict[TransportMode, EmissionFactor]
