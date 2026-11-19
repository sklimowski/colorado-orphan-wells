"""Tests for build_ranked_wells.py, run against small inputs built in the tests.

The block groups here are squares a hundredth of a degree on a side near
Denver, and the OWP zips are written with a minimal dBASE writer, so every
expected value can be worked out by hand.
"""

import csv
import io
import json
import math
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import requests

import build_ranked_wells as brw
from common import DELAY_S
from conftest import dbf_bytes, owp_row, owp_zip


def square(lon: float, lat: float, size: float = 0.01) -> list[list[float]]:
    """A closed counterclockwise square ring with its southwest corner at lon, lat."""
    return [
        [lon, lat],
        [lon + size, lat],
        [lon + size, lat + size],
        [lon, lat + size],
        [lon, lat],
    ]


def feature(  # noqa: PLR0913
    geoid: str,
    rings: list[list[list[float]]],
    *,
    di_type: str = "N/A",
    flags: Mapping[str, float | None] | None = None,
    es: float | None = 50.0,
    pop: float | None = 1000.0,
    county: str = "Adams",
) -> dict[str, Any]:
    """One CDPHE block group as the GeoJSON query returns it."""
    props: dict[str, Any] = dict.fromkeys(brw.DI_CRITERIA, 0.0)
    props["TJ"] = None  # CDPHE leaves TJ null outside tribal land
    props.update(flags or {})
    props.update(
        {
            "GEOID": geoid,
            "Cnt_N": county,
            "ES_S_": es,
            "D_I_C": sum(1 for c in brw.DI_CRITERIA if (props[c] or 0) >= 1),
            "DIType": di_type,
            "Ttl_P": pop,
        }
    )
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": rings},
    }


def bg(geoid: str = "080010000001", **kwargs: Any) -> brw.BlockGroup:  # noqa: ANN401
    """A BlockGroup over a square at -104.9, 39.7 unless rings are given."""
    rings = kwargs.pop("rings", [square(-104.9, 39.7)])
    return brw.blockgroup_from_feature(feature(geoid, rings, **kwargs))


def well(
    api: str = "001-00001", lat: str = "39.705", lon: str = "-104.895", **kw: str
) -> brw.Well:
    """A Well inside the default bg() square unless moved."""
    return brw.read_owp_zip(owp_zip([owp_row(api, lat, lon, **kw)]))[0]


# ---------------------------------------------------------------------------
# Reading the sources


def test_read_dbf_returns_stripped_text_and_skips_deleted_records() -> None:
    rows = [
        owp_row("001-00001", "39.7", "-104.9"),
        owp_row("001-00002", "39.8", "-104.8"),
    ]
    data = dbf_bytes(rows, deleted=[0])
    assert brw.read_dbf(data) == [rows[1]]


def test_read_dbf_decodes_windows_ansi() -> None:
    row = owp_row("001-00001", "39.7", "-104.9") | {"WellName": "PEÑA 1"}
    assert brw.read_dbf(dbf_bytes([row]))[0]["WellName"] == "PEÑA 1"


def test_read_owp_zip_keeps_unplugged_wells_only() -> None:
    rows = [
        owp_row("001-00001", "39.7", "-104.9"),
        owp_row("001-00002", "39.7", "-104.9", status="Plugged"),
        owp_row("", "39.7", "-104.9", status="Federal"),  # site records carry no API
    ]
    wells = brw.read_owp_zip(owp_zip(rows))
    assert [w.api_10 for w in wells] == ["05-001-00001"]
    assert wells[0].county_fips == "001"
    assert wells[0].lat_text == "39.7"


def test_read_owp_zip_rejects_a_repeated_api() -> None:
    rows = [owp_row("001-00001", "39.7", "-104.9")] * 2
    with pytest.raises(ValueError, match="repeats"):
        brw.read_owp_zip(owp_zip(rows))


def test_read_owp_zip_rejects_coordinates_outside_colorado() -> None:
    with pytest.raises(ValueError, match="outside Colorado"):
        brw.read_owp_zip(owp_zip([owp_row("001-00001", "39.7", "104.9")]))


def test_read_owp_zip_rejects_a_zip_with_no_dbf() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "nothing here")
    with pytest.raises(ValueError, match=r"\.dbf"):
        brw.read_owp_zip(buf.getvalue())


def test_di_status_comes_from_ditype_and_criteria_are_counted() -> None:
    # The August 2026 build treated D_I_C as a yes/no flag and scored this
    # block group, which meets two criteria, as non-DI.
    group = bg(
        di_type="More than one category",
        flags={"LIFlag": 1.0, "Justice40F": 1},
    )
    assert group.is_di
    assert group.criteria == 2


