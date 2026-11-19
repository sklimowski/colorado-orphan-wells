#!/usr/bin/env python3
"""Pull COGIS bradenhead test records for Colorado's unplugged orphaned wells.

Companion to cogis_scraper.py.  Every scout card links to a bradenhead
history page at

    https://ecmc.state.co.us/cogisdb/Incidents/bradenheadScout.aspx?api=NNNNNNNN

where NNNNNNNN is the same 8 digit county code and sequence the scout card
uses (05-125-02377 becomes 12502377).  The page holds an HTML table with one
row per reported bradenhead test and sixteen columns:

    View Form/Details | Report Type | Test Date | Submit Date | Well Status |
    Initial Surf Casing | Bradenhead Flow (Start) | Fluid Type |
    End Surf Casing | Bradenhead Flow (End) | Initial Prod Casing |
    End Prod Casing | Sample Taken? | Gas | Liquid | Comments

Example row (api=12309299):

    2606052 | Form 17 | 1/18/2010 | 4/1/2010 | PLUNGER LIFT | 0 | NO FLOW |
    -- | 0 | NO FLOW | 150 | 150 | No | -- | -- | Buried valve was uncovered...

Outputs, keyed on API_10:
    bradenhead_tests.csv    one row per test (long format), values as shown
    bradenhead_summary.csv  one row per well: fetch date, test count and
                            dates, latest test readings, flow and pressure
                            flags, and a flow class for all tests and for the
                            latest test

A well with no bradenhead history still gets a summary row (bh_test_count 0),
so the summary joins to the full well list.  Pages are cached under
op/bradenhead_cache/, so a stopped run resumes without refetching.

Usage:
    python bradenhead_scraper.py [well_list.csv] [output_folder] [--contact ADDRESS]
"""

import logging
import math
import re
import sys
from itertools import pairwise
from pathlib import Path

from common import (
    PROGRESS_EVERY,
    configure_logging,
    facility_id,
    fetched_date,
    get_page,
    make_session,
    read_well_list,
    resolve_contact,
    scraper_arg_parser,
    strip_tags,
    write_csv,
)

log = logging.getLogger(__name__)

URL = "https://ecmc.state.co.us/cogisdb/Incidents/bradenheadScout.aspx?api={facid}"
NOT_FOUND = "could Not be found"
TEST_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)

# The sixteen table columns, in page order, mapped to CSV-friendly names.
TEST_COLS = [
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
    "gas_analysis",
    "liquid_analysis",
    "comments",
]

# Per-well summary columns, in output order.  Definitions are in the README.
SUMMARY_COLS = [
    "API_10",
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
    "bh_flow_class_rank",
    "bh_flow_class",
    "bh_flow_class_latest_rank",
    "bh_flow_class_latest",
]

# Flow classes, checked in rank order; a well takes the first one it meets.
# The order is an analyst convention, since ECMC doesn't rank these
# observations.  Liquid flow comes first because Rule 419 treats any liquid
# flow as reportable, and pressure second because ECMC defines sustained
# casing pressure as pressure that won't bleed to zero or builds back up.
FLOW_CLASSES = {
    1: "liquid flow",
    2: "pressure persists or rebuilds",
    3: "flow at end of test",
    4: "flow bled off",
    5: "no flow",
    6: "flow not reported",
    7: "no tests on file",
}

BLANK_CODES = frozenset({"", "--"})  # flow or fluid cell left empty
NO_FLOW = "NO FLOW"
DOWN_TO_0 = "DOWN TO 0"

# Full and Light records link to their details with a record_id.
RECORD_ID_RE = re.compile(r"record_id=([A-Za-z0-9-]+)")

# Pressure cell states.  See pressure_state().
ZERO, ABOVE_ZERO, UNKNOWN = "zero", "above zero", "unknown"


def is_valid_page(html: str) -> bool:
    """Return True for a real bradenhead page, including one with zero tests.

    A bad API returns the same "could Not be found" text as the scout card
    endpoint.  A good page always carries the Bradenhead heading, even when
    the well has no reports on file.
    """
    return NOT_FOUND not in html and "radenhead" in html


def parse_tests(html: str) -> list[dict[str, str]]:
    """Return one dict per bradenhead test row found in the page.

    Rather than assuming a specific table id, this walks every <tr>, splits
    it into <td> cells, and keeps rows with exactly sixteen cells whose third
    cell is a date (Test Date).  That skips the header row, which uses <th>
    cells, the 8 cell well header row, and any layout tables.

    The first cell is the Form 17 document number.  Full and Light records
    have no document number, only a "Click for Specifics" link, so for those
    the record_id from the link is used instead.

    Args:
        html: Raw bradenhead page HTML.

    Returns:
        Test rows keyed by TEST_COLS, in page order.
    """
    tests = []
    for tr in ROW_RE.findall(html):
        raw = CELL_RE.findall(tr)
        cells = [strip_tags(c) for c in raw]
        if len(cells) == len(TEST_COLS) and TEST_DATE_RE.fullmatch(cells[2]):
            if (rid := RECORD_ID_RE.search(raw[0])) and not cells[0].isdigit():
                cells[0] = rid.group(1)
            tests.append(dict(zip(TEST_COLS, cells, strict=True)))
    return tests


