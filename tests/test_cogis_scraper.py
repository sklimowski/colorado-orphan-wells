"""Tests for cogis_scraper.py against saved COGIS scout card pages.

Fixture pages in tests/fixtures/cogis/ are copies of pages cached by the
2026-08-05 scrape, named by 8 digit API (05-045-06287 is 04506287).

Scalar tests pin fields the 2026-11-17 review checked against the pages and
found correct.  Casing and cement tests check the rewritten parser against
the page text for the defects logged in docs/reviews/261117_code_review.md
(CS-01 to CS-05, CS-08, CS-12).  Synthetic pages cover layouts the fixtures
don't: weights with commas, blank fields, Additional Cement records.
"""

import re
from collections.abc import Callable

import pytest

import cogis_scraper as cs

ScoutLoader = Callable[[str], str]

# What COGIS serves for a bad API.  It's a normal 200 response, which is why
# the scraper has to inspect the page text before caching it.
NOT_FOUND_PAGE = "<html><body>Facility 05-125-02377 could Not be found.</body></html>"

FIXTURE_IDS = ["04506287", "04506947", "11506072", "04506946", "08705485"]


# Page recognition


@pytest.mark.parametrize("facid", FIXTURE_IDS)
def test_is_scout_card_accepts_saved_pages(scout_page: ScoutLoader, facid: str) -> None:
    assert cs.is_scout_card(scout_page(facid))


def test_is_scout_card_rejects_not_found_page() -> None:
    assert not cs.is_scout_card(NOT_FOUND_PAGE)


def test_is_scout_card_rejects_unrelated_page() -> None:
    assert not cs.is_scout_card("<html><body>Site maintenance</body></html>")


# Helpers


def test_grab_returns_empty_string_when_pattern_is_absent() -> None:
    assert cs.grab(re.compile(r"Spud Date:\s*(\S+)"), "no dates here") == ""


# Scalar fields, checked against the page text during the review

SCALAR_EXPECTED = {
    "04506287": {
        "well_status": "SI",
        "status_date": "6/1/2020",
        "spud_date": "",
        "completion_date": "11/9/1980",
        "measured_td_ft": "3833",
        "vertical_td_ft": "3833",
        "pb_depth_ft": "3600",
        "elevation_ft": "5253",
    },
    "04506947": {
        "well_status": "PR",
        "status_date": "12/1/2023",
        "spud_date": "",
        "completion_date": "11/18/1996",
        "measured_td_ft": "4765",
        "vertical_td_ft": "4487",
        "pb_depth_ft": "4717",
        "elevation_ft": "5792",
    },
    "11506072": {
        "well_status": "SI",
        "status_date": "10/1/2023",
        "spud_date": "12/2/2011",
        "completion_date": "12/10/2011",
        "measured_td_ft": "2665",
        "vertical_td_ft": "",
        "pb_depth_ft": "2610",
        "elevation_ft": "3633",
    },
    # No wellbore data on file at all: blanks here are correct, not misses.
    "04506946": {
        "well_status": "SI",
        "status_date": "6/1/2020",
        "spud_date": "",
        "completion_date": "",
        "measured_td_ft": "",
        "vertical_td_ft": "",
        "pb_depth_ft": "",
        "elevation_ft": "5247",
    },
}


@pytest.mark.parametrize("facid", sorted(SCALAR_EXPECTED))
def test_parse_page_scalar_fields(scout_page: ScoutLoader, facid: str) -> None:
    parsed = cs.parse_page(scout_page(facid))
    for field, expected in SCALAR_EXPECTED[facid].items():
        assert parsed[field] == expected, field


def test_parse_page_well_with_no_casing_on_file(scout_page: ScoutLoader) -> None:
    parsed = cs.parse_page(scout_page("04506946"))
    assert parsed["n_casing_strings"] == 0
    assert parsed["n_planned_casing_strings"] == 0
    assert parsed["surf_casing_size_in"] == parsed["surf_casing_depth_ft"] == ""
    assert parsed["n_additional_cement"] == 0
    assert cs.parse_casing(scout_page("04506946")) == ([], [])


def test_parse_page_finds_bradenhead_link(scout_page: ScoutLoader) -> None:
    parsed = cs.parse_page(scout_page("04506287"))
    assert parsed["related_links"] == "../Incidents/bradenheadScout.aspx?api=04506287"


def test_entities_between_label_and_value_are_decoded() -> None:
    # CS-08: an entity such as &nbsp; between a label and its value.
    page = "<td>Spud Date:&nbsp;3/25/2004</td><td>Status:&nbsp;SI - 8/1/2022</td>"
    parsed = cs.parse_page(page)
    assert parsed["spud_date"] == "3/25/2004"
    assert parsed["well_status"] == "SI"


