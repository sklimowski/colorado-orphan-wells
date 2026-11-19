"""Tests for build_dashboard.py, on small inputs with no network."""

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest

import build_dashboard as bd
import build_ranked_wells as brw
from common import DELAY_S
from conftest import (
    WELL_SET_APIS,
    county_zip,
    shp_bytes,
    write_table,
    write_well_tables,
)

TOLERANCE = 0.0001


def square(x: float, y: float, size: float = 0.01) -> list[list[float]]:
    """A closed square ring with its lower left corner at (x, y)."""
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]


def feature(  # noqa: PLR0913
    geoid: str,
    ring: list[list[float]],
    *,
    di_type: str = "N/A",
    tribal: bool = False,
    es: float | None = 50.04,
    population: int | None = 1000,
) -> dict[str, Any]:
    """One block group as the CDPHE layer returns it."""
    return {
        "type": "Feature",
        "properties": {
            "GEOID": geoid,
            "Cnt_N": "Adams",
            "ES_S_": es,
            "TJ": 1 if tribal else None,
            "DIType": di_type,
            "Ttl_P": population,
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


# Three squares side by side, west to east.
WEST = feature("080010000001", square(-104.90, 39.70))
MIDDLE = feature("080010000002", square(-104.89, 39.70), di_type="Low income")
EAST = feature("081230000001", square(-104.88, 39.70), tribal=True, es=None)


def decode(flat: list[int]) -> list[tuple[int, int]]:
    """Undo the delta encoding, the way the page does."""
    points, lat, lon = [], 0, 0
    for i in range(0, len(flat), 2):
        lat, lon = lat + flat[i], lon + flat[i + 1]
        points.append((lat, lon))
    return points


def ring_points(refs: list[int], arcs: list[list[int]]) -> list[tuple[int, int]]:
    """Rebuild a ring from its arc references, the way the page does."""
    out: list[tuple[int, int]] = []
    for ref in refs:
        points = decode(arcs[ref]) if ref >= 0 else decode(arcs[~ref])[::-1]
        out += points[1:] if out else points
    return out


def test_simplify_line_drops_points_near_the_line_and_keeps_the_ends() -> None:
    line = [(0.0, 0.0), (0.5, 0.00001), (1.0, 0.0), (1.5, 0.5), (2.0, 0.0)]
    assert bd.simplify_line(line, TOLERANCE) == [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.5, 0.5),
        (2.0, 0.0),
    ]


def test_simplify_line_leaves_a_two_point_line_alone() -> None:
    assert bd.simplify_line([(0.0, 0.0), (1.0, 1.0)], TOLERANCE) == [
        (0.0, 0.0),
        (1.0, 1.0),
    ]


def test_simplify_arc_keeps_a_closed_loop_open() -> None:
    loop = [(x, y) for x, y in square(0.0, 0.0, 1.0)]
    simple = bd.simplify_arc(loop, TOLERANCE)
    assert simple[0] == simple[-1]
    assert len(set(simple)) >= bd.MIN_RING_POINTS


def test_neighbors_share_one_arc_walked_in_opposite_directions() -> None:
    topology = bd.build_topology([WEST, MIDDLE])
    (west_ring,) = topology.shapes[0][0]
    (middle_ring,) = topology.shapes[1][0]
    shared = {r if r >= 0 else ~r for r in west_ring} & {
        r if r >= 0 else ~r for r in middle_ring
    }
    assert len(shared) == 1
    (n,) = shared
    assert topology.arc_uses[n] == 2
    assert (n in west_ring) != (n in middle_ring)  # one walks it backward


def test_rings_survive_the_round_trip() -> None:
    features = [WEST, MIDDLE, EAST]
    topology = bd.build_topology(features)
    arcs = bd.encode_arcs(topology, TOLERANCE)
    for item, polygons in zip(features, topology.shapes, strict=True):
        ring = item["geometry"]["coordinates"][0]
        expected = {(round(y * 1e5), round(x * 1e5)) for x, y in ring}
        rebuilt = ring_points(polygons[0][0], arcs)
        assert rebuilt[0] == rebuilt[-1]
        assert set(rebuilt) == expected


def test_a_ring_smaller_than_the_tolerance_isnt_lost() -> None:
    tiny = feature("080010000009", square(-104.5, 39.5, 0.00004))
    topology = bd.build_topology([tiny])
    arcs = bd.encode_arcs(topology, tolerance=0.01)
    rebuilt = ring_points(topology.shapes[0][0][0], arcs)
    assert len(set(rebuilt)) >= bd.MIN_RING_POINTS


def test_blockgroup_rows_carry_di_type_tribal_flag_and_blanks() -> None:
    features = [WEST, MIDDLE, EAST]
    rows, di_types = bd.blockgroup_rows(features, bd.build_topology(features))
    assert di_types == ["", "Low income"]
    assert [row[:5] for row in rows] == [
        ["080010000001", 50.0, 1000, 0, 0],
        ["080010000002", 50.0, 1000, 1, 0],
        ["081230000001", None, 1000, 0, 1],  # CDPHE publishes no percentile here
    ]


@pytest.mark.parametrize(
    ("surface", "minerals", "expected"),
    [
        ("Fee", "Fee", False),
        ("State", "State", False),
        ("Fee", "State", False),
        ("Fee", "Federal", True),
        ("Federal", "Fee", True),  # the case the August map's flag left out
        ("Federal", "Federal", True),
        ("Tribal", "Fee", True),
        ("Fee", "Indian", True),
    ],
)
def test_federal_or_tribal_follows_the_jurisdiction_score(
    surface: str, minerals: str, expected: bool
) -> None:
    assert bd.is_federal_or_tribal(surface, minerals) is expected
    full = brw.jurisdiction_score(surface, minerals) == brw.JURISDICTION_POINTS
    assert full is not expected


def test_js_value_cant_close_the_script_element() -> None:
    text = bd.js_value({"comments": "see </script><b> é"})
    assert "</" not in text
    assert json.loads(text) == {"comments": "see </script><b> é"}
    assert text.isascii()


def test_render_fills_tokens_in_one_pass() -> None:
    template = "<a>{{TITLE}}</a><b>{{DATA_JS}}</b>"
    parts = {"TITLE": "{{DATA_JS}}", "DATA_JS": "x"}
    assert bd.render(template, parts) == "<a>{{DATA_JS}}</a><b>x</b>"


def test_render_stops_on_an_unknown_token() -> None:
    with pytest.raises(KeyError):
        bd.render("{{NOPE}}", {})


# ---------------------------------------------------------------------------
# County outlines

ADAMS = [(-104.9, 39.7), (-104.9, 39.8), (-104.8, 39.8), (-104.8, 39.7), (-104.9, 39.7)]
ADAMS_HOLE = [(-104.86, 39.74), (-104.84, 39.74), (-104.84, 39.76), (-104.86, 39.74)]
WELD = [(-104.9, 39.8), (-104.9, 40.2), (-104.4, 40.2), (-104.4, 39.8), (-104.9, 39.8)]
LARAMIE = [(-104.9, 41.0), (-104.9, 41.4), (-104.4, 41.4), (-104.9, 41.0)]
COUNTIES = [
    ("56", "Laramie", [LARAMIE]),  # Wyoming, left out
    ("08", "Adams", [ADAMS, ADAMS_HOLE]),
    ("08", "Weld", [WELD]),
]


def test_read_shp_rings_keeps_every_ring_in_record_order() -> None:
    shapes = bd.read_shp_rings(shp_bytes([[LARAMIE], None, [ADAMS, ADAMS_HOLE]]))
    assert shapes == [[LARAMIE], [], [ADAMS, ADAMS_HOLE]]


def test_read_shp_rings_rejects_a_shape_that_isnt_a_polygon() -> None:
    data = bytearray(shp_bytes([[ADAMS]]))
    data[108:112] = (1).to_bytes(4, "little")  # the first record's shape type
    with pytest.raises(bd.CountyFileError, match="isn't a polygon"):
        bd.read_shp_rings(bytes(data))


def test_county_rings_are_filtered_to_colorado() -> None:
    rings, counties = bd.read_county_rings(county_zip(COUNTIES))
    assert counties == 2
    assert rings == [ADAMS, ADAMS_HOLE, WELD]


def test_a_state_missing_from_the_county_file_is_an_error() -> None:
    with pytest.raises(bd.CountyFileError, match="STATEFP 08"):
        bd.read_county_rings(county_zip(COUNTIES[:1]))


def test_shapes_and_attribute_rows_must_line_up() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(county_zip(COUNTIES))) as src:
        dbf = src.read("cb_2024_us_county_500k.dbf")
    with zipfile.ZipFile(buf, "w") as dst:
        dst.writestr("c.dbf", dbf)
        dst.writestr("c.shp", shp_bytes([[ADAMS]]))
    with pytest.raises(bd.CountyFileError, match="1 shapes but 3 attribute rows"):
        bd.read_county_rings(buf.getvalue())


