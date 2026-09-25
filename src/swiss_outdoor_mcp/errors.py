"""Domain exceptions.

These are raised by the domain and client layers and know nothing about MCP. `server.py` is the
only module that maps them onto the protocol. Every message is written for an LLM to act on: say
what went wrong *and* name the tool call that recovers from it.
"""

from datetime import date

__all__ = [
    "DateOutOfRangeError",
    "SiteNotFoundError",
    "StopNotFoundError",
    "SwissOutdoorError",
    "UpstreamUnavailableError",
]


class SwissOutdoorError(Exception):
    """Base class for every error this server raises on purpose."""


class SiteNotFoundError(SwissOutdoorError):
    """The requested `site_id` is not in `sites.yaml`."""

    def __init__(self, site_id: str) -> None:
        super().__init__(f"Unknown site_id {site_id!r}. Call list_sites to get valid ids.")
        self.site_id = site_id


class StopNotFoundError(SwissOutdoorError):
    """A stop name was not recognised by the transport API."""

    def __init__(self, stop: str, suggestions: list[str] | None = None) -> None:
        message = f"Unknown stop {stop!r}."
        if suggestions:
            message += " Did you mean: " + ", ".join(repr(s) for s in suggestions) + "?"
        else:
            message += " Use the exact stop name as printed on the Swiss timetable."
        super().__init__(message)
        self.stop = stop
        self.suggestions = suggestions or []


class DateOutOfRangeError(SwissOutdoorError):
    """A forecast was requested for a date no weather model currently covers.

    The covered range is read off each response rather than hard-coded, because the models'
    horizon drifts with their run times (`docs/api-notes.md` section 2.6).
    """

    def __init__(self, requested: date, first_available: date, last_available: date) -> None:
        super().__init__(
            f"No forecast available for {requested.isoformat()}. The weather models currently "
            f"cover {first_available.isoformat()} to {last_available.isoformat()}; "
            "ask for a date in that range."
        )
        self.requested = requested
        self.first_available = first_available
        self.last_available = last_available


class UpstreamUnavailableError(SwissOutdoorError):
    """An external API failed or timed out."""

    def __init__(self, service: str, detail: str | None = None) -> None:
        message = f"The {service} service is unavailable right now."
        if detail:
            message += f" ({detail})"
        message += " Retry in a moment; do not treat this as a negative answer."
        super().__init__(message)
        self.service = service
        self.detail = detail