def test_not_di_when_ditype_is_na() -> None:
    assert not bg().is_di


def test_tribal_block_group_with_null_data_is_di_with_zero_scores() -> None:
    group = bg(
        di_type="Area under tribal jurisdiction",
        flags=dict.fromkeys(brw.DI_CRITERIA, None) | {"TJ": 1},
        es=None,
        pop=None,
    )
    assert group.is_di
    assert group.criteria == 1
    assert group.es_pctl == 0.0
    assert group.population == 0.0


def test_multipolygon_rings_are_all_kept() -> None:
    f = feature("080010000001", [])
    f["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [[square(-104.9, 39.7)], [square(-104.8, 39.7)]],
    }
    group = brw.blockgroup_from_feature(f)
    assert len(group.rings) == 2
    assert brw.contains(group, -104.795, 39.705)


# ---------------------------------------------------------------------------
# Geometry


def test_area_of_a_one_degree_cell_at_the_equator() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    expected = brw.AUTHALIC_RADIUS_M**2 * math.radians(1) * math.sin(math.radians(1))
    assert brw.polygon_area_m2([ring]) == pytest.approx(expected, rel=1e-9)
    assert expected / 1e6 == pytest.approx(12364, rel=1e-3)


def test_area_subtracts_a_hole() -> None:
    outer = [(x, y) for x, y in square(-104.9, 39.7, 0.02)]
    hole = [(x, y) for x, y in reversed(square(-104.895, 39.705, 0.01))]
    full = brw.polygon_area_m2([outer])
    assert brw.polygon_area_m2([outer, hole]) == pytest.approx(full * 0.75, rel=1e-3)


def test_contains_honors_holes() -> None:
    group = bg(rings=[square(-104.9, 39.7, 0.02), square(-104.895, 39.705, 0.01)])
    assert brw.contains(group, -104.898, 39.702)
    assert not brw.contains(group, -104.89, 39.71)  # inside the hole
    assert not brw.contains(group, -104.0, 39.7)


def test_distance_to_edge_in_meters() -> None:
    # A point 0.001 degrees of latitude inside the south edge is about 110 m away.
    group = bg()
    d = brw.distance_to_edge_m(group, -104.895, 39.701)
    assert d == pytest.approx(110.6, abs=0.5)


def test_haversine_one_degree_of_latitude() -> None:
    assert brw.haversine_km(39.0, -105.0, 40.0, -105.0) == pytest.approx(111.2, abs=0.1)


# ---------------------------------------------------------------------------
# Scoring


def test_community_score_for_a_di_well() -> None:
    # STROMBERGER UNIT 2-12: one criterion, EnviroScreen 56.2965.
    group = bg(
        di_type="People of color population above 40%",
        flags={"POCFlag": 1.0},
        es=56.2965,
    )
    assert brw.community_score(group, "") == pytest.approx(27.63, abs=0.01)


def test_criteria_points_are_capped() -> None:
    flags = dict.fromkeys(brw.DI_CRITERIA[:6], 1.0)
    group = bg(di_type="More than one category", flags=flags, es=0.0)
    assert brw.community_score(group, "") == 30.0


def test_community_score_for_non_di_wells() -> None:
    assert brw.community_score(bg(), "") == 0.0
    assert brw.community_score(bg(), brw.NEAR_DI_FLAG) == 8.0
    assert brw.community_score(None, "") == 0.0


def test_exposure_score_matches_the_published_formula() -> None:
    group = bg(pop=1100.0)
    group.area_km2 = 1100.0 / 42.47
    expected = 20 * math.log10(43.47) / 2 + 10 * 1100 / 3000
    assert brw.exposure_score(group) == pytest.approx(expected)


def test_exposure_score_is_capped_and_handles_zero_area() -> None:
    group = bg(pop=5000.0)
    group.area_km2 = 1.0
    assert brw.exposure_score(group) == 30.0
    group.area_km2 = 0.0
    assert brw.exposure_score(group) == 10.0
    assert brw.exposure_score(None) == 0.0


@pytest.mark.parametrize(
    ("surface", "minerals", "points"),
    [
        ("Fee", "Fee", 15.0),
        ("State", "Fee", 15.0),
        ("Fee", "State", 15.0),
        ("Fee", "Federal", 8.0),
        ("State", "Federal", 8.0),
        ("Federal", "Federal", 4.0),
        ("Federal", "Fee", 4.0),
        ("Tribal", "Tribal", 0.0),
        ("Indian", "Fee", 0.0),
        ("Fee", "Indian", 0.0),
    ],
)
def test_jurisdiction_score(surface: str, minerals: str, points: float) -> None:
    assert brw.jurisdiction_score(surface, minerals) == points


