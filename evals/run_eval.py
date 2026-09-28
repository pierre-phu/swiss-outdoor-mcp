"""Run the eval tasks against the server in offline mode, then print and save the results.

    uv run --env-file .env python -m evals.run_eval                       # all tasks, Haiku 4.5
    uv run --env-file .env python -m evals.run_eval --task plan-saturday --model claude-sonnet-5

The server is launched the way a client would launch it, as a stdio subprocess, with
`SWISS_OUTDOOR_OFFLINE=1` so it answers from the recorded fixtures. Only that one variable is
passed to it: the MCP SDK starts it from a minimal environment, so the API key stays here.

Every run calls the Anthropic API and costs money. Reports go to `evals/runs/` (git-ignored).
Exit status: 0 when every task passes, 1 when one fails, 2 when the run cannot start.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import anthropic
import anyio
from mcp import Client, StdioServerParameters

from evals.assertions import ToolCall, evaluate
from evals.providers import AnthropicProvider, Provider, ToolSpec
from evals.tasks import Task, load_tasks
from swiss_outdoor_mcp.clients.offline import DEFAULT_FIXTURES_DIR, MANIFEST

__all__ = ["TaskResult", "main", "run_all", "run_task", "system_prompt", "write_report"]

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TURNS = 10
REPO = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO / "evals" / "runs"
EXCERPT = 500  # characters of each tool result kept in the report

# USD per million tokens (input, output), from
# https://platform.claude.com/docs/en/about-claude/pricing, read on 2026-09-27.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}


@dataclass
class TaskResult:
    task_id: str
    prompt: str
    passed: bool
    verdicts: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    final_text: str = ""
    turns: int = 0
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def eval_today(fixtures: Path = DEFAULT_FIXTURES_DIR) -> date:
    """The date the agent is told it is: the offline set's own, so "Saturday" is recorded."""
    manifest = json.loads((fixtures / MANIFEST).read_text(encoding="utf-8"))
    return date.fromisoformat(manifest["eval_today"])


def system_prompt(today: date, instructions: str | None) -> str:
    """Only the facts a real client would supply. No advice on using the tools: that would hide
    exactly the description problems the eval exists to find."""
    lines = [
        "You help plan paragliding outings in Switzerland with the tools provided.",
        f"Today is {today:%A} {today.isoformat()} (Europe/Zurich).",
    ]
    if instructions:
        lines.append(instructions)
    return "\n".join(lines)


async def list_tool_specs(client: Client) -> list[ToolSpec]:
    listed = await client.list_tools()
    return [
        ToolSpec(tool.name, tool.description or "", dict(tool.input_schema))
        for tool in listed.tools
    ]


