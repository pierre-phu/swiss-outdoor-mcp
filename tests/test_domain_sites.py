"""Site filtering.

Built on hand-made sites rather than the packaged file, so these keep passing when Pierre edits
`sites.yaml`. One test does touch the real file, to check the filters agree with the content.
"""

import pytest

from swiss_outdoor_mcp.data_loader import load_sites
from swiss_outdoor_mcp.domain.sites import filter_sites, get_site
from swiss_outdoor_mcp.errors import SiteNotFoundError
from swiss_outdoor_mcp.models import Site


def make_site(site_id: str, region: str, orientations: list[str]) -> Site:
    return Site(
        id=site_id,
        name=site_id.title(),
        region=region,
        lat=46.5,
        lon=6.6,
        altitude_m=1_500,
        orientations=orientations,  # type: ignore[arg-type]
        nearest_stop="Somewhere",
    )


SITES = [
    make_site("alpha", "Vaud", ["S", "SW"]),
    make_site("beta", "Valais", ["W"]),
    make_site("gamma", "Valais", ["S", "SE"]),
]


def test_no_filters_returns_everything_in_order() -> None:
    assert [site.id for site in filter_sites(SITES)] == ["alpha", "beta", "gamma"]


def test_filters_by_region() -> None:
    assert [site.id for site in filter_sites(SITES, region="Valais")] == ["beta", "gamma"]


def test_region_is_case_and_whitespace_insensitive() -> None:
    """An LLM may well send 'valais '. That should not silently return nothing."""
    assert [site.id for site in filter_sites(SITES, region=" valais ")] == ["beta", "gamma"]


def test_filters_by_orientation() -> None:
    assert [site.id for site in filter_sites(SITES, orientation="S")] == ["alpha", "gamma"]


def test_orientation_is_exact_not_widened() -> None:
    """'SW' must not match a site that only faces 'S'; widening is get_flyability's job."""
    assert [site.id for site in filter_sites(SITES, orientation="SW")] == ["alpha"]


def test_filters_combine() -> None:
    assert [site.id for site in filter_sites(SITES, region="Valais", orientation="S")] == ["gamma"]


def test_no_match_returns_an_empty_list() -> None:
    assert filter_sites(SITES, region="Ticino") == []


def test_does_not_mutate_its_input() -> None:
    filter_sites(SITES, region="Vaud")

    assert len(SITES) == 3


def test_every_packaged_site_is_reachable_by_its_own_region_and_orientation() -> None:
    """A site the filters cannot return would be invisible to the LLM."""
    sites = load_sites()

    for site in sites:
        by_region = filter_sites(sites, region=site.region)
        assert site.id in {found.id for found in by_region}
        for sector in site.orientations:
            by_orientation = filter_sites(sites, orientation=sector)
            assert site.id in {found.id for found in by_orientation}


class TestGetSite:
    def test_finds_by_exact_id(self) -> None:
        sites = [make_site("fiesch", "Valais", ["S"]), make_site("jaman", "Vaud", ["W"])]

        assert get_site(sites, "jaman").region == "Vaud"

    @pytest.mark.parametrize("site_id", ["chamonix", "Fiesch", " fiesch", "fie"])
    def test_anything_else_names_the_recovery_call(self, site_id: str) -> None:
        with pytest.raises(SiteNotFoundError, match="Call list_sites"):
            get_site([make_site("fiesch", "Valais", ["S"])], site_id)
