"""The eval harness end to end, with a scripted stand-in for the LLM and the offline server.

No model and no network: `ScriptedProvider` replays a fixed list of tool calls through the same
`call_tool` the real provider gets. Replaying the ideal calls for every task checks two things at
once: that the harness records and grades correctly, and that `tasks.yaml` asks for something a
correct agent actually does.
"""

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from evals.providers import CallTool, ProviderResult, ToolSpec
from evals.run_eval import eval_today, run_all, system_prompt, write_report
from evals.tasks import load_tasks

pytestmark = pytest.mark.anyio

SATURDAY = "2026-09-26"

IDEAL: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "valais-sites": [("list_sites", {"region": "Valais"})],
    "flyable-saturday": [("get_flyability", {"site_id": "fiesch", "date": SATURDAY})],
    "train-to-site": [
        ("list_sites", {}),
        (
            "get_connections",
            {
                "origin": "Lausanne",
                "destination": "Leysin-Feydey",
                "date": SATURDAY,
                "depart_after": "07:00",
            },
        ),
    ],
    "plan-saturday": [
        ("list_sites", {}),
        ("get_flyability", {"site_id": "fiesch", "date": SATURDAY}),
        ("get_flyability", {"site_id": "berneuse", "date": SATURDAY}),
        ("get_connections", {"origin": "Lausanne", "destination": "Fiesch", "date": SATURDAY}),
    ],
    "unknown-site-recovery": [
        ("get_flyability", {"site_id": "fiesch-kuehboden", "date": SATURDAY}),
        ("list_sites", {}),
        ("get_flyability", {"site_id": "fiesch", "date": SATURDAY}),
    ],
}


class ScriptedProvider:
    """Plays each task's calls in order, whatever the tools answer."""

    model = "scripted"

    def __init__(self, scripts: dict[str, list[tuple[str, dict[str, Any]]]]) -> None:
        self._scripts = scripts

    async def run(
        self,
        *,
        system: str,
        prompt: str,
        tools: Sequence[ToolSpec],
        call_tool: CallTool,
        max_turns: int,
    ) -> ProviderResult:
        task_id = next(task.id for task in load_tasks() if task.prompt == prompt)
        for name, arguments in self._scripts[task_id]:
            await call_tool(name, arguments)
        return ProviderResult("done", len(self._scripts[task_id]) + 1, "end_turn", 10, 5)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWISS_OUTDOOR_OFFLINE", "1")
    monkeypatch.delenv("SWISS_OUTDOOR_FIXTURES", raising=False)


async def test_the_ideal_calls_pass_every_task(client: Client, offline: None) -> None:
    results = await run_all(load_tasks(), ScriptedProvider(IDEAL), client, eval_today(), 10)

    failures = {r.task_id: r.verdicts for r in results if not r.passed}
    assert failures == {}
    assert [len(r.trace) for r in results] == [len(IDEAL[r.task_id]) for r in results]


async def test_a_wrong_call_fails_with_a_reason(client: Client, offline: None) -> None:
    guessed = {
        "train-to-site": [
            ("get_connections", {"origin": "Lausanne", "destination": "Leysin", "date": SATURDAY})
        ]
    }
    tasks = [task for task in load_tasks() if task.id == "train-to-site"]

    [result] = await run_all(tasks, ScriptedProvider(guessed), client, eval_today(), 10)

    assert result.passed is False
    assert result.trace[0]["is_error"] is True, "offline mode has no recording for 'Leysin'"
    assert "Leysin-Feydey" in result.verdicts[0]["reason"]


def test_the_agent_is_told_the_offline_sets_date() -> None:
    assert eval_today() == date(2026, 9, 25)
    prompt = system_prompt(eval_today(), "Server instructions.")

    assert "Friday 2026-09-25" in prompt
    assert prompt.endswith("Server instructions.")


async def test_the_report_holds_the_trace_and_the_totals(
    client: Client, offline: None, tmp_path: Path
) -> None:
    tasks = [task for task in load_tasks() if task.id == "valais-sites"]
    results = await run_all(tasks, ScriptedProvider(IDEAL), client, eval_today(), 10)

    path = write_report(
        results, model="claude-haiku-4-5", today=eval_today(), max_turns=10, out_dir=tmp_path
    )

    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 1
    assert report["summary"]["estimated_cost_usd"] == pytest.approx((10 * 1 + 5 * 5) / 1e6)
    assert report["tasks"][0]["trace"][0]["name"] == "list_sites"
    assert report["eval_today"] == "2026-09-25"
