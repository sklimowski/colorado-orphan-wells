"""Tests for bradenhead_scraper.py against saved COGIS bradenhead pages.

Fixture pages in tests/fixtures/bradenhead/ are copies of pages cached by the
2026-08-05 scrape, named by 8 digit API.  The summarize() tests build small
test lists by hand so each rule can be checked on its own.

Strict xfail tests, if any, state the correct result for a defect logged in
docs/reviews/261117_code_review.md that hasn't been fixed yet.
"""

from collections.abc import Callable

import pytest

import bradenhead_scraper as bh

BradenheadLoader = Callable[[str], str]

NOT_FOUND_PAGE = "<html><body>Facility 05-125-02377 could Not be found.</body></html>"


def make_test(**overrides: str) -> dict[str, str]:
    """Build one parsed test row with neutral values, overriding what a test needs."""
    row = dict.fromkeys(bh.TEST_COLS, "--")
    row.update(
        test_date="1/1/2020",
        bh_flow_start="NO FLOW",
        bh_flow_end="NO FLOW",
        initial_surf_casing_psi="0",
        end_surf_casing_psi="0",
    )
    row.update(overrides)
    return row


# Page recognition and helpers


@pytest.mark.parametrize("facid", ["12309299", "06705556", "04505033", "04506297"])
def test_is_valid_page_accepts_saved_pages(
    bradenhead_page: BradenheadLoader, facid: str
) -> None:
    assert bh.is_valid_page(bradenhead_page(facid))


def test_is_valid_page_rejects_not_found_page() -> None:
    assert not bh.is_valid_page(NOT_FOUND_PAGE)


def test_is_valid_page_rejects_page_without_bradenhead_heading() -> None:
    assert not bh.is_valid_page("<html><body>Site maintenance</body></html>")


# parse_tests


def test_parse_tests_reads_the_docstring_example_well(
    bradenhead_page: BradenheadLoader,
) -> None:
    tests = bh.parse_tests(bradenhead_page("12309299"))
    assert len(tests) == 1
    row = tests[0]
    assert row["doc_number"] == "2606052"
    assert row["report_type"] == "Form 17"
    assert row["test_date"] == "1/18/2010"
    assert row["well_status"] == "PLUNGER LIFT"
    assert row["bh_flow_start"] == row["bh_flow_end"] == "NO FLOW"
    assert row["initial_prod_casing_psi"] == row["end_prod_casing_psi"] == "150"
    assert row["comments"].startswith("Buried valve was uncovered")


def test_parse_tests_ignores_the_well_header_row(
    bradenhead_page: BradenheadLoader,
) -> None:
    # This page has no tests.  Its only dated row is the 8 cell well header,
    # which must not be read as a test.
    assert bh.parse_tests(bradenhead_page("06705556")) == []


def test_parse_tests_reads_all_report_types(bradenhead_page: BradenheadLoader) -> None:
    tests = bh.parse_tests(bradenhead_page("04506297"))
    assert [t["report_type"] for t in tests] == ["Form 17", "Form 17", "Full"]
    assert [t["test_date"] for t in tests] == ["12/7/2023", "10/22/2022", "8/17/2021"]


def test_parse_tests_keeps_light_records_with_identical_readings(
    bradenhead_page: BradenheadLoader,
) -> None:
    # ECMC holds two Light records for this well with different IDs and the
    # same readings.  They're separate records, so both are kept.
    tests = bh.parse_tests(bradenhead_page("04505033"))
    assert [t["doc_number"] for t in tests] == [
        "N7S2L75N-B40W-4V4Z-4HXT-34ZRRABXX38K",
        "FA1A3F32-IYG1-H79A-JTM5-L4WO71W68JFC",
    ]
    readings = [{k: v for k, v in t.items() if k != "doc_number"} for t in tests]
    assert readings[0] == readings[1]


def test_full_report_doc_number_is_the_record_id(
    bradenhead_page: BradenheadLoader,
) -> None:
    # BH-08: Full and Light rows show "Click for Specifics" instead of a number.
    tests = bh.parse_tests(bradenhead_page("04506297"))
    assert [t["doc_number"] for t in tests] == [
        "403613354",
        "403292896",
        "Y8E6S3IT-JC7D-ET2I-IVO8-EBYJDWTITZTH",
    ]


# summarize: layout and existing fields


