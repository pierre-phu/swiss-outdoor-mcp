"""The eval's checks, on hand-built traces. The grader must be right before its grades mean much."""

from pathlib import Path

import pytest

from evals.assertions import CHECKS, ToolCall, evaluate, validate
from evals.tasks import load_tasks

SATURDAY = "2026-09-26"


def ok(name: str, **arguments: object) -> ToolCall:
    return ToolCall(name, dict(arguments), is_error=False, result="")


def failed(name: str, **arguments: object) -> ToolCall:
    return ToolCall(name, dict(arguments), is_error=True, result="Unknown site_id")


class TestCalled:
    def test_matches_a_subset_of_arguments_ignoring_case(self) -> None:
        trace = [ok("list_sites", region="valais ", orientation="S")]

        assert CHECKS["called"](trace, {"tool": "list_sites", "with": {"region": "Valais"}}).passed

    def test_a_wrong_value_fails_and_shows_what_was_called(self) -> None:
        verdict = CHECKS["called"](
            [ok("list_sites", region="Vaud")], {"tool": "list_sites", "with": {"region": "Valais"}}
        )

        assert not verdict.passed
        assert "Vaud" in verdict.reason

    def test_a_missing_argument_fails(self) -> None:
        verdict = CHECKS["called"](
            [ok("list_sites")], {"tool": "list_sites", "with": {"region": "Valais"}}
        )

        assert not verdict.passed


class TestMinCalls:
    def test_counts_only_successful_calls(self) -> None:
        trace = [ok("get_flyability"), failed("get_flyability")]

        verdict = CHECKS["min_calls"](trace, {"tool": "get_flyability", "count": 2})

        assert not verdict.passed
        assert "1 successful" in verdict.reason

    def test_passes_at_the_count(self) -> None:
        trace = [ok("get_flyability"), ok("get_flyability")]

        assert CHECKS["min_calls"](trace, {"tool": "get_flyability", "count": 2}).passed


ORDER = {"tools": ["list_sites", "get_flyability", "get_connections"]}
RECOVERY = {"tool": "get_flyability", "via": "list_sites", "with": {"site_id": "fiesch"}}


class TestOrder:
    def test_first_successful_calls_in_order(self) -> None:
        trace = [ok("list_sites"), ok("get_flyability"), ok("list_sites"), ok("get_connections")]

        assert CHECKS["order"](trace, ORDER).passed

    def test_out_of_order_fails(self) -> None:
        trace = [ok("get_flyability"), ok("list_sites"), ok("get_connections")]

        verdict = CHECKS["order"](trace, ORDER)

        assert not verdict.passed
        assert "got get_flyability -> list_sites" in verdict.reason

    def test_a_tool_that_only_failed_counts_as_missing(self) -> None:
        trace = [ok("list_sites"), ok("get_flyability"), failed("get_connections")]

        verdict = CHECKS["order"](trace, ORDER)

        assert not verdict.passed
        assert "get_connections" in verdict.reason


class TestToNearestStop:
    def test_any_sites_stop_passes(self) -> None:
        trace = [ok("get_connections", destination="Leysin-Feydey")]

        assert CHECKS["to_nearest_stop"](trace, {}).passed

    def test_a_guessed_stop_fails(self) -> None:
        """'Berneuse' is the launch, not a stop the timetable knows."""
        trace = [ok("get_connections", destination="Berneuse")]

        verdict = CHECKS["to_nearest_stop"](trace, {})

        assert not verdict.passed
        assert "Leysin-Feydey" in verdict.reason

    def test_can_require_one_sites_stop(self) -> None:
        trace = [ok("get_connections", destination="Fiesch")]

        assert not CHECKS["to_nearest_stop"](trace, {"site": "berneuse"}).passed


class TestRecovers:
    def test_error_then_lookup_then_success(self) -> None:
        trace = [
            failed("get_flyability", site_id="fiesch-kuehboden"),
            ok("list_sites"),
            ok("get_flyability", site_id="fiesch"),
        ]

        assert CHECKS["recovers"](trace, RECOVERY).passed

    def test_no_error_means_nothing_was_tested(self) -> None:
        verdict = CHECKS["recovers"](
            [ok("list_sites"), ok("get_flyability", site_id="fiesch")], RECOVERY
        )

        assert not verdict.passed
        assert "no failed get_flyability" in verdict.reason

    def test_retrying_without_looking_up_is_not_recovery(self) -> None:
        trace = [
            failed("get_flyability", site_id="fiesch-kuehboden"),
            ok("get_flyability", site_id="fiesch"),
        ]

        assert not CHECKS["recovers"](trace, RECOVERY).passed

    def test_looking_up_but_never_succeeding_fails(self) -> None:
        trace = [failed("get_flyability", site_id="x"), ok("list_sites")]

        assert not CHECKS["recovers"](trace, RECOVERY).passed


class TestValidation:
    @pytest.mark.parametrize(
        "assertion",
        [
            {"calld": {"tool": "list_sites"}},
            {"called": {"tool": "x"}, "order": {"tools": []}},
            {"min_calls": {"tool": "x"}},
            {"order": ["list_sites"]},
        ],
    )
    def test_refuses_what_it_cannot_run(self, assertion: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            validate(assertion)

    def test_evaluate_reports_each_assertion(self) -> None:
        results = evaluate([ok("list_sites")], [{"called": {"tool": "list_sites"}}])

        assert [(kind, verdict.passed) for kind, verdict in results] == [("called", True)]


class TestTasksFile:
    def test_holds_the_five_spec_tasks(self) -> None:
        assert len(load_tasks()) == 5

    def test_rejects_duplicate_ids(self, tmp_path: Path) -> None:
        task = "  - {id: a, prompt: p, assertions: [{called: {tool: list_sites}}]}\n"
        path = tmp_path / "tasks.yaml"
        path.write_text("tasks:\n" + task + task, encoding="utf-8")

        with pytest.raises(ValueError, match="duplicate"):
            load_tasks(path)
