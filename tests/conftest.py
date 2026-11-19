"""Shared pytest setup for the colorado-orphan-wells test suite.

The scrapers are standalone scripts at the repo root rather than a package,
so the root is put on sys.path here to make them importable from the tests.
"""

import csv
import io
import struct
import sys
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build_dashboard  # noqa: E402  (needs the repo root on sys.path)

# Builders for small OWP_SHP.ZIP inputs, shared by the tests of the scripts
# that read ECMC's shapefile.

OWP_FIELDS = (
    ("OWPStatus", 20),
    ("ProjName", 40),
    ("WellName", 40),
    ("APInumber", 12),
    ("Surface", 10),
    ("Minerals", 10),
    ("Latitude", 12),
    ("Longitude", 12),
)


def dbf_bytes(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[tuple[str, int]] = OWP_FIELDS,
    deleted: Sequence[int] = (),
) -> bytes:
    """Write a dBASE III table of text fields."""
    header_size = 32 + 32 * len(fields) + 1
    record_size = 1 + sum(width for _, width in fields)
    out = bytearray(struct.pack("<B3xIHH20x", 3, len(rows), header_size, record_size))
    for name, width in fields:
        out += struct.pack("<11sc4xBB14x", name.encode(), b"C", width, 0)
    out += b"\r"
    for i, row in enumerate(rows):
        out += b"*" if i in deleted else b" "
        for name, width in fields:
            out += row.get(name, "").encode("cp1252")[:width].ljust(width)
    return bytes(out + b"\x1a")


def owp_zip(
    rows: Sequence[Mapping[str, str]],
    fields: Sequence[tuple[str, int]] = OWP_FIELDS,
) -> bytes:
    """Wrap a dBASE table in a zip the way ECMC ships OWP_SHP.ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("OWP_Shapefile.dbf", dbf_bytes(rows, fields))
        zf.writestr("OWP_Shapefile.prj", "GEOGCS[...]")
    return buf.getvalue()


def owp_row(  # noqa: PLR0913
    api: str,
    lat: str,
    lon: str,
    *,
    status: str = "Unplugged",
    project: str = "Test Bond Claim",
    surface: str = "Fee",
    minerals: str = "Fee",
) -> dict[str, str]:
    """One OWP shapefile record."""
    return {
        "OWPStatus": status,
        "ProjName": project,
        "WellName": f"WELL {api} (OWP)",
        "APInumber": api,
        "Surface": surface,
        "Minerals": minerals,
        "Latitude": lat,
        "Longitude": lon,
    }


def _read(path: Path) -> str:
    # Same decoding the scrapers use when they read their caches.
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def scout_page() -> Callable[[str], str]:
    """Return a loader for saved COGIS scout card pages, keyed by 8 digit API."""
    return lambda facid: _read(FIXTURES / "cogis" / f"{facid}.html")


@pytest.fixture
def bradenhead_page() -> Callable[[str], str]:
    """Return a loader for saved COGIS bradenhead pages, keyed by 8 digit API."""
    return lambda facid: _read(FIXTURES / "bradenhead" / f"{facid}.html")


# Builders for a small, consistent set of committed tables, shared by the
# well set tests and the dashboard build tests.

WELL_SET_APIS = ("05-001-00001", "05-001-00002", "05-123-00003")


def write_table(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    """Write dict rows to a CSV, taking the columns from the first row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ranked_row(api: str, rank: int, **changes: str) -> dict[str, str]:
    """One ranked list row with every column, inside the test block groups."""
    row = dict.fromkeys(build_dashboard.RANKED_COLUMNS, "")
    row.update(
        Rank=str(rank),
        Tier="1",
        Priority_Score="60.0",
        API_10=api,
        WellName=f"WELL {rank} (OWP)",
        Project="Test Bond Claim",
        County="Adams",
        Lat="39.705",
        Lon="-104.895",
        Surface="Fee",
        Minerals="Fee",
        DI_Community_Nov2024="No",
    )
    row.update(changes)
    return row


