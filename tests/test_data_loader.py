"""Loader tests.

The packaged YAML files hold placeholders today, so these assert on *shape and validation*, never
on real site names or factor values. They must keep passing once Pierre replaces the content.
"""

from pathlib import Path

import pytest

from swiss_outdoor_mcp.data_loader import DataFileError, load_emission_factors, load_sites
from swiss_outdoor_mcp.models import Site

VALID_SITE = """
sites:
  - id: some-launch
    name: Some Launch
    region: Vaud
    lat: 46.5
    lon: 6.6
    altitude_m: 1500
    orientations: [S, SW]
    nearest_stop: Somewhere
"""


def write(tmp_path: Path, content: str, name: str = "sites.yaml") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_packaged_sites_file_loads() -> None:
    sites = load_sites()

    assert sites, "sites.yaml should never be empty"
    assert all(isinstance(site, Site) for site in sites)


def test_packaged_emission_factors_cover_every_mode() -> None:
    factors = load_emission_factors()

    assert set(factors) == {"train", "bus", "car"}


def test_loads_a_valid_site(tmp_path: Path) -> None:
    sites = load_sites(write(tmp_path, VALID_SITE))

    assert len(sites) == 1
    assert sites[0].id == "some-launch"
    assert sites[0].orientations == ["S", "SW"]
    assert sites[0].access_notes == ""


def test_rejects_duplicate_site_ids(tmp_path: Path) -> None:
    doubled = VALID_SITE + VALID_SITE.replace("sites:\n", "")

    with pytest.raises(DataFileError, match="duplicate site id 'some-launch'"):
        load_sites(write(tmp_path, doubled))


def test_rejects_an_unknown_key(tmp_path: Path) -> None:
    """A typo must fail loudly rather than being silently dropped."""
    with pytest.raises(DataFileError, match="orientation"):
        load_sites(write(tmp_path, VALID_SITE + "    orientation: N\n"))


def test_rejects_coordinates_outside_switzerland(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match="lat"):
        load_sites(write(tmp_path, VALID_SITE.replace("lat: 46.5", "lat: 6.6")))


def test_rejects_a_repeated_orientation(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match="same orientation twice"):
        load_sites(write(tmp_path, VALID_SITE.replace("[S, SW]", "[S, S]")))


def test_rejects_an_invalid_orientation(tmp_path: Path) -> None:
    with pytest.raises(DataFileError):
        load_sites(write(tmp_path, VALID_SITE.replace("[S, SW]", "[SOUTH]")))


def test_rejects_a_non_mapping_top_level(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match="mapping at the top level"):
        load_sites(write(tmp_path, "- just\n- a list\n"))


def test_rejects_broken_yaml(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match="not valid YAML"):
        load_sites(write(tmp_path, "sites: [unclosed\n"))


def test_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match="cannot read"):
        load_sites(tmp_path / "absent.yaml")


def test_rejects_an_emission_factor_without_a_source(tmp_path: Path) -> None:
    missing_source = """
factors:
  train:
    value_kg_per_pkm: 0.03
    source_url: https://example.org/factors
    retrieved_on: 2026-01-01
"""
    with pytest.raises(DataFileError, match="source_name"):
        load_emission_factors(write(tmp_path, missing_source, "emission_factors.yaml"))


def test_rejects_an_unknown_transport_mode(tmp_path: Path) -> None:
    unknown_mode = """
factors:
  helicopter:
    value_kg_per_pkm: 0.5
    source_name: Somebody
    source_url: https://example.org/factors
    retrieved_on: 2026-01-01
"""
    with pytest.raises(DataFileError):
        load_emission_factors(write(tmp_path, unknown_mode, "emission_factors.yaml"))
