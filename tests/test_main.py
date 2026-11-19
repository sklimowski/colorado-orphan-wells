"""Tests for main.py, with every download and scraper replaced by a stub."""

import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

import bradenhead_scraper
import build_dashboard
import build_ranked_wells as brw
import cogis_scraper
import main
from conftest import owp_row, owp_zip

# The wells the stubbed OWP download returns; tests change it between runs.
WELLS = ["001-00001"]

BLOCKGROUPS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "GEOID": "080010000001",
                "Cnt_N": "Adams",
                "ES_S_": 50.0,
                **dict.fromkeys(brw.DI_CRITERIA, 0),
                "D_I_C": 0,
                "DIType": "N/A",
                "Ttl_P": 1000.0,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-104.9, 39.7],
                        [-104.89, 39.7],
                        [-104.89, 39.71],
                        [-104.9, 39.71],
                        [-104.9, 39.7],
                    ]
                ],
            },
        }
    ],
}


@pytest.fixture
def stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Replace downloads and scrapers with stubs that log their calls."""
    calls: list[tuple[str, Any]] = []

    def download_owp(_session: object, dest: Path, **_: object) -> None:
        calls.append(("owp", dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(owp_zip([owp_row(api, "39.705", "-104.895") for api in WELLS]))

    def download_blockgroups(_session: object, dest: Path, **_: object) -> int:
        calls.append(("blockgroups", dest))
        dest.write_text(json.dumps(BLOCKGROUPS), encoding="utf-8")
        return 1

    def scraper(name: str) -> Any:  # noqa: ANN401
        def run(*args: object) -> None:
            calls.append((name, args))

        return run

    monkeypatch.setattr(brw, "download_owp", download_owp)
    monkeypatch.setattr(brw, "download_blockgroups", download_blockgroups)
    monkeypatch.setattr(cogis_scraper, "run", scraper("cogis"))
    monkeypatch.setattr(bradenhead_scraper, "run", scraper("bradenhead"))

    def dashboard(_contact: object, **kwargs: object) -> None:
        calls.append(("dashboard", kwargs))

    monkeypatch.setattr(build_dashboard, "run", dashboard)
    monkeypatch.setattr(main, "DEFAULT_WELL_LIST", tmp_path / "ip" / "ranked.csv")
    monkeypatch.setattr(sys.modules[__name__], "WELLS", ["001-00001"])
    return calls


def run_main(tmp_path: Path, **kwargs: Any) -> None:  # noqa: ANN401
    main.run(
        "a@example.org",
        max_age_days=30.0,
        download_dir=tmp_path / "downloads",
        out_dir=tmp_path / "op",
        docs_dir=tmp_path / "docs",
        **kwargs,
    )


def test_runs_every_step_in_order(tmp_path: Path, stubs: list[tuple[str, Any]]) -> None:
    run_main(tmp_path)
    assert [name for name, _ in stubs] == [
        "owp",
        "blockgroups",
        "cogis",
        "bradenhead",
        "dashboard",
    ]
    ranked = tmp_path / "ip" / "ranked.csv"
    assert ranked.is_file()
    assert (tmp_path / "op" / "ecmc_unplugged_orphan_wells.csv").is_file()
    assert stubs[2][1] == (ranked, tmp_path / "op", "a@example.org", 30.0)
    assert stubs[4][1] == {
        "download_dir": tmp_path / "downloads",
        "well_list": ranked,
        "op_dir": tmp_path / "op",
        "out_dir": tmp_path / "docs",
    }


def test_block_groups_are_reused_unless_refresh_is_asked(
    tmp_path: Path, stubs: list[tuple[str, Any]]
) -> None:
    run_main(tmp_path, scrape=False)
    run_main(tmp_path, scrape=False)
    assert [name for name, _ in stubs] == ["owp", "blockgroups", "owp"]
    run_main(tmp_path, scrape=False, refresh_blockgroups=True)
    assert [name for name, _ in stubs][-2:] == ["owp", "blockgroups"]


def test_reports_whether_the_owp_zip_changed(
    tmp_path: Path, stubs: list[tuple[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    run_main(tmp_path, scrape=False)
    run_main(tmp_path, scrape=False)
    assert "hasn't changed" in caplog.text
    assert "has changed" not in caplog.text


def test_skip_scrapers_stops_after_the_ecmc_table(
    tmp_path: Path, stubs: list[tuple[str, Any]]
) -> None:
    run_main(tmp_path, scrape=False)
    names = [name for name, _ in stubs]
    assert "cogis" not in names
    assert "dashboard" not in names


def test_logs_wells_added_and_removed(
    tmp_path: Path,
    stubs: list[tuple[str, Any]],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO)
    run_main(tmp_path, scrape=False)
    assert "no earlier well list" in caplog.text
    run_main(tmp_path, scrape=False)
    assert "well list unchanged: 1 wells" in caplog.text
    monkeypatch.setattr(sys.modules[__name__], "WELLS", ["001-00002", "001-00003"])
    run_main(tmp_path, scrape=False)
    assert "2 added, 1 removed, 2 wells now" in caplog.text
    assert "added: 05-001-00002, 05-001-00003" in caplog.text
    assert "removed: 05-001-00001" in caplog.text


def test_api_summary_is_capped() -> None:
    apis = [f"05-001-{n:05d}" for n in range(main.SHOW_APIS + 3)]
    assert main._api_summary(apis).endswith(", and 3 more")


def test_prune_cache_runs_only_when_asked(
    tmp_path: Path, stubs: list[tuple[str, Any]]
) -> None:
    pages = [tmp_path / "op" / d / "00199999.html" for d in main.CACHE_DIRS]
    keep = tmp_path / "op" / "html_cache" / "00100001.html"
    for page in [*pages, keep]:
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("x", encoding="utf-8")
    run_main(tmp_path, scrape=False)
    assert all(p.exists() for p in pages)
    run_main(tmp_path, scrape=False, prune=True)
    assert not any(p.exists() for p in pages)
    assert keep.exists()