def test_deliverability_score() -> None:
    w = well()
    assert brw.deliverability_score(w, 1) == 15.0
    assert brw.deliverability_score(w, 2) == pytest.approx(17.66, abs=0.01)
    assert brw.deliverability_score(w, 50) == 30.0
    assert brw.deliverability_score(w, 200) == 30.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [(55.0, 1), (54.9, 2), (45.0, 2), (44.9, 3), (30.0, 3), (29.9, 4), (0.0, 4)],
)
def test_tier(score: float, expected: int) -> None:
    assert brw.tier(score) == expected


def test_cluster_sizes_count_same_project_wells_within_5_km() -> None:
    # 0.04 degrees of latitude is about 4.4 km; 0.05 is about 5.5 km.
    rows = [
        owp_row("001-00001", "39.70", "-104.9"),
        owp_row("001-00002", "39.74", "-104.9"),
        owp_row("001-00003", "39.75", "-104.9"),
        owp_row("001-00004", "39.70", "-104.9", project="Other Bond Claim"),
    ]
    sizes = brw.cluster_sizes(brw.read_owp_zip(owp_zip(rows)))
    assert sizes == {
        "05-001-00001": 2,
        "05-001-00002": 3,
        "05-001-00003": 2,
        "05-001-00004": 1,
    }


def test_boundary_flags_on_both_sides_of_a_di_edge() -> None:
    di = bg("080010000001", di_type="Low-income population above 40%")
    other = bg("080010000002", rings=[square(-104.89, 39.7)])
    groups = [di, other]
    near_edge_di = well(lon="-104.8915")  # about 130 m west of the shared edge
    near_edge_other = well(lon="-104.8885")
    deep_di = well(lon="-104.895")  # about 430 m from the edge
    assert brw.boundary_flag(near_edge_di, di, groups) == brw.DI_EDGE_FLAG
    assert brw.boundary_flag(near_edge_other, other, groups) == brw.NEAR_DI_FLAG
    assert brw.boundary_flag(deep_di, di, groups) == ""


def test_edges_between_two_di_block_groups_are_not_flagged() -> None:
    di_type = "Low-income population above 40%"
    a = bg("080010000001", di_type=di_type)
    b = bg("080010000002", di_type=di_type, rings=[square(-104.89, 39.7)])
    assert brw.boundary_flag(well(lon="-104.8915"), a, [a, b]) == ""


# ---------------------------------------------------------------------------
# Building the CSV


def write_inputs(
    tmp_path: Path, wells: Sequence[Mapping[str, str]], features: list[dict[str, Any]]
) -> tuple[Path, Path]:
    """Write an OWP zip and a block group GeoJSON for a build."""
    zip_path = tmp_path / "OWP_SHP.zip"
    zip_path.write_bytes(owp_zip(wells))
    bg_path = tmp_path / "bg.geojson"
    bg_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    return zip_path, bg_path


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV written by the build."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_main_builds_the_ranked_csv_and_manifest(tmp_path: Path) -> None:
    features = [
        feature(
            "080010000001",
            [square(-104.9, 39.7)],
            di_type="Within a Justice 40 census tract",
            flags={"Justice40F": 1},
            es=20.0,
        ),
        feature("080010000002", [square(-104.89, 39.7)]),
        feature("080050000001", [square(-104.88, 39.7)], county="Arapahoe"),
    ]
    wells = [
        owp_row("001-00002", "39.705", "-104.885"),
        owp_row("001-00001", "39.705", "-104.895"),
        owp_row("005-00003", "39.705", "-104.875", surface="Federal"),
        owp_row("005-00004", "39.705", "-104.875", status="Plugged"),
    ]
    zip_path, bg_path = write_inputs(tmp_path, wells, features)
    out = tmp_path / "ranked.csv"
    argv = [
        "--owp-zip",
        str(zip_path),
        "--blockgroups",
        str(bg_path),
        "--out",
        str(out),
    ]
    assert brw.main(argv) == 0

    rows = read_csv(out)
    assert list(rows[0]) == list(brw.COLUMNS)
    assert [r["API_10"] for r in rows] == [
        "05-001-00001",
        "05-001-00002",
        "05-005-00003",
    ]
    assert [r["Rank"] for r in rows] == ["1", "2", "3"]
    first = rows[0]
    assert first["DI_Community_Nov2024"] == "Yes"
    assert first["DI_Criteria_Count"] == "1"
    assert first["County"] == "Adams"
    assert first["Cluster_Size_5km"] == "3"  # all three share a project
    assert first["Score_Community"] == "24.0"  # 20 + 2 + 20 / 10
    assert rows[1]["DI_Type"] == ""
    assert rows[1]["DI_Criteria_Count"] == ""
    assert rows[2]["County"] == "Arapahoe"
    # Federal surface (4) plus a 3 well cluster (15 * ln 3 / ln 50).
    assert rows[2]["Score_Deliverability"] == "8.2"
    for r in rows:
        parts = (r["Score_Community"], r["Score_Exposure"], r["Score_Deliverability"])
        assert float(r["Priority_Score"]) == pytest.approx(
            sum(map(float, parts)), abs=0.11
        )

    manifest = json.loads(out.with_suffix(".sources.json").read_text(encoding="utf-8"))
    assert manifest["wells"] == 3
    assert manifest["sources"]["ecmc_owp_shapefile"]["unplugged_wells"] == 3
    assert manifest["sources"]["cdphe_enviroscreen_v2_blockgroups"]["block_groups"] == 3


