"""`compute_flyability` on synthetic ensembles, where the right answer is known by construction.

Each member below is a set of flat hourly series; a scalar means "this value all day". The
defaults describe a calm, dry day with a southerly breeze, which is flyable at a south-facing
launch, so each test only spells out what it breaks.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from swiss_outdoor_mcp.domain.flyability import (
    ATTRIBUTION,
    DISCLAIMER,
    ZURICH,
    EnsembleForecast,
    MemberForecast,
    angular_distance_deg,
    compute_flyability,
    longest_run,
    sector_bearing_deg,
    window_hours,
)
from swiss_outdoor_mcp.models import CompassSector, FlyabilityCriteria, Site

DAY = date(2026, 9, 26)
GENERATED_AT = datetime(2026, 9, 25, 9, 0, tzinfo=ZURICH)
LOCAL_DAY = tuple(datetime.combine(DAY, time(hour), tzinfo=ZURICH) for hour in range(24))

Series = float | dict[int, float]


def series(value: Series, base: float) -> tuple[float, ...]:
    """A 24-hour series: a scalar all day, or `base` with some local hours overridden."""
    if isinstance(value, dict):
        return tuple(value.get(hour, base) for hour in range(24))
    return (value,) * 24


def member(
    speed: Series = 10.0,
    gust: Series = 15.0,
    direction: Series = 180.0,
    precip: Series = 0.0,
) -> MemberForecast:
    return MemberForecast(
        wind_speed_kmh=series(speed, 10.0),
        wind_gusts_kmh=series(gust, 15.0),
        wind_direction_deg=series(direction, 180.0),
        precipitation_mm=series(precip, 0.0),
    )


def forecast(*members: MemberForecast, times: tuple[datetime, ...] = LOCAL_DAY) -> EnsembleForecast:
    return EnsembleForecast(model="icon_d2_eps", times=times, members=members)


def site(*orientations: CompassSector) -> Site:
    return Site(
        id="test-site",
        name="Test",
        region="Valais",
        lat=46.4,
        lon=8.1,
        altitude_m=2000,
        orientations=list(orientations) or ["S"],
        nearest_stop="Fiesch",
    )


def score(
    ensemble: EnsembleForecast,
    launch: Site | None = None,
    criteria: FlyabilityCriteria | None = None,
) -> float:
    return compute_flyability(
        ensemble,
        launch or site(),
        DAY,
        criteria or FlyabilityCriteria(),
        generated_at=GENERATED_AT,
    ).p_flyable


def _windy_except(*calm_hours: int) -> dict[int, float]:
    return {hour: (10.0 if hour in calm_hours else 40.0) for hour in range(24)}


class TestDayLevelProbability:
    def test_all_members_calm_and_aligned_is_certain(self) -> None:
        assert score(forecast(*[member() for _ in range(20)])) == 1.0

    def test_all_members_too_windy_is_zero(self) -> None:
        assert score(forecast(*[member(speed=35.0) for _ in range(20)])) == 0.0

    def test_half_the_members_flyable_is_one_half(self) -> None:
        members = [member() for _ in range(10)] + [member(gust=45.0) for _ in range(10)]

        assert score(forecast(*members)) == 0.5

    def test_two_consecutive_hours_are_not_enough_for_three(self) -> None:
        # Flyable only at 12:00 and 13:00, windy everywhere else.
        only_two = member(speed=_windy_except(12, 13))

        assert score(forecast(only_two)) == 0.0

    def test_three_consecutive_hours_are_enough(self) -> None:
        three = member(speed=_windy_except(12, 13, 14))

        assert score(forecast(three)) == 1.0

    def test_three_scattered_hours_are_not_a_run(self) -> None:
        scattered = member(speed=_windy_except(10, 12, 14, 16))

        assert score(forecast(scattered)) == 0.0

    def test_each_criterion_can_ground_a_member_on_its_own(self) -> None:
        grounded = [
            member(speed=21.0),
            member(gust=31.0),
            member(precip=0.5),
            member(direction=0.0),  # northerly on a south-facing launch
        ]

        assert score(forecast(*grounded)) == 0.0


class TestLimitsAreInclusive:
    def test_values_exactly_on_every_limit_pass(self) -> None:
        on_the_limit = member(speed=20.0, gust=30.0, precip=0.1, direction=180.0 + 45.0)

        assert score(forecast(on_the_limit)) == 1.0

    def test_values_just_over_fail(self) -> None:
        assert score(forecast(member(speed=20.1))) == 0.0
        assert score(forecast(member(direction=180.0 + 45.1))) == 0.0


class TestDirection:
    def test_wraps_around_north(self) -> None:
        """A north-facing launch: 350 and 10 are both 10 degrees off, not 340."""
        north = site("N")

        assert score(forecast(member(direction=350.0)), north) == 1.0
        assert score(forecast(member(direction=10.0)), north) == 1.0
        assert score(forecast(member(direction=300.0)), north) == 0.0

    def test_any_orientation_of_the_launch_will_do(self) -> None:
        east_or_west = site("E", "W")

        assert score(forecast(member(direction=90.0)), east_or_west) == 1.0
        assert score(forecast(member(direction=270.0)), east_or_west) == 1.0
        assert score(forecast(member(direction=180.0)), east_or_west) == 0.0

    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [(350, 10, 20), (10, 350, 20), (0, 180, 180), (90, 90, 0), (0, 360, 0), (-10, 10, 20)],
    )
    def test_angular_distance(self, a: float, b: float, expected: float) -> None:
        assert angular_distance_deg(a, b) == expected

    @pytest.mark.parametrize(
        ("sector", "bearing"),
        [("N", 0.0), ("NNE", 22.5), ("E", 90.0), ("SW", 225.0), ("NNW", 337.5)],
    )
    def test_sector_bearings(self, sector: CompassSector, bearing: float) -> None:
        assert sector_bearing_deg(sector) == bearing


class TestWindow:
    def test_hours_outside_the_window_are_ignored(self) -> None:
        stormy_outside = member(speed={hour: 60.0 for hour in (*range(10), *range(18, 24))})

        result = compute_flyability(
            forecast(stormy_outside), site(), DAY, FlyabilityCriteria(), generated_at=GENERATED_AT
        )

        assert result.p_flyable == 1.0
        assert [h.time.hour for h in result.hourly] == list(range(10, 18))

    def test_both_ends_are_included(self) -> None:
        stormy_at_17 = member(speed={17: 60.0})

        result = compute_flyability(
            forecast(stormy_at_17), site(), DAY, FlyabilityCriteria(), generated_at=GENERATED_AT
        )

        assert result.hourly[-1].time.hour == 17
        assert result.hourly[-1].p_flyable == 0.0

    def test_window_is_read_in_zurich_time_whatever_the_input_zone(self) -> None:
        """Summer: 10:00 in Zurich is 08:00 UTC. Calm only then, stormy on every other hour."""
        start = datetime(2026, 9, 25, 22, tzinfo=UTC)  # 00:00 on DAY in Zurich
        utc_times = tuple(start + timedelta(hours=h) for h in range(24))
        # Index h is local hour h, so this storm lands on local 00-09 and 18-23 only.
        calm_in_local_window = member(speed=_windy_except(*range(10, 18)))

        result = compute_flyability(
            forecast(calm_in_local_window, times=utc_times),
            site(),
            DAY,
            FlyabilityCriteria(),
            generated_at=GENERATED_AT,
        )

        assert result.p_flyable == 1.0
        assert all(h.p_flyable == 1.0 for h in result.hourly)
        assert result.hourly[0].time.isoformat() == "2026-09-26T10:00:00+02:00"

    def test_a_gap_in_the_window_is_a_bug_not_a_zero(self) -> None:
        without_noon = tuple(t for t in LOCAL_DAY if t.hour != 12)
        gappy = MemberForecast(*(tuple(10.0 for _ in without_noon) for _ in range(4)))

        with pytest.raises(ValueError, match="12:00"):
            compute_flyability(
                forecast(gappy, times=without_noon),
                site(),
                DAY,
                FlyabilityCriteria(),
                generated_at=GENERATED_AT,
            )

    def test_window_hours_default_to_eight_steps(self) -> None:
        assert window_hours(FlyabilityCriteria()) == [time(h) for h in range(10, 18)]


class TestHourlyBreakdown:
    def test_shares_are_per_criterion(self) -> None:
        members = [member(), member(gust=40.0), member(precip=1.0), member(direction=0.0)]

        noon = compute_flyability(
            forecast(*members), site(), DAY, FlyabilityCriteria(), generated_at=GENERATED_AT
        ).hourly[2]

        assert noon.p_wind_ok == 1.0
        assert noon.p_gust_ok == 0.75
        assert noon.p_dry == 0.75
        assert noon.p_direction_ok == 0.75
        assert noon.p_flyable == 0.25

    def test_wind_spread_over_members(self) -> None:
        members = [member(speed=float(speed)) for speed in range(1, 21)]  # 1..20 km/h

        spread = (
            compute_flyability(
                forecast(*members), site(), DAY, FlyabilityCriteria(), generated_at=GENERATED_AT
            )
            .hourly[0]
            .wind_kmh
        )

        assert (spread.p10, spread.median, spread.p90) == (2.9, 10.5, 18.1)

    def test_a_single_member_has_no_spread(self) -> None:
        spread = (
            compute_flyability(
                forecast(member(speed=12.34)),
                site(),
                DAY,
                FlyabilityCriteria(),
                generated_at=GENERATED_AT,
            )
            .hourly[0]
            .wind_kmh
        )

        assert spread.p10 == spread.median == spread.p90 == 12.3


class TestOutputCarriesItsAssumptions:
    def test_echoes_criteria_model_disclaimer_and_attribution(self) -> None:
        criteria = FlyabilityCriteria(max_wind_kmh=15.0)

        result = compute_flyability(
            forecast(member(), member()), site(), DAY, criteria, generated_at=GENERATED_AT
        )

        assert result.site_id == "test-site"
        assert result.date == DAY
        assert result.criteria == criteria
        assert result.model == "icon_d2_eps"
        assert result.n_members == 2
        assert result.generated_at == GENERATED_AT
        assert result.disclaimer == DISCLAIMER
        assert "does not replace pilot judgment" in result.disclaimer
        assert result.attribution == ATTRIBUTION
        assert "Open-Meteo" in result.attribution
        assert "3 consecutive" in result.method

    def test_stricter_criteria_lower_the_score(self) -> None:
        breezy = [member(speed=float(speed)) for speed in range(8, 28)]

        assert score(forecast(*breezy), criteria=FlyabilityCriteria(max_wind_kmh=12.0)) < score(
            forecast(*breezy)
        )


class TestCriteriaValidation:
    def test_defaults_match_the_spec(self) -> None:
        criteria = FlyabilityCriteria()

        assert criteria.max_wind_kmh == 20
        assert criteria.max_gust_kmh == 30
        assert criteria.max_precip_mm_h == 0.1
        assert criteria.direction_tolerance_deg == 45
        assert (criteria.window_start, criteria.window_end) == (time(10), time(17))
        assert criteria.min_consecutive_hours == 3

    @pytest.mark.parametrize(
        "bad",
        [
            {"window_start": time(10, 30)},
            {"window_start": time(17), "window_end": time(10)},
            {"window_start": time(10), "window_end": time(11), "min_consecutive_hours": 3},
            {"direction_tolerance_deg": 200},
            {"max_wind_kmh": 0},
        ],
    )
    def test_rejects_criteria_that_cannot_mean_anything(self, bad: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            FlyabilityCriteria.model_validate(bad)


class TestEnsembleShape:
    def test_needs_a_member(self) -> None:
        with pytest.raises(ValueError, match="at least one member"):
            forecast()

    def test_needs_aware_times(self) -> None:
        naive = tuple(t.replace(tzinfo=None) for t in LOCAL_DAY)

        with pytest.raises(ValueError, match="timezone-aware"):
            forecast(member(), times=naive)

    def test_series_must_match_the_time_axis(self) -> None:
        with pytest.raises(ValueError, match="length"):
            forecast(member(), times=LOCAL_DAY[:12])


@pytest.mark.parametrize(
    ("flags", "expected"),
    [([], 0), ([False], 0), ([True, True, False, True], 2), ([True] * 5, 5)],
)
def test_longest_run(flags: list[bool], expected: int) -> None:
    assert longest_run(flags) == expected
