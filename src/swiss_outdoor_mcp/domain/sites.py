"""Filtering over the launch sites. Pure: the caller loads the data.

`list_sites` is the LLM's entry point into the catalogue, so the filters are forgiving about case
and surrounding whitespace — a model that asks for "valais" should not get an empty list — while
still matching exactly rather than fuzzily, so the result is always explainable.
"""

from __future__ import annotations

from collections.abc import Iterable

from swiss_outdoor_mcp.models import Site

__all__ = ["filter_sites"]


def filter_sites(
    sites: Iterable[Site],
    region: str | None = None,
    orientation: str | None = None,
) -> list[Site]:
    """Return the sites matching every filter given, in input order.

    `region` matches case-insensitively. `orientation` matches when the site faces that compass
    sector, also case-insensitively; it is not widened to neighbouring sectors, because the
    flyable wind window is the business of `get_flyability`, not of the catalogue.
    """
    wanted_region = region.strip().casefold() if region else None
    wanted_orientation = orientation.strip().casefold() if orientation else None

    result: list[Site] = []
    for site in sites:
        if wanted_region is not None and site.region.casefold() != wanted_region:
            continue
        if wanted_orientation is not None and not any(
            sector.casefold() == wanted_orientation for sector in site.orientations
        ):
            continue
        result.append(site)
    return result