def test_a_zip_without_a_shapefile_is_an_error() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "nothing here")
    with pytest.raises(bd.CountyFileError, match=r"expected one \.shp"):
        bd.read_county_rings(buf.getvalue())


# ---------------------------------------------------------------------------
# Leaflet


class FakeResponse:
    """A response holding fixed bytes."""

    def __init__(self, content: bytes, status_code: int = 200) -> None:
        """Hold the body and status to return."""
        self.content = content
        self.status_code = status_code


class FakeSession:
    """A session that serves saved bodies by file name and logs each URL."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        """Hold the bodies to serve."""
        self.bodies = bodies
        self.urls: list[str] = []

    def get(
        self, url: str, *, params: object = None, timeout: float = 0
    ) -> FakeResponse:
        """Return the body saved for the URL's file name."""
        self.urls.append(url)
        return FakeResponse(self.bodies[url.rsplit("/", 1)[1]])


def test_the_county_zip_is_downloaded_once_with_a_pause(tmp_path: Path) -> None:
    body = county_zip(COUNTIES)
    session = FakeSession({bd.COUNTY_FILE: body})
    pauses: list[float] = []
    path = bd.ensure_counties(tmp_path, None, session=session, sleep=pauses.append)
    assert session.urls == [bd.COUNTY_URL]
    assert bd.COUNTY_URL.startswith("https://www2.census.gov/geo/tiger/GENZ2024/shp/")
    assert pauses == [DELAY_S]
    assert path == tmp_path / bd.COUNTY_FILE
    assert path.read_bytes() == body
    again = FakeSession({})
    assert bd.ensure_counties(tmp_path, None, session=again) == path
    assert again.urls == []


