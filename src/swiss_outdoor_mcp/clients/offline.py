"""Offline mode: answer from recorded responses instead of the network.

Set `SWISS_OUTDOOR_OFFLINE=1` and both clients get an `httpx2.MockTransport` that replays the
files listed in `tests/fixtures/offline/manifest.json` (SPEC, "Offline / fixture mode"). The evals
and the demo run this way, so both are reproducible and cost the upstream APIs nothing.

A recording answers for a place, not a time. Requests are matched on the few parameters that say
*where* (coordinates, stop names) and every date, time and limit is ignored. A request with no
recording fails loudly with `NoRecordingError`; offline mode never makes an answer up.

The fixtures live in the source tree, not in the wheel: offline mode is for a checkout. Point
`SWISS_OUTDOOR_FIXTURES` at another directory to use a different recording.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx2

__all__ = [
    "DEFAULT_FIXTURES_DIR",
    "MATCH_KEYS",
    "NoRecordingError",
    "fixture_transport",
    "fixtures_dir",
    "offline_enabled",
]

ENV_FLAG = "SWISS_OUTDOOR_OFFLINE"
ENV_DIR = "SWISS_OUTDOOR_FIXTURES"
MANIFEST = "manifest.json"

# src/swiss_outdoor_mcp/clients/offline.py -> the repository root is three directories up.
DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "offline"

MATCH_KEYS: dict[str, tuple[str, ...]] = {
    "/ensemble": ("latitude", "longitude"),
    "/connections": ("from", "to"),
    "/locations": ("query",),
}
"""The query parameters that identify a recording, per endpoint (matched on the path's end)."""


class NoRecordingError(httpx2.TransportError):
    """Offline mode was asked for something it holds no recording of.

    A transport error on purpose: `clients._http.get_json` turns it into an
    `UpstreamUnavailableError` carrying this message, like any other failed request.
    """


def offline_enabled() -> bool:
    """Whether `SWISS_OUTDOOR_OFFLINE=1` is set. Read at each call, so tests can flip it."""
    return os.environ.get(ENV_FLAG) == "1"


def fixtures_dir() -> Path:
    """Where the recordings are: `SWISS_OUTDOOR_FIXTURES`, else the checkout's own set."""
    return Path(os.environ.get(ENV_DIR) or DEFAULT_FIXTURES_DIR)


def _same(recorded: str, requested: str) -> bool:
    """Coordinates compare as numbers, everything else as case-insensitive text."""
    try:
        return abs(float(recorded) - float(requested)) < 1e-6
    except ValueError:
        return recorded.strip().casefold() == requested.strip().casefold()


def _read_manifest(root: Path, request: httpx2.Request) -> list[dict[str, Any]]:
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NoRecordingError(
            f"offline mode is on but {root / MANIFEST} cannot be read; "
            f"set {ENV_DIR} to a recorded fixtures directory",
            request=request,
        ) from exc
    recordings: list[dict[str, Any]] = manifest["recordings"]
    return recordings


def fixture_transport(directory: Path | None = None) -> httpx2.MockTransport:
    """A transport that replays recordings from `directory` (default: `fixtures_dir()`).

    Nothing is read until the first request, so a missing directory surfaces as a failed tool
    call with a clear message rather than as a crash while the client is being built.
    """
    root = directory or fixtures_dir()

    def respond(request: httpx2.Request) -> httpx2.Response:
        recordings = _read_manifest(root, request)
        path = request.url.path
        endpoint = next((name for name in MATCH_KEYS if path.endswith(name)), None)
        keys = MATCH_KEYS.get(endpoint or "", ())
        asked = {key: request.url.params.get(key, "") for key in keys}

        for recording in recordings:
            if recording["endpoint"] != endpoint:
                continue
            if all(_same(str(recording["match"][key]), asked[key]) for key in keys):
                body = (root / recording["file"]).read_text(encoding="utf-8")
                return httpx2.Response(200, json=json.loads(body))

        shown = " ".join(f"{key}={value!r}" for key, value in asked.items())
        raise NoRecordingError(
            f"offline mode: no recorded response for GET {path} {shown}".rstrip(),
            request=request,
        )

    return httpx2.MockTransport(respond)
