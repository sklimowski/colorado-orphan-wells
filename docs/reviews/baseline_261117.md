# Output baseline, 2026-11-17

Snapshot of the committed outputs in `op/` before any code changes.  A refactor should reproduce these hashes exactly when run against the same HTML cache, or explain every difference in its commit message.

## Files

| File | Rows | SHA-256 |
|---|---|---|
| `bradenhead_summary.csv` | 1,396 | `d6c0bc1171e350edfc4714dd79a84079baeaec59d4f14c899e4c700f645f04a4` |
| `bradenhead_tests.csv` | 3,546 | `e9a0a547c612ac06ec74cb1d8c49292c0e717ff8f1194659c1cf49b88af47142` |
| `cogis_scout_data.csv` | 1,396 | `b5908843afbcd4b7f4d1b9eb79958d4c217a74a88f59a675f4c5b79ced827afd` |
| `ecmc_unplugged_orphan_wells.csv` | 1,396 | `147af3e9078b57ccb6ab9fb032100b14ab26dc51cfd6232ceeec00f47e7c69d7` |

## Blank counts

`cogis_scout_data.csv`: `API_10` 0, `fetched` 0, `well_status` 0, `status_date` 0, `spud_date` 304, `completion_date` 92, `measured_td_ft` 37, `vertical_td_ft` 682, `pb_depth_ft` 137, `elevation_ft` 22, `n_casing_strings` 0 (138 are `0`), `casing_strings` 138, `cement` 597, `related_links` 0.

`bradenhead_summary.csv`: `bh_test_count` 0 (294 are `0`), `bh_last_test_date` 294, `bh_last_flow_end` 313, `bh_last_end_surf_casing_psi` 294, `bh_last_fluid` 295, `bh_ever_flow` 294, `bh_max_surf_casing_psi` 294.

`ecmc_unplugged_orphan_wells.csv`: `TankBattery` 612, all other columns 0.

## Distinct values

`bh_flow_start`: NO FLOW 2,284; WHISPER 510; DOWN TO 0 373; CONTINUOUS 206; WATER H20 97; Down to Zero 64; SURGE 5; GAS 3; blank 2; Whisper 1; Continuous 1.

`bh_flow_end`: NO FLOW 2,507; DOWN TO 0 440; WHISPER 196; blank 167; CONTINUOUS 138; Down to Zero 66; WATER H20 28; SURGE 3; VAPOR 1.

`fluid_type`: `--` 2,259; NONE 1,206; GAS 73; WATER H20 3; blank 2; LIQUID HYDROCARBON 1; GAS AND VAPOR 1; VAPOR 1.

Test `well_status`: SHUT-IN 1,432; blank 779; FLOWING 398; PUMPING 319; PLUNGER LIFT 247; INJECTION 157; CLOCK/INTERMITTER 145; Plunger Lift 20; Flowing 17; Shut-In 14; Pumping 12; GAS LIFT 3; Gas Lift 2; Clock/Intermitter 1.

Scout `well_status`: SI 768; PR 436; TA 82; IJ 39; PA 29; AB 25; AC 13; WO 3; DG 1.

`bh_ever_flow`: N 573; Y 529; blank 294.

## Cache status

`op/html_cache` and `op/bradenhead_cache` were copied from the archive on 2026-11-17 with file dates preserved (1,396 pages each, all dated 2026-08-05).  They're identical to the archive copies, and the archive's four CSVs have the same hashes as the ones above.

Running the current `parse_page`, `parse_tests`, and `summarize` functions over the cached pages reproduces `cogis_scout_data.csv`, `bradenhead_tests.csv`, and `bradenhead_summary.csv` byte for byte.  That makes these hashes a usable regression target for any refactor.

## Update, 2026-11-17 (BH-01)

`bradenhead_summary.csv` was regenerated with the new flags and flow class.  New SHA-256: `5106bd610d5eb684ea579adca5d241893caedd577cc019224d823650c897d7f4`.  The other three CSVs are unchanged.  The regression tests compare the code's output to whatever is committed in `op/`, so they now check against this file.

## Update, 2026-11-17 (casing and cement rewrite)

`cogis_scout_data.csv` was regenerated with new casing summary columns, and two tables were added.  New SHA-256 values:

| File | Rows | SHA-256 |
|---|---|---|
| `cogis_scout_data.csv` | 1,396 | `76cd49267a2d1547a1f0e86d792c15c78b37226303efc5382abb71f377ec6cbf` |
| `cogis_casing.csv` | 3,792 | `97ee4d006740ae0dc3a6d8869fa63b8166ee0c3bf618ad9f8188e60e16e020fe` |
| `cogis_additional_cement.csv` | 71 | `1dd5cc7aa30850785869bae61b5fe907deda40bd7d29fde041c959253b265310` |

The scalar columns of `cogis_scout_data.csv` are unchanged for all 1,396 wells.

## Update, 2026-11-17 (casing counts limited to pipe)

`cogis_scout_data.csv`: `1b3cc3ba4724a1c0482a838500c3599b9bc17a4d071a7b5999dd5b8df7b6174d`.  `cogis_casing.csv` (adds `is_casing_string`): `e331933e322349375c1cefd7227bcfe3fb03fc7a48dbcc11318659d0f4840eca`.  `cogis_additional_cement.csv` is unchanged.

## Update, 2026-11-17 (Batch 1)

| File | SHA-256 |
|---|---|
| `bradenhead_tests.csv` | `a5af3495611918b0422e01369ddbdca1722e0a3f37740e0b8815c6f50a3510d7` |
| `bradenhead_summary.csv` | `e0b429036b4295406caf936064019f53b41a8aee00ae121d44ebd7c7932ee481` |
| `cogis_scout_data.csv` | `cc406b742d3b9f03af0b1f0e5ac4cc16324325f4b4b99ee4d04156f99b64179e` |

`cogis_casing.csv`, `cogis_additional_cement.csv`, and `ecmc_unplugged_orphan_wells.csv` are unchanged.

## Update, 2026-11-17 (Batches 2 and 3)

`bradenhead_tests.csv`: `89bdaa39fdc28e7421575cb76be5742001bf8eabd9ee21f520d638a554027199` (189 `comments` cells now have HTML entities decoded).  The other five CSVs are byte-identical to the Batch 1 versions.  These are the outputs for the first commit.