def test_summarize_writes_every_summary_column_in_order() -> None:
    assert list(bh.summarize("05-001-00001", [make_test()])) == bh.SUMMARY_COLS
    assert list(bh.summarize("05-001-00001", [])) == bh.SUMMARY_COLS


def test_summarize_well_with_no_tests_keeps_a_row() -> None:
    row = bh.summarize("05-067-05556", [])
    assert row["API_10"] == "05-067-05556"
    assert row["bh_test_count"] == 0
    assert row["bh_flow_class_rank"] == row["bh_flow_class_latest_rank"] == 7
    assert row["bh_flow_class"] == row["bh_flow_class_latest"] == "no tests on file"
    filled = {
        "API_10",
        "bh_test_count",
        "bh_flow_class_rank",
        "bh_flow_class",
        "bh_flow_class_latest_rank",
        "bh_flow_class_latest",
    }
    assert all(row[k] == "" for k in row if k not in filled)


def test_summarize_picks_latest_test_by_date_not_page_order(
    bradenhead_page: BradenheadLoader,
) -> None:
    # The page lists newest first; summarize must not assume either order.
    tests = bh.parse_tests(bradenhead_page("04506297"))
    row = bh.summarize("05-045-06297", list(reversed(tests)))
    assert row["bh_test_count"] == 3
    assert row["bh_first_test_date"] == "8/17/2021"
    assert row["bh_last_test_date"] == "12/7/2023"
    assert row["bh_last_flow_end"] == "NO FLOW"
    assert row["bh_last_fluid"] == "NONE"


def test_summarize_does_not_change_the_callers_list() -> None:
    tests = [make_test(test_date="5/1/2021"), make_test(test_date="1/1/2020")]
    before = [dict(t) for t in tests]
    bh.summarize("05-001-00001", tests)
    assert tests == before


# Helpers behind the flags


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Down to Zero", "DOWN TO 0"), (" whisper ", "WHISPER"), ("--", "--"), ("", "")],
)
def test_norm_flow(raw: str, expected: str) -> None:
    assert bh.norm_flow(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", bh.ZERO),
        ("0.0", bh.ZERO),
        ("1,250", bh.ABOVE_ZERO),
        (".5", bh.ABOVE_ZERO),
        ("TSTM", bh.ABOVE_ZERO),
        ("tstm", bh.ABOVE_ZERO),
        ("--", bh.UNKNOWN),
        ("", bh.UNKNOWN),
        ("none", bh.UNKNOWN),
    ],
)
def test_pressure_state(raw: str, expected: str) -> None:
    assert bh.pressure_state(raw) == expected


# Flags (each is Y, N, or U)


def flags_for(*tests: dict[str, str]) -> dict[str, str]:
    """Run flow_flags on tests given oldest first."""
    return bh.flow_flags(list(tests))


def test_any_flow_observed_is_n_when_every_test_shows_no_flow() -> None:
    assert (
        flags_for(make_test(), make_test(bh_flow_end="--"))["bh_any_flow_observed"]
        == "N"
    )


def test_any_flow_observed_ignores_case_of_no_flow() -> None:
    test = make_test(bh_flow_start="No Flow", bh_flow_end="no flow")
    assert flags_for(test)["bh_any_flow_observed"] == "N"


@pytest.mark.parametrize("value", ["WHISPER", "DOWN TO 0", "Down to Zero", "WATER H20"])
def test_any_flow_observed_counts_every_flow_code(value: str) -> None:
    assert flags_for(make_test(bh_flow_start=value))["bh_any_flow_observed"] == "Y"


def test_flow_flags_are_u_when_flow_fields_are_blank() -> None:
    # Bulk-uploaded Light records leave the flow fields empty.
    test = make_test(bh_flow_start="", bh_flow_end="", fluid_type="--")
    flags = flags_for(test)
    assert flags["bh_any_flow_observed"] == "U"
    assert flags["bh_liquid_flow"] == "U"
    assert flags["bh_flow_at_end"] == "U"


@pytest.mark.parametrize(
    "overrides",
    [
        {"bh_flow_start": "WATER H20"},
        {"fluid_type": "WATER H20"},
        {"fluid_type": "LIQUID HYDROCARBON"},
    ],
)
def test_liquid_flow_from_flow_or_fluid_field(overrides: dict[str, str]) -> None:
    assert flags_for(make_test(**overrides))["bh_liquid_flow"] == "Y"


