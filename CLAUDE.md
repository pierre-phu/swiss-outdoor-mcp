# CLAUDE.md — swiss-outdoor-mcp

MCP server that lets any LLM client plan Swiss mountain outings by public transport.
v0.1 use case: paragliding. Maintainer: Pierre (reviews every change).

Full spec: `docs/SPEC.md` · Verified API facts: `docs/api-notes.md` · State: `docs/PROGRESS.md`
Read all three at the start of every session.

## Architecture (3 layers, strict)
- `src/swiss_outdoor_mcp/server.py` — thin MCP layer: validate input, call domain/clients, map errors. No logic.
- `src/swiss_outdoor_mcp/domain/` — pure functions (no I/O, no network, no clock). All business logic lives here.
- `src/swiss_outdoor_mcp/clients/` — async httpx clients for external APIs. Injectable transport for tests/offline mode.
- `src/swiss_outdoor_mcp/models.py` — Pydantic v2 models for every tool input/output.
- `src/swiss_outdoor_mcp/data/` — `sites.yaml`, `emission_factors.yaml` (human-owned content, see below).
- Tools are deterministic: **no LLM calls inside the server**.

## Commands
- Install: `uv sync`
- Checks (run ALL before every commit):
  `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`
- Run server locally: `uv run swiss-outdoor-mcp` (stdio)

## Priority rules (apply in this order when they conflict)
1. **Correctness and a green CI.** Never commit with failing checks. Never skip/disable a test to make CI pass.
2. **No invented facts.** Never invent API fields, endpoints, parameters, coordinates, launch sites,
   emission factors or SDK signatures. If something is not in `docs/api-notes.md`, verify it from
   official docs first and add it there with the URL. If it cannot be verified: STOP and ask.
3. **P0 scope first.** Finish every P0 of the day before touching any P1. P2 = open a GitHub issue, do not build.
4. **Pierre understands everything.** After each task, give a 3–5 line summary of the design
   choices and trade-offs. Prefer simple, readable code over clever code.
5. **Polish last.** Docs wording, refactors and extra tests come after the above.

## Scope cutting (if behind schedule, cut in this order)
1. PyPI publishing → 2. Hypothesis property tests → 3. `estimate_trip_co2` tool.
**Never cut:** CI, the eval harness, error handling, README limitations section.

## Timebox rule
If a task needs more than ~2 failed approaches or grows beyond its description:
stop, summarise what you tried, propose a simpler alternative, and wait for Pierre.

## Human-owned (Claude drafts or scaffolds, Pierre decides/fills)
- Content of `sites.yaml` (real launch sites, coordinates, orientations, nearest stop).
- Emission factor values and their source in `emission_factors.yaml`.
- ADR decisions (Claude may draft, Pierre validates before commit).
- Adding any new runtime dependency (justify it first).
- Secrets, API keys, git tags, releases, publishing.

## Conventions
- Language: English for code, comments, docs, commits.
- Python ≥ 3.11, full type hints, `mypy --strict` clean.
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`), small focused commits.
- Tests never hit the network: use `respx` + fixtures in `tests/fixtures/`
  (recorded once via `scripts/record_fixtures.py`).
- Tool error messages are written for an LLM to recover, e.g.
  `"Unknown site_id 'xyz'. Call list_sites to get valid ids."`
- Timezone: `Europe/Zurich` everywhere dates/hours are user-facing.
- Git workflow : never commit to `main` directly. Create a branch
  `<type>/<short-name>` per feature, commit there, push, and open a PR with a
  short description (what / why / trade-offs). Pierre reviews and squash-merges.

## End of every session
Update `docs/PROGRESS.md`: done / in progress / blocked / decisions taken / next step.
