#!/usr/bin/env python3
"""Write ECMC's unplugged orphan well list from OWP_SHP.ZIP to CSV.

ECMC publishes its Orphaned Well Program records as a shapefile in
OWP_SHP.ZIP.  The records with OWPStatus "Unplugged" are the unplugged orphan
well list, one row per well.  This script writes those records with the
columns ECMC's map service used for the same list, in file order.  The
shapefile's site-level fields (counts, priority, basin) are blank on well
records and are left out.

build_ranked_wells.py downloads the zip to ip/downloads/, and main.py runs
both.

Usage:
    python owp2csv.py [OWP_SHP.zip] [output.csv]
"""

import argparse
import logging
import sys
from pathlib import Path

from build_ranked_wells import DOWNLOAD_DIR, OWP_FILE, read_owp_records
from common import REPO_ROOT, configure_logging, write_csv

log = logging.getLogger(__name__)

DEFAULT_IN = DOWNLOAD_DIR / OWP_FILE
DEFAULT_OUT = REPO_ROOT / "op" / "ecmc_unplugged_orphan_wells.csv"

COLUMNS = (
    "ProjName",
    "WellName",
    "SiteID",
    "TypeID",
    "APInumber",
    "TankBattery",
    "Surface",
    "Minerals",
    "Latitude",
    "Longitude",
    "Loc_Source",
)
# dBASE caps field names at 10 characters, so the shapefile truncates this one.
RENAMED = {"TankBatter": "TankBattery"}


def convert(zip_path: Path, csv_path: Path) -> int:
    """Write one CSV row per unplugged well in an OWP_SHP.ZIP.

    Args:
        zip_path: ECMC's OWP_SHP.ZIP.
        csv_path: The CSV to write.  Its folder is created if needed.

    Returns:
        The number of rows written.
    """
    records = read_owp_records(zip_path.read_bytes())
    rows = [{RENAMED.get(k, k): v for k, v in r.items()} for r in records]
    write_csv(csv_path, COLUMNS, rows)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    """Run the conversion from the command line and return an exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "zip_path",
        nargs="?",
        type=Path,
        default=DEFAULT_IN,
        help="ECMC's OWP_SHP.ZIP (default: ip/downloads/OWP_SHP.zip)",
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=DEFAULT_OUT,
        help="CSV to write (default: op/ecmc_unplugged_orphan_wells.csv)",
    )
    args = parser.parse_args(argv)
    configure_logging()
    if not args.zip_path.exists():
        parser.error(
            f"{args.zip_path} not found; run build_ranked_wells.py or main.py "
            "to download it"
        )
    count = convert(args.zip_path, args.csv_path)
    log.info("%d wells written to %s", count, args.csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
