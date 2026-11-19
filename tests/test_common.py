"""Tests for common.py: API conversion, file helpers, and the fetch loop.

The fetch tests use a fake session and a recorded sleep, so they make no
network requests and don't wait.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests

import common

# facility_id and read_well_list


@pytest.mark.parametrize(
    ("api", "expected"), [("05-125-02377", "12502377"), (" 05-001-06072 ", "00106072")]
)
def test_facility_id(api: str, expected: str) -> None:
    assert common.facility_id(api) == expected


@pytest.mark.parametrize("api", ["125-02377", "05-125-2377", "06-125-02377", ""])
def test_facility_id_rejects_malformed_api(api: str) -> None:
    with pytest.raises(ValueError, match="05-CCC-SSSSS"):
        common.facility_id(api)


def test_read_well_list_keeps_file_order(tmp_path: Path) -> None:
    path = tmp_path / "wells.csv"
    path.write_text("Rank,API_10\n1,05-125-02377\n2,05-001-06072\n", encoding="utf-8")
    assert common.read_well_list(path) == ["05-125-02377", "05-001-06072"]


def test_read_well_list_needs_api_10(tmp_path: Path) -> None:
    path = tmp_path / "wells.csv"
    path.write_text("Rank,API\n1,05-125-02377\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no API_10 column"):
        common.read_well_list(path)


# Text and file helpers


def test_strip_tags_removes_markup_and_collapses_whitespace() -> None:
    assert common.strip_tags("<td>Spud\n  Date:</td><td>3/25/2004</td>") == (
        "Spud Date: 3/25/2004"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("GAS&nbsp;&amp;&nbsp;VAPOR", "GAS & VAPOR"), ("WON&#39;T", "WON'T"),
     ("1&quot; valve", '1" valve'), ("<b>a</b>&lt;b", "a <b")],
)  # fmt: skip
def test_strip_tags_decodes_entities(raw: str, expected: str) -> None:
    assert common.strip_tags(raw) == expected


def test_write_csv_orders_columns_and_leaves_no_temp_file(tmp_path: Path) -> None:
    out = tmp_path / "sub" / "out.csv"
    common.write_csv(out, ["b", "a"], [{"a": 1, "b": 2, "extra": 3}, {"a": "x"}])
    assert out.read_bytes() == b"b,a\r\n2,1\r\n,x\r\n"
    assert [p.name for p in out.parent.iterdir()] == ["out.csv"]


def test_write_csv_keeps_old_file_if_writing_fails(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    out.write_text("old\n", encoding="utf-8")

    def rows() -> list[dict[str, object]]:
        raise RuntimeError("interrupted")

    class Exploding:
        def __iter__(self) -> object:
            return iter(rows())

    with pytest.raises(RuntimeError):
        common.write_csv(out, ["a"], Exploding())  # type: ignore[arg-type]
    assert out.read_text(encoding="utf-8") == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]


def test_fetched_date_is_the_files_utc_date(tmp_path: Path) -> None:
    page = tmp_path / "12345678.html"
    page.write_text("x", encoding="utf-8")
    stamp = datetime(2026, 8, 5, 23, 30, tzinfo=UTC).timestamp()
    os.utime(page, (stamp, stamp))
    assert common.fetched_date(page) == "2026-08-05"


# User-Agent contact


def test_contact_flag_wins_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(common.CONTACT_ENV, "env@example.org")
    assert common.resolve_contact("flag@example.org") == "flag@example.org"


def test_contact_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(common.CONTACT_ENV, " env@example.org ")
    assert common.resolve_contact(None) == "env@example.org"


def test_missing_contact_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(common.CONTACT_ENV, raising=False)
    assert common.resolve_contact(None) is None
    assert common.CONTACT_ENV in caplog.text


def test_user_agent() -> None:
    assert common.user_agent(None) == "colorado-orphan-wells"
    assert common.user_agent("a@example.org") == (
        "colorado-orphan-wells (contact: a@example.org)"
    )
    session = common.make_session("a@example.org")
    assert session.headers["User-Agent"] == common.user_agent("a@example.org")


# get_page


@dataclass
class FakeResponse:
    """Stands in for requests.Response."""

    status_code: int
    text: str = ""

    @property
    def ok(self) -> bool:
        """True below HTTP 400, as in requests."""
        return self.status_code < 400


@dataclass
class FakeSession:
    """Returns or raises queued results, one per request, and logs the URLs."""

    results: list[FakeResponse | Exception]
    urls: list[str] = field(default_factory=list)

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        """Pop the next queued result."""
        self.urls.append(url)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


GOOD = "<html>Wellbore data</html>"


def is_good(html: str) -> bool:
    return "Wellbore" in html


def fetch(session: FakeSession, cache: Path, sleeps: list[float]) -> str | None:
    return common.get_page(session, "https://x/p", cache, is_good, sleep=sleeps.append)


def test_cached_page_is_read_without_a_request(tmp_path: Path) -> None:
    cache = tmp_path / "p.html"
    cache.write_text(GOOD, encoding="utf-8")
    session = FakeSession([])
    sleeps: list[float] = []
    assert fetch(session, cache, sleeps) == GOOD
    assert session.urls == []
    assert sleeps == []


def test_good_page_is_cached_and_followed_by_the_delay(tmp_path: Path) -> None:
    cache = tmp_path / "p.html"
    session = FakeSession([FakeResponse(200, GOOD)])
    sleeps: list[float] = []
    assert fetch(session, cache, sleeps) == GOOD
    assert cache.read_text(encoding="utf-8") == GOOD
    assert sleeps == [common.DELAY_S]


def test_not_found_page_with_http_200_is_not_cached(tmp_path: Path) -> None:
    cache = tmp_path / "p.html"
    session = FakeSession([FakeResponse(200, "could Not be found")])
    assert fetch(session, cache, []) is None
    assert not cache.exists()


def test_transient_errors_are_retried_with_backoff(tmp_path: Path) -> None:
    cache = tmp_path / "p.html"
    session = FakeSession([
        FakeResponse(503),
        requests.ConnectionError("reset"),
        FakeResponse(200, GOOD),
    ])  # fmt: skip
    sleeps: list[float] = []
    assert fetch(session, cache, sleeps) == GOOD
    delay, backoff = common.DELAY_S, common.BACKOFF_S
    assert sleeps == [delay, backoff * 1, delay, backoff * 2, delay]


def test_gives_up_after_max_attempts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    session = FakeSession([FakeResponse(429)] * common.MAX_ATTEMPTS)
    assert fetch(session, tmp_path / "p.html", []) is None
    assert len(session.urls) == common.MAX_ATTEMPTS
    assert "HTTP 429" in caplog.text
    assert "giving up" in caplog.text


def test_client_errors_are_not_retried(tmp_path: Path) -> None:
    session = FakeSession([FakeResponse(404)])
    sleeps: list[float] = []
    assert fetch(session, tmp_path / "p.html", sleeps) is None
    assert len(session.urls) == 1
    assert sleeps == [common.DELAY_S]


def aged_cache(tmp_path: Path, days: float) -> tuple[Path, float]:
    """A cached page and a clock reading `days` after the page was saved."""
    cache = tmp_path / "p.html"
    cache.write_text("<html>Wellbore old</html>", encoding="utf-8")
    return cache, cache.stat().st_mtime + days * common.SECONDS_PER_DAY


def test_recent_cached_page_is_reused_with_max_age(tmp_path: Path) -> None:
    cache, clock = aged_cache(tmp_path, days=10)
    session = FakeSession([])
    page = common.get_page(
        session, "https://x/p", cache, is_good, max_age_days=30, now=lambda: clock
    )
    assert page == "<html>Wellbore old</html>"
    assert session.urls == []


def test_old_cached_page_is_refetched(tmp_path: Path) -> None:
    cache, clock = aged_cache(tmp_path, days=31)
    session = FakeSession([FakeResponse(200, GOOD)])
    page = common.get_page(
        session,
        "https://x/p",
        cache,
        is_good,
        max_age_days=30,
        sleep=lambda _: None,
        now=lambda: clock,
    )
    assert page == GOOD
    assert cache.read_text(encoding="utf-8") == GOOD


def test_failed_refresh_keeps_the_old_page(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache, clock = aged_cache(tmp_path, days=31)
    mtime = cache.stat().st_mtime
    session = FakeSession([FakeResponse(404)])
    page = common.get_page(
        session,
        "https://x/p",
        cache,
        is_good,
        max_age_days=30,
        sleep=lambda _: None,
        now=lambda: clock,
    )
    assert page == "<html>Wellbore old</html>"
    assert cache.stat().st_mtime == mtime
    assert "keeping the cached page" in caplog.text


def test_scraper_parser_reads_max_age_days() -> None:
    parser = common.scraper_arg_parser("x")
    assert parser.parse_args([]).max_age_days is None
    assert parser.parse_args(["--max-age-days", "30"]).max_age_days == 30.0


def test_prune_cache_deletes_pages_for_wells_off_the_list(tmp_path: Path) -> None:
    for name in ("12309299.html", "06705556.html", "notes.txt", "1230.html"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    removed = common.prune_cache(tmp_path, ["05-123-09299", "bad api"])
    assert removed == ["06705556"]
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["1230.html", "12309299.html", "notes.txt"]


def test_prune_cache_ignores_a_missing_folder(tmp_path: Path) -> None:
    assert common.prune_cache(tmp_path / "none", ["05-123-09299"]) == []
