"""Offline mode: every tool answers from `tests/fixtures/offline/`, through a real MCP session.

CI sets `SWISS_OUTDOOR_OFFLINE=1` for the whole suite, so each test here sets or clears the
variable itself and behaves the same locally and in CI.
"""

import json
from pathlib import Path

import httpx2
import pytest
from mcp import Client

import swiss_outdoor_mcp.server as server
from swiss_outdoor_mcp.clients.offline import (
    DEFAULT_FIXTURES_DIR,
    MANIFEST,
    NoRecordingError,
    fixture_transport,
    offline_enabled,
)
from swiss_outdoor_mcp.data_loader import load_sites

pytestmark = pytest.mark.anyio

SATURDAY = "2026-09-26"


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWISS_OUTDOOR_OFFLINE", "1")
    monkeypatch.delenv("SWISS_OUTDOOR_FIXTURES", raising=False)


def payload(result: object) -> object:
    return json.loads(getattr(result, "content")[0].text)  # noqa: B009


def text_of(result: object) -> str:
    return str(getattr(result, "content")[0].text)  # noqa: B009


class TestEveryToolAnswersOffline:
    async def test_get_flyability(self, client: Client, offline: None) -> None:
        result = await client.call_tool("get_flyability", {"site_id": "berneuse", "date": SATURDAY})

        assert result.is_error is False, text_of(result)
        answer = payload(result)
        assert isinstance(answer, dict)
        assert answer["model"] == "icon_d2_eps"
        assert answer["date"] == SATURDAY

    async def test_get_connections(self, client: Client, offline: None) -> None:
        result = await client.call_tool(
            "get_connections",
            {"origin": "Lausanne", "destination": "Leysin-Feydey", "date": SATURDAY},
        )

        assert result.is_error is False, text_of(result)
        assert f'"{SATURDAY}T' in text_of(result)

    async def test_estimate_trip_co2(self, client: Client, offline: None) -> None:
        result = await client.call_tool(
            "estimate_trip_co2", {"origin": "Lausanne", "destination": "Fiesch"}
        )

        assert result.is_error is False, text_of(result)
        answer = payload(result)
        assert isinstance(answer, dict)
        assert answer["destination"] == "Fiesch"

    async def test_list_sites_needs_no_recording(self, client: Client, offline: None) -> None:
        result = await client.call_tool("list_sites", {})

        assert result.is_error is False


class TestMisses:
    async def test_an_unrecorded_request_is_an_error_naming_it(
        self, client: Client, offline: None
    ) -> None:
        """Offline mode never makes an answer up: no recording, no answer."""
        result = await client.call_tool(
            "get_connections", {"origin": "Lausanne", "destination": "Villars", "date": SATURDAY}
        )

        assert result.is_error is True
        message = text_of(result)
        assert "offline mode: no recorded response" in message
        assert "Villars" in message

    async def test_a_missing_fixtures_directory_says_how_to_fix_it(
        self, client: Client, offline: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SWISS_OUTDOOR_FIXTURES", str(tmp_path / "nowhere"))

        result = await client.call_tool("get_flyability", {"site_id": "fiesch", "date": SATURDAY})

        assert result.is_error is True
        assert "SWISS_OUTDOOR_FIXTURES" in text_of(result)


class TestSwitch:
    def test_only_the_value_1_turns_it_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SWISS_OUTDOOR_OFFLINE", "0")
        assert offline_enabled() is False
        monkeypatch.setenv("SWISS_OUTDOOR_OFFLINE", "1")
        assert offline_enabled() is True

    def test_off_means_the_real_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SWISS_OUTDOOR_OFFLINE", raising=False)

        assert server._offline_transport() is None

    def test_on_means_the_recordings(self, offline: None) -> None:
        assert isinstance(server._offline_transport(), httpx2.MockTransport)


class TestMatching:
    async def test_coordinates_match_as_numbers_not_text(self) -> None:
        """46.40480 in sites.yaml and 46.4048 on the wire are the same place."""
        async with httpx2.AsyncClient(transport=fixture_transport(DEFAULT_FIXTURES_DIR)) as http:
            response = await http.get(
                "https://ensemble-api.open-meteo.com/v1/ensemble",
                params={"latitude": "46.40480", "longitude": "8.095980"},
            )

        assert response.status_code == 200

    async def test_dates_are_ignored(self) -> None:
        """A recording answers for a place, whatever day is asked for."""
        async with httpx2.AsyncClient(transport=fixture_transport(DEFAULT_FIXTURES_DIR)) as http:
            response = await http.get(
                "https://transport.opendata.ch/v1/connections",
                params={"from": "lausanne", "to": "FIESCH", "date": "2027-01-01"},
            )

        assert response.status_code == 200

    async def test_an_unknown_endpoint_is_a_miss(self) -> None:
        async with httpx2.AsyncClient(transport=fixture_transport(DEFAULT_FIXTURES_DIR)) as http:
            with pytest.raises(NoRecordingError, match="/v1/stationboard"):
                await http.get("https://transport.opendata.ch/v1/stationboard")


def test_every_site_has_its_recordings() -> None:
    """Adding a site to sites.yaml without re-recording would break offline mode for it."""
    manifest = json.loads((DEFAULT_FIXTURES_DIR / MANIFEST).read_text(encoding="utf-8"))
    recorded = {
        (entry["endpoint"], tuple(entry["match"].values())) for entry in manifest["recordings"]
    }
    hint = "re-record with: uv run python scripts/record_fixtures.py --offline"

    for site in load_sites():
        assert ("/ensemble", (str(site.lat), str(site.lon))) in recorded, f"{site.id}: {hint}"
        assert ("/connections", ("Lausanne", site.nearest_stop)) in recorded, f"{site.id}: {hint}"
        assert ("/locations", (site.nearest_stop,)) in recorded, f"{site.id}: {hint}"