# Casing and cement (CS-01 to CS-05 and CS-12)


def casing_page(*records: str) -> str:
    """Wrap scout card casing and cement text in minimal HTML."""
    return (
        "<html><body>" + " ".join(f"<td>{r}</td>" for r in records) + "</body></html>"
    )


def test_casing_reads_casing_size_not_hole_size(scout_page: ScoutLoader) -> None:
    # Page: SURF hole 12.25 in., casing 8.625 in.; 1ST hole 7.875 in., casing 4.5 in.
    casing, _ = cs.parse_casing(scout_page("04506287"))
    assert [
        (c["string_type"], c["hole_size_in"], c["casing_size_in"]) for c in casing
    ] == [
        ("SURF", "12.25", "8.625"),
        ("1ST", "7.875", "4.5"),
    ]


def test_casing_rows_carry_their_own_cement(scout_page: ScoutLoader) -> None:
    casing, _ = cs.parse_casing(scout_page("04506287"))
    first, second = casing
    assert (
        first["cement_sacks"],
        first["cement_top_ft"],
        first["cement_bottom_ft"],
    ) == ("200", "0", "329")
    assert first["cement_method"] == "VISU"
    assert (
        second["cement_sacks"],
        second["cement_top_ft"],
        second["cement_bottom_ft"],
    ) == ("150", "3100", "3632")
    assert second["cement_method"] == "CBL"


def test_planned_and_run_strings_are_kept_apart(scout_page: ScoutLoader) -> None:
    # Page lists SURF and 1ST twice: PLANNED under the permit, ACTUAL as completed.
    casing, _ = cs.parse_casing(scout_page("11506072"))
    assert [(c["section"], c["citings_type"], c["depth_ft"]) for c in casing] == [
        ("permit", "PLANNED", "450"),
        ("permit", "PLANNED", "3000"),
        ("completed", "ACTUAL", "475"),
        ("completed", "ACTUAL", "2651"),
    ]
    parsed = cs.parse_page(scout_page("11506072"))
    assert parsed["n_casing_strings"] == 2
    assert parsed["n_planned_casing_strings"] == 2


def test_planned_cement_has_no_method(scout_page: ScoutLoader) -> None:
    # Permit cement records end at Bottom; there's no Determination Method.
    casing, _ = cs.parse_casing(scout_page("11506072"))
    assert (casing[0]["cement_sacks"], casing[0]["cement_method"]) == ("180", "")
    assert (casing[2]["cement_sacks"], casing[2]["cement_method"]) == ("114", "CALC")


def test_cement_kept_when_bottom_is_blank(scout_page: ScoutLoader) -> None:
    # Page: "Cement: Sacks: 350, Top: 0 ft., Bottom: , Determination Method:"
    casing, _ = cs.parse_casing(scout_page("04506947"))
    assert casing[0]["cement_sacks"] == "350"
    assert casing[0]["cement_top_ft"] == "0"
    assert casing[0]["cement_bottom_ft"] == ""


def test_casing_kept_when_top_is_blank(scout_page: ScoutLoader) -> None:
    # Page: "String Type: SURF, Hole Size: 13.75 in., Size: 9.625 in., Top: ,
    # Depth: 217 ft."
    casing, _ = cs.parse_casing(scout_page("08705485"))
    assert len(casing) == 1
    assert (
        casing[0]["casing_size_in"],
        casing[0]["top_ft"],
        casing[0]["depth_ft"],
    ) == ("9.625", "", "217")
    assert cs.parse_page(scout_page("08705485"))["n_casing_strings"] == 1


def test_blank_bottom_does_not_swallow_the_method() -> None:
    page = casing_page(
        "Casing: String Type: SURF, Hole Size: , Size: 10.75 in., Top: ,"
        " Depth: 125 ft., Weight: 32.75 , Citings Type: ACTUAL",
        "Cement: Sacks: 100, Top: , Bottom: , Determination Method: CBL",
    )
    casing, _ = cs.parse_casing(page)
    assert (casing[0]["cement_bottom_ft"], casing[0]["cement_method"]) == ("", "CBL")


def test_weight_with_commas_and_symbols_is_kept_as_written() -> None:
    page = casing_page(
        "Casing: String Type: 1ST, Hole Size: 7.875 in., Size: 5.5 in., Top: 0 ft.,"
        " Depth: 8118 ft., Weight: 15.5,17 , Citings Type: ACTUAL",
        "Cement: Sacks: 1,200, Top: 0 ft., Bottom: 8118 ft., Determination Method: CBL",
    )
    casing, _ = cs.parse_casing(page)
    assert casing[0]["weight"] == "15.5,17"
    assert casing[0]["depth_ft"] == "8118"
    assert casing[0]["cement_sacks"] == "1200"


