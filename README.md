# colorado-orphan-wells

Scrapers and output tables for Colorado's unplugged orphaned oil and gas wells, built from public records published by the Colorado Energy and Carbon Management Commission (ECMC).  The data supports an independent article series by Subsurface Risk Analytics on well integrity and plugging priority.  A link to the series will be added here.

The repo covers every well on ECMC's current unplugged orphan well list.  For each well it pulls the COGIS scout card (status, dates, depths, casing, and cement) and the bradenhead test history, then writes CSV files that join on a common API number.

Two pages are in `docs/`.  `dashboard.html` puts the well tables beside the Orphaned Well Program's published record: funding and spending, plugging activity, federal grants, legislation, and figures from other states, each linked to its source.  It also holds a map, a well list, and a printable sheet for each well.  `map.html` is the map on its own.  [Dashboard and map](#dashboard-and-map) describes them.

## Repository layout

```
colorado-orphan-wells/
├── main.py                  runs every step below in order
├── build_ranked_wells.py    builds the ranked well list from ECMC and CDPHE downloads
├── build_dashboard.py       builds docs/dashboard.html and docs/map.html from the tables
├── owp2csv.py               ECMC unplugged orphan well list from OWP_SHP.ZIP to CSV
├── cogis_scraper.py         COGIS scout card scraper
├── bradenhead_scraper.py    COGIS bradenhead test scraper
├── common.py                fetch, cache, and CSV helpers shared by the scripts
├── requirements.txt         runtime dependency (requests)
├── requirements-dev.txt     test, lint, and type-check tools
├── pyproject.toml           settings for ruff, mypy, and pytest
├── data_dictionary.md       column definitions for every committed table
├── ip/
│   ├── unplugged.json                                  ECMC unplugged orphan well list, August 2026
│   ├── CO_Orphan_Wells_EJ_Ranked_Wells.csv             current ranked well list (build_ranked_wells.py)
│   ├── CO_Orphan_Wells_EJ_Ranked_Wells.sources.json    sources and retrieval times for that list
│   ├── program_data.json                               published program figures, legislation, and source links (compiled by hand)
│   └── downloads/                                      source files for the build (not in the repo)
├── op/
│   ├── ecmc_unplugged_orphan_wells.csv
│   ├── cogis_scout_data.csv
│   ├── cogis_casing.csv
│   ├── cogis_additional_cement.csv
│   ├── bradenhead_tests.csv
│   └── bradenhead_summary.csv
├── web/                     page frames, scripts, and styles that build_dashboard.py inlines
├── tests/                   pytest suite and saved sample pages
└── docs/
    ├── dashboard.html           the dashboard (build_dashboard.py)
    ├── map.html                 the map on its own (build_dashboard.py)
    ├── dashboard.sources.json   checksums of the two pages and of every file they were built from
    └── ...                      review procedure and code review records
```

The scrapers also write `op/html_cache/` and `op/bradenhead_cache/`.  Those folders aren't in the repo, and a fresh run rebuilds them.

## Data sources

The current well list comes from ECMC's Orphaned Well Program shapefile, OWP_SHP.ZIP, which `main.py` downloads on every run.  [Ranked well list](#ranked-well-list) describes it and the CDPHE block group data the ranking uses.

`ip/unplugged.json` is the August 2026 list as ECMC's ArcGIS map service returned it on 2026-08-05: an Esri JSON feature set with 1,396 records.  It's kept as the source of the August snapshot.  No script reads it now, because the map service requires a sign-in token.

Scout cards come from the COGIS facility detail endpoint:

    https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=NNNNNNNN

Bradenhead test histories come from:

    https://ecmc.state.co.us/cogisdb/Incidents/bradenheadScout.aspx?api=NNNNNNNN

### API number formats

The sources write the same API number three ways.

| Where | Column | Example |
|---|---|---|
| ECMC shapefile and `ecmc_unplugged_orphan_wells.csv` | `APInumber` | `123-09299` |
| Ranked list and all scraper outputs | `API_10` | `05-123-09299` |
| COGIS URLs | `api=` | `12309299` |