def write_well_tables(
    root: Path, apis: Sequence[str] = WELL_SET_APIS
) -> tuple[Path, Path]:
    """Write a ranked list and six op tables that agree on apis.

    Returns:
        The ranked list path and the op folder.
    """
    well_list = root / "ip" / "ranked.csv"
    op = root / "op"
    write_table(well_list, [ranked_row(api, n) for n, api in enumerate(apis, 1)])
    write_table(
        op / build_dashboard.ECMC_TABLE,
        [
            {"APInumber": api[3:], **dict.fromkeys(build_dashboard.ECMC_COLUMNS, "")}
            for api in apis
        ],
    )
    scout = dict.fromkeys(build_dashboard.SCOUT_COLUMNS, "")
    scout.update(fetched="True", fetched_at="2026-11-18", spud_date="4/14/1987")
    write_table(
        op / build_dashboard.SCOUT_TABLE, [{"API_10": api, **scout} for api in apis]
    )
    summary = dict.fromkeys(build_dashboard.BH_COLUMNS, "")
    summary.update(bh_fetched_at="2026-11-18", bh_test_count="0")
    summary.update(bh_flow_class="no tests on file")
    summary.update(bh_flow_class_latest="no tests on file")
    write_table(
        op / build_dashboard.BH_SUMMARY_TABLE,
        [{"API_10": api, **summary} for api in apis],
    )
    casing = dict.fromkeys(build_dashboard.CASING_COLUMNS, "")
    casing.update(seq="1", citings_type="ACTUAL", string_type="SURF")
    write_table(op / build_dashboard.CASING_TABLE, [{"API_10": apis[0], **casing}])
    cement = dict.fromkeys(build_dashboard.CEMENT_COLUMNS, "")
    write_table(op / build_dashboard.CEMENT_TABLE, [{"API_10": apis[0], **cement}])
    test = dict.fromkeys(build_dashboard.TEST_COLUMNS, "")
    test.update(test_date="11/2/2022", comments="valve </script> {{APP_JS}}")
    write_table(op / build_dashboard.BH_TESTS_TABLE, [{"API_10": apis[0], **test}])
    return well_list, op


# Builders for a small Census county zip: a polygon .shp and its .dbf.

COUNTY_FIELDS = (("STATEFP", 2), ("COUNTYFP", 3), ("NAME", 30))
Ring = Sequence[tuple[float, float]]


def shp_polygon_record(number: int, rings: Sequence[Ring]) -> bytes:
    """One polygon record of a .shp file, with its record header."""
    points = [p for ring in rings for p in ring]
    starts, at = [], 0
    for ring in rings:
        starts.append(at)
        at += len(ring)
    xs, ys = [x for x, _ in points], [y for _, y in points]
    content = struct.pack(
        "<i4d2i", 5, min(xs), min(ys), max(xs), max(ys), len(rings), len(points)
    )
    content += struct.pack(f"<{len(starts)}i", *starts)
    content += b"".join(struct.pack("<2d", x, y) for x, y in points)
    return struct.pack(">2i", number, len(content) // 2) + content


def shp_bytes(shapes: Sequence[Sequence[Ring] | None]) -> bytes:
    """Write a polygon .shp file.  None writes a null shape."""
    body = b""
    for number, rings in enumerate(shapes, 1):
        if rings is None:
            body += struct.pack(">2i", number, 2) + struct.pack("<i", 0)
        else:
            body += shp_polygon_record(number, rings)
    words = (100 + len(body)) // 2
    header = struct.pack(">i20xi", 9994, words) + struct.pack("<2i64x", 1000, 5)
    return header + body


def county_zip(
    counties: Sequence[tuple[str, str, Sequence[Ring] | None]],
) -> bytes:
    """Zip a county shapefile the way the Census Bureau ships it.

    Args:
        counties: One (STATEFP, NAME, rings) per county.
    """
    rows = [
        {"STATEFP": state, "COUNTYFP": f"{n:03d}", "NAME": name}
        for n, (state, name, _) in enumerate(counties, 1)
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cb_2024_us_county_500k.shp", shp_bytes([c[2] for c in counties]))
        zf.writestr("cb_2024_us_county_500k.dbf", dbf_bytes(rows, COUNTY_FIELDS))
        zf.writestr("cb_2024_us_county_500k.prj", "GEOGCS[...]")
    return buf.getvalue()
