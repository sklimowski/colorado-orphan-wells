#!/usr/bin/env python3
"""Build docs/dashboard.html and docs/map.html from the committed tables.

Both pages are single self-contained HTML files.  The well data, the block
group boundaries, and Leaflet are embedded, so the pages open from a local
file or GitHub Pages with no server.  Only the basemap tiles load at view
time.

The script reads the ranked well list in ip/, the six CSVs in op/, and the
CDPHE block group GeoJSON that build_ranked_wells.py saves in ip/downloads/.
The dashboard's program pages (funding, plugging activity, legislation,
state comparison, and sources) come from ip/program_data.json, a compiled
file of published figures that's edited by hand.  The map doesn't carry it.
It downloads Leaflet 1.9.4 from cdnjs once, checks it against a pinned
SHA-512, and keeps it in ip/downloads/.

Before writing anything it checks that every table describes the same wells
(see well_set_problems) and that the program data is consistent with itself
(see program_problems), and stops with the differences if they aren't.

Block group boundaries are simplified for display only.  Shared edges are
simplified once and reused by both neighbors, so the simplified polygons
still meet without gaps.  Scoring in build_ranked_wells.py always uses the
full-resolution boundaries.

County outlines come from the Census Bureau's 2024 cartographic boundary
file for counties at 1:500,000, downloaded once to ip/downloads/ and
filtered to Colorado.

The output is deterministic: the same inputs give the same bytes, with no
build time in either page.  Ages of the data are computed in the browser.

Usage:
    python build_dashboard.py [--contact ADDR] [--out-dir docs]
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import logging
import math
import re
import struct
import sys
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import build_ranked_wells as brw
from common import (
    DEFAULT_OUT_DIR,
    DEFAULT_WELL_LIST,
    REPO_ROOT,
    configure_logging,
    make_session,
    resolve_contact,
    write_text_atomic,
)

log = logging.getLogger(__name__)

DOCS_DIR = REPO_ROOT / "docs"
WEB_DIR = REPO_ROOT / "web"
DASHBOARD_FILE = "dashboard.html"
MAP_FILE = "map.html"
MANIFEST_FILE = "dashboard.sources.json"
PROGRAM_DATA = REPO_ROOT / "ip" / "program_data.json"

# Where the README lives once the repo is public; the About page links to it.
REPO_URL = "https://github.com/sklimowski/colorado-orphan-wells"

# Leaflet, inlined so the pages work offline apart from the basemap.  The
# hashes are the SHA-512, in Subresource Integrity form, of leaflet.js and
# leaflet.css from Leaflet's 1.9.4 release, computed from the npm package on
# 2026-11-18.  A download that differs by one byte is rejected.
LEAFLET_VERSION = "1.9.4"
LEAFLET_BASE = f"https://cdnjs.cloudflare.com/ajax/libs/leaflet/{LEAFLET_VERSION}"
LEAFLET_FILES = {
    "leaflet.js": (
        "sha512-BwHfrr4c9kmRkLw6iXFdzcdWV/PGkVgiIyIWLLlTSXzWQzxuSg4DiQUCpauz/"
        "EWjgk5TYQqX/kvn9pG1NpYfqg=="
    ),
    "leaflet.css": (
        "sha512-Zcn6bjR/8RZbLEpLIeOwNtzREBAJnUKESxces60Mpoj+2okopSAcSUIUOseddDm0"
        "cxnGQzxIR7vJgsLZbdLE3w=="
    ),
}

# County outlines: the Census Bureau's cartographic boundary file, which
# covers every county in the country.  Only Colorado's are embedded.
COUNTY_VINTAGE = "2024"
COUNTY_FILE = f"cb_{COUNTY_VINTAGE}_us_county_500k.zip"
COUNTY_URL = f"https://www2.census.gov/geo/tiger/GENZ{COUNTY_VINTAGE}/shp/{COUNTY_FILE}"
COUNTY_SOURCE = (
    f"U.S. Census Bureau {COUNTY_VINTAGE} cartographic boundary file, 1:500,000"
)
COLORADO_FIPS = "08"
SHP_HEADER = 100  # bytes before the first record in a .shp file
SHP_RECORD_HEADER = 8  # record number and content length, big-endian
SHP_NULL = 0
SHP_POLYGON = 5
SHP_POLYGON_FIXED = 44  # shape type, bounding box, part count, point count

ECMC_TABLE = "ecmc_unplugged_orphan_wells.csv"
SCOUT_TABLE = "cogis_scout_data.csv"
BH_SUMMARY_TABLE = "bradenhead_summary.csv"
CASING_TABLE = "cogis_casing.csv"
CEMENT_TABLE = "cogis_additional_cement.csv"
BH_TESTS_TABLE = "bradenhead_tests.csv"
PER_WELL_TABLES = (ECMC_TABLE, SCOUT_TABLE, BH_SUMMARY_TABLE)
DETAIL_TABLES = (CASING_TABLE, CEMENT_TABLE, BH_TESTS_TABLE)
SHOW_APIS = 10  # API numbers listed per problem before the message is cut short

# Display simplification.  Tolerance is in degrees of latitude, about 5.5 m.
# Coordinates are embedded as integers in units of 1e-5 degree, about 1 m.
SIMPLIFY_TOLERANCE_DEG = 0.00005
COORD_SCALE = 100000
LON_SCALE = math.cos(math.radians(39.0))  # Colorado's middle latitude
MIN_RING_POINTS = 3  # a ring needs three distinct points to enclose anything

STALE_DAYS = 30  # main.py's refresh default; the pages mark older sources

# Columns embedded for each well.  The map page takes MAP_COLUMNS, and the
# dashboard takes all of them.  Values stay text, as the tables hold them.
RANKED_COLUMNS = (
    "Rank",
    "Tier",
    "Priority_Score",
    "API_10",
    "WellName",
    "Project",
    "County",
    "Lat",
    "Lon",
    "Surface",
    "Minerals",
    "DI_Community_Nov2024",
    "DI_Type",
    "DI_Criteria_Count",
    "EnviroScreen2_Pctl",
    "BG_GEOID",
    "BG_Pop",
    "BG_PopDensity_km2",
    "Cluster_Size_5km",
    "Score_Community",
    "Score_Exposure",
    "Score_Deliverability",
    "Boundary_Flag",
)
ECMC_COLUMNS = ("SiteID", "TypeID", "TankBattery", "Loc_Source")
SCOUT_COLUMNS = (
    "fetched",
    "fetched_at",
    "well_status",
    "status_date",
    "spud_date",
    "completion_date",
    "measured_td_ft",
    "vertical_td_ft",
    "pb_depth_ft",
    "elevation_ft",
    "n_casing_strings",
    "n_planned_casing_strings",
    "surf_casing_size_in",
    "surf_casing_depth_ft",
    "n_additional_cement",
)
BH_COLUMNS = (
    "bh_fetched_at",
    "bh_test_count",
    "bh_first_test_date",
    "bh_last_test_date",
    "bh_last_flow_start",
    "bh_last_flow_end",
    "bh_last_end_surf_casing_psi",
    "bh_last_fluid",
    "bh_max_surf_casing_psi",
    "bh_any_flow_observed",
    "bh_liquid_flow",
    "bh_flow_at_end",
    "bh_not_bled_to_zero",
    "bh_pressure_rebuild",
    "bh_flow_class",
    "bh_flow_class_latest",
)
FED_COLUMN = "fed"  # derived: 1 when the well scores under full jurisdiction points
WELL_COLUMNS = (
    *RANKED_COLUMNS,
    FED_COLUMN,
    *ECMC_COLUMNS,
    *SCOUT_COLUMNS,
    *BH_COLUMNS,
)
MAP_COLUMNS = (
    "Rank",
    "Tier",
    "Priority_Score",
    "API_10",
    "WellName",
    "Project",
    "County",
    "Lat",
    "Lon",
    "Surface",
    "Minerals",
    "DI_Community_Nov2024",
    "Boundary_Flag",
    FED_COLUMN,
    "spud_date",
    "completion_date",
    "bh_last_test_date",
    "bh_flow_class",
    "bh_flow_class_latest",
)
CASING_COLUMNS = (
    "seq",
    "section",
    "citings_type",
    "string_type",
    "is_casing_string",
    "hole_size_in",
    "casing_size_in",
    "top_ft",
    "depth_ft",
    "weight",
    "cement_sacks",
    "cement_top_ft",
    "cement_bottom_ft",
    "cement_method",
)
CEMENT_COLUMNS = (
    "seq",
    "string_type",
    "top_ft",
    "depth_ft",
    "bottom_ft",
    "sacks",
    "method",
)
TEST_COLUMNS = (
    "doc_number",
    "report_type",
    "test_date",
    "submit_date",
    "well_status",
    "initial_surf_casing_psi",
    "bh_flow_start",
    "fluid_type",
    "end_surf_casing_psi",
    "bh_flow_end",
    "initial_prod_casing_psi",
    "end_prod_casing_psi",
    "sample_taken",
    "comments",
)

# Scout card fields whose blank counts the About page reports.
BLANK_RATE_FIELDS = (
    ("spud_date", "Spud date"),
    ("completion_date", "Completion date"),
    ("measured_td_ft", "Measured TD"),
    ("vertical_td_ft", "Vertical TD"),
    ("pb_depth_ft", "Plugback depth"),
    ("elevation_ft", "Elevation"),
    ("surf_casing_size_in", "Surface casing size"),
    ("surf_casing_depth_ft", "Surface casing depth"),
)

Point = tuple[float, float]  # (lon, lat), as the GeoJSON holds them
Row = dict[str, str]

TOKEN_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


class WellSetError(ValueError):
    """The committed tables don't describe the same set of wells."""