The COGIS endpoints want the 8 digit county code and sequence with no dashes and no `05` state prefix.  A dashed API returns a "could Not be found" page rather than an HTTP error, so both scrapers check that a page holds real well content before caching it.  To join the ECMC list to the other tables, prefix `APInumber` with `05-`.

## Running the scripts

Requires Python 3.13 and `requests` (`pip install -r requirements.txt`).  The scripts find `ip/` and `op/` relative to their own location, so they can be run from any folder.

To refresh everything from the latest public data, run:

    python main.py --contact you@example.org

`main.py` runs these steps in order and stops at the first one that fails:

1. Downloads OWP_SHP.ZIP from ECMC and logs whether it changed since the last run.  The CDPHE block groups are downloaded only the first time, or again with `--refresh-blockgroups`, since CDPHE updates them rarely.
2. Runs `build_ranked_wells.py`, which writes `ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv`, and logs the wells added to and removed from the list since the last run, by API number.
3. Runs `owp2csv.py`, which writes the unplugged records from the zip to `op/ecmc_unplugged_orphan_wells.csv`.
4. Runs `cogis_scraper.py`, which writes `op/cogis_scout_data.csv`, `op/cogis_casing.csv`, and `op/cogis_additional_cement.csv`, then `bradenhead_scraper.py`, which writes `op/bradenhead_tests.csv` and `op/bradenhead_summary.csv`.

5. Runs `build_dashboard.py`, which checks that every table describes the same wells and then writes `docs/dashboard.html` and `docs/map.html`.

Both scrapers fetch again any cached page older than `--max-age-days`, 30 by default, so wells that stay on the list get current data too.  Every output is written fresh from the current list, so a well that leaves the list drops out of every table.  Its cached pages stay in `op/html_cache/` and `op/bradenhead_cache/` unless you pass `--prune-cache`, which deletes cached pages for wells no longer on the list after the scrapers finish.  `--skip-scrapers` stops after step 3, so it doesn't rebuild the pages either.

Each script also runs on its own.  The scrapers read `ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv` by default.  To use a different well list or output folder, pass them in that order:

    python cogis_scraper.py <wells.csv> <output_folder>

The input CSV only needs an `API_10` column in `05-CCC-SSSSS` form.  A malformed API number is logged and the well gets a row with `fetched` set to `False`.  `owp2csv.py` takes an input zip and output CSV the same way.  Run alone, the scrapers reuse cached pages however old they are unless you pass `--max-age-days`.  Each script has `--help`.

Each scraper waits 1 second after every request, so a run that fetches every well takes at least as many seconds as there are wells, for each scraper.  Timeouts, connection errors, and HTTP 429 or 5xx responses are retried twice more with a longer wait, and anything that still fails is logged with its reason.  Pages are cached under their 8 digit API number, and only pages with real well content are cached.  A rerun reads from the cache and only fetches wells that aren't there yet, or whose pages are older than `--max-age-days`, so a stopped run picks up where it left off.  If a page can't be fetched again, the cached copy is used and keeps its old date.  `fetched_at` and `bh_fetched_at` come from the cache files' timestamps, so if you copy a cache, keep the timestamps.

The scrapers identify themselves to ECMC with a User-Agent header.  Give it a contact address so ECMC can reach you about your requests, either with `--contact you@example.org` or by setting the `ORPHAN_WELLS_CONTACT` environment variable.  Without one, the scripts still run and log a warning.

Output CSVs are written to a temporary file and renamed into place, so an interrupted run leaves the previous file intact.

## Development

Install the tools with `pip install -r requirements-dev.txt`, then from the repo root:

    pytest              # unit tests, plus regression tests over the full cache
    pytest -m "not slow"  # skip the two scraper regression tests
    ruff check .
    ruff format --check .
    mypy

The regression tests rerun each script over the saved inputs and require the output to match the committed files byte for byte.  The ranked list and ECMC table tests need the downloads in `ip/downloads/` and skip themselves unless the files' checksums match `ip/CO_Orphan_Wells_EJ_Ranked_Wells.sources.json`.  The dashboard and map test needs the same downloads, the two saved Leaflet files, and the Census county zip, and it reads the committed `ip/program_data.json`.  The scraper tests need complete page caches in `op/` and skip themselves otherwise, so a test run never contacts ECMC.

