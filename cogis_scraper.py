#!/usr/bin/env python3
"""Pull COGIS scout cards for Colorado's unplugged orphaned wells.

For each well in the input list this fetches the COGIS facility detail page

    https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=NNNNNNNN

where NNNNNNNN is the 8 digit county code and sequence with no dashes and no
05 state prefix (05-125-02377 becomes 12502377).  A dashed API returns a
"could Not be found" page with HTTP 200, so a page is checked for real well
content before it's cached.  Pages are cached under op/html_cache/, so a
stopped run resumes without refetching.

Fields are read from the page text by their labels, for example:

    Status: SI - 8/1/2022        Spud Date: 3/25/2004
    Measured TD: 2950 ft.  Vertical TD: 2950 ft.  Measured PB depth: 2905 ft.
    Casing: String Type: SURF, Hole Size: 12.25 in., Size: 8.625 in.,
        Top: 0 ft., Depth: 427 ft., Weight: 24 , Citings Type: ACTUAL
    Cement: Sacks: 350, Top: 0 ft., Bottom: 427 ft., Determination Method: CBL
    Additional Cement: String Type: OPEN HOLE , Top: 5400 ft., Depth: 5600 ft.,
        Bottom: 5600 ft., Sacks: 70, Method:

Casing strings appear twice on many pages: PLANNED under Wellbore Permit and
ACTUAL or HISTORICAL under Wellbore Completed.  Every string is followed by
one Cement record.  Any field can be blank.

Outputs, all keyed on API_10:
    cogis_scout_data.csv            one row per well
    cogis_casing.csv                one row per casing record, with its cement
    cogis_additional_cement.csv     one row per Additional Cement record

Usage:
    python cogis_scraper.py [well_list.csv] [output_folder] [--contact ADDRESS]
"""

import logging
import re
import sys
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

URL = "https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api={facid}"
NOT_FOUND = "could Not be found"

SCOUT_COLS = [
    "API_10", "fetched", "fetched_at", "well_status", "status_date",
    "spud_date", "completion_date", "measured_td_ft", "vertical_td_ft",
    "pb_depth_ft", "elevation_ft", "n_casing_strings",
    "n_planned_casing_strings", "surf_casing_size_in", "surf_casing_depth_ft",
    "n_additional_cement", "related_links",
]  # fmt: skip
CASING_COLS = [
    "API_10", "seq", "section", "citings_type", "string_type",
    "is_casing_string", "hole_size_in", "casing_size_in", "top_ft",
    "depth_ft", "weight", "cement_sacks", "cement_top_ft", "cement_bottom_ft",
    "cement_method",
]  # fmt: skip
ADD_CEMENT_COLS = [
    "API_10", "seq", "string_type", "top_ft", "depth_ft", "bottom_ft",
    "sacks", "method",
]  # fmt: skip

# Scalar fields and the label pattern each is read from.  The first match on
# the page wins.  Status codes are matched case-sensitively (two capitals);
# the rest ignore case.  Depths and elevation drop thousands separators.
SCALAR_PATTERNS: dict[str, re.Pattern[str]] = {
    "well_status": re.compile(r"Status:\s*([A-Z]{2})\s*-"),
    "status_date": re.compile(r"Status:\s*[A-Z]{2}\s*-\s*([0-9/]{6,10})"),
    "spud_date": re.compile(r"Spud Date:\s*([0-9/]{6,10})", re.I),
    "completion_date": re.compile(r"Completion Date:\s*([0-9/]{6,10})", re.I),
    "measured_td_ft": re.compile(r"Measured\s*TD:\s*([\d,]+)", re.I),
    "vertical_td_ft": re.compile(r"Vertical\s*TD:\s*([\d,]+)", re.I),
    "pb_depth_ft": re.compile(r"Measured PB depth:\s*([\d,]+)", re.I),
    "elevation_ft": re.compile(r"Elevation[:\s]+([\d,]+)\s*ft", re.I),
}
NUMERIC_SCALARS = frozenset(
    {"measured_td_ft", "vertical_td_ft", "pb_depth_ft", "elevation_ft"}
)

# Links to other COGIS inquiry pages for the well (bradenhead, MIT).  In the
# 2026-08-05 snapshot every page offers exactly one, the bradenhead page.
RELATED_LINK_RE = re.compile(r'href="([^"]*(?:[Bb]radenhead|MIT|[Ii]ntegrity)[^"]*)"')

# Citings types for casing actually run.  PLANNED strings come from the permit.
RUN_CITINGS = ("ACTUAL", "HISTORICAL")

