"""Shared fetch, cache, and output helpers for the COGIS scrapers.

cogis_scraper.py and bradenhead_scraper.py read the same well list, request
one ECMC COGIS page per well at a polite rate, cache every valid page, and
write CSVs.  json2csv.py shares the CSV writer.  This module holds the parts
they have in common so the scripts can't drift apart.
"""

import argparse
import csv
import html
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import requests

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
# Written by build_ranked_wells.py; the same name every run, so git keeps the history.
DEFAULT_WELL_LIST = REPO_ROOT / "ip" / "CO_Orphan_Wells_EJ_Ranked_Wells.csv"
DEFAULT_OUT_DIR = REPO_ROOT / "op"

DELAY_S = 1.0  # minimum pause after every request to ECMC; stay polite
TIMEOUT_S = 30.0
MAX_ATTEMPTS = 3  # one try plus two retries for transient failures
BACKOFF_S = 5.0  # extra wait before retry n is BACKOFF_S * n
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
PROGRESS_EVERY = 50  # log a progress line every this many wells
SECONDS_PER_DAY = 86400.0

# The User-Agent names the project and, when one is set, a contact address
# ECMC can use to reach whoever is running the scrapers.
USER_AGENT = "colorado-orphan-wells"
CONTACT_ENV = "ORPHAN_WELLS_CONTACT"

# Wells are listed as 05-CCC-SSSSS (state, county, sequence).  COGIS wants
# the county and sequence only, with no dashes: 05-125-02377 is 12502377.
API_10_RE = re.compile(r"05-(\d{3})-(\d{5})")
CACHE_NAME_RE = re.compile(r"\d{8}\.html")  # a cached page, named by COGIS id


class ResponseLike(Protocol):
    """The parts of requests.Response that get_page uses."""

    @property
    def ok(self) -> bool:
        """True for an HTTP status below 400."""

    @property
    def status_code(self) -> int:
        """The HTTP status code."""

    @property
    def text(self) -> str:
        """The decoded response body."""


class SessionLike(Protocol):
    """The part of requests.Session that get_page uses."""

    def get(self, url: str, *, timeout: float) -> ResponseLike:
        """Send a GET request."""


def facility_id(api_10: str) -> str:
    """Convert an API_10 such as 05-125-02377 to its COGIS id, 12502377.

    Args:
        api_10: A well's API number in 05-CCC-SSSSS form.

    Returns:
        The 8 digit county code and sequence with no dashes.

    Raises:
        ValueError: If api_10 isn't in 05-CCC-SSSSS form.
    """
    match = API_10_RE.fullmatch(api_10.strip())
    if not match:
        raise ValueError(f"API_10 not in 05-CCC-SSSSS form: {api_10!r}")
    return match[1] + match[2]


def read_well_list(path: Path) -> list[str]:
    """Return the API_10 values from a well list CSV, in file order.

    Args:
        path: A CSV with an API_10 column.  Other columns are ignored.

    Returns:
        One API_10 string per data row.

    Raises:
        ValueError: If the file has no API_10 column.
    """
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "API_10" not in reader.fieldnames:
            raise ValueError(f"{path} has no API_10 column")
        return [row["API_10"] for row in reader]


def resolve_contact(cli_value: str | None) -> str | None:
    """Pick the User-Agent contact: the --contact value, else the environment.

    Args:
        cli_value: The --contact argument, or None if it wasn't given.

    Returns:
        The contact address, or None if neither source sets one.
    """
    contact = (cli_value or os.environ.get(CONTACT_ENV, "")).strip()
    if not contact:
        log.warning(
            "No contact address set.  Pass --contact or set %s so ECMC can "
            "reach you about your requests.",
            CONTACT_ENV,
        )
        return None
    return contact


def user_agent(contact: str | None) -> str:
    """Build the User-Agent header value, with the contact if there is one."""
    return f"{USER_AGENT} (contact: {contact})" if contact else USER_AGENT


def make_session(contact: str | None) -> requests.Session:
    """Open a requests session that identifies the project to ECMC."""
    session = requests.Session()
    session.headers["User-Agent"] = user_agent(contact)
    return session


def prune_cache(cache_dir: Path, apis: Iterable[str]) -> list[str]:
    """Delete cached pages for wells that aren't in apis.

    Only files named like a cached page (8 digits, .html) are touched, so
    anything else in the folder is left alone.

    Args:
        cache_dir: A scraper's page cache folder.
        apis: The API_10 values on the current well list.

    Returns:
        The 8 digit ids of the pages deleted, sorted.
    """
    keep = set()
    for api in apis:
        try:
            keep.add(facility_id(api))
        except ValueError:
            continue
    removed = []
    if cache_dir.is_dir():
        for page in cache_dir.glob("*.html"):
            if CACHE_NAME_RE.fullmatch(page.name) and page.stem not in keep:
                page.unlink()
                removed.append(page.stem)
    return sorted(removed)


