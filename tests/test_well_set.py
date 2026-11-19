"""Check that the committed tables describe the same set of wells.

The ranked list in ip/ defines the well set.  The tables with one row per
well must hold exactly the same API numbers, and the tables with many rows
per well may only hold wells from that set.  A ranked list rebuilt without a
scraper run (main.py with the scrapers skipped) breaks this, and so would a
map or dashboard drawn from the mismatched tables.

The check itself is build_dashboard.well_set_problems, the same function
build_dashboard.py runs before it writes a page, so the test and the build
can't drift apart.  The first test reads only committed files, so it runs on
a fresh clone with no downloads or page caches.  The rest show the check
catches each kind of mismatch.
"""

import csv
from pathlib import Path

import pytest

import build_dashboard
from build_dashboard import well_set_problems
from common import DEFAULT_WELL_LIST
from conftest import (
    REPO_ROOT,
    WELL_SET_APIS,
    ranked_row,
    write_table,
    write_well_tables,
)

OP = REPO_ROOT / "op"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_committed_tables_describe_the_same_wells() -> None:
    assert well_set_problems(DEFAULT_WELL_LIST, OP) == []


def test_consistent_tables_have_no_problems(tmp_path: Path) -> None:
    well_list, op = write_well_tables(tmp_path)
    assert well_set_problems(well_list, op) == []
    build_dashboard.check_well_set(well_list, op)


@pytest.mark.parametrize("table", build_dashboard.PER_WELL_TABLES)
def test_a_well_missing_from_a_per_well_table_is_reported(
    tmp_path: Path, table: str
) -> None:
    well_list, op = write_well_tables(tmp_path)
    rows = read_rows(op / table)
    write_table(op / table, rows[:-1])
    problems = well_set_problems(well_list, op)
    assert problems == [f"in the ranked list but not {table}: {WELL_SET_APIS[-1]}"]


@pytest.mark.parametrize("table", build_dashboard.PER_WELL_TABLES)
def test_a_repeated_well_is_reported(tmp_path: Path, table: str) -> None:
    well_list, op = write_well_tables(tmp_path)
    rows = read_rows(op / table)
    write_table(op / table, [*rows, rows[0]])
    assert well_set_problems(well_list, op) == [
        f"repeated in {table}: {WELL_SET_APIS[0]}"
    ]


@pytest.mark.parametrize(
    "table", (*build_dashboard.PER_WELL_TABLES[1:], *build_dashboard.DETAIL_TABLES)
)
def test_a_well_off_the_list_is_reported(tmp_path: Path, table: str) -> None:
    well_list, op = write_well_tables(tmp_path)
    rows = read_rows(op / table)
    write_table(op / table, [*rows, {**rows[0], "API_10": "05-999-99999"}])
    assert well_set_problems(well_list, op) == [
        f"in {table} but not the ranked list: 05-999-99999"
    ]


def test_a_repeat_on_the_ranked_list_is_reported(tmp_path: Path) -> None:
    well_list, op = write_well_tables(tmp_path)
    rows = read_rows(well_list)
    write_table(well_list, [*rows, rows[0]])
    assert well_set_problems(well_list, op) == [
        f"repeated in ranked.csv: {WELL_SET_APIS[0]}"
    ]


@pytest.mark.parametrize(
    ("lat", "lon"), [("", ""), ("39.7", ""), ("45.0", "-104.9"), ("39.7", "-99.0")]
)
def test_a_well_that_cant_be_mapped_is_reported(
    tmp_path: Path, lat: str, lon: str
) -> None:
    # A well with blank or out-of-state coordinates would drop off the map.
    well_list, op = write_well_tables(tmp_path)
    rows = [ranked_row(api, n) for n, api in enumerate(WELL_SET_APIS, 1)]
    rows[1].update(Lat=lat, Lon=lon)
    write_table(well_list, rows)
    assert well_set_problems(well_list, op) == [
        f"blank or outside Colorado: {WELL_SET_APIS[1]}"
    ]


def test_check_well_set_lists_every_problem(tmp_path: Path) -> None:
    well_list, op = write_well_tables(tmp_path)
    scout = op / build_dashboard.SCOUT_TABLE
    write_table(scout, read_rows(scout)[:-1])
    tests = op / build_dashboard.BH_TESTS_TABLE
    write_table(tests, [{**read_rows(tests)[0], "API_10": "05-999-99999"}])
    with pytest.raises(build_dashboard.WellSetError) as raised:
        build_dashboard.check_well_set(well_list, op)
    message = str(raised.value)
    assert WELL_SET_APIS[-1] in message
    assert "05-999-99999" in message


def test_long_lists_of_api_numbers_are_cut_short(tmp_path: Path) -> None:
    apis = [f"05-001-{n:05d}" for n in range(1, 16)]
    well_list, op = write_well_tables(tmp_path, apis)
    scout = op / build_dashboard.SCOUT_TABLE
    write_table(scout, read_rows(scout)[:2])
    (problem,) = well_set_problems(well_list, op)
    assert problem.endswith("and 3 more")
