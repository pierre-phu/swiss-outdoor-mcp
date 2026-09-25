# swiss-outdoor-mcp

[![pages-build-deployment](https://github.com/pierre-phu/pierre-phu.github.io/actions/workflows/pages/pages-build-deployment/badge.svg)](https://github.com/pierre-phu/pierre-phu.github.io/actions/workflows/pages/pages-build-deployment)

An [MCP](https://modelcontextprotocol.io) server that gives an LLM client reliable, computed facts
for planning Swiss mountain outings by public transport. The v0.1 use case is paragliding:

> "Saturday, from Lausanne, where can I go paragliding by train?"

The server does not answer that question. It provides the deterministic pieces — launch sites,
ensemble-based flyability probabilities, train connections — and the LLM composes them.
**There are no LLM calls inside the server.**

## Status

Day 1 of a 5-day build: project scaffold, a `ping` tool and the data schemas. The real tools
(`list_sites`, `get_flyability`, `get_connections`, `estimate_trip_co2`) land on days 2–4.
See [`docs/SPEC.md`](docs/SPEC.md).

## Install and run

```bash
uv sync
uv run swiss-outdoor-mcp     # speaks MCP over stdio
```

## Development

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Verified facts about every upstream API live in
[`docs/api-notes.md`](docs/api-notes.md) — read it before touching a client.

## Limitations

This is **not a flight-safety tool.** Flyability output is an indicator built from a public
weather model; it does not replace pilot judgment, a site briefing, or official aviation weather.

## Data sources

- Weather: [Open-Meteo](https://open-meteo.com) Ensemble API — weather data by Open-Meteo.com,
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Public transport: [transport.opendata.ch](https://transport.opendata.ch) (an unofficial API over
  the Swiss timetable; its terms of use are not stated — see `docs/api-notes.md`).

## Licence

MIT — see [LICENSE](LICENSE).
