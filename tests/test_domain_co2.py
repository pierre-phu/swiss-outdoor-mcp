"""CO2 estimate: distance maths and per-mode pricing.

Built on hand-made factors rather than the packaged file, so these keep passing when Pierre edits
`emission_factors.yaml`. The one real-data test uses recorded stop coordinates, to pin the
latitude/longitude order of the transport API.
"""

import math
from datetime import date

import pytest

from conftest import load_fixture
from swiss_outdoor_mcp.domain.co2 import EARTH_RADIUS_KM, estimate_co2, haversine_km
from swiss_outdoor_mcp.domain.transport import to_station
from swiss_outdoor_mcp.models import EmissionFactor, Station, TransportMode


def factor(value: float, source: str = "Test source") -> EmissionFactor:
    return EmissionFactor(
        value_kg_per_pkm=value,
        source_name=source,
        source_url="https://example.org/factors",  # type: ignore[arg-type]
        retrieved_on=date(2026, 1, 1),
    )


FACTORS: dict[TransportMode, EmissionFactor] = {
    "train": factor(0.01),
    "bus": factor(0.05),
    "public_transport": factor(0.02),
    "car": factor(0.2),
}

# One degree of latitude apart on the same meridian.
NORTH = Station(id="1", name="North", lat=47.0, lon=7.0)
SOUTH = Station(id="2", name="South", lat=46.0, lon=7.0)
ONE_DEGREE_KM = 2 * math.pi * EARTH_RADIUS_KM / 360


class TestHaversine:
    def test_same_point_is_zero(self) -> None:
        assert haversine_km(46.5, 6.6, 46.5, 6.6) == 0

    def test_one_degree_of_latitude_is_one_360th_of_a_meridian_circle(self) -> None:
        assert haversine_km(46.0, 7.0, 47.0, 7.0) == pytest.approx(ONE_DEGREE_KM)

    def test_is_symmetric(self) -> None:
        there = haversine_km(46.52, 6.63, 46.34, 7.01)
        back = haversine_km(46.34, 7.01, 46.52, 6.63)

        assert there == pytest.approx(back)

    def test_recorded_coordinates_are_read_latitude_first(self) -> None:
        """`coordinate.x` is the latitude (docs/api-notes.md 3.1). Swapped, this reads ~46 km."""
        lausanne = to_station(load_fixture("locations_lausanne.json")["stations"][0])
        leysin = to_station(load_fixture("locations_leysin_feydey.json")["stations"][0])
        assert (lausanne.name, leysin.name) == ("Lausanne", "Leysin-Feydey")

        estimate = estimate_co2(lausanne, leysin, FACTORS)

        assert 34 < estimate.straight_line_km < 36


class TestEstimateCo2:
    def test_applies_the_detour_factor_to_the_straight_line(self) -> None:
        estimate = estimate_co2(NORTH, SOUTH, FACTORS, detour_factor=1.5)

        assert estimate.straight_line_km == round(ONE_DEGREE_KM, 1)
        assert estimate.distance_km == round(ONE_DEGREE_KM * 1.5, 1)
        assert estimate.detour_factor == 1.5

    def test_defaults_to_the_spec_detour_factor(self) -> None:
        assert estimate_co2(NORTH, SOUTH, FACTORS).detour_factor == 1.3

    def test_prices_every_mode_over_the_same_distance(self) -> None:
        estimate = estimate_co2(NORTH, SOUTH, FACTORS, detour_factor=1.0)

        assert set(estimate.by_mode) == set(FACTORS)
        for mode, value in FACTORS.items():
            expected = round(ONE_DEGREE_KM * value.value_kg_per_pkm, 3)
            assert estimate.by_mode[mode] == expected
        assert estimate.factors_kg_per_pkm["car"] == 0.2

    def test_totals_come_from_the_unrounded_distance(self) -> None:
        """Rounding the distance first would drift by up to 0.05 km times the factor."""
        estimate = estimate_co2(NORTH, SOUTH, {"car": factor(1.0)}, detour_factor=1.0)

        assert estimate.by_mode["car"] == round(ONE_DEGREE_KM, 3)
        assert estimate.by_mode["car"] != estimate.distance_km

    def test_same_stop_costs_nothing(self) -> None:
        estimate = estimate_co2(NORTH, NORTH, FACTORS)

        assert estimate.distance_km == 0
        assert all(value == 0 for value in estimate.by_mode.values())

    def test_echoes_the_resolved_stop_names(self) -> None:
        estimate = estimate_co2(NORTH, SOUTH, FACTORS)

        assert (estimate.origin, estimate.destination) == ("North", "South")

    def test_a_shared_source_is_cited_once(self) -> None:
        estimate = estimate_co2(NORTH, SOUTH, FACTORS)

        assert estimate.factor_source.count("Test source") == 1
        assert "https://example.org/factors" in estimate.factor_source
        assert "2026-01-01" in estimate.factor_source

    def test_distinct_sources_are_all_cited(self) -> None:
        mixed = {"train": factor(0.01, "Source A"), "car": factor(0.2, "Source B")}

        source = estimate_co2(NORTH, SOUTH, mixed).factor_source

        assert "Source A" in source
        assert "Source B" in source

    def test_the_method_states_the_detour_factor(self) -> None:
        assert "1.3" in estimate_co2(NORTH, SOUTH, FACTORS).method

    def test_a_stop_without_coordinates_is_refused(self) -> None:
        nowhere = Station(id="3", name="Nowhere")

        with pytest.raises(ValueError, match="Nowhere"):
            estimate_co2(NORTH, nowhere, FACTORS)
