"""Checks on a tool-call trace. Pure: no model, no server, no network.

Each check takes the trace and its spec from `tasks.yaml` and returns a `Verdict` whose reason
says what was looked for and what was found, so a failed task explains itself in the report.

String arguments compare ignoring case and surrounding spaces, as the tools themselves mostly do.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from swiss_outdoor_mcp.data_loader import load_sites

__all__ = ["CHECKS", "ToolCall", "Verdict", "evaluate", "validate"]


@dataclass(frozen=True)
class ToolCall:
    """One call the agent made, as the server answered it."""

    name: str
    arguments: dict[str, Any]
    is_error: bool
    result: str


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str


Spec = Mapping[str, Any]
Check = Callable[[Sequence[ToolCall], Spec], Verdict]


def _norm(value: object) -> str:
    return str(value).strip().casefold()


def _matches(call: ToolCall, tool: str, wanted: Spec) -> bool:
    return call.name == tool and all(
        key in call.arguments and _norm(call.arguments[key]) == _norm(value)
        for key, value in wanted.items()
    )


def _show(calls: Sequence[ToolCall]) -> str:
    if not calls:
        return "no calls"
    return "; ".join(
        f"{call.name}({call.arguments}){' -> error' if call.is_error else ''}" for call in calls
    )


def called(trace: Sequence[ToolCall], spec: Spec) -> Verdict:
    """Some call to `tool` had at least the arguments in `with`."""
    tool, wanted = spec["tool"], spec.get("with", {})
    if any(_matches(call, tool, wanted) for call in trace):
        return Verdict(True, f"{tool} called with {dict(wanted)}")
    same_tool = [call for call in trace if call.name == tool]
    return Verdict(False, f"expected {tool} with {dict(wanted)}, got: {_show(same_tool)}")


def min_calls(trace: Sequence[ToolCall], spec: Spec) -> Verdict:
    """At least `count` successful calls to `tool`."""
    tool, count = spec["tool"], int(spec["count"])
    done = sum(1 for call in trace if call.name == tool and not call.is_error)
    return Verdict(done >= count, f"{done} successful {tool} call(s), need at least {count}")


def order(trace: Sequence[ToolCall], spec: Spec) -> Verdict:
    """The first successful call of each tool comes in this order."""
    tools: list[str] = list(spec["tools"])
    first: dict[str, int] = {}
    for index, call in enumerate(trace):
        if not call.is_error:
            first.setdefault(call.name, index)
    missing = [tool for tool in tools if tool not in first]
    if missing:
        return Verdict(False, f"never called successfully: {', '.join(missing)}")
    positions = [first[tool] for tool in tools]
    if positions == sorted(positions):
        return Verdict(True, f"first calls in order: {' -> '.join(tools)}")
    actual = sorted(tools, key=lambda tool: first[tool])
    return Verdict(False, f"expected {' -> '.join(tools)}, got {' -> '.join(actual)}")


def to_nearest_stop(trace: Sequence[ToolCall], spec: Spec) -> Verdict:
    """A successful call used a site's `nearest_stop` (that site's, if `site` is given)."""
    tool = spec.get("tool", "get_connections")
    argument = spec.get("argument", "destination")
    sites = load_sites()
    if "site" in spec:
        sites = [site for site in sites if site.id == spec["site"]]
    stops = {_norm(site.nearest_stop): site.nearest_stop for site in sites}
    used = [
        call.arguments.get(argument) for call in trace if call.name == tool and not call.is_error
    ]
    if any(_norm(value) in stops for value in used):
        return Verdict(True, f"{tool}.{argument} is a site's nearest_stop")
    return Verdict(
        False, f"expected {tool}.{argument} in {sorted(stops.values())}, got {used or 'no call'}"
    )


def recovers(trace: Sequence[ToolCall], spec: Spec) -> Verdict:
    """A failed `tool` call, then a `via` call, then a successful `tool` call matching `with`."""
    tool, via, wanted = spec["tool"], spec["via"], spec.get("with", {})
    failed = next((i for i, call in enumerate(trace) if call.name == tool and call.is_error), None)
    if failed is None:
        return Verdict(False, f"no failed {tool} call, so nothing to recover from")
    looked = next((i for i in range(failed + 1, len(trace)) if trace[i].name == via), None)
    if looked is None:
        return Verdict(False, f"{tool} failed but {via} was never called afterwards")
    fixed = any(_matches(call, tool, wanted) and not call.is_error for call in trace[looked + 1 :])
    if fixed:
        return Verdict(True, f"{tool} failed, {via} was called, then {tool} succeeded")
    return Verdict(False, f"after {via}, no successful {tool} with {dict(wanted)}")


CHECKS: dict[str, Check] = {
    "called": called,
    "min_calls": min_calls,
    "order": order,
    "to_nearest_stop": to_nearest_stop,
    "recovers": recovers,
}

REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "called": ("tool",),
    "min_calls": ("tool", "count"),
    "order": ("tools",),
    "to_nearest_stop": (),
    "recovers": ("tool", "via"),
}


def validate(assertion: Mapping[str, Any]) -> None:
    """Refuse an assertion the harness cannot run, at load time rather than mid-run."""
    if len(assertion) != 1:
        raise ValueError(f"an assertion is a one-key mapping, got {dict(assertion)}")
    [(kind, spec)] = assertion.items()
    if kind not in CHECKS:
        raise ValueError(f"unknown assertion {kind!r}; known: {', '.join(CHECKS)}")
    if not isinstance(spec, Mapping):
        raise ValueError(f"{kind}: expected a mapping, got {spec!r}")
    missing = [key for key in REQUIRED_KEYS[kind] if key not in spec]
    if missing:
        raise ValueError(f"{kind}: missing {', '.join(missing)}")


def evaluate(
    trace: Sequence[ToolCall], assertions: Sequence[Mapping[str, Any]]
) -> list[tuple[str, Verdict]]:
    """Run every assertion against the trace, in order."""
    results: list[tuple[str, Verdict]] = []
    for assertion in assertions:
        validate(assertion)
        [(kind, spec)] = assertion.items()
        results.append((kind, CHECKS[kind](trace, spec)))
    return results
