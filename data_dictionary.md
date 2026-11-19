# Data dictionary

Column definitions for the committed tables: the six CSVs in `op/` and the ranked well list in `ip/`.  All files are UTF-8 CSV with a header row.  Every table except `ecmc_unplugged_orphan_wells.csv` joins on `API_10`.

Values from ECMC pages are kept as the pages show them.  A blank cell means the source left the field empty or the scraper couldn't find the label on the page.  It never means zero.  Units are feet (ft), inches (in), and pounds per square inch (psi), as ECMC reports them.  Dates read from COGIS pages keep ECMC's M/D/YYYY text.  Dates the scripts add are ISO dates (YYYY-MM-DD) in UTC.

## Common key

| Column | Type | Description |
|---|---|---|
| `API_10` | text | API number in `05-CCC-SSSSS` form: `05` for Colorado, a 3 digit county code, and a 5 digit sequence.  See the README's API number formats section for how it maps to ECMC's `APInumber` and to COGIS URLs. |

## op/ecmc_unplugged_orphan_wells.csv

One row per unplugged orphan well, written by `owp2csv.py` from the records in ECMC's `OWP_SHP.ZIP` whose `OWPStatus` is `Unplugged`.  Columns keep ECMC's names.

| Column | Type | Description |
|---|---|---|
| `ProjName` | text | ECMC Orphaned Well Program project the well belongs to. |
| `WellName` | text | Well name as ECMC lists it. |
| `SiteID` | text | ECMC site identifier for the well's location. |
| `TypeID` | text | What `SiteID` identifies.  `Location ID` on every current record. |
| `APInumber` | text | API number in `CCC-SSSSS` form.  Prefix with `05-` to get `API_10`. |
| `TankBattery` | text | ECMC's note on where the well's tank battery sits, for example `Same as Well (on-site)`, `None`, or `Site ID 476137 (off-site)`.  Kept as written, including ECMC's placeholder `Site ID xyz (off-site)` on some records.  The shapefile truncates the field name to `TankBatter`; the script restores it. |
| `Surface` | text | Surface ownership: `Fee`, `State`, or `Federal` on current records. |
| `Minerals` | text | Mineral ownership: `Fee`, `State`, or `Federal` on current records. |
| `Latitude` | decimal | Latitude in decimal degrees, NAD83, as ECMC publishes it. |
| `Longitude` | decimal | Longitude in decimal degrees, NAD83, as ECMC publishes it. |
| `Loc_Source` | text | What the coordinates locate.  `Well` on every current record. |

## op/cogis_scout_data.csv

One row per well, parsed by `cogis_scraper.py` from the COGIS scout card (facility detail page).  Wells whose page couldn't be retrieved keep a row with `fetched` set to `False` and the parsed fields blank.

| Column | Type | Description |
|---|---|---|
| `API_10` | text | See Common key. |
| `fetched` | flag | `True` when a scout card was retrieved, otherwise `False`. |
| `fetched_at` | date | UTC date the scout card was saved, from the cached file's timestamp. |
| `well_status` | text | Two letter COGIS status code from the `Status:` line, for example `SI` (shut in), `PR` (producing), or `TA` (temporarily abandoned).  ECMC's code list governs.  The scout card status can differ from the well's place on the unplugged orphan list; a few wells on the list show `PA` here. |
| `status_date` | date | Date that follows the status code. |
| `spud_date` | date | Spud date. |
| `completion_date` | date | Completion date. |
| `measured_td_ft` | integer | Measured total depth, ft.  Thousands separators removed. |
| `vertical_td_ft` | integer | True vertical total depth, ft. |
| `pb_depth_ft` | integer | Measured plugback depth, ft.  `0` means the card lists 0, not that the field is blank. |
| `elevation_ft` | integer | Elevation, ft, as the card lists it. |
| `n_casing_strings` | integer | Casing strings run in the well: records with `citings_type` ACTUAL or HISTORICAL and `is_casing_string` Y in `cogis_casing.csv`. |
| `n_planned_casing_strings` | integer | Planned casing strings from the drilling permit: records with `citings_type` PLANNED and `is_casing_string` Y. |
| `surf_casing_size_in` | decimal | Outside diameter of the deepest run surface (`SURF`) string, in. |
| `surf_casing_depth_ft` | integer | Set depth of the deepest run surface string, ft.  Blank when the card lists no run surface string with a depth. |
| `n_additional_cement` | integer | Number of rows for the well in `cogis_additional_cement.csv`. |
| `related_links` | text | Links on the scout card to other COGIS inquiry pages for the well (bradenhead, MIT, or integrity), as relative URLs, sorted and joined with `; `. |

## op/cogis_casing.csv

One row per casing record on the scout card, in page order, with the cement record that follows it.  Written by `cogis_scraper.py`.