class ProgramDataError(ValueError):
    """The program data cites something it doesn't define, or is malformed."""


class LeafletError(ValueError):
    """A Leaflet download doesn't match its pinned hash."""


class CountyFileError(ValueError):
    """The Census county file isn't the shapefile the build expects."""


# ---------------------------------------------------------------------------
# One set of wells


def read_table(path: Path) -> list[Row]:
    """Read a committed CSV as a list of dicts, in file order."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def table_apis(path: Path) -> list[str]:
    """Return a table's well API numbers as API_10, in file order.

    ECMC's table writes the API without the 05 state prefix (125-02377), in
    a column named APInumber.  Every other table has an API_10 column.
    """
    rows = read_table(path)
    if path.name == ECMC_TABLE:
        return [f"05-{row['APInumber']}" for row in rows]
    return [row["API_10"] for row in rows]


def _sample(apis: Iterable[str]) -> str:
    """Format API numbers for a message, cut short after SHOW_APIS."""
    listed = sorted(apis)
    more = f" and {len(listed) - SHOW_APIS} more" if len(listed) > SHOW_APIS else ""
    return ", ".join(listed[:SHOW_APIS]) + more


def unmappable_wells(ranked: Sequence[Mapping[str, str]]) -> set[str]:
    """Return the API numbers whose coordinates are blank or outside Colorado."""
    bad = set()
    for row in ranked:
        try:
            lat, lon = float(row["Lat"]), float(row["Lon"])
        except ValueError:
            bad.add(row["API_10"])
            continue
        in_lat = brw.CO_LAT[0] <= lat <= brw.CO_LAT[1]
        in_lon = brw.CO_LON[0] <= lon <= brw.CO_LON[1]
        if not (in_lat and in_lon):
            bad.add(row["API_10"])
    return bad


def well_set_problems(well_list: Path, op_dir: Path) -> list[str]:
    """Check that every table describes the wells on the ranked list.

    The ranked list defines the well set.  The tables with one row per well
    must hold exactly those API numbers once each, the tables with many rows
    per well may hold only wells from the set, and every well needs
    coordinates inside Colorado so it lands on the map.

    Args:
        well_list: The ranked well list CSV.
        op_dir: The folder holding the six output tables.

    Returns:
        One message per problem, naming the table and the API numbers.  An
        empty list means the tables agree.
    """
    problems = []
    ranked_rows = read_table(well_list)
    ranked = [row["API_10"] for row in ranked_rows]
    expected = set(ranked)
    repeated = {api for api, n in Counter(ranked).items() if n > 1}
    if repeated:
        problems.append(f"repeated in {well_list.name}: {_sample(repeated)}")
    for name in PER_WELL_TABLES:
        apis = table_apis(op_dir / name)
        repeated = {api for api, n in Counter(apis).items() if n > 1}
        if repeated:
            problems.append(f"repeated in {name}: {_sample(repeated)}")
        missing = expected - set(apis)
        if missing:
            problems.append(f"in the ranked list but not {name}: {_sample(missing)}")
        extra = set(apis) - expected
        if extra:
            problems.append(f"in {name} but not the ranked list: {_sample(extra)}")
    for name in DETAIL_TABLES:
        extra = set(table_apis(op_dir / name)) - expected
        if extra:
            problems.append(f"in {name} but not the ranked list: {_sample(extra)}")
    bad = unmappable_wells(ranked_rows)
    if bad:
        problems.append(f"blank or outside Colorado: {_sample(bad)}")
    return problems


def check_well_set(well_list: Path, op_dir: Path) -> None:
    """Raise WellSetError, listing every problem, unless the tables agree."""
    problems = well_set_problems(well_list, op_dir)
    if problems:
        raise WellSetError(
            "the tables don't describe the same wells; rerun the scrapers "
            "(python main.py) before building the pages:\n  " + "\n  ".join(problems)
        )


# ---------------------------------------------------------------------------
# Block group boundaries for display


def simplify_line(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Simplify an open line with the Douglas-Peucker method.

    The first and last points are always kept.  Distances are measured in
    degrees of latitude, with longitude scaled to match at Colorado's
    latitude.

    Args:
        points: The line's vertices as (lon, lat).
        tolerance: Points closer than this to the simplified line are dropped.

    Returns:
        The vertices kept, in order.
    """
    if len(points) <= 2:  # noqa: PLR2004
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first][0] * LON_SCALE, points[first][1]
        bx, by = points[last][0] * LON_SCALE, points[last][1]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        worst, worst_at = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i][0] * LON_SCALE - ax, points[i][1] - ay
            if length == 0:
                distance = math.hypot(px, py)
            else:
                distance = abs(px * dy - py * dx) / length
            if distance > worst:
                worst, worst_at = distance, i
        if worst > tolerance:
            keep[worst_at] = True
            stack.append((first, worst_at))
            stack.append((worst_at, last))
    return [p for p, kept in zip(points, keep, strict=True) if kept]