@pytest.mark.parametrize(
    "next_heading", ["Formation Interval Top", "No formation data"]
)
def test_next_heading_is_not_read_as_a_method(next_heading: str) -> None:
    page = casing_page(
        "Casing: String Type: SURF, Hole Size: , Size: 7 in., Top: 0 ft.,"
        " Depth: 60 ft., Weight: 20 , Citings Type: ACTUAL",
        f"Cement: Sacks: 15, Top: , Bottom: , Determination Method: {next_heading}",
    )
    casing, _ = cs.parse_casing(page)
    assert casing[0]["cement_method"] == ""


def test_additional_cement_records() -> None:
    page = casing_page(
        "Additional Cement: String Type: OPEN HOLE , Top: 5400 ft., Depth: 5600 ft.,"
        " Bottom: 5600 ft., Sacks: 70, Method:",
        "Additional Cement: String Type: OPEN HOLE , Top: 442 ft., Depth: 604 ft.,"
        " Bottom: 604 ft., Sacks: 80, Method: Formation Interval Top",
    )
    _, additional = cs.parse_casing(page)
    assert additional == [
        {
            "seq": "1",
            "string_type": "OPEN HOLE",
            "top_ft": "5400",
            "depth_ft": "5600",
            "bottom_ft": "5600",
            "sacks": "70",
            "method": "",
        },
        {
            "seq": "2",
            "string_type": "OPEN HOLE",
            "top_ft": "442",
            "depth_ft": "604",
            "bottom_ft": "604",
            "sacks": "80",
            "method": "",
        },
    ]
    assert cs.parse_page(page)["n_additional_cement"] == 2


def test_surface_casing_is_the_deepest_run_surf_string() -> None:
    page = casing_page(
        "Wellbore Permit",
        "Casing: String Type: SURF, Hole Size: 12.25 in., Size: 8.625 in., Top: 0 ft.,"
        " Depth: 900 ft., Weight: 24 , Citings Type: PLANNED",
        "Wellbore Completed",
        "Casing: String Type: SURF, Hole Size: 17.5 in., Size: 13.375 in., Top: 0 ft.,"
        " Depth: 60 ft., Weight: 48 , Citings Type: ACTUAL",
        "Casing: String Type: SURF, Hole Size: 12.25 in., Size: 8.625 in., Top: 0 ft.,"
        " Depth: 410 ft., Weight: 24 , Citings Type: ACTUAL",
    )
    parsed = cs.parse_page(page)
    assert (parsed["surf_casing_size_in"], parsed["surf_casing_depth_ft"]) == (
        "8.625",
        "410",
    )
    assert parsed["n_casing_strings"] == 2
    assert parsed["n_planned_casing_strings"] == 1


@pytest.mark.parametrize(
    ("string_type", "expected"),
    [
        ("SURF", True),
        ("1ST LINER", True),
        ("CONDUCTOR", True),
        ("OPEN HOLE", False),
        ("STAGE TOOL", False),
        ("S.C. 1.1", False),
        ("S.C. 3.2", False),
    ],
)
def test_is_casing_string(string_type: str, expected: bool) -> None:
    assert cs.is_casing_string(string_type) is expected


def test_string_counts_leave_out_non_pipe_records() -> None:
    page = casing_page(
        "Wellbore Completed",
        "Casing: String Type: SURF, Hole Size: 12.25 in., Size: 8.625 in., Top: 0 ft.,"
        " Depth: 410 ft., Weight: 24 , Citings Type: ACTUAL",
        "Casing: String Type: 1ST, Hole Size: 7.875 in., Size: 4.5 in., Top: 0 ft.,"
        " Depth: 4700 ft., Weight: 11.6 , Citings Type: ACTUAL",
        "Casing: String Type: S.C. 1.1, Hole Size: , Size: , Top: , Depth: 4950 ft.,"
        " Weight: , Citings Type: ACTUAL",
        "Casing: String Type: OPEN HOLE, Hole Size: 7.875 in., Size: , Top: 4700 ft.,"
        " Depth: 4770 ft., Weight: , Citings Type: ACTUAL",
    )
    casing, _ = cs.parse_casing(page)
    assert [c["is_casing_string"] for c in casing] == ["Y", "Y", "N", "N"]
    assert cs.parse_page(page)["n_casing_strings"] == 2
