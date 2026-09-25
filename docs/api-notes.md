# API notes — verified facts

Every statement here was checked against the source linked next to it, on **2026-09-23**.
§2.5, §2.6 and §3.5 were added on **2026-09-24**; §3.6, §3.7, the two SDK notes at the end of
§1.4 and the wind-direction convention in §2.2 on **2026-09-25**.
Anything that could not be confirmed is in [UNVERIFIED](#unverified) at the bottom — never build
on those without checking first.

Facts marked *(probe)* were confirmed by issuing a real request to the live API; the exact request
is given so it can be repeated.

---

## 1. MCP Python SDK

| Fact | Value | Source |
| --- | --- | --- |
| PyPI package | `mcp` (extras: `cli`, `rich`) | <https://pypi.org/pypi/mcp/json> |
| Latest version | 2.2.0 | <https://pypi.org/pypi/mcp/json> |
| `requires-python` | `>=3.10` | <https://pypi.org/pypi/mcp/json> |
| Tested Python versions | 3.10, 3.11, 3.12, 3.13, 3.14 (classifiers) | <https://github.com/modelcontextprotocol/python-sdk/blob/main/pyproject.toml> |
| HTTP dependency | `httpx2>=2.5.0` — **not** `httpx` | <https://github.com/modelcontextprotocol/python-sdk/blob/main/pyproject.toml> |
| Other key deps | `pydantic>=2.12.0`, `mcp-types`, `anyio`, `jsonschema>=4.20.0` | <https://pypi.org/pypi/mcp/json> |

> **This is the 2.x SDK, not the 1.x `FastMCP` API.** Most blog posts and older examples online
> show `from mcp.server.fastmcp import FastMCP`. That is not what we target. `fastmcp.py` still
> exists in the tree but the documented entry point is `MCPServer`.

### 1.1 Creating a server and declaring a tool

Source: <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/get-started/first-steps.md>
and <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/tools.md>

```python
from mcp.server import MCPServer  # the docs state: "There is no `from mcp import MCPServer`."

mcp = MCPServer("my-server")


@mcp.tool()
def search_books(query: str, limit: int = 10):
    """Search the catalog by title or author."""
```

- Tool **name, description and JSON schema are derived from the function**: its name, its
  docstring and its type hints. No separate schema declaration.
- Per-argument constraints and descriptions use `Annotated[..., Field(...)]`; Pydantic models are
  accepted as argument types and as return types (structured output).
- The decorator accepts `name=`, `title=`, `description=` and `annotations={...}` (behavioural
  hints such as `read_only_hint`, `idempotent_hint`).
- `async def` tools are supported.

### 1.2 How tool errors reach the client

Source: <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/handling-errors.md>
and <https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/mcpserver/exceptions.py>

```python
from mcp.server.mcpserver.exceptions import ToolError

raise ToolError(f"No book titled '{title}' in the catalog.")
```

Three distinct failure modes:

| Raise | Result seen by the client | Use it for |
| --- | --- | --- |
| `ToolError` | `is_error=True`, `content=[TextContent(text="Error executing tool <name>: <your message>")]`, `structured_content=None`. Logged at INFO, no traceback. | Failures the model can recover from by calling again differently. |
| `MCPError` (`mcp.shared.exceptions`) | JSON-RPC protocol error, e.g. code `-32602` INVALID_PARAMS. Goes to the host application; the model gets no retry. | Protocol-level failures. |
| Anything else | Wrapped as `UnexpectedToolError`; the model only sees `"Error executing tool <name>"`, the traceback is logged server-side at ERROR. | Bugs. |

The documented decision rule: *"Could a smarter model have avoided this?"* Yes → `ToolError`.
No → `MCPError`.

**Critical gotcha, quoted from the docs:** *"A returned string has `is_error=False`, so to the
model (and to every client UI) it looks like the tool worked."* — so we must **raise**, never
return, an error message. This is what `errors.py` + the mapping in `server.py` enforce.

Exception hierarchy (`src/mcp/server/mcpserver/exceptions.py`): `MCPServerError(Exception)` →
`ToolError`, `ResourceError`; `UnexpectedToolError(ToolError)`;
`ResourceNotFoundError(ResourceError)`; `UnexpectedResourceError(ResourceError)`.

### 1.3 Running over stdio

Source: <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md>

```python
if __name__ == "__main__":
    mcp.run()  # stdio is the DEFAULT transport; mcp.run(transport="stdio") is equivalent
```

- `run()` is synchronous and *"blocks for the life of the server"*.
- The host launches the file as a subprocess and speaks over its stdin/stdout. No port.
- Local inspection: `uv run mcp dev server.py` (MCP Inspector) — needs the `cli` extra.

### 1.4 In-process test client

Source: <https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/get-started/testing.md>

The server object is passed straight to `Client`, like FastAPI's `TestClient` — no subprocess, no
manual memory streams:

```python
import pytest
from mcp import Client

from server import mcp


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
```

- `Client` is exported from the top level: `from mcp import Client`
  (<https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/__init__.py>).
- `raise_exceptions=True` surfaces real errors from crashes *outside* tool bodies. Tool failures
  still come back normally as a result with `is_error=True`.
- The docs use **`anyio`'s pytest plugin** (`@pytest.mark.anyio` + an `anyio_backend` fixture),
  which is why this project uses `anyio` rather than `pytest-asyncio`.
- `mcp.shared.memory` exposes only `create_client_server_memory_streams()` — the lower-level
  primitive. We do not need it.
- ⚠️ **A listed tool's schema is `tool.input_schema`, snake_case** *(confirmed 2026-09-25 by
  `AttributeError` in a test)*. The wire format keeps the JSON-RPC spelling `inputSchema`, and the
  1.x SDK exposed that name on the Python object too, so every older example is wrong here. The
  Pydantic model raises `AttributeError: 'Tool' object has no attribute 'inputSchema'`.
