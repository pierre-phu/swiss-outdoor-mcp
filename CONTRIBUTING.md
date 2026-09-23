# Contributing

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+ (uv will fetch an interpreter if you
do not have one).

```bash
uv sync
uv run pre-commit install    # optional, runs lint + format on commit
```

## Checks

Run all four before every commit. CI runs exactly these, on Python 3.11, 3.12 and 3.13.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Or in one line:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
```

`uv run ruff check --fix .` and `uv run ruff format .` fix most complaints automatically.

## Running the server

```bash
uv run swiss-outdoor-mcp     # MCP over stdio; blocks until the client disconnects
```

To poke at it by hand:

```bash
uv run mcp dev src/swiss_outdoor_mcp/server.py   # MCP Inspector, needs the `cli` extra
```

## Ground rules

- **Tests never touch the network.** Clients take an injectable `httpx2` transport; tests pass an
  `httpx2.MockTransport` serving fixtures from `tests/fixtures/`.
- **No invented API facts.** Every endpoint, parameter, field and SDK signature must be in
  [`docs/api-notes.md`](docs/api-notes.md) with the URL it was verified against. If it is not
  there, verify it from official docs and add it — or stop and ask.
- **Three layers, strictly.** `server.py` is the MCP boundary and holds no logic; `domain/` is
  pure functions with no I/O, no network and no clock; `clients/` does the network.
- **`data/` is human-owned.** Real launch sites, coordinates and emission factors are the
  maintainer's to fill; an emission factor without a citable source does not go in.
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`), small and focused.
- English everywhere: code, comments, docs, commit messages.
- Dates and times shown to users are `Europe/Zurich`.

## Branches

Work on a branch named `<type>/<short-name>`, push it, and open a PR describing what changed, why,
and the trade-offs. The maintainer reviews and squash-merges.
