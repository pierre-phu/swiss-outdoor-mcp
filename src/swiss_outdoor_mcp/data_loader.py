"""Load and validate the YAML data files shipped in `swiss_outdoor_mcp.data`.

The loaders live here rather than in `data/` so that `data/` stays pure, human-owned content.
Both take an optional path so tests can point at a fixture instead of the packaged file.
"""

from importlib import resources
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from swiss_outdoor_mcp.models import (
    EmissionFactor,
    EmissionFactorsFile,
    Site,
    SitesFile,
    TransportMode,
)

__all__ = [
    "DataFileError",
    "load_emission_factors",
    "load_sites",
]

_DATA_PACKAGE = "swiss_outdoor_mcp.data"
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class DataFileError(Exception):
    """A packaged data file is missing, unparseable or fails validation.

    Not a `SwissOutdoorError`: this is a packaging bug, not something an LLM can recover from by
    calling a different tool.
    """


def _read(filename: str, path: Path | None) -> str:
    if path is not None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DataFileError(f"cannot read {path}: {exc}") from exc
    return resources.files(_DATA_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def _load(filename: str, path: Path | None, model: type[_ModelT]) -> _ModelT:
    raw = _read(filename, path)
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise DataFileError(f"{filename} is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise DataFileError(
            f"{filename} must contain a mapping at the top level, got {type(parsed).__name__}"
        )
    try:
        return model.model_validate(parsed)
    except ValidationError as exc:
        raise DataFileError(f"{filename} is invalid:\n{exc}") from exc


def load_sites(path: Path | None = None) -> list[Site]:
    """Return every launch site, in file order.

    Raises `DataFileError` if the file is unparseable, has an unknown key, or repeats a site id.
    """
    return _load("sites.yaml", path, SitesFile).sites


def load_emission_factors(path: Path | None = None) -> dict[TransportMode, EmissionFactor]:
    """Return the emission factor for each transport mode.

    Raises `DataFileError` if the file is unparseable or a factor is missing its source.
    """
    return _load("emission_factors.yaml", path, EmissionFactorsFile).factors