`tests/test_well_set.py` checks that the committed tables describe the same wells.  The ranked list defines the set.  The ECMC table, `cogis_scout_data.csv`, and `bradenhead_summary.csv` must hold exactly those API numbers once each, the casing, additional cement, and bradenhead test tables may hold only wells from the set, and every well on the ranked list needs coordinates inside Colorado.  It reads only committed files, so it always runs.  A failure after a refresh usually means the ranked list was rebuilt without rerunning the scrapers.  The check is `build_dashboard.well_set_problems`, the same function `build_dashboard.py` runs before it writes a page.

`docs/code_review_procedure.md` describes the review these checks support.

## Output tables

`ecmc_unplugged_orphan_wells.csv`, `cogis_scout_data.csv`, and `bradenhead_summary.csv` have one row per well.  `cogis_casing.csv` has one row per casing string, `cogis_additional_cement.csv` one row per additional cement record, and `bradenhead_tests.csv` one row per test.  Column definitions are in `data_dictionary.md`.

`ecmc_unplugged_orphan_wells.csv` is the ECMC list with its original columns: project name, well name, site ID, API number, tank battery, surface and mineral ownership, and coordinates.  `owp2csv.py` writes the same columns from OWP_SHP.ZIP, except `OBJECTID`, a row number from ECMC's map service that the shapefile doesn't carry.

`cogis_scout_data.csv` holds the parsed scout card fields: well status and status date, spud and completion dates, measured and vertical TD, plugback depth, elevation, and a casing summary.  `n_casing_strings` counts the casing strings ECMC lists as run (citings type ACTUAL or HISTORICAL), and `n_planned_casing_strings` counts the PLANNED strings from the drilling permit.  Both count strings of pipe only (see `is_casing_string` below).  `surf_casing_size_in` and `surf_casing_depth_ft` come from the deepest run surface (SURF) string when a well lists more than one.  `n_additional_cement` counts additional cement records.  `fetched` is `True` when a scout card was retrieved.  `fetched_at` is the UTC date the page was saved, taken from the cached file's timestamp.

`cogis_casing.csv` has one row per casing record on the scout card, in page order (`seq`), with the cement record that follows it.  `section` is `permit` or `completed`, matching the page heading the record sits under, and `citings_type` is ECMC's PLANNED, ACTUAL, or HISTORICAL.  So far PLANNED records have all sat under the permit and ACTUAL and HISTORICAL records under the completed wellbore, but filter on `citings_type` for casing actually run.  Sizes are in inches and depths in feet, as ECMC lists them.  `weight` is kept as written (for example `15.5,17` or `14 & 15.5`).  Any field can be blank, and some records have no cement values on the page at all.  `string_type` includes records that aren't a string of pipe: OPEN HOLE intervals, STAGE TOOL entries, and records labeled S.C. 1.1 through S.C. 3.2, which read as cement stages on an existing string.  `is_casing_string` is `N` for these, and the scout card counts leave them out.  `cement_method` holds ECMC's Determination Method (CBL, CALC, VISU, and so on); a few records hold a casing grade (such as H-40 or J-55) in that field, as entered by the operator.

`cogis_additional_cement.csv` has one row per Additional Cement record: string type, top, depth, bottom, sacks, and method, as ECMC lists them.

`bradenhead_tests.csv` has one row for each test on the COGIS bradenhead page and keeps all sixteen columns the page shows: document number, report type, test and submit dates, well status, surface and production casing pressures at start and end, bradenhead flow at start and end, fluid type, sampling, and operator comments.  Values are kept as text as the page shows them, including ECMC's `--` for blank and `NO FLOW` for no flow, with HTML entities such as `&#39;` decoded.  `doc_number` is the Form 17 document number.  Full and Light records have no document number on the page, so `doc_number` holds the record ID from their detail link instead.  Light records with different IDs and identical readings on the same well are all kept.

