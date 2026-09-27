"""The LLM side of the eval, behind one small interface.

A provider runs one task end to end: it gets the prompt, the server's tools and a `call_tool`
callback, and loops until the model stops calling tools. The harness wraps `call_tool` to record
the trace, so no provider can forget to.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam

__all__ = ["AnthropicProvider", "CallTool", "Provider", "ProviderResult", "ToolSpec"]


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the MCP server lists it."""

    name: str
    description: str
    input_schema: dict[str, Any]


CallTool = Callable[[str, dict[str, Any]], Awaitable[tuple[str, bool]]]
"""Run one tool call; returns the result text and whether it is an error."""


@dataclass(frozen=True)
class ProviderResult:
    final_text: str
    turns: int
    stop_reason: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    model: str

    async def run(
        self,
        *,
        system: str,
        prompt: str,
        tools: Sequence[ToolSpec],
        call_tool: CallTool,
        max_turns: int,
    ) -> ProviderResult: ...


class AnthropicProvider:
    """Claude through the Messages API, with a hand-written tool loop.

    A manual loop rather than the SDK's beta tool runner: it is a dozen lines, it keeps the MCP
    call in our hands, and every step the trace depends on is visible. No `temperature` or
    `thinking` settings, so the model runs as a client would run it by default.
    """

    def __init__(
        self, model: str, *, max_tokens: int = 4096, client: AsyncAnthropic | None = None
    ) -> None:
        self.model = model
        self._max_tokens = max_tokens
        self._client = client or AsyncAnthropic()

    async def run(
        self,
        *,
        system: str,
        prompt: str,
        tools: Sequence[ToolSpec],
        call_tool: CallTool,
        max_turns: int,
    ) -> ProviderResult:
        tool_params: list[ToolParam] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        messages: list[MessageParam] = [{"role": "user", "content": prompt}]
        input_tokens = output_tokens = 0

        for turn in range(1, max_turns + 1):
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=system,
                tools=tool_params,
                messages=messages,
            )
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            tool_uses = [block for block in response.content if block.type == "tool_use"]

            if response.stop_reason != "tool_use" or not tool_uses:
                text = "".join(block.text for block in response.content if block.type == "text")
                return ProviderResult(
                    text, turn, str(response.stop_reason), input_tokens, output_tokens
                )

            messages.append({"role": "assistant", "content": response.content})
            # Every result of the turn goes back in one message, as the API expects for
            # parallel calls; a failed call is sent with is_error rather than dropped.
            results: list[ToolResultBlockParam] = []
            for block in tool_uses:
                text, is_error = await call_tool(block.name, dict(block.input))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": text,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})

        return ProviderResult("", max_turns, "max_turns", input_tokens, output_tokens)