| Column | Type | Description |
|---|---|---|
| `API_10` | text | See Common key. |
| `seq` | integer | Order of the record on the page, starting at 1 for each well. |
| `section` | text | `permit` for records under the Wellbore Permit heading, `completed` for records under Wellbore Completed. |
| `citings_type` | text | ECMC's citings type: `PLANNED` (from the permit), `ACTUAL`, or `HISTORICAL`.  Filter on `ACTUAL` or `HISTORICAL` for casing actually run. |
| `string_type` | text | ECMC's string type, for example `CONDUCTOR`, `SURF`, `1ST`, `2ND`, `1ST LINER`, `OPEN HOLE`, `STAGE TOOL`, or `S.C. 1.1`. |
| `is_casing_string` | flag | `Y` for a string of pipe.  `N` for `OPEN HOLE`, `STAGE TOOL`, and records whose type starts with `S.C.`, which read as cement stages on an existing string.  `N` records don't count toward the scout data string totals. |
| `hole_size_in` | decimal | Hole diameter, in. |
| `casing_size_in` | decimal | Casing outside diameter, in. |
| `top_ft` | integer | Top of the casing, ft. |
| `depth_ft` | integer | Setting depth (bottom) of the casing, ft. |
| `weight` | text | Casing weight as written, which can hold more than one value (for example `15.5,17` or `14 & 15.5`). |
| `cement_sacks` | integer | Sacks of cement in the cement record that follows the casing record. |
| `cement_top_ft` | integer | Top of cement, ft. |
| `cement_bottom_ft` | integer | Bottom of cement, ft. |
| `cement_method` | text | ECMC's Determination Method for the cement top, for example `CBL` (cement bond log), `CALC` (calculated), or `VISU` (visual).  Kept as entered, including lower case and a few casing grades (such as `H-40`) that operators entered in this field.  PLANNED records carry no method. |

## op/cogis_additional_cement.csv

One row per Additional Cement record on the scout card, in page order.  Written by `cogis_scraper.py`.

| Column | Type | Description |
|---|---|---|
| `API_10` | text | See Common key. |
| `seq` | integer | Order of the record on the page, starting at 1 for each well. |
| `string_type` | text | String the cement was placed on, using the same types as `cogis_casing.csv`. |
| `top_ft` | integer | Top of the cemented interval, ft. |
| `depth_ft` | integer | Depth field as ECMC lists it, ft. |
| `bottom_ft` | integer | Bottom of the cemented interval, ft. |
| `sacks` | integer | Sacks of cement. |
| `method` | text | Placement method as written, for example `SQUEEZE`, `STAGE`, `PERF`, or `DV`.  Some records hold `1`; it's kept as entered. |

## op/bradenhead_tests.csv

One row per test on the COGIS bradenhead page, in page order, written by `bradenhead_scraper.py`.  The sixteen page columns are kept as text, as the page shows them, with HTML entities decoded.  ECMC's `--` means blank.

| Column | Type | Description |
|---|---|---|
| `API_10` | text | See Common key. |
| `doc_number` | text | Form 17 document number.  Full and Light records have none on the page, so this holds the record ID from their detail link instead. |
| `report_type` | text | `Form 17`, `Full`, or `Light`. |
| `test_date` | date | Date of the test. |
| `submit_date` | date | Date the report was submitted. |
| `well_status` | text | Well status reported with the test, for example `SHUT-IN`, `FLOWING`, or `PUMPING`.  Case varies between records. |
| `initial_surf_casing_psi` | text | Surface casing (bradenhead) pressure at the start of the test, psi.  Can hold `TSTM`, too small to measure. |
| `bh_flow_start` | text | Bradenhead flow code at the start of the test: `NO FLOW`, `DOWN TO 0`, `WHISPER`, `SURGE`, `CONTINUOUS`, `WATER H20`, or `GAS`.  Full records write `Down to Zero` and mixed case. |
| `fluid_type` | text | Fluid observed, for example `NONE`, `GAS`, `VAPOR`, `WATER H20`, or `LIQUID HYDROCARBON`. |
| `end_surf_casing_psi` | text | Surface casing pressure at the end of the test, psi. |
| `bh_flow_end` | text | Bradenhead flow code at the end of the test, same codes as `bh_flow_start`. |
| `initial_prod_casing_psi` | text | Production casing pressure at the start of the test, psi. |
| `end_prod_casing_psi` | text | Production casing pressure at the end of the test, psi. |
| `sample_taken` | text | `Yes` or `No`. |
| `gas_analysis` | text | Gas analysis column as shown. |
| `liquid_analysis` | text | Liquid analysis column as shown. |
| `comments` | text | Operator comments. |

## op/bradenhead_summary.csv

One row per well on the list, including wells with no bradenhead history, written by `bradenhead_scraper.py`.  The latest test is the one with the latest test date, then the later submit date, then the higher document number.  The README's Bradenhead flow indicators section explains the flags and classes and their limits.