- A `tools/call` result carries `content`, `isError` **and** `structuredContent` *(probe over real
  stdio, 2026-09-25)*. A tool returning a Pydantic model or a list of them gets the parsed object
  in `structuredContent`, with the JSON text mirrored in `content[0].text`.

---

## 2. Open-Meteo Ensemble API

Docs: <https://open-meteo.com/en/docs/ensemble-api>

| Fact | Value |
| --- | --- |
| Endpoint | `https://ensemble-api.open-meteo.com/v1/ensemble` |
| API key | Not required for the free non-commercial tier (*"Only required to commercial use to access reserved API resources for customers."*) |
| Query parameters | `latitude`, `longitude`, `hourly`, `models`, `forecast_days`, `start_date`, `end_date`, `timezone`, `wind_speed_unit` |
| Max horizon | *"Up to 35 days of forecast are possible"* — but **per model**, see the table below |

### 2.1 Models (name, resolution, members, horizon)

| Model id | Coverage | Resolution | Members | Horizon |
| --- | --- | --- | --- | --- |
| `icon_d2_eps` | Central Europe | **2 km** | 20 | **2 days** |
| `icon_eu_eps` | Europe | 13 km | 40 | 5 days |
| `icon_seamless` / global ICON-EPS | Global | 26 km | 40 | 7.5 days |
| GFS Ensemble 0.25° | Global | 0.25° | 31 | 10 days |
| GFS Ensemble 0.5° | Global | 0.5° | 31 | 35 days |
| ECMWF IFS 0.25° | Global | 0.25° | 51 | 15 days |
| ECMWF IFS Europe | Europe | 9 km (O1280) | 51 | 15 days |
| UKMO MOGREPS-G | Global | 20 km | 18 | 8 days |
| GEM | Global | 0.25° | 21 | 16 days |
| Google WeatherNext 2 | Global | — | 64 | 15 days |

> **Decided (Pierre, 2026-09-24): request both `icon_d2_eps` and `icon_eu_eps` in a single call,
> and use whichever one actually covers the requested date** — `icon_d2_eps` for the near term
> (today and tomorrow), `icon_eu_eps` from day 3 out to day 5. `Flyability.model` reports which
> one answered, so the user always knows whether they got the 2 km grid or the 13 km one.
> The mechanics of a two-model request are in §2.5; the selection rule is in §2.6.

### 2.2 Hourly variables we need

