# swiss-outdoor-mcp

[![CI](https://github.com/pierre-phu/swiss-outdoor-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/pierre-phu/swiss-outdoor-mcp/actions/workflows/ci.yml)

An [MCP](https://modelcontextprotocol.io) server that gives an LLM client reliable, computed facts
for planning Swiss mountain outings by public transport. The v0.1 use case is paragliding:

> "Saturday, from Lausanne, where can I go paragliding by train?"

The server does not answer that question. It provides the deterministic pieces — launch sites,
ensemble-based flyability probabilities, train connections — and the LLM composes them.
**There are no LLM calls inside the server.**

## Status

Work in progress (day 3 of a 5-day build). Working today: `list_sites`, `get_flyability` and
`get_connections`. Still to come: `estimate_trip_co2`, offline fixture mode and the eval harness.
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

- `p_flyable` is the **share of ensemble members** that agree, not a calibrated probability.
- Winds are **10 m above the model's terrain**, not at launch height. The model cell can sit
  hundreds of metres from the real launch altitude; `grid_elevation_m` reports it. No thermals,
  no foehn, no upper winds.
- **Near-calm hours can score low**: the direction check applies whatever the wind speed, so a
  1 km/h breeze from the wrong side fails it.
- The forecast reaches about **four days out**. The exact horizon moves with each model run and
  is read from every response.
- The sites' `access_notes` (the last leg from the stop to the launch) are not filled in yet.

## Data sources

- Weather: [Open-Meteo](https://open-meteo.com) Ensemble API — weather data by Open-Meteo.com,
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Public transport: [transport.opendata.ch](https://transport.opendata.ch) (an unofficial API over
  the Swiss timetable; its terms of use are not stated — see `docs/api-notes.md`).

## Licence

MIT — see [LICENSE](LICENSE).