def test_liquid_flow_is_n_for_gas_only() -> None:
    test = make_test(bh_flow_start="CONTINUOUS", fluid_type="GAS")
    assert flags_for(test)["bh_liquid_flow"] == "N"


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        ("WHISPER", "Y"),
        ("CONTINUOUS", "Y"),
        ("DOWN TO 0", "N"),
        ("Down to Zero", "N"),
        ("NO FLOW", "N"),
        ("", "U"),
    ],
)
def test_flow_at_end(end: str, expected: str) -> None:
    test = make_test(bh_flow_start="CONTINUOUS", bh_flow_end=end)
    assert flags_for(test)["bh_flow_at_end"] == expected


@pytest.mark.parametrize(
    ("end_psi", "expected"), [("12", "Y"), ("TSTM", "Y"), ("0", "N"), ("--", "U")]
)
def test_not_bled_to_zero(end_psi: str, expected: str) -> None:
    flags = flags_for(make_test(end_surf_casing_psi=end_psi))
    assert flags["bh_not_bled_to_zero"] == expected


def test_rebuild_when_next_test_starts_above_zero() -> None:
    first = make_test(test_date="1/1/2020", end_surf_casing_psi="0")
    second = make_test(test_date="1/1/2021", initial_surf_casing_psi="TSTM")
    assert flags_for(first, second)["bh_pressure_rebuild"] == "Y"


def test_rebuild_is_n_when_next_test_starts_at_zero() -> None:
    first = make_test(test_date="1/1/2020")
    second = make_test(test_date="1/1/2021")
    assert flags_for(first, second)["bh_pressure_rebuild"] == "N"


def test_rebuild_is_u_for_a_single_test() -> None:
    assert flags_for(make_test())["bh_pressure_rebuild"] == "U"


def test_rebuild_is_u_when_first_test_did_not_end_at_zero() -> None:
    # A rebuild needs a bleed to zero first; pressure that never reached zero
    # is caught by bh_not_bled_to_zero instead.
    first = make_test(test_date="1/1/2020", end_surf_casing_psi="30")
    second = make_test(test_date="1/1/2021", initial_surf_casing_psi="40")
    assert flags_for(first, second)["bh_pressure_rebuild"] == "U"


# Flow class: checked in rank order, first match wins


def test_flow_class_liquid_outranks_pressure() -> None:
    test = make_test(bh_flow_start="WATER H20", end_surf_casing_psi="50")
    assert bh.flow_class(flags_for(test)) == 1


def test_flow_class_pressure_outranks_flow_at_end() -> None:
    test = make_test(bh_flow_end="CONTINUOUS", end_surf_casing_psi="50")
    assert bh.flow_class(flags_for(test)) == 2


def test_flow_class_rebuild_counts_as_pressure() -> None:
    first = make_test(test_date="1/1/2020")
    second = make_test(test_date="1/1/2021", initial_surf_casing_psi="17")
    assert bh.flow_class(flags_for(first, second)) == 2


def test_flow_class_flow_at_end() -> None:
    assert bh.flow_class(flags_for(make_test(bh_flow_end="WHISPER"))) == 3


def test_flow_class_flow_bled_off() -> None:
    test = make_test(bh_flow_start="DOWN TO 0", bh_flow_end="DOWN TO 0")
    assert bh.flow_class(flags_for(test)) == 4


def test_flow_class_no_flow() -> None:
    assert bh.flow_class(flags_for(make_test())) == 5


def test_flow_class_flow_not_reported() -> None:
    test = make_test(bh_flow_start="", bh_flow_end="", end_surf_casing_psi="--")
    assert bh.flow_class(flags_for(test)) == 6


def test_every_rank_has_a_label() -> None:
    assert sorted(bh.FLOW_CLASSES) == list(range(1, 8))


# Ever versus latest


def test_latest_class_uses_only_the_latest_test(
    bradenhead_page: BradenheadLoader,
) -> None:
    # Two earlier tests bled down to zero; the latest showed no flow.
    tests = bh.parse_tests(bradenhead_page("04506297"))
    row = bh.summarize("05-045-06297", tests)
    assert row["bh_flow_class"] == "flow bled off"
    assert row["bh_flow_class_latest"] == "no flow"