def strip_tags(fragment: str) -> str:
    """Drop HTML tags, decode entities, collapse whitespace, and trim.

    Entities are decoded after the tags are removed, so text such as
    WON&#39;T or 1&quot; valve comes out as WON'T and 1" valve.
    """
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def write_text_atomic(path: Path, text: str) -> None:
    """Write UTF-8 text to path through a temp file, so a crash can't truncate it."""
    _write_atomic(path, lambda f: f.write(text))


def write_csv(
    path: Path, columns: Sequence[str], rows: Iterable[Mapping[str, object]]
) -> None:
    """Write rows to a UTF-8 CSV in the given column order.

    The file is written to a temp file in the same folder and renamed into
    place, so an interrupted run leaves the previous file intact.  Keys not
    in columns are ignored, and missing keys are written blank.
    """

    def emit(f: "_TextFile") -> None:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    _write_atomic(path, emit)


class _TextFile(Protocol):
    def write(self, s: str, /) -> int: ...


def _write_atomic(path: Path, emit: Callable[["_TextFile"], object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            emit(f)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def fetched_date(path: Path) -> str:
    """Return the UTC date a cached page was saved, from its file time.

    Copying the cache without keeping file times resets these dates, so copy
    with timestamps preserved (shutil.copytree, cp -p, robocopy /COPY:DAT).
    """
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()


def get_page(  # noqa: PLR0913
    session: SessionLike,
    url: str,
    cache_path: Path,
    is_valid: Callable[[str], bool],
    *,
    max_age_days: float | None = None,
    sleep: Callable[[float], object] = time.sleep,
    now: Callable[[], float] = time.time,
) -> str | None:
    """Return a page's HTML from the cache, or fetch, check, and cache it.

    A cached page is returned without a request, unless max_age_days is set
    and the cached copy is older than that.  Otherwise the page is
    requested, and every request is followed by a DELAY_S pause.  Timeouts,
    connection errors, and HTTP 429 or 5xx responses are retried up to
    MAX_ATTEMPTS times with a growing backoff.  Only pages that pass is_valid
    are cached, so a "Not found" page served with HTTP 200 is never kept.
    If refreshing an old cached page fails, the old copy is returned and the
    cache file keeps its date.

    Args:
        session: The HTTP session to request with.
        url: The page URL.
        cache_path: Where the page is or will be cached.
        is_valid: Returns True for a page with real well content.
        max_age_days: Refetch cached pages older than this.  None keeps
            cached pages however old they are.
        sleep: The pause function; tests pass a stub.
        now: The clock, in epoch seconds; tests pass a stub.

    Returns:
        The page HTML, or None if it couldn't be retrieved or wasn't valid.
        Each failure is logged with its reason.
    """
    cached: str | None = None
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8", errors="replace")
        age_days = (now() - cache_path.stat().st_mtime) / SECONDS_PER_DAY
        if max_age_days is None or age_days <= max_age_days:
            return cached
    page = _fetch(session, url, cache_path, is_valid, sleep)
    if page is None and cached is not None:
        log.warning("%s: refresh failed, keeping the cached page", url)
        return cached
    return page


def _fetch(
    session: SessionLike,
    url: str,
    cache_path: Path,
    is_valid: Callable[[str], bool],
    sleep: Callable[[float], object],
) -> str | None:
    """Request a page with retries, cache it if valid, and return it or None."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=TIMEOUT_S)
        except requests.RequestException as exc:
            problem, transient = f"{type(exc).__name__}: {exc}", True
        else:
            if response.ok:
                sleep(DELAY_S)
                if is_valid(response.text):
                    write_text_atomic(cache_path, response.text)
                    return response.text
                log.warning(
                    "%s: HTTP %s but no well content", url, response.status_code
                )
                return None
            problem = f"HTTP {response.status_code}"
            transient = response.status_code in RETRY_STATUSES
        sleep(DELAY_S)
        if not transient or attempt == MAX_ATTEMPTS:
            log.warning(
                "%s: %s (attempt %d of %d), giving up",
                url,
                problem,
                attempt,
                MAX_ATTEMPTS,
            )
            return None
        log.info("%s: %s, retrying", url, problem)
        sleep(BACKOFF_S * attempt)
    return None  # not reached: the last attempt always returns above


def configure_logging(verbose: bool = False) -> None:
    """Send log messages to stderr; DEBUG with verbose, else INFO."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )


def scraper_arg_parser(description: str) -> argparse.ArgumentParser:
    """Build the command line shared by the two scrapers."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "well_list",
        nargs="?",
        type=Path,
        default=DEFAULT_WELL_LIST,
        help="CSV with an API_10 column (default: the ranked list in ip/)",
    )
    parser.add_argument(
        "out_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="folder for the CSVs and the page cache (default: op/)",
    )
    parser.add_argument(
        "--contact",
        help=f"contact address for the User-Agent header (default: ${CONTACT_ENV})",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        help="refetch cached pages older than this many days (default: never)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log more detail")
    return parser
