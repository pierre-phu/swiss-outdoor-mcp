"""Model selection and parsing of the two-model Open-Meteo response.

Two kinds of input: small hand-built payloads where the cut-off is placed exactly where a test
needs it, and the real recorded fixture (`ensemble_two_models.json`, recorded 2026-09-25 at the
Fiesch launch) to prove the parser agrees with the live key grammar of `docs/api-notes.md` 2.5.
"""

from datetime import date, datetime, time, timedelta
from typing import Any

import pytest

from conftest import load_fixture
from swiss_outdoor_mcp.domain.flyability import ZURICH
from swiss_outdoor_mcp.domain.openmeteo import VARIABLES, member_keys, select_forecast
from swiss_outdoor_mcp.errors import DateOutOfRangeError, UpstreamUnavailableError
from swiss_outdoor_mcp.models import EnsembleModel

START, END = time(10), time(17)
FIRST_DAY = date(2026, 9, 25)


def payload(
    cutoffs: dict[EnsembleModel, int], *, days: int = 5, members: int = 3
) -> dict[str, Any]:
    """A two-model response whose model `m` has values up to hour index `cutoffs[m]`, then nulls.

    Mirrors the live shape: one shared time axis, `_memberNN_<model>` sibling keys, null tails.
    """
    steps = 24 * days
    start = datetime.combine(FIRST_DAY, time(0))
    hourly: dict[str, Any] = {
        "time": [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(steps)]
    }
    for model, cutoff in cutoffs.items():
        for variable in VARIABLES:
            value = 180 if variable == "wind_direction_10m" else 5.0
            series = [value if h <= cutoff else None for h in range(steps)]
            hourly[f"{variable}_{model}"] = series
            for n in range(1, members):
                hourly[f"{variable}_member{n:02d}_{model}"] = list(series)
    return {"timezone": "Europe/Zurich", "elevation": 2173.0, "hourly": hourly}


def hour_index(day: date, hour: int) -> int:
    return (day - FIRST_DAY).days * 24 + hour


class TestModelSelection:
    def test_the_2km_grid_wins_when_it_covers_the_window(self) -> None:
        both = payload({"icon_d2_eps": hour_index(date(2026, 9, 26), 20), "icon_eu_eps": 116})

        assert select_forecast(both, date(2026, 9, 26), START, END).model == "icon_d2_eps"

    def test_falls_back_to_the_13km_grid_beyond_the_2km_horizon(self) -> None:
        both = payload({"icon_d2_eps": hour_index(date(2026, 9, 26), 20), "icon_eu_eps": 116})

        assert select_forecast(both, date(2026, 9, 27), START, END).model == "icon_eu_eps"

    def test_a_window_only_partly_covered_is_not_covered(self) -> None:
        """icon_d2_eps stops at 14:00: it must not answer with half a day, nor pad with nulls."""
        both = payload({"icon_d2_eps": hour_index(date(2026, 9, 26), 14), "icon_eu_eps": 116})

        assert select_forecast(both, date(2026, 9, 26), START, END).model == "icon_eu_eps"

    def test_window_ending_exactly_at_the_cutoff_is_covered(self) -> None:
        both = payload({"icon_d2_eps": hour_index(date(2026, 9, 26), 17), "icon_eu_eps": 116})

        assert select_forecast(both, date(2026, 9, 26), START, END).model == "icon_d2_eps"

    def test_a_missing_model_is_skipped(self) -> None:
        only_eu = payload({"icon_eu_eps": 116})

        assert select_forecast(only_eu, FIRST_DAY, START, END).model == "icon_eu_eps"

    def test_a_single_null_member_disqualifies_the_model(self) -> None:
        """Never pool, never patch: a hole in one member means the model does not answer."""
        both = payload({"icon_d2_eps": 116, "icon_eu_eps": 116})
        both["hourly"]["wind_gusts_10m_member02_icon_d2_eps"][hour_index(FIRST_DAY, 13)] = None

        assert select_forecast(both, FIRST_DAY, START, END).model == "icon_eu_eps"