async def run_task(
    task: Task,
    provider: Provider,
    client: Client,
    tools: Sequence[ToolSpec],
    system: str,
    max_turns: int,
) -> TaskResult:
    trace: list[ToolCall] = []

    async def call_tool(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        result = await client.call_tool(name, arguments)
        text = "\n".join(str(getattr(item, "text", "")) for item in result.content)
        trace.append(ToolCall(name, arguments, bool(result.is_error), text[:EXCERPT]))
        return text, bool(result.is_error)

    outcome = None
    error = None
    try:
        outcome = await provider.run(
            system=system,
            prompt=task.prompt,
            tools=tools,
            call_tool=call_tool,
            max_turns=max_turns,
        )
    except anthropic.APIError as exc:  # fails this task, not the whole run
        error = f"{type(exc).__name__}: {exc}"

    verdicts = evaluate(trace, task.assertions)
    result = TaskResult(
        task_id=task.id,
        prompt=task.prompt,
        passed=error is None and all(verdict.passed for _, verdict in verdicts),
        verdicts=[
            {"assertion": kind, "passed": verdict.passed, "reason": verdict.reason}
            for kind, verdict in verdicts
        ],
        trace=[asdict(call) for call in trace],
        error=error,
    )
    if outcome is not None:
        result.final_text = outcome.final_text
        result.turns = outcome.turns
        result.stop_reason = outcome.stop_reason
        result.input_tokens = outcome.input_tokens
        result.output_tokens = outcome.output_tokens
        if outcome.stop_reason == "max_turns":
            result.notes.append(f"stopped after {max_turns} turns without a final answer")
    return result


async def run_all(
    tasks: Sequence[Task], provider: Provider, client: Client, today: date, max_turns: int
) -> list[TaskResult]:
    tools = await list_tool_specs(client)
    system = system_prompt(today, client.instructions)
    return [await run_task(task, provider, client, tools, system, max_turns) for task in tasks]


def estimated_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def git_revision() -> str:
    """The commit the run measured, marked `+dirty` when the tree had local changes."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        return "unknown"
    return f"{head}+dirty" if dirty else head


def summarise(results: Sequence[TaskResult], model: str) -> dict[str, Any]:
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    cost = estimated_cost(model, input_tokens, output_tokens)
    return {
        "passed": sum(result.passed for result in results),
        "total": len(results),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 6) if cost is not None else None,
    }


def write_report(
    results: Sequence[TaskResult],
    *,
    model: str,
    today: date,
    max_turns: int,
    out_dir: Path = RUNS_DIR,
    started_at: datetime | None = None,
) -> Path:
    started = started_at or datetime.now().astimezone()
    report = {
        "model": model,
        "started_at": started.isoformat(timespec="seconds"),
        "git_revision": git_revision(),
        "eval_today": today.isoformat(),
        "max_turns": max_turns,
        "summary": summarise(results, model),
        "tasks": [asdict(result) for result in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{started:%Y%m%d-%H%M%S}_{model}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def print_table(results: Sequence[TaskResult], model: str) -> None:
    print(f"{'task':<24} {'result':<6} {'calls':>5} {'turns':>5} {'in_tok':>8} {'out_tok':>8}")
    for result in results:
        status = "ERROR" if result.error else "PASS" if result.passed else "FAIL"
        print(
            f"{result.task_id:<24} {status:<6} {len(result.trace):>5} {result.turns:>5} "
            f"{result.input_tokens:>8,} {result.output_tokens:>8,}"
        )
    summary = summarise(results, model)
    cost = summary["estimated_cost_usd"]
    cost_text = f"~${cost:.3f}" if cost is not None else "cost unknown for this model"
    print(
        f"\n{summary['passed']}/{summary['total']} passed · {summary['input_tokens']:,} in / "
        f"{summary['output_tokens']:,} out tokens · {cost_text} ({model})"
    )
    for result in results:
        if result.error:
            print(f"  ERROR {result.task_id}: {result.error}")
        for verdict in result.verdicts:
            if not verdict["passed"]:
                print(f"  FAIL  {result.task_id} / {verdict['assertion']}: {verdict['reason']}")
        for note in result.notes:
            print(f"  NOTE  {result.task_id}: {note}")


def server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "swiss_outdoor_mcp"],
        env={"SWISS_OUTDOOR_OFFLINE": "1"},
        cwd=REPO,
    )


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the tool-trace eval.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    parser.add_argument(
        "--task", action="append", dest="tasks", metavar="ID", help="run only this task"
    )
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set. Put it in .env and run:\n"
            "  uv run --env-file .env python -m evals.run_eval",
            file=sys.stderr,
        )
        return 2

    tasks = load_tasks()
    if args.tasks:
        unknown = set(args.tasks) - {task.id for task in tasks}
        if unknown:
            print(f"unknown task id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        tasks = [task for task in tasks if task.id in args.tasks]

    today = eval_today()
    provider = AnthropicProvider(args.model)
    async with Client(server_parameters()) as client:
        results = await run_all(tasks, provider, client, today, args.max_turns)

    path = write_report(results, model=args.model, today=today, max_turns=args.max_turns)
    print_table(results, args.model)
    print(f"\nReport: {path.relative_to(REPO)}")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(anyio.run(main))
