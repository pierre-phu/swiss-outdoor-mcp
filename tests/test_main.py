"""The console script must start the server on stdio and nothing else.

Cheap, but it catches the entry point rotting after a refactor — which would only show up when a
real MCP host tried to launch us.
"""

import pytest

from swiss_outdoor_mcp import __main__


def test_main_runs_the_server_on_the_default_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(__main__.mcp, "run", fake_run)

    __main__.main()

    # stdio is MCPServer.run()'s default; passing it explicitly would be noise.
    assert calls == [((), {})]