def test_ties_are_ranked_by_api_number() -> None:
    group = bg()
    wells = brw.read_owp_zip(
        owp_zip(
            [
                owp_row("001-00009", "39.705", "-104.895", project="A"),
                owp_row("001-00001", "39.705", "-104.895", project="B"),
            ]
        )
    )
    rows = brw.rank_wells(wells, [group])
    assert [r["API_10"] for r in rows] == ["05-001-00001", "05-001-00009"]


def test_a_well_outside_every_block_group_is_kept_with_blank_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rows = brw.rank_wells([well(lon="-104.5")], [bg()])
    assert rows[0]["BG_GEOID"] == ""
    assert rows[0]["DI_Community_Nov2024"] == "No"
    assert "no block group" in caplog.text


# ---------------------------------------------------------------------------
# Downloading


class FakeResponse:
    """A canned response."""

    def __init__(self, status_code: int, content: bytes = b"") -> None:
        """Store the status and body."""
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Returns queued responses and records each request."""

    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        """Queue the responses to return, in order."""
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, *, params: Mapping[str, str] | None = None, timeout: float
    ) -> FakeResponse:
        """Pop the next queued response, raising it if it's an exception."""
        self.calls.append((url, dict(params or {})))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def no_sleep(_seconds: float) -> None:
    """Stand-in for time.sleep."""


def test_get_retries_transient_failures() -> None:
    session = FakeSession(
        [requests.ConnectionError("reset"), FakeResponse(503), FakeResponse(200, b"ok")]
    )
    assert brw._get(session, "https://x", sleep=no_sleep) == b"ok"
    assert len(session.calls) == 3


def test_get_gives_up_on_a_404_without_retrying() -> None:
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(requests.RequestException, match="HTTP 404"):
        brw._get(session, "https://x", sleep=no_sleep)
    assert len(session.calls) == 1


def test_get_pauses_after_every_request() -> None:
    pauses: list[float] = []
    session = FakeSession([FakeResponse(200, b"ok")])
    brw._get(session, "https://x", sleep=pauses.append)
    assert pauses == [DELAY_S]


def geojson_page(features: list[dict[str, Any]], more: bool) -> FakeResponse:
    """A CDPHE query page."""
    body: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if more:
        body["properties"] = {"exceededTransferLimit": True}
    return FakeResponse(200, json.dumps(body).encode())


def test_download_blockgroups_pages_until_the_service_says_done(tmp_path: Path) -> None:
    f1 = feature("080010000001", [square(-104.9, 39.7)])
    f2 = feature("080010000002", [square(-104.89, 39.7)])
    session = FakeSession(
        [geojson_page([f1], more=True), geojson_page([f2], more=False)]
    )
    dest = tmp_path / "bg.geojson"
    assert brw.download_blockgroups(session, dest, sleep=no_sleep) == 2
    assert [c[1]["resultOffset"] for c in session.calls] == ["0", "1"]
    assert session.calls[0][0] == f"{brw.CDPHE_LAYER_URL}/query"
    assert session.calls[0][1]["f"] == "geojson"
    assert [g.geoid for g in brw.read_blockgroups(dest)] == [
        "080010000001",
        "080010000002",
    ]


def test_download_blockgroups_raises_on_a_service_error(tmp_path: Path) -> None:
    error = FakeResponse(200, b'{"error": {"code": 499, "message": "Token Required"}}')
    with pytest.raises(ValueError, match="Token Required"):
        brw.download_blockgroups(
            FakeSession([error]), tmp_path / "bg.geojson", sleep=no_sleep
        )


def test_download_owp_rejects_a_page_that_is_not_a_zip(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(200, b"<html>moved</html>")])
    with pytest.raises(zipfile.BadZipFile):
        brw.download_owp(session, tmp_path / "OWP_SHP.zip", sleep=no_sleep)
    assert not (tmp_path / "OWP_SHP.zip").exists()