def test_a_county_download_that_isnt_a_zip_is_rejected(tmp_path: Path) -> None:
    session = FakeSession({bd.COUNTY_FILE: b"<html>Access denied</html>"})
    with pytest.raises(zipfile.BadZipFile):
        bd.ensure_counties(tmp_path, None, session=session, sleep=lambda _: None)
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def leaflet_bodies(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Stand-in Leaflet files, with the pinned hashes set to match them."""
    bodies = {"leaflet.js": b"/* js */", "leaflet.css": b"/* css */"}
    pinned = {name: bd._sri(body) for name, body in bodies.items()}
    monkeypatch.setattr(bd, "LEAFLET_FILES", pinned)
    return bodies


def test_leaflet_is_downloaded_once_with_a_pause_after_each_request(
    tmp_path: Path, leaflet_bodies: dict[str, bytes]
) -> None:
    session = FakeSession(leaflet_bodies)
    pauses: list[float] = []
    paths = bd.ensure_leaflet(tmp_path, None, session=session, sleep=pauses.append)
    assert session.urls == [
        f"{bd.LEAFLET_BASE}/leaflet.js",
        f"{bd.LEAFLET_BASE}/leaflet.css",
    ]
    assert pauses == [DELAY_S, DELAY_S]
    assert paths["leaflet.js"].read_bytes() == b"/* js */"
    again = FakeSession(leaflet_bodies)
    bd.ensure_leaflet(tmp_path, None, session=again, sleep=pauses.append)
    assert again.urls == []


def test_a_leaflet_download_that_doesnt_match_its_hash_is_rejected(
    tmp_path: Path, leaflet_bodies: dict[str, bytes]
) -> None:
    session = FakeSession({**leaflet_bodies, "leaflet.js": b"tampered"})
    with pytest.raises(bd.LeafletError, match="pinned hash"):
        bd.ensure_leaflet(tmp_path, None, session=session, sleep=lambda _: None)
    assert list(tmp_path.iterdir()) == []


def test_a_saved_leaflet_file_that_changed_is_rejected(
    tmp_path: Path, leaflet_bodies: dict[str, bytes]
) -> None:
    session = FakeSession(leaflet_bodies)
    paths = bd.ensure_leaflet(tmp_path, None, session=session, sleep=lambda _: None)
    paths["leaflet.css"].write_bytes(b"edited")
    with pytest.raises(bd.LeafletError, match="delete it"):
        bd.ensure_leaflet(tmp_path, None, session=session, sleep=lambda _: None)


def test_the_pinned_hashes_are_sha512_integrity_values() -> None:
    for value in bd.LEAFLET_FILES.values():
        assert re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", value)


# ---------------------------------------------------------------------------
# Program data


def small_program() -> dict[str, Any]:
    """One source, one tile, one chart, one finding, and one law."""
    return {
        "asOf": "2026-11-19",
        "facts": {},
        "findings": {
            "lead": "",
            "items": [
                {
                    "title": "Wells plugged </script> {{APP_JS}}",
                    "text": "",
                    "see": [["Wells plugged", "activity", "plugged"]],
                    "src": ["report"],
                }
            ],
        },
        "sourcesLead": "",
        "sources": {
            "report": {"t": "Annual report", "url": "https://example.org/report.pdf"}
        },
        "kpis": [{"k": "Wells plugged", "v": "2", "src": "report"}],
        "pages": {
            "activity": {
                "lead": "",
                "cards": [
                    {
                        "id": "plugged",
                        "kind": "bars",
                        "title": "Wells plugged",
                        "x": ["FY25", "FY26"],
                        "series": [{"name": "Wells", "values": [None, 2]}],
                        "src": ["report"],
                    },
                    {
                        "kind": "bullets",
                        "title": "Pending",
                        "items": [{"b": "Claims.", "t": "", "src": ["report"]}],
                    },
                ],
            }
        },
        "laws": {
            "lead": "",
            "items": [{"cite": "SB 1", "links": [["Bill", "https://example.org/sb1"]]}],
        },
        "gaps": [],
    }


def test_the_committed_program_data_is_consistent() -> None:
    program = json.loads(bd.PROGRAM_DATA.read_text(encoding="utf-8"))
    assert bd.program_problems(program) == []


def test_a_consistent_program_file_has_no_problems() -> None:
    assert bd.program_problems(small_program()) == []


def test_a_missing_section_is_reported_alone() -> None:
    program = small_program()
    del program["laws"]
    assert bd.program_problems(program) == ["the program data has no 'laws' entry"]


def test_every_cited_source_must_be_defined() -> None:
    program = small_program()
    program["sources"] = {}
    problems = bd.program_problems(program)
    assert len(problems) == 4  # the tile, the chart, the bullet, and the finding
    assert all("undefined source 'report'" in line for line in problems)


def test_a_source_needs_a_title_and_a_link() -> None:
    program = small_program()
    program["sources"]["report"] = {"t": "", "url": "example.org/report.pdf"}
    assert bd.program_problems(program) == [
        "source 'report' has no title",
        "source 'report' has no http or https link",
    ]


def test_a_series_must_match_its_categories() -> None:
    program = small_program()
    program["pages"]["activity"]["cards"][0]["x"].append("FY27")
    (problem,) = bd.program_problems(program)
    assert "series 'Wells' has 2 values for 3 categories" in problem


def test_a_finding_must_point_to_a_card_that_exists() -> None:
    program = small_program()
    del program["pages"]["activity"]["cards"][0]["id"]
    (problem,) = bd.program_problems(program)
    assert "activity/plugged" in problem


def test_a_law_link_must_be_a_web_address() -> None:
    program = small_program()
    program["laws"]["items"][0]["links"] = [["Bill", "sb1.pdf"]]
    (problem,) = bd.program_problems(program)
    assert "law 'SB 1'" in problem


def test_read_program_rejects_a_file_that_isnt_json(tmp_path: Path) -> None:
    path = tmp_path / "program_data.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(bd.ProgramDataError, match="isn't valid JSON"):
        bd.read_program(path)


def test_every_page_in_the_sidebar_has_a_section_and_a_route() -> None:
    frame = (bd.WEB_DIR / "dashboard.html").read_text(encoding="utf-8")
    js = (bd.WEB_DIR / "app.js").read_text(encoding="utf-8")
    linked = re.findall(r'data-page="([a-z]+)"', frame)
    sections = re.findall(r'<section id="page-([a-z]+)"', frame)
    routed = re.findall(r"^    \['([a-z]+)', '[^']+'\],?$", js, flags=re.MULTILINE)
    assert linked == sections == routed
    assert len(set(linked)) == len(linked)


def test_the_program_pages_label_a_missing_figure() -> None:
    js = (bd.WEB_DIR / "program.js").read_text(encoding="utf-8")
    assert "var NP = 'not published';" in js
    assert "if (v === null || v === undefined || v === '') { return NP; }" in js


# ---------------------------------------------------------------------------
# A whole build on small inputs


@pytest.fixture
def inputs(tmp_path: Path) -> bd.Inputs:
    """Three wells, three block groups, and stand-in Leaflet files."""
    well_list, op = write_well_tables(tmp_path)
    blockgroups = tmp_path / "blockgroups.geojson"
    collection = {"type": "FeatureCollection", "features": [WEST, MIDDLE, EAST]}
    blockgroups.write_text(json.dumps(collection), encoding="utf-8")
    manifest = {
        "sources": {
            "ecmc_owp_shapefile": {
                "url": "https://example.org/OWP_SHP.ZIP",
                "retrieved_at": "2026-11-18T16:00:35+00:00",
                "sha256": "a" * 64,
            },
            "cdphe_enviroscreen_v2_blockgroups": {
                "url": "https://example.org/layer",
                "retrieved_at": "2026-11-18T14:56:39+00:00",
                "sha256": brw.sha256(blockgroups),
            },
        }
    }
    well_list.with_suffix(".sources.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    counties = tmp_path / bd.COUNTY_FILE
    counties.write_bytes(county_zip(COUNTIES))
    js = tmp_path / "leaflet.js"
    css = tmp_path / "leaflet.css"
    js.write_text("var L={};", encoding="utf-8")
    css.write_text(".leaflet{}", encoding="utf-8")
    program = tmp_path / "program_data.json"
    program.write_text(json.dumps(small_program()), encoding="utf-8")
    return bd.Inputs(well_list, op, blockgroups, counties, js, css, program)


def embedded(html: str, name: str) -> Any:  # noqa: ANN401
    """Read one embedded variable back out of a built page."""
    match = re.search(rf"^var {name}=(.*);$", html, flags=re.MULTILINE)
    assert match, f"{name} isn't embedded"
    return json.loads(match[1])


def test_build_writes_both_pages_with_every_well(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    written = bd.build(inputs, tmp_path / "docs")
    assert sorted(path.name for path in written.values()) == [
        "dashboard.html",
        "dashboard.sources.json",
        "map.html",
    ]
    for key, mode in (("dashboard", "dashboard"), ("map", "map")):
        html = written[key].read_text(encoding="utf-8")
        assert embedded(html, "MODE") == mode
        columns = embedded(html, "WCOLS")
        apis = [row[columns.index("API_10")] for row in embedded(html, "W")]
        assert apis == list(WELL_SET_APIS)
        assert embedded(html, "META")["wells"] == len(WELL_SET_APIS)
        assert len(embedded(html, "BG")) == 3
        assert len(embedded(html, "COUNTY")) == 3
        assert not bd.TOKEN_RE.search(html.split("<script>")[0])
        assert "var L={};" in html
        assert "BSD 2-Clause License" in html


def test_the_map_page_leaves_out_the_detail_tables(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    written = bd.build(inputs, tmp_path / "docs")
    dashboard = written["dashboard"].read_text(encoding="utf-8")
    standalone = written["map"].read_text(encoding="utf-8")
    assert embedded(dashboard, "CAS") == {
        WELL_SET_APIS[0]: [[*["1", ""], "ACTUAL", "SURF", *[""] * 10]]
    }
    assert list(embedded(dashboard, "TESTS")) == [WELL_SET_APIS[0]]
    for name in ("CAS", "CEM", "TESTS"):
        assert f"\nvar {name}=" not in standalone
    assert embedded(standalone, "WCOLS") == list(bd.MAP_COLUMNS)
    assert len(standalone) < len(dashboard)


def test_table_text_cant_break_out_of_the_page(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    # The fixture's test comment holds "</script>" and a template token.
    written = bd.build(inputs, tmp_path / "docs")
    html = written["dashboard"].read_text(encoding="utf-8")
    tests = embedded(html, "TESTS")[WELL_SET_APIS[0]]
    assert tests[0][-1] == "valve </script> {{APP_JS}}"
    assert html.count("</script>") == html.count("<script>")


def test_only_the_dashboard_carries_the_program_data(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    written = bd.build(inputs, tmp_path / "docs")
    dashboard = written["dashboard"].read_text(encoding="utf-8")
    standalone = written["map"].read_text(encoding="utf-8")
    match = re.search(r"^var PROGRAM = (.*);$", dashboard, flags=re.MULTILINE)
    assert match
    program = json.loads(match[1])
    assert program == small_program()
    assert program["pages"]["activity"]["cards"][0]["series"][0]["values"][0] is None
    assert "var PROGRAM" not in standalone
    assert "owpProgram = {" not in standalone
    assert dashboard.count("</script>") == dashboard.count("<script>")


def test_build_stops_before_writing_when_the_program_data_is_inconsistent(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    program = small_program()
    program["kpis"][0]["src"] = "memo"
    inputs.program.write_text(json.dumps(program), encoding="utf-8")
    with pytest.raises(bd.ProgramDataError, match="undefined source 'memo'"):
        bd.build(inputs, tmp_path / "docs")
    assert not (tmp_path / "docs").exists()


def test_blanks_stay_blank_in_the_embedded_data(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    written = bd.build(inputs, tmp_path / "docs")
    html = written["dashboard"].read_text(encoding="utf-8")
    columns = embedded(html, "WCOLS")
    first = dict(zip(columns, embedded(html, "W")[0], strict=True))
    assert first["measured_td_ft"] == ""
    assert first["pb_depth_ft"] == ""
    assert first["bh_max_surf_casing_psi"] == ""
    assert first["bh_test_count"] == "0"  # a recorded zero stays a zero


def test_build_is_deterministic(tmp_path: Path, inputs: bd.Inputs) -> None:
    first = bd.build(inputs, tmp_path / "a")
    second = bd.build(inputs, tmp_path / "b")
    for key in ("dashboard", "map"):
        assert first[key].read_bytes() == second[key].read_bytes()
        assert b"\r" not in first[key].read_bytes()


def test_build_stops_before_writing_when_the_tables_disagree(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    scout = inputs.op_dir / bd.SCOUT_TABLE
    rows = bd.read_table(scout)
    write_table(scout, rows[:-1])
    with pytest.raises(bd.WellSetError, match=WELL_SET_APIS[-1]):
        bd.build(inputs, tmp_path / "docs")
    assert not (tmp_path / "docs").exists()


def test_federal_flag_and_counts_reach_the_page(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    rows = bd.read_table(inputs.well_list)
    rows[1].update(Surface="Federal", Minerals="Fee")
    write_table(inputs.well_list, rows)
    html = bd.build(inputs, tmp_path / "docs")["map"].read_text(encoding="utf-8")
    columns = embedded(html, "WCOLS")
    flags = [row[columns.index(bd.FED_COLUMN)] for row in embedded(html, "W")]
    assert flags == ["", "1", ""]
    meta = embedded(html, "META")
    assert meta["bgCount"] == 3
    assert meta["bgDiCount"] == 1
    assert meta["countyCount"] == 2
    assert meta["countySource"] == (
        "U.S. Census Bureau 2024 cartographic boundary file, 1:500,000"
    )
    assert meta["listRetrieved"] == "2026-11-18T16:00:35+00:00"
    assert ["Measured TD", 3] in meta["blanks"]


def test_a_changed_block_group_file_is_flagged(
    tmp_path: Path, inputs: bd.Inputs, caplog: pytest.LogCaptureFixture
) -> None:
    collection = {"type": "FeatureCollection", "features": [WEST, MIDDLE]}
    inputs.blockgroups.write_text(json.dumps(collection), encoding="utf-8")
    bd.build(inputs, tmp_path / "docs")
    assert "isn't the file the ranked list was scored with" in caplog.text


def test_the_page_code_never_shows_a_blank_as_zero() -> None:
    # The page's one way to show a value is show(), which labels a blank.
    js = (bd.WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert (
        "if (v === '' || v === null || v === undefined) { return blank(label); }" in js
    )
    assert "|| 0)" not in js.split("// Well sheet")[1].split("// County and project")[0]
    assert "L.DomUtil.disableClickPropagation" not in js
    assert "openstreetmap" not in js.lower()


def test_county_rings_reach_the_page_in_page_units(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    html = bd.build(inputs, tmp_path / "docs")["map"].read_text(encoding="utf-8")
    rings = [decode(flat) for flat in embedded(html, "COUNTY")]
    assert rings[0] == [(round(y * 1e5), round(x * 1e5)) for x, y in ADAMS]
    assert rings[0][0] == (3970000, -10490000)  # (lat, lon) in 0.00001 degree


def test_the_manifest_records_the_county_file(
    tmp_path: Path, inputs: bd.Inputs
) -> None:
    written = bd.build(inputs, tmp_path / "docs")
    manifest = json.loads(written["manifest"].read_text(encoding="utf-8"))
    record = manifest["county_boundaries"]
    assert record["url"] == bd.COUNTY_URL
    assert record["file"] == bd.COUNTY_FILE
    assert record["counties"] == 2
    assert record["retrieved_at"] == brw.file_time(inputs.counties)
    members = bd.county_members(inputs.counties.read_bytes())
    assert sorted(record["sha256"]) == [".dbf", ".shp"]
    assert all(len(value) == 64 for value in record["sha256"].values())
    assert sorted(members) == [".dbf", ".shp"]