| Column | Type | Description |
|---|---|---|
| `API_10` | text | See Common key. |
| `bh_fetched_at` | date | UTC date the bradenhead page was saved, from the cached file's timestamp.  Blank if the page wasn't retrieved. |
| `bh_test_count` | integer | Number of tests on file.  `0` for wells with no history. |
| `bh_first_test_date` | date | Earliest test date. |
| `bh_last_test_date` | date | Latest test date. |
| `bh_last_flow_start` | text | Latest test's start flow code, as shown. |
| `bh_last_flow_end` | text | Latest test's end flow code, as shown. |
| `bh_last_end_surf_casing_psi` | text | Latest test's end surface casing pressure, as shown. |
| `bh_last_fluid` | text | Latest test's fluid type, as shown. |
| `bh_max_surf_casing_psi` | integer | Highest numeric start or end surface casing pressure across all tests, rounded half up to whole psi.  `TSTM` and other text readings are left out.  Blank when no test has a numeric reading. |
| `bh_any_flow_observed` | flag | `Y` if any test shows a start or end flow code other than No Flow, including Down to 0. |
| `bh_liquid_flow` | flag | `Y` if any test shows water in a flow field, or water or liquid hydrocarbon as the fluid type. |
| `bh_flow_at_end` | flag | `Y` if any test ends with a flow code other than No Flow or Down to 0. |
| `bh_not_bled_to_zero` | flag | `Y` if any test ends with surface casing pressure above 0 psi, or `TSTM`. |
| `bh_pressure_rebuild` | flag | `Y` if a test that ended at 0 psi is followed by a test that started above 0 psi or at `TSTM`. |
| `bh_flow_class_rank` | integer | Rank, 1 to 7, of `bh_flow_class`, for sorting. |
| `bh_flow_class` | text | First class the well's tests meet, in rank order: `liquid flow`, `pressure persists or rebuilds`, `flow at end of test`, `flow bled off`, `no flow`, `flow not reported`, `no tests on file`. |
| `bh_flow_class_latest_rank` | integer | Rank of `bh_flow_class_latest`. |
| `bh_flow_class_latest` | text | Same classes applied to the latest test alone, with rebuild judged from the last two tests. |

Each flag is `Y`, `N`, or `U`.  `U` means the records can't answer the question, for example because the flow fields are blank or the well has only one test.  Flags are blank for wells with no tests.  The order of the classes is a convention of this dataset, not an ECMC ranking, and no class is an ECMC compliance finding.

## ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv

One row per unplugged orphan well, written by `build_ranked_wells.py` and sorted by `Rank`.  The scoring is described in the README's Ranked well list section.  `ip/CO_Orphan_Wells_EJ_Ranked_Wells.sources.json` records the sources, retrieval times, record counts, and checksums behind each build.

| Column | Type | Description |
|---|---|---|
| `Rank` | integer | Order by `Priority_Score`, highest first, with ties broken by API number. |
| `Tier` | integer | 1 for a score of 55 and above, 2 from 45 to 54.9, 3 from 30 to 44.9, 4 below 30. |
| `Priority_Score` | decimal | Sum of the three score parts, 0 to 100, to one decimal. |
| `API_10` | text | See Common key. |
| `WellName` | text | Well name from ECMC's list. |
| `Project` | text | ECMC Orphaned Well Program project. |
| `County` | text | County name, from the county code in the API number. |
| `Lat` | decimal | Latitude as ECMC publishes it, NAD83. |
| `Lon` | decimal | Longitude as ECMC publishes it, NAD83. |
| `Surface` | text | Surface ownership from ECMC's list. |
| `Minerals` | text | Mineral ownership from ECMC's list. |
| `DI_Community_Nov2024` | text | `Yes` when the well's census block group is a Disproportionately Impacted community under CDPHE's November 2024 designation, otherwise `No`. |
| `DI_Type` | text | CDPHE's `DIType` for DI wells, for example `Low-income population above 40%` or `More than one category`.  Blank for non-DI wells. |
| `DI_Criteria_Count` | integer | Number of the seven DI criteria the block group meets.  Blank for non-DI wells. |
| `EnviroScreen2_Pctl` | decimal | CDPHE EnviroScreen 2.0 statewide percentile for the block group, to one decimal. |
| `BG_GEOID` | text | 12 digit census block group ID containing the well. |
| `BG_Pop` | integer | Block group total population, CDPHE's `Ttl_P`. |
| `BG_PopDensity_km2` | decimal | Block group population per km², with area computed from the polygon on an equal-area sphere, to one decimal. |
| `Cluster_Size_5km` | integer | Wells in the same OWP project within 5 km, the well itself included. |
| `Score_Community` | decimal | Community burden part, 0 to 40. |
| `Score_Exposure` | decimal | Population exposure part, 0 to 30. |
| `Score_Deliverability` | decimal | Deliverability part, 0 to 30: project clustering plus jurisdiction. |
| `Boundary_Flag` | text | `DI edge <300m` for a DI well within 300 m of a non-DI block group, `near DI <300m` for a non-DI well within 300 m of a DI block group, otherwise blank. |

Block group columns are blank for a well that falls outside every block group.  The score is Subsurface Risk Analytics' method for this dataset.  ECMC sets its own plugging priorities.