YMD = tuple[int, int, int]  # (year, month, day)


def mdy(value: str) -> YMD:
    """Turn an M/D/YYYY date into a sortable (year, month, day); blank sorts first."""
    try:
        m, d, y = value.split("/")
        return (int(y), int(m), int(d))
    except ValueError:
        return (0, 0, 0)


def chronological_key(test: dict[str, str]) -> tuple[YMD, YMD, tuple[int, int, str]]:
    """Sort key that puts a well's tests in date order, oldest first.

    Ties on test date go to submit date, then document number, so the
    "latest" test is the one submitted last.  Numeric Form 17 document
    numbers sort by value and come before Full and Light record IDs.
    """
    doc = test["doc_number"]
    doc_key = (0, int(doc), "") if doc.isdigit() else (1, 0, doc)
    return (mdy(test["test_date"]), mdy(test["submit_date"]), doc_key)


def surface_psi(value: str) -> float | None:
    """Read a surface casing pressure as a number, or None.

    Accepts values like 1,250 and .3.  TSTM and other text return None: they
    don't count toward the maximum, and the pressure flags handle TSTM.
    """
    v = value.replace(",", "").strip()
    return float(v) if re.fullmatch(r"\d+(\.\d*)?|\.\d+", v) else None


def norm_flow(value: str) -> str:
    """Uppercase a Bradenhead Flow value and merge the two Down to 0 spellings.

    Form 17 rows write DOWN TO 0 and Full rows write Down to Zero for the
    same Form 17 code (D).
    """
    v = value.strip().upper()
    return DOWN_TO_0 if v == "DOWN TO ZERO" else v


def pressure_state(value: str) -> str:
    """Classify a pressure cell as ZERO, ABOVE_ZERO, or UNKNOWN.

    TSTM (too small to measure) counts as above zero.  ECMC uses it for a
    shut-in pressure greater than zero that the gauge can't resolve.  Blanks,
    '--', and other text are UNKNOWN.
    """
    v = value.replace(",", "").strip().upper()
    if v == "TSTM":
        return ABOVE_ZERO
    try:
        return ABOVE_ZERO if float(v) > 0 else ZERO
    except ValueError:
        return UNKNOWN


def flag(found: bool, assessable: bool) -> str:
    """Y if the evidence was found, N if it could have been and wasn't, else U."""
    if found:
        return "Y"
    return "N" if assessable else "U"


def flow_flags(tests: list[dict[str, str]]) -> dict[str, str]:
    """Derive the bradenhead flags for a list of tests sorted oldest first.

    Each flag is Y, N, or U (can't be determined from these records, for
    example because the flow fields are blank or there's only one test).

    Args:
        tests: Parsed test rows for one well, oldest first.

    Returns:
        The five flag columns of SUMMARY_COLS.
    """
    flows = [norm_flow(t[k]) for t in tests for k in ("bh_flow_start", "bh_flow_end")]
    ends = [norm_flow(t["bh_flow_end"]) for t in tests]
    fluids = [t["fluid_type"].strip().upper() for t in tests]
    flow_reported = any(v not in BLANK_CODES for v in flows)
    fluid_reported = any(f not in BLANK_CODES for f in fluids)

    # WATER H20 turns up in the flow fields as well as the fluid field.
    liquid = any("WATER" in v for v in flows) or any(
        "WATER" in f or "LIQUID" in f for f in fluids
    )

    end_states = [pressure_state(t["end_surf_casing_psi"]) for t in tests]

    # Rebuild: one test ended at 0 psi and the next started above 0.  Each
    # test follows a 7 to 14 day shut-in, so a nonzero start pressure after a
    # bleed to zero means pressure built back up between tests.
    pairs = [
        (
            pressure_state(a["end_surf_casing_psi"]),
            pressure_state(b["initial_surf_casing_psi"]),
        )
        for a, b in pairwise(tests)
    ]
    rebuild = any(p == (ZERO, ABOVE_ZERO) for p in pairs)
    rebuild_known = any(end == ZERO and start != UNKNOWN for end, start in pairs)

    return {
        "bh_any_flow_observed": flag(
            any(v not in BLANK_CODES and v != NO_FLOW for v in flows), flow_reported
        ),
        "bh_liquid_flow": flag(liquid, flow_reported or fluid_reported),
        "bh_flow_at_end": flag(
            any(e not in BLANK_CODES and e not in (NO_FLOW, DOWN_TO_0) for e in ends),
            any(e not in BLANK_CODES for e in ends),
        ),
        "bh_not_bled_to_zero": flag(
            ABOVE_ZERO in end_states, any(e != UNKNOWN for e in end_states)
        ),
        "bh_pressure_rebuild": flag(rebuild, rebuild_known),
    }