| Variable | Meaning (quoted from the docs) | Unit |
| --- | --- | --- |
| `wind_speed_10m` | "Wind speed at 10, 80, 100 or 120 meters above ground" | km/h by default |
| `wind_gusts_10m` | "Gusts at 10 meters above ground as a maximum of the preceding hour" | km/h |
| `wind_direction_10m` | Wind direction at the given height | ° |
| `precipitation` | "Total precipitation (rain, showers, snow) sum of the preceding hour" | mm |

**`wind_direction_10m` is the direction the wind blows _from_** (meteorological convention),
0-360° with 0/360 = north. *(verified 2026-09-25 from source — neither the
[ensemble docs](https://open-meteo.com/en/docs/ensemble-api) nor the
[forecast docs](https://open-meteo.com/en/docs) state it.)* Open-Meteo derives direction from the
u/v wind components in `windirectionFast(u, v)`,
[`Sources/CHelper/src/shim.c` at `faa076a`](https://github.com/open-meteo/open-meteo/blob/faa076aee2142cf921a4df3c6223b1818089a5f7/Sources/CHelper/src/shim.c):
a pure eastward flow (`v == 0`, `u > 0`) returns **270** (from the west) and a pure northward flow
(`u == 0`, `v > 0`) returns **180** (from the south). The commented-out reference formula in
`Sources/App/Helper/Meteorology.swift`, `atan2(u, v) + 180`, agrees. This is what lets
`get_flyability` compare the value directly with the sector a launch faces: a south-facing slope
wants wind from the south.

### 2.3 Ensemble members in the JSON response *(probe)*

The docs do not spell this out. Confirmed live:

```
GET https://ensemble-api.open-meteo.com/v1/ensemble
    ?latitude=46.52&longitude=6.63&hourly=wind_speed_10m&models=icon_d2_eps&forecast_days=1
```

Members are **flattened into sibling keys** of `hourly` (and `hourly_units`), suffixed
`_memberNN` with a **two-digit, 1-based** index. There is **no nested array of members**:

```json
{
  "hourly_units": { "time": "iso8601", "wind_speed_10m": "km/h", "wind_speed_10m_member01": "km/h", "...": "..." },
  "hourly": { "time": ["2026-09-23T00:00", "..."], "wind_speed_10m": [...], "wind_speed_10m_member01": [...] }
}
```

- For `icon_d2_eps` the response carried the unsuffixed `wind_speed_10m` plus
  `wind_speed_10m_member01` … `wind_speed_10m_member19` → **the unsuffixed series is the control
  run**, and control + 19 perturbed members = the 20 members the docs advertise.
- Consequence for the client: member count must be **discovered from the response keys**, not
  hard-coded, and the control run must be counted deliberately (in or out of `n_members`).
- `elevation` is echoed back (483.0 m for the probe above) — the model's grid-cell elevation, not
  the site's. Worth returning so the user can see the model is flying a different mountain.
- Without `timezone=`, times come back as **naive UTC** (`"timezone":"GMT"`,
  `utc_offset_seconds: 0`). We must pass `timezone=Europe/Zurich` or convert explicitly.

> ⚠️ **The key names above are the _single-model_ shape.** `get_flyability` always asks for two
> models at once, and that appends a `_<model_id>` suffix to every key. Build the client against
> §2.5, not against this section, and do not record a single-model fixture for it.

### 2.4 Rate limits, licence, attribution

Source: <https://open-meteo.com/en/terms> and <https://open-meteo.com/en/licence>

- Free non-commercial limits: **600 calls/min, 5 000 calls/hour, 10 000 calls/day**.
- Licence: **CC BY 4.0** (<https://creativecommons.org/licenses/by/4.0/>).
- Attribution is **required**: *"You must include a link next to any location Open-Meteo data are
  displayed, for example: Weather data by Open-Meteo.com"*. → the `Flyability` output must carry
  this attribution, and it goes in the README.

### 2.5 Requesting two models at once *(probe)*

This resolves [UNVERIFIED 5](#unverified). Probed on **2026-09-24**:

```
GET https://ensemble-api.open-meteo.com/v1/ensemble
    ?latitude=46.4048&longitude=8.09598
    &hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation
    &models=icon_d2_eps,icon_eu_eps&forecast_days=5&timezone=Europe/Zurich
```

**One merged object, not a list.** The response is a single JSON object with one `hourly` block
and **one shared `time` axis**, exactly like a single-model response. There is no per-model
nesting and no list to iterate.

**Every series gains a `_<model_id>` suffix.** The key grammar becomes:

```
<variable>[_memberNN]_<model_id>
    wind_speed_10m_icon_d2_eps            <- control run, ICON-D2-EPS
    wind_speed_10m_member01_icon_d2_eps   <- perturbed member 1
    wind_speed_10m_member39_icon_eu_eps   <- perturbed member 39, ICON-EU-EPS
```

- The suffix appears **even on the control run**, and in `hourly_units` as well.
- Series counts matched the advertised member counts exactly, for all four variables we need:
  **20 for `icon_d2_eps`** (control + `member01`…`member19`) and **40 for `icon_eu_eps`**
  (control + `member01`…`member39`). That is a second, independent confirmation of the
  control-run reading in §2.3 (see [UNVERIFIED 4](#unverified)).

**The shorter model is padded with `null`, not truncated.** The shared time axis runs to the
**longest** model's horizon; the shorter model's series are the same length and simply end in
`null`. From the probe above (issued 2026-09-24, `forecast_days=5`, 120 hourly steps):

| Model | Non-null steps | Last non-null timestamp |
| --- | --- | --- |
| `icon_d2_eps` | 45 of 120 | `2026-09-25T20:00` (D+1) |
| `icon_eu_eps` | 117 of 120 | `2026-09-28T20:00` (D+4) |

- The `null` tail is **contiguous** — once a model's values stop, every later step is `null`. So
  "does this model cover hour X" is a plain non-null test, with no holes to defend against.
- **`forecast_days` cannot buy horizon.** Re-probed with `forecast_days=7`: the time axis grew to
  168 steps but the non-null counts did not move (still 45 and 117). Asking for more days only
  enlarges the `null` padding and the payload. Size the request to the date actually requested.
- ⚠️ **A model's cut-off is run-relative and drifts through the day**, so it is not a whole number
  of calendar days. Both models ended at 20:00 local here — mid-evening, not midnight.
  **Never derive coverage arithmetically from the lead time; read it off the `null`s.**

**One `elevation` for the whole response.** The merged response returns a single top-level
`elevation` (2173.0 m in the probe), not one per model. Both models also returned 2173.0 m when
probed individually at this site, so nothing was lost here — but that is one site, and a merged
request cannot show a per-model grid elevation.

### 2.6 Model selection rule for `get_flyability`

Decided by Pierre on 2026-09-24. It relies on the mechanics in §2.5.

1. Ask for **both** models in **one** HTTP call (one call, two models — not two calls).
2. Slice the requested date's window (10:00–17:00 Europe/Zurich) out of the shared `time` axis.
3. If **`icon_d2_eps` is non-null across that whole window → use `icon_d2_eps`** (2 km).
4. Otherwise, if **`icon_eu_eps` is → use `icon_eu_eps`** (13 km).
5. Otherwise → `DateOutOfRangeError`.

`Flyability.model` reports the id that answered, and `n_members` counts **that model's** keys only
(20 vs 40). The two ensembles must never be pooled: different resolutions, different biases.

> **Why the rule tests the data rather than the lead time.** Pierre's instruction was "d2 under
> 2 days, eu for 3–5 days". Written as arithmetic that leaves D+2 undefined and, worse, assumes a
> cut-off that actually drifts with the model run (§2.5). Testing the `null`s carries out the same
> intent without either problem: on the probe date `icon_d2_eps` reached D+1 20:00, so D+0 and D+1
> take the 2 km grid and D+2 onward fall through to `icon_eu_eps` — the rule exactly as stated.
> When a run is late, behaviour degrades to the coarser model instead of reading `null` as data.

> **Horizon, stated as dates.** On the probe date `icon_eu_eps` covered the 10:00–17:00 window
> through **D+4** — five calendar days counting today. "5 days" in the model table is *not* D+5.
> `DateOutOfRangeError` should quote the last date that actually answered instead of a hard-coded
> `+5`, and the eval's "Saturday" task must not sit silently on that boundary.

---

## 3. transport.opendata.ch

Docs: <https://transport.opendata.ch/docs.html> · Base URL: `https://transport.opendata.ch/v1`

The site describes itself as an **inofficial** API over the Swiss timetable
(<https://transport.opendata.ch/>).

### 3.1 `/locations`

Parameters: `query` (name search), `x` (latitude), `y` (longitude), `type`
(`all` | `station` | `poi` | `address`).

Response *(probe: `GET /v1/locations?query=Lausanne`)*:

```json
{"stations": [
  {"id": "8501120", "name": "Lausanne", "score": null,
   "coordinate": {"type": "WGS84", "x": 46.516795, "y": 6.629087},
   "distance": null, "icon": "train"}
]}
```

> ⚠️ **`coordinate.x` is the LATITUDE and `coordinate.y` is the LONGITUDE.** Confirmed by the
> probe: Lausanne is 46.52 N / 6.63 E, and the response gives `x: 46.51`, `y: 6.62`. Getting this
> backwards silently produces a plausible-looking distance somewhere in Somalia. The haversine
> code in `estimate_trip_co2` must have a test pinning this.

- `distance` was `null` for a `query=` search. Presumably populated for an `x`/`y` search — see
  [UNVERIFIED](#unverified).
- `score` was `null` throughout the probe, so we cannot rank suggestions by it.

### 3.2 `/connections`

Parameters: `from` (required), `to` (required), `via` (≤ 5), `date` (`YYYY-MM-DD`), `time`
(`hh:mm`), `isArrivalTime` (boolean), `transportations`
(`train` | `tram` | `ship` | `bus` | `cableway`), `limit` (1–16), `page` (0–3).

Response *(probe: `GET /v1/connections?from=Lausanne&to=Leysin&limit=1`)*:

- Top level: `connections`, `from`, `to`, `stations`.
- Each connection: `from`, `to`, `duration`, `transfers`, `service`, `products`, `capacity1st`,
  `capacity2nd`, `sections`.

> ⚠️ **`duration` is a string like `"00d04:41:00"`** (`DDd HH:MM:SS`), not a number of minutes.
> `SPEC.md` wants `duration_min: int`, so the client must parse this. Needs a unit test with a
> multi-day value.

> ⚠️ **Sections are keyed `departure` / `arrival`, not `from` / `to`.** A section has exactly
> `{departure, arrival, journey, walk}`. `SPEC.md` calls the fields `from_stop`/`to_stop`, so the
> mapping happens in the client.

- A **checkpoint** (`connection.from`, `section.departure`, …) has: `departure`,
  `departureTimestamp`, `arrival`, `arrivalTimestamp`, `delay`, `platform`, `prognosis`,
  `realtimeAvailability`, `location`, `station`. In the probe `station` and `location` were the
  **same object** — `station` is the legacy alias; prefer `location`.
- Timestamps are ISO 8601 **with offset** (`"2026-09-24T00:24:00+0200"`), plus a Unix
  `*Timestamp`. Good: no timezone guessing needed.
- `journey` (null on walking sections) has: `category`, `categoryCode`, `number`, `name`,
  `operator`, `subcategory`, `passList`, `to`, `capacity1st`, `capacity2nd`.
  In the probe `categoryCode` was `null` while `category` was `"R"` — **use `category`**.
- `walk` is `null` on transport sections and `{"duration": 120}` (seconds) on walking sections.
- `products` is a list of category codes, e.g. `["R", "EV", "R"]`. `"EV"` is a rail-replacement
  bus, so the list is not restricted to the five `transportations` values.
- **No distance field anywhere** in a connection. `SPEC.md` is right to compute the CO₂ distance
  from `/locations` coordinates + haversine.

### 3.3 Cable cars *(probe)*

Cable cars **do** appear. `GET /v1/connections?from=Grindelwald&to=Männlichen&limit=1` returned a
connection whose sections included `category: "CC"` (operator `WAB`, the cog railway) and
`category: "PB"` (operator `LWM`, the Wengen–Männlichen aerial cableway).

But coverage is **uneven and must not be assumed**:

- `Zermatt` → `Sunnegga` returned a connection with `products: []` and a single section with no
  `journey` at all.
- `Fiesch` → `Fiescheralp` likewise returned `products: []`.
- `Leysin` → `Berneuse` (the paragliding launch) resolved only as far as a train, then a section
  with no journey.

→ **Design consequence:** `sites.yaml` must name a `nearest_stop` that the API actually routes to.
Do not rely on the API to cover the final cable car up to a launch site; `access_notes` carries
that last leg for the human.

### 3.4 Rate limits and licence

The docs say only: *"The number of HTTP requests you can send is constraint by the rate limit of
timetable.search.ch"*. No number is given, and the landing page carries no terms or licence
statement. See [UNVERIFIED](#unverified).

Response headers on a live call showed `cache-control: no-cache` and
`access-control-allow-origin: *` — **no `X-RateLimit-*` headers**, so we cannot observe our budget.

> **Decided (Pierre, 2026-09-24): transport.opendata.ch is the transport source for v0.1.** The
> unknowns in UNVERIFIED 1–2 are accepted rather than resolved, so they become engineering
> constraints instead of blockers:
>
> - **One call per user question, never a loop over sites.** `get_connections` and
>   `estimate_trip_co2` are called for a site the user already chose. Nothing may fan out across
>   `sites.yaml`; if a future tool needs that, it comes back to Pierre first.
> - **Keep `limit` at the SPEC default of 3.** The parameter accepts up to 16; we do not use it.
> - **Tests and evals never hit this API** — fixtures only, which is already the rule in
>   `CLAUDE.md`. The eval harness must stay runnable offline so a nightly run costs zero calls.
> - **Credit it in the README and state in the limitations section that its terms and rate limit
>   are undocumented and it self-describes as "inofficial".** This is the honest disclosure the
>   unknown licence calls for.
> - **A failure here is `UpstreamUnavailableError`, never a crash** — an undocumented limit means
>   we could be throttled without warning, so that path has to be real from day 2.

### 3.5 The stops named by `sites.yaml` all resolve *(probe)*

Checked on **2026-09-24**, one `GET /v1/locations?query=<nearest_stop>&type=station` per site.
Every `nearest_stop` string in `sites.yaml` came back as an **exact top match**:

| `nearest_stop` | Resolved station | id |
| --- | --- | --- |
| `Les Pléiades` | Les Pléiades | `8501288` |
| `Lally` | Lally | `8501287` |
| `Jaman` | Jaman | `8501367` |
| `Leysin-Feydey` | Leysin-Feydey | `8501482` |
| `Verbier, Médran` | Verbier, Médran | `8570693` |
| `Fiesch` | Fiesch | `8501672` |

- Three of the six are **ambiguous on a prefix search** and are only unambiguous because the
  stored string is exact: `Jaman` also matches `Clarens, Jaman`; `Leysin-Feydey` also matches
  `Leysin-Feydey, gare`; `Fiesch` also matches `Fiesch Feriendorf` and `Fiesch (Talstation)`.
  → Take the **exact-name match** when one exists rather than blindly taking `stations[0]`, and
  never "helpfully" normalise or truncate a `nearest_stop` before querying.
- Entries with a `null` `id` appear in `/locations` results and are not usable stops; filter them
  out before matching.
- These ids are **recorded for reference, not for use** — `sites.yaml` stores names, and the SPEC
  routes by name. Do not hard-code ids into the client.

### 3.6 What an unknown stop looks like *(probe)*

Probed on **2026-09-25**. This one matters: the failure is **not** an HTTP error.

```text
GET /v1/connections?from=Lausanne&to=NotARealStopXYZ&limit=1
-> HTTP 200
{"connections": [], "from": null, "to": null, "stations": {"from": [], "to": []}}
```

- **HTTP 200 with nulls.** `raise_for_status()` will never catch this. A client that only checks
  the status code reports "no connections" for a typo, which is the worst possible answer for an
  LLM: plausible, confident and wrong.
- ⚠️ **It does not say which side failed.** Probed with a valid `from=Lausanne` and a bogus `to`:
  `from`, `to` and *both* `stations` lists still came back null/empty. The response carries no
  signal about which of the two names was the bad one.
- `stations.from` / `stations.to` were empty in both probes, so they are not a source of
  candidates either.

**Design consequence.** To name the offending stop, the client has to resolve each side itself via
`/locations` and see which one has no exact match — up to two extra calls, on the error path only.
That is what `clients/transport.py` does, and it is also what makes the suggestions in
`StopNotFoundError` possible.

**The discriminator between "bad name" and "no service":** on a successful search `from` and `to`
are populated (probe: `from.name == "Lausanne"`, `to.name == "Leysin-Feydey"`). So:

| `from`/`to` | `connections` | Meaning |
| --- | --- | --- |
| populated | non-empty | normal answer |
| populated | `[]` | **no service** at that time — a real answer, not an error |
| `null` | `[]` | a stop could not be resolved — find out which, then `StopNotFoundError` |

> **`/connections` is more forgiving than it looks.** Live check on 2026-09-25:
> `to=Leysin Feydey` (the real stop is hyphenated) **routed fine** rather than failing. So the
> unknown-stop path is reached only by genuinely unresolvable names, not by ordinary misspellings.
> Good for users; it does mean the error path is rarer than the tests might suggest.

### 3.7 Category codes seen in live responses

`category` is an open vocabulary and the docs do not enumerate it, so `domain/transport.py` maps
only codes we have actually observed and lets everything else fall through to `mode: "other"` with
the raw code preserved on `Section.category`. Extend the table from evidence, never from memory.

| Code | Seen as | Mapped to |
| --- | --- | --- |
| `R` | regional train, operator SBB | `train` |
| `IR` | InterRegio, operator SBB | `train` |
| `CC` | WAB cog railway (§3.3) | `train` |
| `EV` | rail-replacement bus (§3.2) | `bus` |
| `PB` | Wengen–Männlichen aerial cableway (§3.3) | `cableway` |
| `SN` | night service, Lausanne→Aigle | *(unmapped → `other`)* |

> **`journey.number` is not always a line number.** `R` gave `70` and `IR` gave `90`, but `SN`
> gave `030845` (an internal code) and `EV` gave `EV1`, which already repeats the category. The
> line label therefore drops the prefix when the number already starts with it, so we print
> `EV1` rather than `EV EV1`.

---

## UNVERIFIED

Do not build on any of these without checking first. Listed for Pierre.

1. **transport.opendata.ch rate limit — no number anywhere.** The docs defer to
   timetable.search.ch, whose own limit we have not found. *Still unverified, but no longer a
   blocker:* Pierre accepted the risk on 2026-09-24 and it is handled by the call-budget rules
   in [§3.4](#34-rate-limits-and-licence).
2. **transport.opendata.ch licence and terms of use.** Neither the docs page nor the landing page
   states one, and the API self-describes as "inofficial". Unknown whether attribution is required
   or whether production use is sanctioned. *Still unverified, but no longer a blocker:* Pierre
   accepted the risk on 2026-09-24; we credit it and disclose the uncertainty in the README's
   limitations section. See [§3.4](#34-rate-limits-and-licence).
3. **Whether `/locations?x=&y=` populates `distance`.** It was `null` for a `query=` search. Not
   probed with coordinates. Only matters if we ever do nearest-stop lookup by position.
4. **Open-Meteo: whether the unsuffixed series is formally the control run.** The member-count
   arithmetic makes this near-certain, and [§2.5](#25-requesting-two-models-at-once-probe)
   reproduced it independently for `icon_eu_eps` (control + 39 = the 40 advertised). Still
   inference from probes rather than a documented statement. Affects what `n_members` reports.
5. ~~**Open-Meteo: per-model horizon when several models are requested at once.**~~
   **RESOLVED 2026-09-24** by probe — it pads with `null` to the longest model's horizon and each
   model stops at its own contiguous cut-off. Full findings in
   [§2.5](#25-requesting-two-models-at-once-probe). (Number kept so older references still resolve.)
6. **`mcp` 2.2.0 is pinned from PyPI metadata only.** The exact `ToolError` message envelope and
   `Client` signature come from the SDK docs on `main`, which may be ahead of the 2.2.0 release.
   The `ping` tool and its test exist precisely to catch a mismatch on day 1.