# Casing records that aren't a string of pipe: open hole intervals, stage
# tools, and stage cement entries (S.C. 1.1, S.C. 2.2, and so on).  They stay
# in cogis_casing.csv but don't count toward the string totals.
NON_CASING_TYPES = ("OPEN HOLE", "STAGE TOOL")
STAGE_CEMENT_PREFIX = "S.C."

# Each casing, cement, or section marker starts a new segment of page text.
# A record's fields are read only from its own segment.
MARKER_RE = re.compile(
    r"Wellbore Permit|Wellbore Completed|Additional Cement:"
    r"|Casing: String Type:|Cement: Sacks:"
)
# A number such as 8.625, 1,200, or .5, or nothing when ECMC left it blank.
# It can't begin or end with a comma, so a blank field doesn't swallow the
# comma that separates it from the next label.
NUM = r"((?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)?)"
IN, FT, SEP = r"\s*(?:in\.)?", r"\s*(?:ft\.)?", r"\s*,\s*"
CASING_RE = re.compile(
    r"Casing: String Type:\s*(.*?)" + SEP
    + r"Hole Size:\s*" + NUM + IN + SEP
    + r"Size:\s*" + NUM + IN + SEP
    + r"Top:\s*" + NUM + FT + SEP
    + r"Depth:\s*" + NUM + FT + SEP
    + r"Weight:\s*(.*?)" + SEP
    + r"Citings Type:\s*([A-Za-z]+)"
)  # fmt: skip
# PLANNED cement records stop at Bottom; completed ones add the method.
CEMENT_RE = re.compile(
    r"Cement: Sacks:\s*" + NUM + SEP
    + r"Top:\s*" + NUM + FT + SEP
    + r"Bottom:\s*" + NUM + FT
    + r"(?:" + SEP + r"Determination Method:\s*([^\s,]*))?"
)  # fmt: skip
ADD_CEMENT_RE = re.compile(
    r"Additional Cement: String Type:\s*(.*?)" + SEP
    + r"Top:\s*" + NUM + FT + SEP
    + r"Depth:\s*" + NUM + FT + SEP
    + r"Bottom:\s*" + NUM + FT + SEP
    + r"Sacks:\s*" + NUM + SEP
    + r"Method:\s*([^\s,]*)"
)  # fmt: skip
# When a method is blank, the next heading's first word lands in its place.
NOT_A_METHOD = frozenset({"", "Formation", "No", "Additional", "Casing:"})

Row = dict[str, str]


def is_scout_card(html: str) -> bool:
    """Return True only for a real well detail page, not a "Not found" page."""
    return NOT_FOUND not in html and (
        "Scout Card" in html or "Wellbore" in html or "Spud Date" in html
    )


def grab(pattern: re.Pattern[str], text: str) -> str:
    """Return the first capture group of pattern in text, trimmed, or ''."""
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def is_casing_string(string_type: str) -> bool:
    """Return False for open hole, stage tool, and stage cement records."""
    upper = string_type.upper()
    return upper not in NON_CASING_TYPES and not upper.startswith(STAGE_CEMENT_PREFIX)


def clean_num(value: str) -> str:
    """Drop thousands separators from a captured number; blank stays blank."""
    return value.replace(",", "")


def method(value: str | None) -> str:
    """Return a cement method, or '' when the field held the next heading."""
    return "" if value is None or value in NOT_A_METHOD else value


def parse_casing(html: str) -> tuple[list[Row], list[Row]]:
    """Read every casing record and Additional Cement record on a scout card.

    Casing records keep page order and carry the cement record that follows
    them.  Rows don't include API_10; run() adds it.

    Args:
        html: Raw scout card HTML.

    Returns:
        Casing rows keyed by CASING_COLS and Additional Cement rows keyed by
        ADD_CEMENT_COLS, each without API_10.
    """
    text = strip_tags(html)
    marks = list(MARKER_RE.finditer(text))
    casing: list[Row] = []
    additional: list[Row] = []
    section = ""
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        segment = text[mark.start() : end]
        if mark.group() == "Wellbore Permit":
            section = "permit"
        elif mark.group() == "Wellbore Completed":
            section = "completed"
        elif m := CASING_RE.match(segment):
            casing.append({
                "seq": str(len(casing) + 1), "section": section,
                "citings_type": m[7].upper(), "string_type": m[1],
                "is_casing_string": "Y" if is_casing_string(m[1]) else "N",
                "hole_size_in": clean_num(m[2]), "casing_size_in": clean_num(m[3]),
                "top_ft": clean_num(m[4]), "depth_ft": clean_num(m[5]),
                "weight": m[6], "cement_sacks": "", "cement_top_ft": "",
                "cement_bottom_ft": "", "cement_method": "",
            })  # fmt: skip
        elif (m := CEMENT_RE.match(segment)) and casing:
            casing[-1].update({
                "cement_sacks": clean_num(m[1]), "cement_top_ft": clean_num(m[2]),
                "cement_bottom_ft": clean_num(m[3]), "cement_method": method(m[4]),
            })  # fmt: skip
        elif m := ADD_CEMENT_RE.match(segment):
            additional.append({
                "seq": str(len(additional) + 1), "string_type": m[1],
                "top_ft": clean_num(m[2]), "depth_ft": clean_num(m[3]),
                "bottom_ft": clean_num(m[4]), "sacks": clean_num(m[5]),
                "method": method(m[6]),
            })  # fmt: skip
    return casing, additional