def flow_class(flags: dict[str, str]) -> int:
    """Return the rank of the first FLOW_CLASSES entry the flags meet."""
    if flags["bh_liquid_flow"] == "Y":
        return 1
    if "Y" in (flags["bh_not_bled_to_zero"], flags["bh_pressure_rebuild"]):
        return 2
    if flags["bh_flow_at_end"] == "Y":
        return 3
    if flags["bh_any_flow_observed"] == "Y":
        return 4
    if flags["bh_any_flow_observed"] == "N":
        return 5
    return 6


def summarize(
    api: str, tests: list[dict[str, str]], fetched_at: str = ""
) -> dict[str, str | int]:
    """Collapse a well's test list into one summary row for joining.

    The flags and bh_flow_class cover every test on file.
    bh_flow_class_latest uses the latest test alone, except that rebuild is
    judged from the latest test and the one before it.

    Args:
        api: The well's API_10.
        tests: Parsed test rows for the well, in any order.
        fetched_at: UTC date the bradenhead page was retrieved, or blank.

    Returns:
        One row keyed by SUMMARY_COLS.
    """
    row: dict[str, str | int] = dict.fromkeys(SUMMARY_COLS, "")
    row["API_10"] = api
    row["bh_fetched_at"] = fetched_at
    row["bh_test_count"] = len(tests)
    if not tests:
        row["bh_flow_class_rank"] = row["bh_flow_class_latest_rank"] = 7
        row["bh_flow_class"] = row["bh_flow_class_latest"] = FLOW_CLASSES[7]
        return row

    tests = sorted(tests, key=chronological_key)
    last = tests[-1]
    row["bh_first_test_date"] = tests[0]["test_date"]
    row["bh_last_test_date"] = last["test_date"]
    row["bh_last_flow_start"] = last["bh_flow_start"]
    row["bh_last_flow_end"] = last["bh_flow_end"]
    row["bh_last_end_surf_casing_psi"] = last["end_surf_casing_psi"]
    row["bh_last_fluid"] = last["fluid_type"]

    psis = [
        p
        for t in tests
        for k in ("initial_surf_casing_psi", "end_surf_casing_psi")
        if (p := surface_psi(t[k])) is not None
    ]
    if psis:
        # Round half up; Python's round() would send 12.5 to 12.
        row["bh_max_surf_casing_psi"] = math.floor(max(psis) + 0.5)

    flags = flow_flags(tests)
    row.update(flags)
    rank = flow_class(flags)
    row["bh_flow_class_rank"], row["bh_flow_class"] = rank, FLOW_CLASSES[rank]

    latest = flow_flags([last])
    latest["bh_pressure_rebuild"] = flow_flags(tests[-2:])["bh_pressure_rebuild"]
    rank = flow_class(latest)
    row["bh_flow_class_latest_rank"] = rank
    row["bh_flow_class_latest"] = FLOW_CLASSES[rank]
    return row


def run(
    well_list: Path,
    out_dir: Path,
    contact: str | None,
    max_age_days: float | None = None,
) -> None:
    """Fetch or read from cache every well's bradenhead page and write the CSVs.

    Args:
        well_list: CSV with an API_10 column.
        out_dir: Folder for the CSVs; the page cache goes in bradenhead_cache/.
        contact: Contact address for the User-Agent header, or None.
        max_age_days: Refetch cached pages older than this many days.  None
            reuses every cached page.
    """
    cache = out_dir / "bradenhead_cache"
    cache.mkdir(parents=True, exist_ok=True)
    apis = read_well_list(well_list)
    log.info("%d wells to fetch", len(apis))
    session = make_session(contact)

    all_tests: list[dict[str, str]] = []
    summaries: list[dict[str, str | int]] = []
    for i, api in enumerate(apis, 1):
        html, fetched_at = None, ""
        try:
            facid = facility_id(api)
        except ValueError as exc:
            log.warning("%s", exc)
        else:
            cached = cache / f"{facid}.html"
            html = get_page(
                session,
                URL.format(facid=facid),
                cached,
                is_valid_page,
                max_age_days=max_age_days,
            )
            fetched_at = fetched_date(cached) if html else ""
        tests = parse_tests(html) if html else []
        all_tests += [{"API_10": api, **t} for t in tests]
        summaries.append(summarize(api, tests, fetched_at))
        if i % PROGRESS_EVERY == 0:
            log.info("%d/%d done (%d tests so far)", i, len(apis), len(all_tests))

    write_csv(out_dir / "bradenhead_tests.csv", ["API_10", *TEST_COLS], all_tests)
    write_csv(out_dir / "bradenhead_summary.csv", SUMMARY_COLS, summaries)
    with_history = sum(1 for s in summaries if s["bh_test_count"])
    log.info(
        "wrote bradenhead_tests.csv (%d tests) and bradenhead_summary.csv "
        "(%d/%d wells with history) to %s",
        len(all_tests), with_history, len(summaries), out_dir,
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    """Run the scraper from the command line and return an exit code."""
    parser = scraper_arg_parser(
        "Pull COGIS bradenhead test records for every well in a list."
    )
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    if not args.well_list.exists():
        parser.error(f"well list not found: {args.well_list}")
    run(
        args.well_list,
        args.out_dir,
        resolve_contact(args.contact),
        args.max_age_days,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
