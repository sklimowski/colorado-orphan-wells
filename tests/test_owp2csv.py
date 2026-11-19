"""Tests for owp2csv.py, run against small OWP zips built in the tests."""

import csv
from pathlib import Path

import pytest

import owp2csv
from conftest import OWP_FIELDS, owp_row, owp_zip

# The full set of fields the ECMC table keeps, as the shapefile names them.
FIELDS = (
    *OWP_FIELDS,
    ("SiteID", 10),
    ("TypeID", 20),
    ("TankBatter", 40),
    ("Loc_Source", 10),
)


def write_zip(tmp_path: Path) -> Path:
    """An OWP zip with two unplugged wells and one plugged well."""
    extra = {"SiteID": "319645", "TypeID": "Location ID", "Loc_Source": "Well"}
    rows = [
        owp_row("001-06072", "39.9443", "-104.12469")
        | extra
        | {"TankBatter": "Same as Well (on-site)"},
        owp_row("001-06084", "39.96221", "-104.13462", status="Plugged") | extra,
        owp_row("123-09299", "40.325253", "-104.717761") | extra,
    ]
    path = tmp_path / "OWP_SHP.zip"
    path.write_bytes(owp_zip(rows, FIELDS))
    return path


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV written by owp2csv."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_writes_unplugged_wells_in_file_order(tmp_path: Path) -> None:
    out = tmp_path / "wells.csv"
    assert owp2csv.convert(write_zip(tmp_path), out) == 2
    rows = read_rows(out)
    assert list(rows[0]) == list(owp2csv.COLUMNS)
    assert [r["APInumber"] for r in rows] == ["001-06072", "123-09299"]


def test_restores_the_truncated_tank_battery_name(tmp_path: Path) -> None:
    out = tmp_path / "wells.csv"
    owp2csv.convert(write_zip(tmp_path), out)
    rows = read_rows(out)
    assert rows[0]["TankBattery"] == "Same as Well (on-site)"
    assert rows[1]["TankBattery"] == ""


def test_main_takes_paths_on_the_command_line(tmp_path: Path) -> None:
    out = tmp_path / "op" / "wells.csv"
    assert owp2csv.main([str(write_zip(tmp_path)), str(out)]) == 0
    assert len(read_rows(out)) == 2


def test_main_explains_a_missing_zip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        owp2csv.main([str(tmp_path / "missing.zip"), str(tmp_path / "w.csv")])
    assert "build_ranked_wells.py" in capsys.readouterr().err
