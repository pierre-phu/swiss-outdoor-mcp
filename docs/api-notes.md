# API notes — verified facts

Every statement here was checked against the source linked next to it, on **2026-09-23**.
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

> **Decision needed for `get_flyability` (day 2).** `icon_d2_eps` has the resolution the Alps
> demand (2 km) but only reaches **2 days** ahead — not enough for "where can I fly on Saturday"
> asked on a Monday. `icon_eu_eps` gives 5 days at 13 km, which smooths Alpine valley wind badly.
> Options: pick `icon_eu_eps` for range; or select the model per requested date; or request
> several models and report which one answered. **Pierre decides.**

### 2.2 Hourly variables we need

| Variable | Meaning (quoted from the docs) | Unit |
| --- | --- | --- |
| `wind_speed_10m` | "Wind speed at 10, 80, 100 or 120 meters above ground" | km/h by default |
| `wind_gusts_10m` | "Gusts at 10 meters above ground as a maximum of the preceding hour" | km/h |
| `wind_direction_10m` | Wind direction at the given height | ° |
| `precipitation` | "Total precipitation (rain, showers, snow) sum of the preceding hour" | mm |

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

### 2.4 Rate limits, licence, attribution

Source: <https://open-meteo.com/en/terms> and <https://open-meteo.com/en/licence>

- Free non-commercial limits: **600 calls/min, 5 000 calls/hour, 10 000 calls/day**.
- Licence: **CC BY 4.0** (<https://creativecommons.org/licenses/by/4.0/>).
- Attribution is **required**: *"You must include a link next to any location Open-Meteo data are
  displayed, for example: Weather data by Open-Meteo.com"*. → the `Flyability` output must carry
  this attribution, and it goes in the README.

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

---

## UNVERIFIED

Do not build on any of these without checking first. Listed for Pierre.

1. **transport.opendata.ch rate limit — no number anywhere.** The docs defer to
   timetable.search.ch, whose own limit we have not found. *Mitigation:* treat the API as scarce —
   cache aggressively, keep `limit` small, and never call it in a loop over all sites.
2. **transport.opendata.ch licence and terms of use.** Neither the docs page nor the landing page
   states one, and the API self-describes as "inofficial". Unknown whether attribution is required
   or whether production use is sanctioned. *Mitigation:* credit it in the README anyway, and note
   in the README limitations that the upstream terms are unclear.
3. **Whether `/locations?x=&y=` populates `distance`.** It was `null` for a `query=` search. Not
   probed with coordinates. Only matters if we ever do nearest-stop lookup by position.
4. **Open-Meteo: whether the unsuffixed series is formally the control run.** The member-count
   arithmetic (control + 19 = 20 advertised) makes this near-certain, but it is inference from a
   probe, not a documented statement. Affects what `n_members` should report.
5. **Open-Meteo: per-model horizon when several models are requested at once.** Untested whether
   a mixed `models=` request truncates to the shortest horizon or pads with nulls.
6. **`mcp` 2.2.0 is pinned from PyPI metadata only.** The exact `ToolError` message envelope and
   `Client` signature come from the SDK docs on `main`, which may be ahead of the 2.2.0 release.
   The `ping` tool and its test exist precisely to catch a mismatch on day 1.