def parse_page(html: str) -> dict[str, str | int]:
    """Parse a scout card into the per-well fields of cogis_scout_data.csv.

    Args:
        html: Raw scout card HTML.

    Returns:
        Every SCOUT_COLS field except API_10, fetched, and fetched_at.
    """
    text = strip_tags(html)
    out: dict[str, str | int] = {}
    for field, pattern in SCALAR_PATTERNS.items():
        value = grab(pattern, text)
        out[field] = clean_num(value) if field in NUMERIC_SCALARS else value

    casing, additional = parse_casing(html)
    pipe = [c for c in casing if c["is_casing_string"] == "Y"]
    run = [c for c in pipe if c["citings_type"] in RUN_CITINGS]
    out["n_casing_strings"] = len(run)
    out["n_planned_casing_strings"] = len(pipe) - len(run)
    # Deepest run surface string; a few wells list more than one.
    surf = [c for c in run if c["string_type"] == "SURF" and c["depth_ft"]]
    deepest = max(surf, key=lambda c: float(c["depth_ft"])) if surf else None
    out["surf_casing_size_in"] = deepest["casing_size_in"] if deepest else ""
    out["surf_casing_depth_ft"] = deepest["depth_ft"] if deepest else ""
    out["n_additional_cement"] = len(additional)

    out["related_links"] = "; ".join(sorted(set(RELATED_LINK_RE.findall(html))))
    return out


def run(
    well_list: Path,
    out_dir: Path,
    contact: str | None,
    max_age_days: float | None = None,
) -> None:
    """Fetch or read from cache every well's scout card and write the CSVs.

    Args:
        well_list: CSV with an API_10 column.
        out_dir: Folder for the CSVs; the page cache goes in html_cache/.
        contact: Contact address for the User-Agent header, or None.
        max_age_days: Refetch cached pages older than this many days.  None
            reuses every cached page.
    """
    cache = out_dir / "html_cache"
    cache.mkdir(parents=True, exist_ok=True)
    apis = read_well_list(well_list)
    log.info("%d wells to fetch", len(apis))
    session = make_session(contact)

    rows: list[dict[str, object]] = []
    casing_rows: list[Row] = []
    cement_rows: list[Row] = []
    for i, api in enumerate(apis, 1):
        html = None
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
                is_scout_card,
                max_age_days=max_age_days,
            )
        rec: dict[str, object] = {
            "API_10": api,
            "fetched": bool(html),
            "fetched_at": fetched_date(cached) if html else "",
        }
        if html:
            rec.update(parse_page(html))
            casing, additional = parse_casing(html)
            casing_rows += [{"API_10": api, **c} for c in casing]
            cement_rows += [{"API_10": api, **c} for c in additional]
        rows.append(rec)
        if i % PROGRESS_EVERY == 0:
            log.info("%d/%d done", i, len(apis))

    write_csv(out_dir / "cogis_scout_data.csv", SCOUT_COLS, rows)
    write_csv(out_dir / "cogis_casing.csv", CASING_COLS, casing_rows)
    write_csv(out_dir / "cogis_additional_cement.csv", ADD_CEMENT_COLS, cement_rows)
    log.info(
        "wrote cogis_scout_data.csv (%d/%d scout cards), cogis_casing.csv "
        "(%d records), and cogis_additional_cement.csv (%d records) to %s",
        sum(1 for r in rows if r["fetched"]), len(rows), len(casing_rows),
        len(cement_rows), out_dir,
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    """Run the scraper from the command line and return an exit code."""
    parser = scraper_arg_parser("Pull COGIS scout cards for every well in a list.")
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