`bradenhead_summary.csv` reduces the test table to one row per well: the date the bradenhead page was saved (`bh_fetched_at`), the test count, first and last test dates, the latest test's start and end flow, end surface casing pressure, and fluid, the highest surface casing pressure on record, five flags, and a flow class.  When two tests share the latest date, the one submitted later is the latest, then the higher document number.  `bh_max_surf_casing_psi` is rounded to whole psi and leaves out TSTM readings, which the pressure flags count as above zero.  Wells without a bradenhead history keep a row with `bh_test_count` set to 0, so the summary joins to the full list.

### Bradenhead flow indicators

Form 17 records a flow code for the bradenhead annulus during a 30 minute test (No Flow, Down to 0, Whisper, Surge, Continuous), a fluid type, and surface casing pressures.  COGIS shows the flow code at the start and end of each test.  ECMC doesn't define the codes beyond their labels and doesn't rank them, so the summary reports what the tests recorded as separate flags and adds one class per well for sorting and mapping.

Each flag is `Y`, `N`, or `U`.  `U` means the records can't answer the question, for example because the flow fields are blank or the well has only one test.  Flags are blank for wells with no tests.

| Column | `Y` when any test shows |
|---|---|
| `bh_any_flow_observed` | a start or end flow code other than No Flow, including Down to 0 |
| `bh_liquid_flow` | water in a flow field, or water or liquid hydrocarbon as the fluid type |
| `bh_flow_at_end` | an end flow code other than No Flow or Down to 0 |
| `bh_not_bled_to_zero` | end surface casing pressure above 0 psi, or TSTM |
| `bh_pressure_rebuild` | a test that ended at 0 psi, followed by a test that started above 0 psi or TSTM |

TSTM counts as above zero.  ECMC's testing instructions use it for a shut-in pressure greater than zero that's too small to measure.  The rebuild flag rests on the same instructions, which ask operators to shut the bradenhead in for 7 to 14 days before a test so pressures can stabilize.  A nonzero starting pressure after an earlier test bled to zero therefore means pressure built back up between tests.  That's an inference from the procedure, not an ECMC finding.

`bh_flow_class` gives each well the first of these classes its tests meet, checked in rank order:

| Rank | Class | Meets it when |
|---|---|---|
| 1 | liquid flow | `bh_liquid_flow` is `Y` |
| 2 | pressure persists or rebuilds | `bh_not_bled_to_zero` or `bh_pressure_rebuild` is `Y` |
| 3 | flow at end of test | `bh_flow_at_end` is `Y` |
| 4 | flow bled off | `bh_any_flow_observed` is `Y` |
| 5 | no flow | `bh_any_flow_observed` is `N` |
| 6 | flow not reported | flow fields are blank on every test |
| 7 | no tests on file | `bh_test_count` is 0 |

`bh_flow_class` covers every test on file.  `bh_flow_class_latest` applies the same checks to the most recent test alone, with rebuild judged from the last two tests.  The `_rank` columns hold the rank as a number for sorting.

The order is a convention of this dataset, not an ECMC ranking.  Liquid flow comes first because Rule 419 requires action when a well flows liquids or continuous gas from the bradenhead annulus.  Pressure comes second because ECMC's bradenhead operator guidance (last updated April 29, 2025) defines sustained casing pressure as annulus pressure that won't blow down to zero or builds up after being bled down.  The pressure flags use 0 psi rather than the Rule 419 action thresholds, which depend on surface casing depth and area orders, so they're stricter than the rule in most of the state.  No class here is an ECMC compliance finding.

Down to 0 is the hardest code to read.  Form 17 lists it as a flow code without a definition, and the plain reading is that the annulus flowed and then stopped during the test.  Operators don't seem to use it consistently: most test rows coded Down to 0 also record an initial surface casing pressure of 0 psi.  A well whose only recorded flow is Down to 0 falls in class 2 if its pressure persisted or rebuilt, and in class 4 otherwise.  Class 4 also holds wells whose flow started as Whisper, Surge, Continuous, or Gas and had stopped by the end of the test.