def test_latest_class_judges_rebuild_from_the_last_two_tests() -> None:
    tests = [
        make_test(test_date="1/1/2019", bh_flow_start="WATER H20"),
        make_test(test_date="1/1/2020"),
        make_test(test_date="1/1/2021", initial_surf_casing_psi="8"),
    ]
    row = bh.summarize("05-001-00001", tests)
    assert row["bh_flow_class_rank"] == 1
    assert row["bh_flow_class_latest_rank"] == 2


def test_light_only_well_is_flow_not_reported(
    bradenhead_page: BradenheadLoader,
) -> None:
    tests = bh.parse_tests(bradenhead_page("04505033"))
    row = bh.summarize("05-045-05033", tests)
    assert row["bh_any_flow_observed"] == "U"
    assert row["bh_flow_class"] == row["bh_flow_class_latest"] == "flow not reported"


def test_same_date_tie_goes_to_the_later_submit_date() -> None:
    # BH-02: the later-submitted test is the latest, whatever the input order.
    later = make_test(
        test_date="3/1/2022", submit_date="4/2/2022", bh_flow_end="NO FLOW"
    )
    earlier = make_test(
        test_date="3/1/2022", submit_date="3/5/2022", bh_flow_end="WHISPER"
    )
    for order in ([later, earlier], [earlier, later]):
        assert bh.summarize("05-001-00001", order)["bh_last_flow_end"] == "NO FLOW"


def test_same_date_and_submit_tie_goes_to_the_higher_document_number() -> None:
    a = make_test(
        test_date="3/1/2022",
        submit_date="3/5/2022",
        doc_number="403292896",
        bh_flow_end="WHISPER",
    )
    b = make_test(
        test_date="3/1/2022",
        submit_date="3/5/2022",
        doc_number="403613354",
        bh_flow_end="NO FLOW",
    )
    for order in ([a, b], [b, a]):
        assert bh.summarize("05-001-00001", order)["bh_last_flow_end"] == "NO FLOW"


def test_chronological_key_sorts_numbers_by_value_before_record_ids() -> None:
    rows = [make_test(doc_number=d) for d in ("Y8E6S3IT", "1000", "999")]
    assert [r["doc_number"] for r in sorted(rows, key=bh.chronological_key)] == [
        "999",
        "1000",
        "Y8E6S3IT",
    ]


def test_summarize_reports_latest_start_flow_and_fetch_date() -> None:
    # BH-06: the end flow can be blank when the start flow isn't.
    tests = [make_test(bh_flow_start="WHISPER", bh_flow_end="")]
    row = bh.summarize("05-001-00001", tests, fetched_at="2026-08-05")
    assert (row["bh_last_flow_start"], row["bh_last_flow_end"]) == ("WHISPER", "")
    assert row["bh_fetched_at"] == "2026-08-05"


def test_summarize_max_psi_reads_both_surface_readings_and_commas() -> None:
    tests = [
        make_test(initial_surf_casing_psi="1,250", end_surf_casing_psi="40"),
        make_test(initial_surf_casing_psi="--", end_surf_casing_psi="TSTM"),
    ]
    assert bh.summarize("05-001-00001", tests)["bh_max_surf_casing_psi"] == 1250


def test_summarize_max_psi_blank_when_no_reading_is_numeric() -> None:
    tests = [make_test(initial_surf_casing_psi="--", end_surf_casing_psi="TSTM")]
    assert bh.summarize("05-001-00001", tests)["bh_max_surf_casing_psi"] == ""


def test_summarize_max_psi_accepts_leading_decimal() -> None:
    # BH-05
    tests = [make_test(initial_surf_casing_psi=".6", end_surf_casing_psi="--")]
    assert bh.summarize("05-001-00001", tests)["bh_max_surf_casing_psi"] == 1


@pytest.mark.parametrize(
    ("psi", "expected"), [("12.7", 13), ("12.5", 13), ("12.4", 12)]
)
def test_summarize_max_psi_rounds_half_up(psi: str, expected: int) -> None:
    # BH-05
    tests = [make_test(initial_surf_casing_psi=psi, end_surf_casing_psi="0")]
    assert bh.summarize("05-001-00001", tests)["bh_max_surf_casing_psi"] == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,250", 1250.0),
        (".3", 0.3),
        ("40", 40.0),
        ("TSTM", None),
        ("--", None),
        ("", None),
    ],
)
def test_surface_psi(raw: str, expected: float | None) -> None:
    assert bh.surface_psi(raw) == expected