class TestOutOfRange:
    def test_beyond_the_horizon_quotes_the_range_that_answered(self) -> None:
        both = payload({"icon_d2_eps": hour_index(date(2026, 9, 26), 20), "icon_eu_eps": 116})

        with pytest.raises(DateOutOfRangeError) as caught:
            select_forecast(both, date(2026, 9, 30), START, END)

        assert caught.value.first_available == FIRST_DAY
        assert caught.value.last_available == date(2026, 9, 29)

    def test_the_last_day_needs_its_whole_window(self) -> None:
        """icon_eu_eps stops at 16:00 on the 29th, one step short of 17:00: the 29th is out."""
        short = payload({"icon_eu_eps": hour_index(date(2026, 9, 29), 16)})

        with pytest.raises(DateOutOfRangeError) as caught:
            select_forecast(short, date(2026, 9, 29), START, END)

        assert caught.value.last_available == date(2026, 9, 28)

    def test_a_past_date_is_out_of_range(self) -> None:
        with pytest.raises(DateOutOfRangeError, match="2026-09-20"):
            select_forecast(payload({"icon_eu_eps": 116}), date(2026, 9, 20), START, END)

    def test_no_data_for_any_date_is_an_outage_not_a_bad_date(self) -> None:
        with pytest.raises(UpstreamUnavailableError):
            select_forecast(payload({"icon_eu_eps": -1}), FIRST_DAY, START, END)


class TestShape:
    def test_slices_to_the_window_in_zurich_time(self) -> None:
        forecast = select_forecast(payload({"icon_eu_eps": 116}), FIRST_DAY, START, END)

        assert forecast.times[0] == datetime(2026, 9, 25, 10, tzinfo=ZURICH)
        assert len(forecast.times) == 8
        assert all(len(m.wind_speed_kmh) == 8 for m in forecast.members)

    def test_counts_the_control_run_as_a_member(self) -> None:
        forecast = select_forecast(payload({"icon_eu_eps": 116}, members=3), FIRST_DAY, START, END)

        assert len(forecast.members) == 3

    def test_members_disagreeing_across_variables_is_a_shape_error(self) -> None:
        broken = payload({"icon_eu_eps": 116})
        del broken["hourly"]["precipitation_member02_icon_eu_eps"]

        with pytest.raises(ValueError, match="member count"):
            select_forecast(broken, FIRST_DAY, START, END)

    def test_member_keys_are_ordered_control_first(self) -> None:
        hourly = {
            "wind_speed_10m_member02_icon_d2_eps": [],
            "wind_speed_10m_icon_d2_eps": [],
            "wind_speed_10m_member01_icon_d2_eps": [],
            "wind_speed_10m_member01_icon_eu_eps": [],
            "wind_gusts_10m_icon_d2_eps": [],
        }

        assert member_keys(hourly, "wind_speed_10m", "icon_d2_eps") == [
            "wind_speed_10m_icon_d2_eps",
            "wind_speed_10m_member01_icon_d2_eps",
            "wind_speed_10m_member02_icon_d2_eps",
        ]


class TestRecordedFixture:
    """The real response, recorded on 2026-09-25 at Fiesch (api-notes.md 2.5)."""

    @pytest.fixture
    def recorded(self) -> dict[str, Any]:
        return load_fixture("ensemble_two_models.json")

    @pytest.mark.parametrize(("model", "expected"), [("icon_d2_eps", 20), ("icon_eu_eps", 40)])
    def test_member_counts_match_the_docs(
        self, recorded: dict[str, Any], model: EnsembleModel, expected: int
    ) -> None:
        for variable in VARIABLES:
            assert len(member_keys(recorded["hourly"], variable, model)) == expected

    @pytest.mark.parametrize(
        ("day", "model", "n_members"),
        [
            (date(2026, 9, 25), "icon_d2_eps", 20),  # D+0
            (date(2026, 9, 26), "icon_d2_eps", 20),  # D+1: d2 runs to 20:00
            (date(2026, 9, 27), "icon_eu_eps", 40),  # D+2: d2 is all null
            (date(2026, 9, 29), "icon_eu_eps", 40),  # D+4: eu runs to 20:00
        ],
    )
    def test_picks_the_model_the_nulls_say(
        self, recorded: dict[str, Any], day: date, model: EnsembleModel, n_members: int
    ) -> None:
        forecast = select_forecast(recorded, day, START, END)

        assert forecast.model == model
        assert len(forecast.members) == n_members
        assert forecast.grid_elevation_m == 2173.0

    def test_d_plus_5_is_out_of_range(self, recorded: dict[str, Any]) -> None:
        with pytest.raises(DateOutOfRangeError, match="cover 2026-09-25 to 2026-09-29"):
            select_forecast(recorded, date(2026, 9, 30), START, END)
