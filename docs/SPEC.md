# SPEC — swiss-outdoor-mcp v0.1

## Goal
Give an LLM client reliable, computed facts to answer questions like:
"Saturday, from Lausanne, where can I go paragliding by train?"
The LLM orchestrates; the server provides data and deterministic computations.

## Non-goals (v0.1)
Not a flight-safety tool. No thermal/sounding analysis, no cable-car timetables,
no user accounts, no HTTP deployment, no LLM inside the server.

## Design principles
- One tool = one responsibility; the LLM composes them.
- Every flyability output carries a `disclaimer` the LLM should relay:
  indicator only, does not replace pilot judgment or official aviation forecasts.
- Assumptions are explicit and returned in outputs (`criteria`, `method`).

## Tools

### 1. `list_sites(region: str | None = None, orientation: str | None = None) -> list[Site]`
`Site`: `id`, `name`, `region`, `lat`, `lon`, `altitude_m`, `orientations: list[CompassSector]`
(e.g. `["S", "SW"]`), `nearest_stop` (exact stop name as known by the transport API), `access_notes`.
Source: `data/sites.yaml` (~10 sites in Vaud/Valais, hand-written by Pierre).

### 2. `get_flyability(site_id: str, date: date) -> Flyability`
Data: hourly ensemble forecast at the site coordinates from Open-Meteo — `wind_speed_10m`,
`wind_gusts_10m`, `wind_direction_10m`, `precipitation` (`docs/api-notes.md` §2.2).

**Model: both `icon_d2_eps` and `icon_eu_eps`, requested in a single call, and whichever one
actually covers the requested date wins** — `icon_d2_eps` (2 km, Alpine resolution) reaches about
two days out, `icon_eu_eps` (13 km) about five. Coverage is decided by testing the response for
`null`s across the window, not by arithmetic on the lead time, because a model's cut-off drifts
with its run. Full rule and the probe behind it: `docs/api-notes.md` §2.5–§2.6.

`FlyabilityCriteria` (defaults, overridable in code, returned in output):
- `max_wind_kmh = 20`, `max_gust_kmh = 30`, `max_precip_mm_h = 0.1`
- `direction_tolerance_deg = 45` (wind must come from within ±45° of one of the launch orientations;
  handle circular wrap, e.g. 350° vs 10°)
- `window = 10:00–17:00 Europe/Zurich`, `min_consecutive_hours = 3`

Computation (pure function `compute_flyability`):
- Per member and hour: flyable if all criteria hold.
- `hourly[h]`: share of members satisfying each criterion (`p_wind_ok`, `p_gust_ok`, `p_dry`,
  `p_direction_ok`) and all of them (`p_flyable`).
- Day-level `p_flyable`: share of members with ≥ `min_consecutive_hours` consecutive flyable hours in the window.
- `wind_kmh`: median, p10, p90 over members, per hour.

`Flyability` also includes: `site_id`, `date`, `criteria`, `n_members`, `model`, `generated_at`, `disclaimer`.
`model` is the id that answered (`icon_d2_eps` or `icon_eu_eps`), so the user can tell a 2 km
answer from a 13 km one; `n_members` counts that model's members only (20 vs 40) — the two
ensembles are never pooled.
Errors: unknown site, date outside the forecast horizon (the last date `icon_eu_eps` actually
answers for, discovered per request, not a hard-coded `+5`), upstream unavailable.

### 3. `get_connections(origin: str, destination: str, date: date, arrive_before: time | None = None, depart_after: time | None = None, limit: int = 3) -> list[Connection]`
`Connection`: `departure`, `arrival`, `duration_min`, `transfers`,
`sections: list[Section]` (`mode`, `line`, `from_stop`, `to_stop`, `departure`, `arrival`).
At most one of `arrive_before` / `depart_after` may be set (validation error otherwise).
Errors: unknown stop (suggest close matches if the API provides them), upstream unavailable.

### 4. `estimate_trip_co2(origin: str, destination: str) -> Co2Estimate`
Method: geocode both stops via the transport API, haversine distance × `detour_factor`
(default 1.3, documented assumption). `by_mode`: kg CO2e for train, bus, car.
`Co2Estimate`: `distance_km`, `method`, `detour_factor`, `by_mode`, `factor_source`.
Factors from `data/emission_factors.yaml`: `value_kg_per_pkm`, `source_name`, `source_url`, `retrieved_on`.

## Errors
Domain exceptions in `errors.py` (`SiteNotFoundError`, `StopNotFoundError`, `DateOutOfRangeError`,
`UpstreamUnavailableError`), mapped by `server.py` to MCP tool errors (mechanism to verify in the SDK)
with actionable messages for the LLM.

## Offline / fixture mode
Clients take an injectable `httpx2` transport. Env var `SWISS_OUTDOOR_OFFLINE=1` makes the server
serve recorded fixtures (used by evals and the demo GIF, so both are reproducible).

## Evaluation (`evals/`)
`tasks.yaml`: 5 tasks, each with a user prompt and assertions on the **tool-call trace** (not the prose):
1. "Which sites are in Valais?" → `list_sites(region="Valais")`
2. "Is it flyable on Saturday at <site>?" → `get_flyability` with correct id and resolved date
3. "How do I get from Lausanne to <site> on Saturday morning?" → `get_connections` using the site's `nearest_stop`
4. "Saturday from Lausanne, where can I fly by train?" → `list_sites` → `get_flyability` (≥ 2) → `get_connections`
5. Unknown site name → error → agent calls `list_sites` and recovers
`run_eval.py`: connects to the server over stdio as an MCP client, exposes tools to an LLM
(provider behind a small interface; first provider chosen by Pierre), records traces, prints a
pass/fail table and writes a JSON report. Run manually or nightly, never on PRs (cost, secrets).

## ADRs (`docs/adr/`)
- 0001 Deterministic tools, no LLM inside the server
- 0002 Ensemble-based flyability probability (criteria, consecutive-hours rule, limits)
- 0003 Offline fixtures for tests and evals