Sources: [Form 17, rev. 11/2020](https://ecmc.state.co.us/documents/reg/Forms/PDF_Forms/Form17_11_2020.pdf); [Bradenhead Testing and Reporting Instructions, rev. 10/18/2018](https://ecmc.state.co.us/documents/reg/OpGuidance/Bradenhead%20Testing%20Instructions%2020181018.pdf); [ECMC operator guidance on bradenhead monitoring and testing](https://ecmc.colorado.gov/sites/ecmc/files/documents/ECMC_operator_guidance_Bradenhead_Monitoring_Testing_Reporting.pdf), which also quotes Rule 419.b(4).

## Ranked well list

`build_ranked_wells.py` downloads two public datasets, places each well in its census block group, scores it, and writes `ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv`.  The name stays the same from run to run, so the scrapers always find it and git keeps earlier versions.  `ip/CO_Orphan_Wells_EJ_Ranked_Wells.sources.json`, written beside it, records the source URLs, when each file was retrieved, record counts, and a SHA-256 checksum of each file read.  Pass `--out` to write somewhere else.

    python build_ranked_wells.py --contact you@example.org

The sources are:

- ECMC's Orphaned Well Program shapefile, [OWP_SHP.ZIP](https://ecmc.state.co.us/documents/data/downloads/gis/OWP_SHP.ZIP), listed on ECMC's [downloadable data page](https://ecmc.colorado.gov/data-maps-reports/downloadable-data-documents) and updated daily.  Records with `OWPStatus` of `Unplugged` are the unplugged orphan well list, with the same fields as `ip/unplugged.json` apart from `OBJECTID`.  The August 2026 list came from ECMC's ArcGIS map service, which now requires a sign-in token (checked November 2026), so the script uses the shapefile download instead.
- CDPHE's Colorado EnviroScreen 2.0 block groups, read from the [public feature layer](https://services3.arcgis.com/66aUo8zsujfVXRIT/ArcGIS/rest/services/EJP_Main_English_v1_BlockGroup_20230803/FeatureServer/0) in pages of 2,000.  The block groups carry the November 2024 Disproportionately Impacted (DI) community designation, which ECMC's operator guidance makes operative for Form 2A submittals after December 15, 2024.  The script uses `GEOID`, `Cnt_N`, `ES_S_`, `DIType`, `Ttl_P`, and the seven criterion flags.

Downloads go to `ip/downloads/`, which isn't in the repo, and later runs reuse them.  Pass `--refresh` to download again.  `--owp-zip` and `--blockgroups` point the script at saved copies instead, which is how to rebuild an earlier snapshot.  The script waits 1 second after every request and retries failures the way the scrapers do.

### Method

Each well is placed in the block group that contains its ECMC coordinates, tested against the full-resolution boundaries.  `County` comes from the county code in the API number.  The priority score has three parts.

| Part | Points | How it's scored |
|---|---|---|
| `Score_Community` | 0 to 40 | 20 if the block group is a November 2024 DI community, meaning its `DIType` isn't `N/A`.  Plus 2 for each DI criterion it meets, up to 10.  Plus its EnviroScreen 2.0 percentile divided by 10.  A non-DI well within 300 m of a DI block group gets a flat 8 instead. |
| `Score_Exposure` | 0 to 30 | 20 &times; log10(1 + density) / log10(100), capped at 20, where density is people per km&sup2; in the block group.  Plus 10 &times; population / 3,000, capped at 10. |
| `Score_Deliverability` | 0 to 30 | 15 &times; ln(n) / ln(50), capped at 15, where n counts the wells in the same OWP project within 5 km, the well itself included.  Plus 15 for fee or state surface and minerals, 8 for fee or state surface over federal minerals, 4 for federal surface, or 0 for tribal land. |

The seven DI criteria are people of color above 40%, low income above 40%, linguistic isolation above 20%, housing cost burden above 50%, an EnviroScreen percentile above 80, location in a federal Justice40 census tract, and tribal jurisdiction.  Density uses the block group's total population over its area, computed from the polygon on an equal-area sphere.  Distances between wells are great-circle distances.  Federal and tribal wells score lower on jurisdiction because their plugging has separate funding and authority.

`Priority_Score` is the sum of the three parts, rounded to one decimal.  `Tier` is 1 at 55 and above, 2 from 45 to 54.9, 3 from 30 to 44.9, and 4 below 30.  `Rank` orders wells by `Priority_Score`, highest first, with ties broken by API number.  The weights and cutoffs are constants at the top of the script, so the ranking can be rerun under different priorities.

`Boundary_Flag` is `DI edge <300m` for a DI well within 300 m of a non-DI block group and `near DI <300m` for a non-DI well within 300 m of a DI block group.  A small location error could change these wells' DI status, so they're worth checking at the parcel level.

CDPHE publishes no EnviroScreen or population data for the block groups inside the Southern Ute and Ute Mountain Ute reservations.  Those block groups are DI by tribal jurisdiction, and a well there scores 22 for community burden and 0 for exposure.

Other columns: `DI_Type` is CDPHE's `DIType` for DI wells, `DI_Criteria_Count` is the number of criteria met (blank for non-DI wells), `EnviroScreen2_Pctl` is `ES_S_` to one decimal, `BG_Pop` is `Ttl_P`, and `Cluster_Size_5km` is n above.  `Lat` and `Lon` are as ECMC publishes them (NAD83).

### Changes from the August 2026 list

The August 2026 ranked list of 1,396 wells, built on 2026-08-05 with an earlier version of this method, has been replaced by `ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv` and isn't in the repo.  Rebuilding the same 1,396 wells with the current script changes five things.

DI status.  The August build counted a block group as DI only when CDPHE's `D_I_C` field equaled 1.  `D_I_C` holds the number of criteria met, so DI block groups meeting two or more criteria were scored as non-DI, as were the tribal block groups, where `D_I_C` is 0.  That affected 41 wells: 20 in Kiowa County, 8 in Baca, 7 in Moffat, 4 on tribal land in La Plata and Montezuma, 1 in Fremont, and 1 in Weld.  `DI_Criteria_Count` also read 0 for wells meeting one criterion.  With the fix, 674 of the 1,396 wells are in DI communities, up from 633.

Density.  The August build divided by CDPHE's `Sqmiles` field, which is rounded to whole square miles and is 0 for 2,369 of the 4,058 block groups.  Wells in those block groups got a density of 0.  The script now computes area from the polygon.

Boundary flag.  The August build flagged a DI well within 300 m of any edge of its own block group, including edges shared with another DI block group and the state line.  The script now flags only edges where DI status changes, which removes 23 flags and adds 1.

Cluster distance.  Great-circle distance replaces the August build's flat-earth approximation, which changes the cluster count by one for 156 wells.

`Changed_vs_May2023` is gone.  It compared each well against ECMC's copy of the superseded May 2023 DI designation, which is no longer publicly reachable.

Together these move 52 wells up at least one tier, and none down.  The tier counts for the August wells go from 435, 196, 369, and 396 to 439, 234, 366, and 357.

## Dashboard and map

`build_dashboard.py` writes two pages to `docs/` from the committed tables.  Each is a single HTML file with its data embedded, so it opens from a local file with no server.

    python build_dashboard.py

`docs/dashboard.html` groups its pages in a sidebar.

Program pages, drawn from `ip/program_data.json`:

- Overview.  Summary tiles and the main charts, each linked to the page that holds the detail.
- Key findings.  Short statements the published figures support, each with its basis and a link to the chart behind it.  The numbers are worked out from the chart data when the page opens, so a finding and its chart can't disagree.  The page gives no causes, forecasts, or recommendations.
- Funding and spending.  Program spending by funding source, the mitigation fee, the state budget line, bond claims, spending by project and county, and statewide financial assurance.
- Plugging and inventory.  Wells plugged, tasks and sites, the orphan list over time, and what ECMC staff have reported as pending.
- Federal funding.  Colorado's Infrastructure Investment and Jobs Act awards and spending, and Bureau of Land Management agreements.

Well pages, drawn from the tables in `op/` and the ranked list, sharing one set of filters:

- Map.  The wells over CDPHE's EnviroScreen 2.0 block groups, with the November 2024 DI communities outlined.  Wells can be colored by priority tier or by bradenhead flow class, for all tests on file or for the latest test alone.
- Well list.  One sortable row per well, with filters for county, OWP project, tier, flow class, DI status, and Federal/Tribal, and a CSV export of the rows shown.
- Well sheet.  One well's identity, priority score, wellbore, casing and cement records, and bradenhead test history, laid out to print on one or two letter pages, with a searchable list of the filtered wells beside it.  `dashboard.html#well=05-125-02377` opens a sheet directly.
- Well list in charts.  The filtered wells counted by tier, DI status, county, project, decade drilled, depth, flow class, year of last test, and scout card status.
- County and project summary.  Well counts by tier, DI status, Federal/Tribal, and flow class.  Clicking a row filters every well page.  The counts follow the filters, and each table leaves out its own filter so every county or project stays listed.
- Bradenhead and casing records.  The filtered wells by flow class, the year of each well's last test, wells with no tests on file, and wells whose scout card shows no surface casing record.

Law and other states, also from `ip/program_data.json`:

- Legislation and rules.  Colorado bills, rules, and orders, federal actions, and court decisions on orphaned wells and financial assurance in date order, with the statute sections and definitions they rest on, each linked to its text.
- State comparison.  Colorado beside other oil and gas states on published counts, spending, and federal awards.  The page reports ranks and figures and doesn't grade them.
- Bonding and fees by state.  How each state funds its program and what it requires of operators.

Reference:

- Sources.  Every document behind the program pages with its link, the pages that cite it, and a list of figures that weren't found.
- About the data.  Sources for the well pages, retrieval dates, checksums, definitions, and blank counts for the main scout card fields.

`docs/map.html` is the map alone, for readers who only want the map.  It's built in the same run from the same well data and the same map code, and its well popups link to the dashboard's well sheets.  It doesn't carry the program pages.

### Who it's for

The pages serve readers of the article series, and they give ECMC Orphaned Well Program staff and plugging contractors one place to review a well's records before a site visit.  Every well sheet links to the well's live COGIS scout card and bradenhead page, and those pages are the ones to act on.

### What the pages do and don't show

- The priority rank, tier, and score are Subsurface Risk Analytics' method (see [Ranked well list](#ranked-well-list)).  ECMC sets its own plugging priorities, and the pages label the score as SRA's everywhere it appears.
- Values appear as ECMC recorded them.  A blank is shown as "not on the scout card" or "not reported" and never as zero.
- The pages carry no safety or hazard rating.  The bradenhead flags and flow classes sort what the tests recorded, with the limits described in [Bradenhead flow indicators](#bradenhead-flow-indicators).
- The scout cards and bradenhead tests say nothing about H2S, the current condition of a wellhead or surface equipment, site access, or anything since the last filing.
- The pages don't replace ECMC's files, the operator's records, or a site-specific safety assessment, and they're provided as is.
- The dashboard is an independent compilation by Subsurface Risk Analytics.  It isn't an ECMC publication, and its program pages report published figures without recommending a policy.
- A banner gives the age of the well list, the scout cards, and the bradenhead pages, computed in the reader's browser, and marks any of them older than 30 days.  Well age is computed the same way, in whole years from the spud date, or from the completion date when the scout card has no spud date.

### Program data

`ip/program_data.json` holds every figure, chart, legislation entry, and source link on the program pages.  It's compiled by hand from documents the agencies publish, mainly ECMC's annual reports and board presentations, Joint Budget Committee documents, Interior Department reports, and other states' program reports.  No script generates it, and `main.py` doesn't refresh it.  The date it was last compiled is in the file as `asOf` and shows in the dashboard's header.

- Every chart, table, and tile names its sources by id, and the Sources page lists each one with its link.  News reports are used only where no agency document gives a figure, and are marked as news.
- A figure an agency didn't publish is `null` in the file.  The pages draw it as a gap labeled "not published" and never as zero.
- "Derived" marks arithmetic on published totals, and the card states the arithmetic.  Total spending divided by wells plugged is labeled as that and not as a cost per well.
- Where two documents disagree, the pages show both figures and say so.
- Some other-state rows are marked "carried."  They come from an October 2026 Subsurface Risk Analytics compilation of state agency pages and weren't re-checked against the agencies' documents for this file.
- Figures were read from the linked documents, many of them PDFs read as extracted text.  A reader who relies on a number should check it against its source, which is one click from the chart.

Before writing either page, `build_dashboard.py` runs `program_problems` on the file.  It stops if a card, tile, or finding cites a source the file doesn't define, a source has no title or link, a chart series doesn't match its categories, or a finding points to a card that doesn't exist.  The check is structural.  It can't tell whether a figure matches its document.

To correct or add a figure, edit `ip/program_data.json`, rebuild, and commit the file with both regenerated pages.

### One set of wells

The ranked list defines the well set.  Before it writes anything, `build_dashboard.py` checks that the ECMC table, the scout data, and the bradenhead summary hold exactly the ranked list's API numbers once each, that the casing, additional cement, and bradenhead test tables hold only wells from that list, and that every well has coordinates inside Colorado.  On a mismatch it stops and lists the API numbers by table.  Both maps, every dashboard page, and the CSVs therefore show the same wells.

### Map details

- A well counts as Federal/Tribal when it scores less than the full 15 jurisdiction points, meaning its surface or its minerals are Federal, Tribal, or Indian.  The map filter calls the scoring function, so the filter and the score use one definition.
- A block group is drawn as a DI community when its `DIType` isn't `N/A`, the same test the ranking uses.
- Block group boundaries are simplified for display, to within about 6 m, and stored to the nearest 0.00001 degree.  A boundary shared by two block groups is simplified once and used by both, so neighbors still meet.  Scoring always uses the full-resolution boundaries.
- County outlines are Colorado's 64 counties from the Census Bureau's 2024 cartographic boundary file for counties at 1:500,000 (`cb_2024_us_county_500k.zip`).  The script downloads the national file from census.gov once, keeps it in `ip/downloads/`, and embeds the records with `STATEFP` 08, read with the standard library.  The file is generalized for mapping at that scale, so a county line can sit slightly off the block group boundaries.
- The half-mile and one-mile rings are circles of 804.672 m and 1,609.344 m around each well.  They measure straight-line distance from ECMC's published coordinates, whose accuracy varies by well.
- The map uses [Leaflet](https://leafletjs.com/) 1.9.4, embedded in each page under its BSD 2-Clause license.  The script downloads `leaflet.js` and `leaflet.css` from cdnjs once, checks each against a pinned SHA-512, and keeps them in `ip/downloads/`.  Basemap tiles come from Esri and the USGS and are the only thing loaded at view time, so everything but the basemap works offline.

### How the pages are built

`build_dashboard.py` uses `requests` and the standard library.  It reads the ranked list and its `sources.json`, the six tables in `op/`, `ip/program_data.json`, the block group GeoJSON that `build_ranked_wells.py` saves in `ip/downloads/`, and the Census county file.  The page frames, scripts, and styles are in `web/`: `dashboard.html`, `dashboard.css`, and `program.js` for the dashboard, `map.html` and `map.css` for the map, and `app.js` for the well pages and the map in both.  The charts are drawn on canvas by `program.js` with no chart library.  The output holds no build time and is the same byte for byte from the same inputs, which the regression test checks.  `docs/dashboard.sources.json` records a SHA-256 for both pages and for each file they were built from.  For the county file it records the URL, the saved file's time, and a SHA-256 of the `.shp` and `.dbf` inside the zip.

## Limitations

The outputs are a snapshot of ECMC records as of the last run.  `ip/CO_Orphan_Wells_EJ_Ranked_Wells.sources.json` records when the well list was retrieved, and `fetched_at` and `bh_fetched_at` record when each well's pages were saved.  ECMC updates well status, adds tests, and revises the orphan list, so a fresh run will give different results.

Both scrapers parse page text with regular expressions keyed to the labels on the live pages.  If ECMC changes a label, the affected field comes back blank without an error, so check blank rates after any new run.

Values are reported as ECMC shows them.  The outputs don't correct or fill in missing operator data.

## License

The code is released under the MIT License (see `LICENSE`).  The underlying well records are public records of the Colorado Energy and Carbon Management Commission.

## Author

Steven R. Klimowski, Subsurface Risk Analytics.  Questions and corrections are welcome through GitHub issues.
