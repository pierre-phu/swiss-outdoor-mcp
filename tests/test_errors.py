"""The wording of these errors is a contract, not decoration.

They are what an LLM reads after a failed call, and they are the only thing telling it how to
recover. Each one must name the fix. If you change a message, change the assertion deliberately.
"""

import pytest

from swiss_outdoor_mcp.errors import (
    DateOutOfRangeError,
    SiteNotFoundError,
    StopNotFoundError,
    SwissOutdoorError,
    UpstreamUnavailableError,
)


def test_site_not_found_names_the_recovery_call() -> None:
    error = SiteNotFoundError("chamonix")

    assert str(error) == "Unknown site_id 'chamonix'. Call list_sites to get valid ids."
    assert error.site_id == "chamonix"


def test_stop_not_found_offers_suggestions_when_there_are_any() -> None:
    error = StopNotFoundError("Lausane", suggestions=["Lausanne", "Lausanne-Flon"])

    assert "Did you mean: 'Lausanne', 'Lausanne-Flon'?" in str(error)
    assert error.suggestions == ["Lausanne", "Lausanne-Flon"]


def test_stop_not_found_falls_back_to_advice_without_suggestions() -> None:
    error = StopNotFoundError("Lausane")

    assert "exact stop name" in str(error)
    assert error.suggestions == []


def test_date_out_of_range_states_the_horizon() -> None:
    error = DateOutOfRangeError("2026-10-01", max_days_ahead=2)

    assert "2026-10-01" in str(error)
    assert "2 days ahead" in str(error)
    assert "earlier date" in str(error)


def test_upstream_unavailable_tells_the_model_not_to_conclude_anything() -> None:
    error = UpstreamUnavailableError("Open-Meteo", detail="504 gateway timeout")

    assert "Open-Meteo" in str(error)
    assert "504 gateway timeout" in str(error)
    assert "do not treat this as a negative answer" in str(error)


def test_upstream_unavailable_without_detail() -> None:
    assert "(" not in str(UpstreamUnavailableError("transport.opendata.ch"))


@pytest.mark.parametrize(
    "error",
    [
        SiteNotFoundError("x"),
        StopNotFoundError("x"),
        DateOutOfRangeError("2026-01-01", 2),
        UpstreamUnavailableError("x"),
    ],
)
def test_every_domain_error_shares_the_base_class(error: SwissOutdoorError) -> None:
    """`tool_errors` catches `SwissOutdoorError` only, so anything outside it escapes as a crash."""
    assert isinstance(error, SwissOutdoorError)
