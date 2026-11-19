"""End-to-end regression tests against the committed outputs.

Each test reruns a script over the saved inputs in a temp folder and checks
that it reproduces the committed file byte for byte.  That's the check every
refactor has to pass: the committed outputs are exactly what the code
produces from its inputs.  A change that's meant to alter outputs (a
methodology fix) regenerates them in the same commit, so these tests still
pass.

The inputs aren't in the repo, so each test skips when its inputs are
missing:

- The ranked list and the ECMC table need the two downloads in ip/downloads/,
  and only run when their checksums match the ones recorded in
  ip/CO_Orphan_Wells_EJ_Ranked_Wells.sources.json.  A newer download means
  the committed files are due for a refresh (python main.py), not a failure.
- The dashboard and map test needs those downloads too, plus the two Leaflet
  files build_dashboard.py saves there, matching their pinned hashes, and the
  Census county zip, holding the shapefile docs/dashboard.sources.json records.
- The scraper tests need complete page caches in op/html_cache and
  op/bradenhead_cache.  The scrapers only fetch wells missing from the cache,
  so with a complete cache these tests make no network requests.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import bradenhead_scraper
import build_dashboard
import build_ranked_wells
import cogis_scraper
import owp2csv
from common import DEFAULT_WELL_LIST, facility_id, read_well_list
from conftest import REPO_ROOT

OP = REPO_ROOT / "op"
WELL_LIST = DEFAULT_WELL_LIST
MANIFEST = WELL_LIST.with_suffix(".sources.json")


def require_downloads() -> tuple[Path, Path]:
    """Return the saved downloads, or skip if they don't match the manifest."""
    if not MANIFEST.is_file():
        pytest.skip(f"{MANIFEST.name} not present")
    sources = json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]
    owp = build_ranked_wells.DOWNLOAD_DIR / build_ranked_wells.OWP_FILE
    bg = build_ranked_wells.DOWNLOAD_DIR / build_ranked_wells.BLOCKGROUP_FILE
    pairs = [
        (owp, sources["ecmc_owp_shapefile"]["sha256"]),
        (bg, sources["cdphe_enviroscreen_v2_blockgroups"]["sha256"]),
    ]
    for path, expected in pairs:
        if not path.is_file():
            pytest.skip(f"ip/downloads/{path.name} not present")
        if build_ranked_wells.sha256(path) != expected:
            pytest.skip(f"ip/downloads/{path.name} is newer than the committed list")
    return owp, bg


def require_full_cache(name: str) -> Path:
    """Return the cache folder, or skip if it's missing or incomplete.

    An incomplete cache would make the scraper fetch from ECMC, which a test
    run should never do.
    """
    cache = OP / name
    if not cache.is_dir():
        pytest.skip(f"op/{name} not present")
    if not WELL_LIST.is_file():
        pytest.skip(f"{WELL_LIST.name} not present")
    for api in read_well_list(WELL_LIST):
        if not (cache / f"{facility_id(api)}.html").is_file():
            pytest.skip(f"op/{name} is incomplete; a run would fetch from ECMC")
    return cache


def assert_same_bytes(produced: Path, committed: Path) -> None:
    assert produced.read_bytes() == committed.read_bytes(), (
        f"{produced.name} differs from the committed copy"
    )


@pytest.mark.slow
def test_cogis_scraper_reproduces_committed_output(tmp_path: Path) -> None:
    # Copy with timestamps kept: fetched_at comes from the cache file times.
    shutil.copytree(require_full_cache("html_cache"), tmp_path / "html_cache")
    cogis_scraper.run(WELL_LIST, tmp_path, contact=None)
    for name in (
        "cogis_scout_data.csv",
        "cogis_casing.csv",
        "cogis_additional_cement.csv",
    ):
        assert_same_bytes(tmp_path / name, OP / name)


@pytest.mark.slow
def test_bradenhead_scraper_reproduces_committed_output(tmp_path: Path) -> None:
    cache = require_full_cache("bradenhead_cache")
    shutil.copytree(cache, tmp_path / "bradenhead_cache")
    bradenhead_scraper.run(WELL_LIST, tmp_path, contact=None)
    for name in ("bradenhead_tests.csv", "bradenhead_summary.csv"):
        assert_same_bytes(tmp_path / name, OP / name)


def test_build_reproduces_committed_ranked_list(tmp_path: Path) -> None:
    owp, bg = require_downloads()
    out = tmp_path / WELL_LIST.name
    build_ranked_wells.build(owp, bg, out, {"owp": "", "blockgroups": ""})
    assert_same_bytes(out, WELL_LIST)


def test_owp2csv_reproduces_committed_output(tmp_path: Path) -> None:
    owp, _ = require_downloads()
    name = "ecmc_unplugged_orphan_wells.csv"
    owp2csv.convert(owp, tmp_path / name)
    assert_same_bytes(tmp_path / name, OP / name)


def test_build_dashboard_reproduces_committed_pages(tmp_path: Path) -> None:
    _, bg = require_downloads()
    leaflet = {}
    for name, expected in build_dashboard.LEAFLET_FILES.items():
        version = build_dashboard.LEAFLET_VERSION
        path = build_ranked_wells.DOWNLOAD_DIR / f"leaflet-{version}-{name}"
        if not path.is_file():
            pytest.skip(f"ip/downloads/{path.name} not present")
        if build_dashboard._sri(path.read_bytes()) != expected:
            pytest.skip(f"ip/downloads/{path.name} doesn't match its pinned hash")
        leaflet[name] = path
    counties = build_ranked_wells.DOWNLOAD_DIR / build_dashboard.COUNTY_FILE
    if not counties.is_file():
        pytest.skip(f"ip/downloads/{counties.name} not present")
    manifest = build_dashboard.DOCS_DIR / build_dashboard.MANIFEST_FILE
    recorded = json.loads(manifest.read_text(encoding="utf-8"))["county_boundaries"]
    members = build_dashboard.county_members(counties.read_bytes())
    for suffix, data in members.items():
        if hashlib.sha256(data).hexdigest() != recorded["sha256"][suffix]:
            pytest.skip(f"the {suffix} in ip/downloads/{counties.name} has changed")
    inputs = build_dashboard.Inputs(
        well_list=WELL_LIST,
        op_dir=OP,
        blockgroups=bg,
        counties=counties,
        leaflet_js=leaflet["leaflet.js"],
        leaflet_css=leaflet["leaflet.css"],
    )
    build_dashboard.build(inputs, tmp_path)
    for name in (build_dashboard.DASHBOARD_FILE, build_dashboard.MAP_FILE):
        assert_same_bytes(tmp_path / name, build_dashboard.DOCS_DIR / name)