def simplify_arc(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Simplify an arc, which may be a closed loop.

    A closed loop is split at the point farthest from its start so it can't
    collapse to a single point.
    """
    if points[0] != points[-1]:
        return simplify_line(points, tolerance)
    x0, y0 = points[0]
    far = max(
        range(len(points)),
        key=lambda i: math.hypot((points[i][0] - x0) * LON_SCALE, points[i][1] - y0),
    )
    head = simplify_line(points[: far + 1], tolerance)
    tail = simplify_line(points[far:], tolerance)
    return head + tail[1:]


def _as_ints(points: Iterable[Point]) -> list[tuple[int, int]]:
    """Round (lon, lat) points to (lat, lon) integers, dropping repeats."""
    out: list[tuple[int, int]] = []
    for lon, lat in points:
        p = (round(lat * COORD_SCALE), round(lon * COORD_SCALE))
        if not out or out[-1] != p:
            out.append(p)
    return out


def _delta_encode(points: Sequence[tuple[int, int]]) -> list[int]:
    """Flatten integer points to [lat, lon, dlat, dlon, ...]."""
    flat = [points[0][0], points[0][1]]
    for (lat0, lon0), (lat1, lon1) in zip(points, points[1:], strict=False):
        flat += [lat1 - lat0, lon1 - lon0]
    return flat


@dataclass
class Topology:
    """Block group boundaries as shared arcs.

    Each boundary segment between two junctions is stored once.  A ring is a
    list of arc references: n for arc n walked forward, ~n (a negative
    number) for arc n walked backward.
    """

    arcs: list[list[Point]] = field(default_factory=list)
    arc_uses: list[int] = field(default_factory=list)
    # One entry per block group: its polygons, each a list of rings.
    shapes: list[list[list[list[int]]]] = field(default_factory=list)
    _index: dict[tuple[Point, Point, Point, Point, int], int] = field(
        default_factory=dict
    )

    def add_arc(self, points: list[Point]) -> int:
        """Store an arc, or find it if a neighbor already stored it.

        Returns:
            The arc reference for the direction the caller walked it.
        """
        if points[0] == points[-1]:
            backward = points[1] > points[-2]
        else:
            backward = points[0] > points[-1]
        if backward:
            points = points[::-1]
        key = (points[0], points[1], points[-2], points[-1], len(points))
        n = self._index.get(key)
        if n is None:
            n = len(self.arcs)
            self._index[key] = n
            self.arcs.append(points)
            self.arc_uses.append(0)
        self.arc_uses[n] += 1
        return ~n if backward else n


def _feature_polygons(feature: Mapping[str, Any]) -> list[list[list[Point]]]:
    """Return a GeoJSON feature's polygons as rings of (lon, lat) points."""
    geometry = feature["geometry"]
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    return [
        [[(float(x), float(y)) for x, y, *_ in ring] for ring in polygon]
        for polygon in polygons
    ]


def _ring_arcs(ring: Sequence[Point], junctions: set[Point]) -> list[list[Point]]:
    """Split a closed ring into arcs that start and end at junctions.

    A ring that touches no junction comes back as one closed arc, rotated to
    start at its smallest point so both rings that share it agree.
    """
    points = list(ring[:-1]) if ring[0] == ring[-1] else list(ring)
    at = [i for i, p in enumerate(points) if p in junctions]
    if not at:
        start = min(range(len(points)), key=lambda i: points[i])
        loop = points[start:] + points[:start]
        return [[*loop, loop[0]]]
    loop = points[at[0] :] + points[: at[0]]
    loop.append(loop[0])
    cuts = [i for i, p in enumerate(loop) if p in junctions]
    return [loop[a : b + 1] for a, b in zip(cuts, cuts[1:], strict=False)]


def build_topology(features: Sequence[Mapping[str, Any]]) -> Topology:
    """Split every block group ring into arcs shared with its neighbors.

    A junction is a vertex where three or more boundary edges meet.  Between
    two junctions a boundary has the same block group on each side for its
    whole length, so it can be stored and simplified once.
    """
    shapes = [_feature_polygons(feature) for feature in features]
    edges: set[tuple[Point, Point]] = set()
    for polygons in shapes:
        for polygon in polygons:
            for ring in polygon:
                for a, b in zip(ring, ring[1:], strict=False):
                    if a != b:
                        edges.add((a, b) if a < b else (b, a))
    degree: Counter[Point] = Counter()
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    junctions = {p for p, n in degree.items() if n != 2}  # noqa: PLR2004
    topology = Topology()
    for polygons in shapes:
        topology.shapes.append(
            [
                [
                    [topology.add_arc(arc) for arc in _ring_arcs(ring, junctions)]
                    for ring in polygon
                ]
                for polygon in polygons
            ]
        )
    return topology


def _ring_points(
    refs: Sequence[int], arcs: Sequence[Sequence[tuple[int, int]]]
) -> list[tuple[int, int]]:
    """Join a ring's arcs into one list of integer points, without repeats."""
    out: list[tuple[int, int]] = []
    for ref in refs:
        arc = arcs[ref] if ref >= 0 else arcs[~ref][::-1]
        for p in arc:
            if not out or out[-1] != p:
                out.append(p)
    return out


def encode_arcs(topology: Topology, tolerance: float) -> list[list[int]]:
    """Simplify, round, and delta-encode every arc.

    A ring that simplification would leave with fewer than three distinct
    points keeps its arcs at full detail, so no block group disappears.
    """
    simple = [_as_ints(simplify_arc(arc, tolerance)) for arc in topology.arcs]
    for polygons in topology.shapes:
        for polygon in polygons:
            for refs in polygon:
                if len(set(_ring_points(refs, simple))) < MIN_RING_POINTS:
                    for ref in refs:
                        n = ref if ref >= 0 else ~ref
                        simple[n] = _as_ints(topology.arcs[n])
    return [_delta_encode(arc) for arc in simple]


def blockgroup_rows(
    features: Sequence[Mapping[str, Any]], topology: Topology
) -> tuple[list[list[object]], list[str]]:
    """Build the embedded block group records.

    Returns:
        The records, one per block group, as [GEOID, EnviroScreen percentile
        or None, population or None, DI type index, tribal flag, polygons],
        and the DI type names the index points into.  Index 0 is "not DI".
    """
    di_types = [""]
    rows: list[list[object]] = []
    for feature, polygons in zip(features, topology.shapes, strict=True):
        props = feature["properties"]
        di_type = str(props["DIType"] or "")
        if di_type == brw.NOT_DI:
            di_type = ""
        if di_type not in di_types:
            di_types.append(di_type)
        es = props["ES_S_"]
        population = props["Ttl_P"]
        rows.append(
            [
                str(props["GEOID"]),
                None if es is None else round(float(es), 1),
                None if population is None else int(population),
                di_types.index(di_type),
                1 if props["TJ"] else 0,
                polygons,
            ]
        )
    return rows, di_types


# ---------------------------------------------------------------------------
# County outlines


def read_shp_rings(data: bytes) -> list[list[list[Point]]]:
    """Read the rings of every record in a polygon .shp file.

    Args:
        data: The whole .shp file.

    Returns:
        One list of rings per record, in file order, so the list lines up
        with the rows of the .dbf.  Each ring is a list of (lon, lat) points.
        A null shape gives an empty list.

    Raises:
        CountyFileError: If a record holds anything but a polygon.
    """
    records: list[list[list[Point]]] = []
    pos = SHP_HEADER
    while pos < len(data):
        (words,) = struct.unpack(">i", data[pos + 4 : pos + SHP_RECORD_HEADER])
        start = pos + SHP_RECORD_HEADER
        pos = start + 2 * words  # the length counts 16-bit words
        (shape_type,) = struct.unpack("<i", data[start : start + 4])
        if shape_type == SHP_NULL:
            records.append([])
            continue
        if shape_type != SHP_POLYGON:
            raise CountyFileError(f"shape type {shape_type} isn't a polygon")
        n_parts, n_points = struct.unpack(
            "<ii", data[start + 36 : start + SHP_POLYGON_FIXED]
        )
        parts_at = start + SHP_POLYGON_FIXED
        points_at = parts_at + 4 * n_parts
        parts = struct.unpack(f"<{n_parts}i", data[parts_at:points_at])
        flat = struct.unpack(
            f"<{2 * n_points}d", data[points_at : points_at + 16 * n_points]
        )
        points = list(zip(flat[0::2], flat[1::2], strict=True))
        ends = [*parts[1:], n_points]
        records.append([points[a:b] for a, b in zip(parts, ends, strict=True)])
    return records


def _zip_member(archive: zipfile.ZipFile, suffix: str) -> bytes:
    """Read the one member of a zip whose name ends with suffix."""
    names = [name for name in archive.namelist() if name.lower().endswith(suffix)]
    if len(names) != 1:
        raise CountyFileError(f"expected one {suffix} file in the zip, found {names}")
    return archive.read(names[0])


def county_members(zip_bytes: bytes) -> dict[str, bytes]:
    """Return the .shp and .dbf from the Census county zip, keyed by suffix."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        return {suffix: _zip_member(archive, suffix) for suffix in (".shp", ".dbf")}


def read_county_rings(
    zip_bytes: bytes, state_fips: str = COLORADO_FIPS
) -> tuple[list[list[Point]], int]:
    """Read one state's county boundary rings from the Census county zip.

    Args:
        zip_bytes: The whole zip.
        state_fips: The state's two-digit FIPS code, matched to STATEFP.

    Returns:
        Every ring of every county in the state, and the number of counties.

    Raises:
        CountyFileError: If the zip's shapes and attribute rows don't line
            up, or the state has no counties in it.
    """
    members = county_members(zip_bytes)
    rows = brw.read_dbf(members[".dbf"], encoding="utf-8")
    shapes = read_shp_rings(members[".shp"])
    if len(rows) != len(shapes):
        raise CountyFileError(
            f"{len(shapes)} shapes but {len(rows)} attribute rows in the county zip"
        )
    rings: list[list[Point]] = []
    counties = 0
    for row, shape in zip(rows, shapes, strict=True):
        if row["STATEFP"] == state_fips:
            counties += 1
            rings.extend(shape)
    if not counties:
        raise CountyFileError(f"no counties with STATEFP {state_fips} in the zip")
    return rings, counties


def ensure_counties(
    download_dir: Path,
    contact: str | None,
    *,
    session: brw.GetSession | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> Path:
    """Return the saved Census county zip, downloading it if it's missing.

    Raises:
        zipfile.BadZipFile: If the download isn't a zip, such as an error
            page.  Nothing is written in that case.
    """
    path = download_dir / COUNTY_FILE
    if not path.is_file():
        if session is None:
            session = make_session(contact)
        log.info("downloading %s", COUNTY_URL)
        data = brw._get(session, COUNTY_URL, sleep=sleep)
        with zipfile.ZipFile(io.BytesIO(data)):  # fail now on an HTML error page
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Leaflet


def _sri(data: bytes) -> str:
    """Return the sha512 Subresource Integrity value for some bytes."""
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")


def ensure_leaflet(
    download_dir: Path,
    contact: str | None,
    *,
    session: brw.GetSession | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> dict[str, Path]:
    """Return the saved Leaflet files, downloading any that are missing.

    Every file, saved or just downloaded, is checked against its pinned hash.

    Args:
        download_dir: Where downloads are kept between runs.
        contact: Contact address for the User-Agent header, or None.
        session: The HTTP session to use; one is opened if a download is
            needed and none is given.
        sleep: The pause function; tests pass a stub.

    Returns:
        The path of each file, keyed by its name.

    Raises:
        LeafletError: If a file doesn't match its pinned hash.
    """
    paths = {}
    for name, expected in LEAFLET_FILES.items():
        path = download_dir / f"leaflet-{LEAFLET_VERSION}-{name}"
        if not path.is_file():
            if session is None:
                session = make_session(contact)
            url = f"{LEAFLET_BASE}/{name}"
            log.info("downloading %s", url)
            data = brw._get(session, url, sleep=sleep)
            if _sri(data) != expected:
                raise LeafletError(f"{url} doesn't match its pinned hash")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if _sri(path.read_bytes()) != expected:
            raise LeafletError(f"{path} doesn't match its pinned hash; delete it")
        paths[name] = path
    return paths


# ---------------------------------------------------------------------------
# Embedded data


def is_federal_or_tribal(surface: str, minerals: str) -> bool:
    """True when a well scores less than the full jurisdiction points.

    That's the score's own definition: the surface or the minerals are
    Federal, Tribal, or Indian.  Using the scoring function keeps the map
    filter and the score from drifting apart.
    """
    return brw.jurisdiction_score(surface, minerals) < brw.JURISDICTION_POINTS


def well_rows(well_list: Path, op_dir: Path) -> list[Row]:
    """Join the four one-row-per-well tables, in ranked order.

    Returns:
        One dict per well holding every column in WELL_COLUMNS.
    """
    ecmc = {f"05-{row['APInumber']}": row for row in read_table(op_dir / ECMC_TABLE)}
    scout = {row["API_10"]: row for row in read_table(op_dir / SCOUT_TABLE)}
    summary = {row["API_10"]: row for row in read_table(op_dir / BH_SUMMARY_TABLE)}
    rows = []
    for ranked in read_table(well_list):
        api = ranked["API_10"]
        row = {column: ranked[column] for column in RANKED_COLUMNS}
        fed = is_federal_or_tribal(ranked["Surface"], ranked["Minerals"])
        row[FED_COLUMN] = "1" if fed else ""
        row.update({column: ecmc[api][column] for column in ECMC_COLUMNS})
        row.update({column: scout[api][column] for column in SCOUT_COLUMNS})
        row.update({column: summary[api][column] for column in BH_COLUMNS})
        rows.append(row)
    return rows


def detail_rows(path: Path, columns: Sequence[str]) -> dict[str, list[list[str]]]:
    """Group a many-rows-per-well table by API_10, keeping file order."""
    grouped: dict[str, list[list[str]]] = {}
    for row in read_table(path):
        grouped.setdefault(row["API_10"], []).append([row[c] for c in columns])
    return grouped


def page_meta(
    wells: Sequence[Mapping[str, str]],
    ranked_manifest: Mapping[str, Any],
    casing: Mapping[str, object],
    n_blockgroups: int,
    n_di_blockgroups: int,
) -> dict[str, object]:
    """Collect the dates, counts, and source records the pages show."""
    sources = ranked_manifest["sources"]
    owp = sources["ecmc_owp_shapefile"]
    cdphe = sources["cdphe_enviroscreen_v2_blockgroups"]
    scout_dates = sorted(w["fetched_at"] for w in wells if w["fetched_at"])
    bh_dates = sorted(w["bh_fetched_at"] for w in wells if w["bh_fetched_at"])
    blanks = [
        [label, sum(1 for w in wells if not w[column])]
        for column, label in BLANK_RATE_FIELDS
    ]
    blanks.append(
        ["Casing records", sum(1 for w in wells if w["API_10"] not in casing)]
    )
    blanks.append(
        ["Bradenhead tests", sum(1 for w in wells if w["bh_test_count"] in ("", "0"))]
    )
    return {
        "wells": len(wells),
        "listRetrieved": owp["retrieved_at"],
        "listUrl": owp["url"],
        "listSha256": owp["sha256"],
        "bgRetrieved": cdphe["retrieved_at"],
        "bgUrl": cdphe["url"],
        "bgSha256": cdphe["sha256"],
        "bgCount": n_blockgroups,
        "countySource": COUNTY_SOURCE,
        "countyUrl": COUNTY_URL,
        "bgDiCount": n_di_blockgroups,
        "scoutOldest": scout_dates[0] if scout_dates else "",
        "scoutNewest": scout_dates[-1] if scout_dates else "",
        "scoutMissing": sum(1 for w in wells if not w["fetched_at"]),
        "bhOldest": bh_dates[0] if bh_dates else "",
        "bhNewest": bh_dates[-1] if bh_dates else "",
        "bhMissing": sum(1 for w in wells if not w["bh_fetched_at"]),
        "blanks": blanks,
        "staleDays": STALE_DAYS,
        "tierCutoffs": list(brw.TIER_CUTOFFS),
        "simplifyMeters": round(SIMPLIFY_TOLERANCE_DEG * brw.M_PER_DEG_LAT),
        "leafletVersion": LEAFLET_VERSION,
        "repoUrl": REPO_URL,
    }


def js_value(value: object) -> str:
    """Serialize a value as JSON that's safe inside an HTML script element."""
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text.replace("</", "<\\/")


def data_script(mode: str, values: Mapping[str, object]) -> str:
    """Write the embedded data as JavaScript variable declarations."""
    lines = [f"var MODE={js_value(mode)};"]
    lines += [f"var {name}={js_value(value)};" for name, value in values.items()]
    return "\n".join(lines)


def render(template: str, parts: Mapping[str, str]) -> str:
    """Fill a template's {{NAME}} tokens in one pass.

    One pass matters: the embedded data may itself contain text that looks
    like a token, and it must not be filled in.

    Raises:
        KeyError: If the template names a token that parts doesn't hold.
    """
    return TOKEN_RE.sub(lambda match: parts[match[1]], template)


# ---------------------------------------------------------------------------
# Program data

PROGRAM_KEYS = (
    "asOf",
    "facts",
    "findings",
    "sourcesLead",
    "sources",
    "kpis",
    "pages",
    "laws",
    "gaps",
)


def _is_link(url: object) -> bool:
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def _card_problems(page: str, card: Mapping[str, Any], known: set[str]) -> list[str]:
    """Check one card's source ids and, for a bar chart, its series lengths."""
    where = f"{page} card {card.get('title', '?')!r}"
    cited = set(card.get("src", []))
    for item in card.get("items", []):
        if isinstance(item, dict):
            cited.update(item.get("src", []))
    problems = [
        f"{where} cites the undefined source {source!r}"
        for source in sorted(cited - known)
    ]
    if card.get("kind") == "bars":
        problems += [
            f"{where}: series {series['name']!r} has {len(series['values'])} "
            f"values for {len(card['x'])} categories"
            for series in card["series"]
            if len(series["values"]) != len(card["x"])
        ]
    return problems


def program_problems(program: Mapping[str, Any]) -> list[str]:
    """Describe every way the program data is inconsistent with itself.

    The checks are structural.  They can't tell whether a figure matches
    its source document, only that every figure names a source the file
    defines and that the pages can draw what the file holds.

    Args:
        program: The parsed contents of ip/program_data.json.

    Returns:
        One line per problem, empty when the file is consistent.
    """
    missing = [key for key in PROGRAM_KEYS if key not in program]
    if missing:
        return [f"the program data has no {key!r} entry" for key in missing]
    problems: list[str] = []
    sources = program["sources"]
    known = set(sources)
    for source_id, source in sources.items():
        if not source.get("t"):
            problems.append(f"source {source_id!r} has no title")
        if not _is_link(source.get("url")):
            problems.append(f"source {source_id!r} has no http or https link")
    problems += [
        f"tile {tile.get('k', '?')!r} cites the undefined source {tile['src']!r}"
        for tile in program["kpis"]
        if tile.get("src") and tile["src"] not in known
    ]
    card_ids: set[tuple[str, str]] = set()
    for page, content in program["pages"].items():
        for card in content.get("cards", []):
            problems += _card_problems(page, card, known)
            if card.get("id"):
                card_ids.add((page, card["id"]))
    for finding in program["findings"]["items"]:
        where = f"finding {finding.get('title', '?')!r}"
        problems += [
            f"{where} cites the undefined source {source!r}"
            for source in finding.get("src", [])
            if source not in known
        ]
        problems += [
            f"{where} points to the card {page}/{card_id}, which doesn't exist"
            for _label, page, card_id in finding.get("see", [])
            if (page, card_id) not in card_ids
        ]
    for law in program["laws"]["items"]:
        problems += [
            f"law {law.get('cite', '?')!r} has a link that isn't http or https: "
            f"{label!r}"
            for label, url in law.get("links", [])
            if not _is_link(url)
        ]
    return problems


def read_program(path: Path) -> dict[str, Any]:
    """Read the program data, stopping if it's inconsistent.

    Raises:
        ProgramDataError: If the file isn't a JSON object or fails a check
            in program_problems.
    """
    try:
        program = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProgramDataError(f"{path.name} isn't valid JSON: {exc}") from exc
    if not isinstance(program, dict):
        raise ProgramDataError(f"{path.name} doesn't hold a JSON object")
    problems = program_problems(program)
    if problems:
        raise ProgramDataError(f"{path.name}:\n" + "\n".join(problems))
    return program


# ---------------------------------------------------------------------------
# Running


@dataclass(frozen=True)
class Inputs:
    """Every file a build reads."""

    well_list: Path
    op_dir: Path
    blockgroups: Path
    counties: Path
    leaflet_js: Path
    leaflet_css: Path
    program: Path = PROGRAM_DATA
    web_dir: Path = WEB_DIR

    def data_files(self) -> list[Path]:
        """Return the data inputs, for the manifest."""
        return [
            self.well_list,
            self.well_list.with_suffix(".sources.json"),
            *(self.op_dir / name for name in (*PER_WELL_TABLES, *DETAIL_TABLES)),
            self.blockgroups,
            self.program,
            self.leaflet_js,
            self.leaflet_css,
        ]


def build(inputs: Inputs, out_dir: Path) -> dict[str, Path]:
    """Check the tables, then write the dashboard, the map, and a manifest.

    Args:
        inputs: The files to read.
        out_dir: Where the two pages and the manifest go.

    Returns:
        The paths written, keyed "dashboard", "map", and "manifest".

    Raises:
        WellSetError: If the tables don't describe the same wells.  Nothing
            is written in that case.
        ProgramDataError: If the program data is inconsistent.  Nothing is
            written in that case either.
    """
    check_well_set(inputs.well_list, inputs.op_dir)
    program = read_program(inputs.program)
    wells = well_rows(inputs.well_list, inputs.op_dir)
    casing = detail_rows(inputs.op_dir / CASING_TABLE, CASING_COLUMNS)
    cement = detail_rows(inputs.op_dir / CEMENT_TABLE, CEMENT_COLUMNS)
    tests = detail_rows(inputs.op_dir / BH_TESTS_TABLE, TEST_COLUMNS)
    manifest_path = inputs.well_list.with_suffix(".sources.json")
    ranked_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    scored_with = ranked_manifest["sources"]["cdphe_enviroscreen_v2_blockgroups"]
    if brw.sha256(inputs.blockgroups) != scored_with["sha256"]:
        log.warning(
            "%s isn't the file the ranked list was scored with; the shading "
            "and the wells' DI status may disagree until the list is rebuilt",
            inputs.blockgroups.name,
        )
    with inputs.blockgroups.open(encoding="utf-8") as f:
        features = json.load(f)["features"]
    topology = build_topology(features)
    arcs = encode_arcs(topology, SIMPLIFY_TOLERANCE_DEG)
    blockgroups, di_types = blockgroup_rows(features, topology)
    n_di = sum(1 for row in blockgroups if row[3])
    log.info(
        "%d wells, %d block groups (%d DI), %d boundary arcs",
        len(wells),
        len(blockgroups),
        n_di,
        len(arcs),
    )
    county_zip = inputs.counties.read_bytes()
    county_rings, n_counties = read_county_rings(county_zip)
    log.info("%d counties, %d boundary rings", n_counties, len(county_rings))
    meta = page_meta(wells, ranked_manifest, casing, len(blockgroups), n_di)
    meta["countyCount"] = n_counties
    shared: dict[str, object] = {
        "META": meta,
        "ARCS": arcs,
        "BG": blockgroups,
        "DITYPES": di_types,
        "COUNTY": [_delta_encode(_as_ints(ring)) for ring in county_rings],
    }
    dashboard_data = {
        **shared,
        "WCOLS": list(WELL_COLUMNS),
        "W": [[w[c] for c in WELL_COLUMNS] for w in wells],
        "CASCOLS": list(CASING_COLUMNS),
        "CAS": casing,
        "CEMCOLS": list(CEMENT_COLUMNS),
        "CEM": cement,
        "TESTCOLS": list(TEST_COLUMNS),
        "TESTS": tests,
    }
    map_data = {
        **shared,
        "WCOLS": list(MAP_COLUMNS),
        "W": [[w[c] for c in MAP_COLUMNS] for w in wells],
    }

    web = inputs.web_dir

    def web_text(name: str) -> str:
        return (web / name).read_text(encoding="utf-8").rstrip("\n")

    common_parts = {
        "LEAFLET_LICENSE": (web / "leaflet-LICENSE.txt").read_text(encoding="utf-8"),
        "LEAFLET_CSS": inputs.leaflet_css.read_text(encoding="utf-8"),
        "LEAFLET_JS": inputs.leaflet_js.read_text(encoding="utf-8"),
        "APP_JS": web_text("app.js"),
    }
    # Each page has its own frame and styles.  The dashboard also carries
    # the program data and the script that draws its pages.
    pages = {
        "dashboard": (
            DASHBOARD_FILE,
            "dashboard.html",
            {
                "TITLE": "Colorado Orphaned Well Program: data and sources",
                "APP_CSS": web_text("dashboard.css"),
                "DATA_JS": data_script("dashboard", dashboard_data),
                "PROGRAM_JSON": js_value(program),
                "PROGRAM_JS": web_text("program.js"),
            },
        ),
        "map": (
            MAP_FILE,
            "map.html",
            {
                "TITLE": "Colorado unplugged orphaned wells: map",
                "APP_CSS": web_text("map.css"),
                "DATA_JS": data_script("map", map_data),
            },
        ),
    }
    written = {}
    for key, (name, frame, parts) in pages.items():
        template = (web / frame).read_text(encoding="utf-8")
        html = render(template, {**common_parts, **parts})
        write_text_atomic(out_dir / name, html)
        written[key] = out_dir / name
        log.info("%s written, %.1f MB", name, len(html.encode("utf-8")) / 1e6)

    manifest = {
        "pages": {
            path.name: {"sha256": brw.sha256(path)}
            for path in (written["dashboard"], written["map"])
        },
        "wells": len(wells),
        "leaflet": {
            "version": LEAFLET_VERSION,
            "source": LEAFLET_BASE,
            "integrity": dict(LEAFLET_FILES),
        },
        # The hashes are of the shapefile parts, which identify the boundaries
        # however the zip that carried them was packed.
        "county_boundaries": {
            "source": COUNTY_SOURCE,
            "url": COUNTY_URL,
            "file": inputs.counties.name,
            "retrieved_at": brw.file_time(inputs.counties),
            "counties": n_counties,
            "sha256": {
                suffix: hashlib.sha256(data).hexdigest()
                for suffix, data in county_members(county_zip).items()
            },
        },
        "inputs": {
            path.name: {"sha256": brw.sha256(path)} for path in inputs.data_files()
        },
    }
    written["manifest"] = out_dir / MANIFEST_FILE
    write_text_atomic(written["manifest"], json.dumps(manifest, indent=2) + "\n")
    return written


def run(  # noqa: PLR0913
    contact: str | None,
    *,
    download_dir: Path = brw.DOWNLOAD_DIR,
    blockgroups: Path | None = None,
    well_list: Path = DEFAULT_WELL_LIST,
    op_dir: Path = DEFAULT_OUT_DIR,
    out_dir: Path = DOCS_DIR,
) -> dict[str, Path]:
    """Fetch what's missing, then build both pages.

    Args:
        contact: Contact address for the User-Agent header, or None.
        download_dir: Where downloads are kept between runs.
        blockgroups: A saved block group GeoJSON to use.  None uses the one
            in download_dir, downloading it if it isn't there.
        well_list: The ranked well list CSV.
        op_dir: The folder holding the six output tables.
        out_dir: Where the two pages and the manifest go.

    Returns:
        The paths written, keyed "dashboard", "map", and "manifest".

    Raises:
        WellSetError: If the tables don't describe the same wells.
        ProgramDataError: If ip/program_data.json is inconsistent.
        LeafletError: If a Leaflet file doesn't match its pinned hash.
        CountyFileError: If the Census county file can't be read.
    """
    if blockgroups is None:
        blockgroups = download_dir / brw.BLOCKGROUP_FILE
        if not blockgroups.exists():
            count = brw.download_blockgroups(make_session(contact), blockgroups)
            log.info("%d block groups saved to %s", count, blockgroups)
    counties = ensure_counties(download_dir, contact)
    leaflet = ensure_leaflet(download_dir, contact)
    inputs = Inputs(
        well_list=well_list,
        op_dir=op_dir,
        blockgroups=blockgroups,
        counties=counties,
        leaflet_js=leaflet["leaflet.js"],
        leaflet_css=leaflet["leaflet.css"],
    )
    return build(inputs, out_dir)


def main(argv: list[str] | None = None) -> int:
    """Build both pages from the command line and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DOCS_DIR,
        help="folder for the two pages and their manifest (default: docs/)",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=brw.DOWNLOAD_DIR,
        help="where downloads are kept between runs (default: ip/downloads/)",
    )
    parser.add_argument(
        "--blockgroups", type=Path, help="use this block group GeoJSON, no download"
    )
    parser.add_argument("--contact", help="contact address for the User-Agent header")
    parser.add_argument("-v", "--verbose", action="store_true", help="log more detail")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    saved = args.blockgroups or args.download_dir / brw.BLOCKGROUP_FILE
    wanted = [
        saved,
        args.download_dir / COUNTY_FILE,
        *(
            args.download_dir / f"leaflet-{LEAFLET_VERSION}-{name}"
            for name in LEAFLET_FILES
        ),
    ]
    need_download = any(not path.is_file() for path in wanted)
    contact = resolve_contact(args.contact) if need_download else None
    try:
        run(
            contact,
            download_dir=args.download_dir,
            blockgroups=args.blockgroups,
            out_dir=args.out_dir,
        )
    except (WellSetError, ProgramDataError, CountyFileError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
