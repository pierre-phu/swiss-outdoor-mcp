"""Trip CO2 estimate. Pure: the caller resolves the stops and loads the factors.

The method is deliberately coarse and says so in its output: one distance for every mode, the
great-circle distance between the two stops stretched by a fixed detour factor, since the
timetable API reports no route length (`docs/api-notes.md` section 3.2). Each mode's life-cycle
factor per passenger-km is then applied to that same distance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from swiss_outdoor_mcp.models import Co2Estimate, EmissionFactor, Station, TransportMode

__all__ = ["DEFAULT_DETOUR_FACTOR", "estimate_co2", "haversine_km"]

DEFAULT_DETOUR_FACTOR = 1.3
"""Road or rail length over straight-line length. A documented assumption from the SPEC."""

# Mean Earth radius. The spherical model is off by well under 1 % at Swiss latitudes, which is
# noise next to the detour factor.
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 points given in degrees."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _coordinates(station: Station) -> tuple[float, float]:
    if station.lat is None or station.lon is None:
        raise ValueError(f"stop {station.name!r} has no coordinates")
    return station.lat, station.lon


def estimate_co2(
    origin: Station,
    destination: Station,
    factors: Mapping[TransportMode, EmissionFactor],
    detour_factor: float = DEFAULT_DETOUR_FACTOR,
) -> Co2Estimate:
    """Price one one-way trip in kg CO2e per passenger, for every mode we hold a factor for.

    Totals are computed from the unrounded distance, then rounded to the gram.
    """
    straight = haversine_km(*_coordinates(origin), *_coordinates(destination))
    distance = straight * detour_factor

    # Every row usually shares one source, so this collapses to a single citation.
    sources = sorted(
        {f"{f.source_name}, {f.source_url}, retrieved {f.retrieved_on}" for f in factors.values()}
    )
    return Co2Estimate(
        origin=origin.name,
        destination=destination.name,
        straight_line_km=round(straight, 1),
        detour_factor=detour_factor,
        distance_km=round(distance, 1),
        by_mode={mode: round(distance * f.value_kg_per_pkm, 3) for mode, f in factors.items()},
        factors_kg_per_pkm={mode: f.value_kg_per_pkm for mode, f in factors.items()},
        method=(
            f"Straight-line distance between the two stops times a detour factor of "
            f"{detour_factor:g}, the same distance for every mode, times each mode's life-cycle "
            "emission factor per passenger-km. Car is per passenger at an average occupancy. "
            "public_transport is the Swiss average over all public modes, for a mixed journey. "
            "An order-of-magnitude comparison between modes, not a route-exact footprint."
        ),
        factor_source="; ".join(sources),
    )
