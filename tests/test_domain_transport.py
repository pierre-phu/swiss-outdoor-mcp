"""Mapping raw timetable JSON onto our models.

These are the traps `docs/api-notes.md` section 3.2 warns about, pinned as tests: a duration that
is a string, endpoints named `departure`/`arrival`, and a legacy `station` alias shadowing
`location`. Every test here runs on a dict, so none of them needs a transport.
"""

from typing import Any

import pytest

from conftest import load_fixture
from swiss_outdoor_mcp.domain.transport import (
    parse_duration_minutes,
    to_connection,
    to_section,
    to_station,
)


class TestParseDurationMinutes:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("00d00:00:00", 0),
            ("00d01:15:00", 75),
            ("00d04:41:00", 281),
            # A multi-day value: the `DDd` prefix is not decoration.
            ("02d03:04:00", 3_064),
            # Half-up, not Python's banker's rounding, which would make this 0.
            ("00d00:00:30", 1),
            ("00d00:00:29", 0),
            # A single-digit day count is accepted: it is a harmless variant, not a shape change.
            ("1d01:15:00", 75 + 1_440),
        ],
    )
    def test_parses_the_api_format(self, raw: str, expected: int) -> None:
        assert parse_duration_minutes(raw) == expected

    @pytest.mark.parametrize("raw", ["", "75", "01:15:00", "00d1:15:00", "00d01:15", "banana"])
    def test_rejects_anything_else(self, raw: str) -> None:
        """A duration we cannot read is an upstream shape change; it must not silently become 0."""
        with pytest.raises(ValueError, match="unrecognised duration"):
            parse_duration_minutes(raw)


class TestToSection:
    def test_maps_a_train_leg(self) -> None:
        raw: dict[str, Any] = {
            "journey": {"category": "IR", "number": "95", "name": "024211"},
            "walk": None,
            "departure": {
                "location": {"name": "Lausanne"},
                "departure": "2026-09-25T05:24:00+0200",
            },
            "arrival": {"location": {"name": "Aigle"}, "arrival": "2026-09-25T06:09:00+0200"},
        }

        section = to_section(raw)

        assert section.mode == "train"
        assert section.category == "IR"
        # Not journey.name, which is the internal code "024211".
        assert section.line == "IR 95"
        assert section.from_stop == "Lausanne"
        assert section.to_stop == "Aigle"
        assert section.departure is not None
        assert section.departure.hour == 5
        assert section.arrival is not None
        assert section.arrival.hour == 6

    def test_prefers_location_over_the_legacy_station_alias(self) -> None:
        """`station` is the legacy alias. If the two ever disagree, `location` wins."""
        raw: dict[str, Any] = {
            "journey": {"category": "R", "number": "2"},
            "departure": {"location": {"name": "Right"}, "station": {"name": "Legacy"}},
            "arrival": {"location": {"name": "Also right"}, "station": {"name": "Legacy"}},
        }

        section = to_section(raw)

        assert section.from_stop == "Right"
        assert section.to_stop == "Also right"

    def test_a_section_without_a_journey_is_a_walk(self) -> None:
        raw: dict[str, Any] = {
            "journey": None,
            "walk": {"duration": 120},
            "departure": {"location": {"name": "Lausanne"}},
            "arrival": {"location": {"name": "Lausanne-Flon"}},
        }

        section = to_section(raw)

        assert section.mode == "walk"
        assert section.category is None
        assert section.line is None

    def test_an_unmapped_category_degrades_to_other_but_keeps_the_code(self) -> None:
        """The category vocabulary is open-ended, so an unknown code must not raise or be lost."""
        raw: dict[str, Any] = {
            "journey": {"category": "ZZZ", "number": "1"},
            "departure": {"location": {"name": "A"}},
            "arrival": {"location": {"name": "B"}},
        }

        section = to_section(raw)

        assert section.mode == "other"
        assert section.category == "ZZZ"

    @pytest.mark.parametrize(
        ("category", "number", "expected"),
        [
            ("IR", "95", "IR 95"),
            ("R", "70", "R 70"),
            # Seen live: the number already carries the category, so do not print "EV EV1".
            ("EV", "EV1", "EV1"),
            ("R", None, "R"),
            ("R", "", "R"),
        ],
    )
    def test_line_label_never_repeats_the_category(
        self, category: str, number: str | None, expected: str
    ) -> None:
        raw: dict[str, Any] = {
            "journey": {"category": category, "number": number},
            "departure": {"location": {"name": "A"}},
            "arrival": {"location": {"name": "B"}},
        }

        assert to_section(raw).line == expected

    @pytest.mark.parametrize(
        ("category", "mode"),
        [("R", "train"), ("IR", "train"), ("CC", "train"), ("EV", "bus"), ("PB", "cableway")],
    )
    def test_known_categories_map(self, category: str, mode: str) -> None:
        raw: dict[str, Any] = {
            "journey": {"category": category, "number": "1"},
            "departure": {"location": {"name": "A"}},
            "arrival": {"location": {"name": "B"}},
        }

        assert to_section(raw).mode == mode


class TestToStation:
    def test_x_is_latitude_and_y_is_longitude(self) -> None:
        """Swapping these puts Swiss stops in Somalia. See docs/api-notes.md section 3.1."""
        station = to_station(
            {
                "id": "8501120",
                "name": "Lausanne",
                "coordinate": {"type": "WGS84", "x": 46.516795, "y": 6.629087},
            }
        )

        assert station.lat == pytest.approx(46.516795)
        assert station.lon == pytest.approx(6.629087)

    def test_an_entry_without_an_id_is_still_mapped(self) -> None:
        """Addresses and POIs come back with a null id; filtering them is the client's job."""
        station = to_station({"id": None, "name": "Epicerie du Feydey", "coordinate": {}})

        assert station.id is None
        assert station.lat is None


class TestToConnectionOnRealData:
    """Against the recorded response, so a change in the real API breaks this."""

    def test_maps_the_recorded_connection(self) -> None:
        payload = load_fixture("connections_lausanne_leysin.json")

        connection = to_connection(payload["connections"][0])

        assert connection.duration_min == 75
        assert connection.transfers == 1
        assert len(connection.sections) == 2
        assert connection.sections[0].from_stop == "Lausanne"
        assert connection.sections[-1].to_stop == "Leysin-Feydey"
        assert connection.departure is not None
        assert connection.arrival is not None
        assert connection.arrival > connection.departure

    def test_every_recorded_section_has_both_endpoints_named(self) -> None:
        payload = load_fixture("connections_lausanne_leysin.json")

        for raw in payload["connections"]:
            for section in to_connection(raw).sections:
                assert section.from_stop, "a section lost its origin name"
                assert section.to_stop, "a section lost its destination name"
