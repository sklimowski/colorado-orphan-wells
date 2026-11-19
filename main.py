#!/usr/bin/env python3
"""Refresh every output from the latest public data, in order.

1. Download ECMC's OWP_SHP.ZIP and log whether it changed since the last run.
   The CDPHE block groups are downloaded only if missing or with
   --refresh-blockgroups, since CDPHE updates them rarely.
2. Rebuild ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv (build_ranked_wells.py)
   and log the wells added to and removed from the list since the last run.
3. Write op/ecmc_unplugged_orphan_wells.csv from the zip (owp2csv.py).
4. Run cogis_scraper.py and then bradenhead_scraper.py over the new list.
   Cached pages older than --max-age-days are fetched again.  With
   --prune-cache, cached pages for wells no longer on the list are deleted.
5. Rebuild docs/dashboard.html and docs/map.html (build_dashboard.py), which
   first checks that every table describes the same wells.  Skipped with
   --skip-scrapers, since the tables may then be behind the new list.

The scrapers pause 1 second after every request to ECMC and run one after
the other, so a run that fetches every well takes about 45 minutes.

Usage:
    python main.py --contact you@example.org [--max-age-days 30]
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import bradenhead_scraper
import build_dashboard
import build_ranked_wells as brw
import cogis_scraper
import owp2csv
from common import (
    CONTACT_ENV,
    DEFAULT_OUT_DIR,
    DEFAULT_WELL_LIST,
    configure_logging,
    make_session,
    prune_cache,
    read_well_list,
    resolve_contact,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 30.0
SHOW_APIS = 50  # list at most this many API numbers per change in the log
CACHE_DIRS = ("html_cache", "bradenhead_cache")


def list_changes(old: Sequence[str], new: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return the API numbers added and removed between two well lists, sorted."""
    return sorted(set(new) - set(old)), sorted(set(old) - set(new))


def _api_summary(apis: Sequence[str]) -> str:
    """Up to SHOW_APIS API numbers for a log line."""
    shown = ", ".join(apis[:SHOW_APIS])
    more = len(apis) - SHOW_APIS
    return f"{shown}, and {more} more" if more > 0 else shown


def log_list_changes(old: Sequence[str] | None, new: Sequence[str]) -> None:
    """Log how the well list changed since the last build."""
    if old is None:
        log.info("no earlier well list to compare with; %d wells", len(new))
        return
    added, removed = list_changes(old, new)
    if not added and not removed:
        log.info("well list unchanged: %d wells", len(new))
        return
    log.info(
        "well list changed: %d added, %d removed, %d wells now",
        len(added),
        len(removed),
        len(new),
    )
    if added:
        log.info("added: %s", _api_summary(added))
    if removed:
        log.info("removed: %s", _api_summary(removed))


def refresh_sources(
    contact: str | None, download_dir: Path, *, refresh_blockgroups: bool
) -> tuple[Path, Path]:
    """Download the OWP zip, and the block groups if needed.

    Returns:
        The paths of the OWP zip and the block group GeoJSON.
    """
    owp_zip = download_dir / brw.OWP_FILE
    blockgroups = download_dir / brw.BLOCKGROUP_FILE
    session = make_session(contact)
    before = brw.sha256(owp_zip) if owp_zip.exists() else None
    brw.download_owp(session, owp_zip)
    if before is None:
        log.info("downloaded the OWP zip")
    elif brw.sha256(owp_zip) == before:
        log.info("the OWP zip hasn't changed since the last download")
    else:
        log.info("the OWP zip has changed since the last download")
    if refresh_blockgroups or not blockgroups.exists():
        count = brw.download_blockgroups(session, blockgroups)
        log.info("%d block groups saved to %s", count, blockgroups)
    return owp_zip, blockgroups


def run(  # noqa: PLR0913
    contact: str | None,
    *,
    max_age_days: float | None,
    refresh_blockgroups: bool = False,
    scrape: bool = True,
    prune: bool = False,
    download_dir: Path = brw.DOWNLOAD_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    docs_dir: Path = build_dashboard.DOCS_DIR,
) -> None:
    """Run every step, stopping at the first one that fails.

    Args:
        contact: Contact address for the User-Agent header, or None.
        max_age_days: The scrapers refetch cached pages older than this.
        refresh_blockgroups: Download the CDPHE block groups even if saved.
        scrape: Run the two scrapers and rebuild the pages.  False stops
            after the ECMC table.
        prune: Delete cached pages for wells no longer on the list.
        download_dir: Where the source downloads are kept.
        out_dir: Folder for the output CSVs and page caches.
        docs_dir: Folder for the dashboard and the map.
    """
    log.info("step 1 of 5: checking the sources")
    owp_zip, blockgroups = refresh_sources(
        contact, download_dir, refresh_blockgroups=refresh_blockgroups
    )

    log.info("step 2 of 5: building %s", DEFAULT_WELL_LIST.name)
    previous = (
        read_well_list(DEFAULT_WELL_LIST) if DEFAULT_WELL_LIST.is_file() else None
    )
    sources = {"owp": brw.OWP_URL, "blockgroups": brw.CDPHE_LAYER_URL}
    rows = brw.build(owp_zip, blockgroups, DEFAULT_WELL_LIST, sources)
    apis = [str(row["API_10"]) for row in rows]
    log_list_changes(previous, apis)

    log.info("step 3 of 5: writing %s", owp2csv.DEFAULT_OUT.name)
    owp2csv.convert(owp_zip, out_dir / owp2csv.DEFAULT_OUT.name)

    if scrape:
        log.info("step 4 of 5: scout cards, then bradenhead tests")
        cogis_scraper.run(DEFAULT_WELL_LIST, out_dir, contact, max_age_days)
        bradenhead_scraper.run(DEFAULT_WELL_LIST, out_dir, contact, max_age_days)
        log.info("step 5 of 5: building the dashboard and the map")
        build_dashboard.run(
            contact,
            download_dir=download_dir,
            well_list=DEFAULT_WELL_LIST,
            op_dir=out_dir,
            out_dir=docs_dir,
        )
    else:
        log.info("step 4 of 5: scrapers skipped")
        log.info("step 5 of 5: dashboard and map skipped along with the scrapers")

    if prune:
        for name in CACHE_DIRS:
            removed = prune_cache(out_dir / name, apis)
            log.info("pruned %d pages from %s", len(removed), name)


def main(argv: list[str] | None = None) -> int:
    """Refresh everything from the command line and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--contact",
        help=f"contact address for the User-Agent header (default: ${CONTACT_ENV})",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=DEFAULT_MAX_AGE_DAYS,
        help="refetch cached pages older than this many days (default: 30)",
    )
    parser.add_argument(
        "--refresh-blockgroups",
        action="store_true",
        help="download the CDPHE block groups again",
    )
    parser.add_argument(
        "--prune-cache",
        action="store_true",
        help="delete cached pages for wells no longer on the list",
    )
    parser.add_argument(
        "--skip-scrapers",
        action="store_true",
        help="stop after the ranked list and the ECMC table; no scrapers, no pages",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log more detail")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    run(
        resolve_contact(args.contact),
        max_age_days=args.max_age_days,
        refresh_blockgroups=args.refresh_blockgroups,
        scrape=not args.skip_scrapers,
        prune=args.prune_cache,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
