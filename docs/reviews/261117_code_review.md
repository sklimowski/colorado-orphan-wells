# Code review, 2026-11-17

Review of `json2csv.py`, `cogis_scraper.py`, and `bradenhead_scraper.py` following `docs/code_review_procedure.md`.  No code was changed.  The output baseline is in `baseline_261117.md`.

Updated the same day after the HTML caches were copied in from the archive.  Every casing and bradenhead finding below was rechecked against all 1,396 cached pages, and the earlier sample-based estimates were replaced with full counts.

## Summary

The review found 4 Blockers, 10 Majors, 18 Minors, and 1 Nit, plus 5 data notes.  As of the end of 2026-11-17, all of them are closed, along with BH-10, found during the cleanup.

All four Blockers are in the casing and cement parse in `cogis_scraper.py`.  The cached pages hold 3,792 casing records and 3,792 cement records.  Against those:

- About 90% of the casing sizes in `casing_strings` are hole (bit) sizes, not casing sizes (2,804 of the 3,110 values that could be matched to a page record).
- 760 of the casing records (20%) are PLANNED strings from the permit section, mixed in with the strings actually run.
- 608 casing records are dropped because their Top is blank.  That's why 116 of the 138 wells showing no casing actually have casing on their scout card.  Only 22 wells truly have none.
- The output holds 2,323 cement records.  1,364 of the 3,792 on the pages are dropped because their Bottom is blank.

Steven confirmed on 2026-11-17 that the article series hasn't used any casing or cement values from `cogis_scout_data.csv`, so no published figures need correcting.  The fix is needed before the repo goes public.

The bradenhead outputs are sound.  Every well's bradenhead page is in the cache, and the 294 wells with zero tests have pages that hold only the well header, so none of them is a failed fetch.  The open questions there are definitions: what `bh_ever_flow` should count, and which test is "last" when two share a date.

The cached pages reproduce all three scraper outputs byte for byte with the current code, so any refactor can now be checked offline against the baseline.  All cached pages are dated 2026-08-05, which is the scrape date the README is missing.

The code is short, readable, and better commented than most scraper code.  It falls short of team standards in the usual places: duplicated logic across the two scrapers, no tests, no type hints, `print` instead of logging, and a conversion script that runs on import.

## How this review was done

- Automated: `ruff check` with the rule set in the procedure (59 hits), `ruff format --diff` (3 files would change), and `mypy --strict` (30 errors).
- Output checks: blank rates, distinct values, date validity, key integrity, depth plausibility, and sensitivity tests on derived flags, all run against the committed CSVs.
- Live page checks on four wells (05-115-06072, 05-045-06947, 05-045-06287, 05-045-06946), first through a web fetch tool and then for 05-045-06947 directly from the ECMC site.  The live casing text for that well matches its cached page exactly, so ECMC hasn't changed the layout since the scrape.
- Cache checks: the current parse functions were run against all 1,396 cached scout cards and bradenhead pages and reproduced `cogis_scout_data.csv`, `bradenhead_tests.csv`, and `bradenhead_summary.csv` byte for byte.  An independent block parser (with HTML entities decoded) was then run over the same pages to count every casing and cement record and its fields.  The scripts in the repo weren't modified or run against the network.

## cogis_scraper.py

| ID | Severity | Category | Location | Finding | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| CS-01 | Closed | Methodology | lines 64-66 | The casing regex matches the `Size:` inside `Hole Size:`, so it captures bit size as casing size.  When hole size is blank, the lazy match runs on to the real `Size:`, so the column mixes the two with no way to tell which is which. | Raw HTML for 05-045-06947 reads `Hole Size: 12.25 in., Size: 8.625 in.`; output reads `SURF 12.25in`.  Across all cached pages, 2,804 of 3,110 matchable output values are the hole size and 265 are the casing size.  490 records have a blank hole size. | Anchor on the full label sequence and capture hole size and casing size as separate fields.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-02 | Closed | Methodology | lines 64-71 | Casing and cement are collected from both the Wellbore Permit section (Citings Type PLANNED) and the Wellbore Completed section (ACTUAL or HISTORICAL).  `n_casing_strings` double counts, and planned depths appear as if they were run. | 05-115-06072 shows 4 strings, including a planned 1ST string to 3,000 ft; the actual string goes to 2,651 ft.  Across all pages: 2,307 ACTUAL, 673 HISTORICAL, and 760 PLANNED records.  5 wells have only PLANNED casing on file. | Capture `Citings Type` for each string.  Keep ACTUAL and HISTORICAL for analysis and either drop PLANNED or keep it in a flagged column.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-03 | Closed | Methodology | line 70 | The cement regex requires numeric `Top:` and `Bottom:` values.  When ECMC leaves either blank, the whole cement record is dropped, including sacks. | 05-045-06947 has `Sacks: 350, Top: 0 ft., Bottom: ,` on the page and a blank `cement` in the output.  Across all pages, 1,364 cement records have a blank Bottom and 283 a blank Top.  The output holds 2,323 of 3,792 cement records. | Make each cement field optional and keep the record when any field is present.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-04 | Closed | Methodology | line 70 | The sacks group `([\d,]+)` takes the trailing comma, so every cement entry reads like `180,sx`.  A value over 999 with a thousands separator would be ambiguous. | Every non-blank `cement` value. | Capture digits only and strip separators in a second step.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-05 | Closed | Methodology | lines 63-71 | Casing and cement are parsed as two independent lists and packed into text fields.  A cement record can't be tied to its string, and the packed format has to be parsed again downstream (including in Fabric). | Output layout. | Write a long table, one row per string: API, wellbore, citings type, string type, hole size, casing size, top, depth, sacks, cement top, cement bottom, determination method.  Keep per-well counts in the summary.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-06 | Closed | Methodology | lines 51-62 | Scalar fields take the first match anywhere on the page, which would mix wellbores on a page with sidetracks. | Closed after the cache check: no cached page has more than one wellbore, so the 7 wells with PB depth greater than MD and the 3 with MD 0 are as ECMC published them (see D-02).  Spud date, vertical TD, completion date, and PB depth blanks are all genuinely absent from their pages. | Parse per wellbore if sidetracked wells are ever added. |
| CS-12 | Closed | Methodology | lines 64-66 | The casing regex requires a numeric `Top:`.  When ECMC leaves Top blank, the whole casing record is dropped. | 608 casing records have a blank Top.  116 of the 138 wells with `n_casing_strings` 0 have casing on their scout card. | Make each casing field optional and keep the record when any field is present.  Fix together with CS-01 to CS-05.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-07 | Closed | Methodology | line 54 | `re.I` makes `[A-Z]{2}` match any two letters, lowercase included. | All 9 status codes in the output are valid, so there's no current impact. | Drop `re.I` for this pattern or compile it separately.  Closed 2026-11-17: `well_status` and `status_date` patterns are now case-sensitive; output unchanged. |
| CS-08 | Closed | Robustness | lines 41-43 | `strip_tags` doesn't decode HTML entities, unlike the bradenhead version. | No `&` found in any parsed field, so no current impact. | Use `html.unescape` in one shared function.  Closed 2026-11-17 by the casing and cement rewrite. |
| CS-09 | Closed | Methodology | lines 74-75 | `related_links` is cut to 5 entries with no stated reason, and in practice holds only the bradenhead link that the other scraper builds anyway. | Every well has exactly one link. | Drop the column, or document what it's for.  Closed 2026-11-17: The 5 link cap is gone and the pattern is documented; every page in the snapshot offers exactly one link, so output is unchanged. |
| CS-10 | Closed | Structure | lines 84-91 | The v1 cache purge reads every cached page on every run.  It was a one-time migration and is now startup cost plus dead logic in a public repo. | 1,396 file reads before the first fetch. | Remove it.  Note the v1 history in the commit message or a changelog.  Closed 2026-11-17: The v1 cache purge is removed. |
| CS-11 | Closed | Documentation | lines 1-20 | The module docstring is mostly v1 to v2 change history, which belongs in git.  The label example omits `Hole Size`, which is how CS-01 slipped through. | Docstring text. | Rewrite as what the script does, inputs, outputs, and a correct label example.  Closed 2026-11-17: Module docstring rewritten: what the script does, the URL rule, a label example that includes Hole Size, outputs, and usage. |

## bradenhead_scraper.py

| ID | Severity | Category | Location | Finding | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| BH-01 | Closed | Methodology | `summarize()` | `bh_ever_flow` counted any code other than `NO FLOW`, `--`, or blank as flow, so a well that bled down to zero once and a well with continuous flow got the same `Y`. | 529 wells were `Y`; 199 of them only because of `DOWN TO 0`. | Closed 2026-11-17.  Replaced by `bh_any_flow_observed` plus four flags and an ordered flow class, for all tests and for the latest test.  Definitions are in the README under Bradenhead flow indicators. |
| BH-02 | Closed | Methodology | lines 95-100 | "Last test" is picked by test date only.  When two tests share a date, the stable sort keeps page order, which nothing guarantees. | 35 wells have more than one test on their latest date with different end flow values. | Break ties by submit date, then document number, and say so in the data dictionary.  Closed 2026-11-17: ties go to the later submit date, then the higher document number (Steven's call).  35 wells changed their latest-test fields. |
| BH-03 | Closed | Robustness | lines 136-154 | A fetch failure (timeout, HTTP 5xx, rate limit) produces the same summary row as a well with no bradenhead history: `bh_test_count` 0.  The log line says "no bradenhead page" for both. | Not an issue in the current snapshot: all 1,396 bradenhead pages are cached, and the 294 zero-test pages hold only the well header.  The risk is in future runs. | Add a `bh_fetched` column like the scout scraper's `fetched`, and log the HTTP status.  Closed 2026-11-17: `bh_fetched_at` is blank when the page wasn't retrieved, so a failed fetch no longer looks like a well with no tests.  Logging the HTTP status stays with X-03. |
| BH-04 | Closed | Methodology | summary columns | Category values come in mixed case (`WHISPER` and `Whisper`, `DOWN TO 0` and `Down to Zero`, `SHUT-IN` and `Shut-In`). | See baseline distinct values. | Keep raw values in `bradenhead_tests.csv` and add normalized columns for analysis.  Closed 2026-11-17: The summary flags normalize case and spelling; `bradenhead_tests.csv` keeps the values as the page shows them, which the README states. |
| BH-05 | Closed | Methodology | lines 111-115 | The pressure regex rejects leading-decimal values (`.3`, `.5`) and the reading `TSTM` (too small to measure).  `int()` truncates rather than rounds. | 3 decimal values and 13 `TSTM` readings in `end_surf_casing_psi` alone. | Accept `.3` style values, map `TSTM` to a documented value or flag, and round.  Closed 2026-11-17: leading-decimal values are read and the maximum rounds half up.  TSTM stays out of the number (Steven's call).  No well's value changed in this snapshot. |
| BH-06 | Closed | Methodology | line 102 | `bh_last_flow_end` is blank for 19 wells that have tests, because their latest test left end flow blank. | 313 blanks against 294 wells with no tests. | Document it, or add `bh_last_flow_start` so the latest test still has a reading.  Closed 2026-11-17: added `bh_last_flow_start`.  Only 1 well now has both latest flow readings blank. |
| BH-07 | Closed | Robustness | `main()` | `summaries[0]` raised `IndexError` on an empty well list. | Code path. | Closed 2026-11-17.  The summary header now comes from the `SUMMARY_COLS` constant. |
| BH-08 | Closed | Methodology | lines 47, 79-82 | `doc_number` holds the link text `Click for Specifics` instead of a number for the 68 Full and Light reports.  Only Form 17 rows carry a real document number.  One well (05-045-05033) has two identical Light reports on the page. | 68 rows.  The duplicate is in ECMC's page, not a parse error. | Take the document or report ID from the link's `href`, and drop exact duplicate rows in the summary.  Closed 2026-11-17: Full and Light rows take the record_id from their link.  The two Light records for 05-045-05033 have different IDs, so both are kept. |
| BH-09 | Closed | Documentation | line 27 | The docstring hard-codes the 1,396 well count. | Docstring text. | Say "the full well list" so it stays true when ECMC updates the list.  Closed 2026-11-17: Docstring now says "the full well list". |
| BH-10 | Closed | Methodology | `strip_tags()` | Found during Batch 3.  The bradenhead `strip_tags` decoded only `&nbsp;` and `&amp;`, so 189 operator comments kept raw entities such as `WON&#39;T` and `1&quot; valve`. | 189 cells in `comments`. | Closed 2026-11-17: both scrapers use `common.strip_tags()`, which decodes all entities.  Only those 189 cells changed. |

## json2csv.py

| ID | Severity | Category | Location | Finding | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| JC-01 | Closed | Standards | whole file | Runs at module level with no `main()`, no `if __name__ == "__main__"` guard, no docstring, and paths relative to the working directory.  It can't be imported by a test without writing files. | ruff D100.  Code structure. | Wrap it in functions with arguments for input and output paths and add a module docstring.  Closed 2026-11-17: Split into `convert()` and `main(argv)` with a module docstring; defaults resolve from the script location; tests call it in-process. |
| JC-02 | Closed | Robustness | line 8 | The JSON is opened without `encoding=`.  Python 3.13 on Windows still defaults to the locale encoding unless UTF-8 mode is on. | Code. | Pass `encoding="utf-8"`.  Closed 2026-11-17: The JSON is read as UTF-8. |
| JC-03 | Closed | Robustness | line 12 | Columns come from the first feature only.  A later feature with an extra key would raise `ValueError`. | All 1,396 features share one key set today, so the risk is latent. | Use the `fields` list in the Esri JSON as the column source.  Closed 2026-11-17: Columns come from the feature set's `fields` list (same order as before, so the output is byte-identical); attributes outside it are appended with a warning. |
| JC-04 | Closed | Standards | line 1 | Two imports on one line, unsorted. | ruff E401, I001. | One import per line.  Closed 2026-11-17: Imports split and sorted. |

## Cross-cutting

| ID | Severity | Category | Location | Finding | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| X-01 | Closed | Structure | both scrapers | Constants, session setup, API conversion, the fetch-and-cache loop, CSV loading, and the CLI block are duplicated.  The two `strip_tags` functions have already drifted apart (CS-08). | Side-by-side read. | Move shared code into one module (for example `cow_common.py`) with one fetch function that both scrapers call.  Closed 2026-11-17: Shared code moved to `common.py`: API conversion, well list reading, session and User-Agent, cached fetch with retry, atomic CSV writes, fetch dates, tag stripping, logging, and the CLI parser. |
| X-02 | Closed | Methodology | all outputs | No output records when each page was retrieved.  The only record is the cache file timestamp, and the caches aren't published. | Output columns. | Add `fetched_at` (UTC date) per well, taken from the fetch time or the cache file time.  Closed 2026-11-17: `fetched_at` (scout) and `bh_fetched_at` (bradenhead) hold the UTC date from the cached file time; 2026-08-05 for every well in this snapshot. |
| X-03 | Closed | Robustness | both fetch loops | No retry or backoff.  HTTP 429 and 5xx are treated like a missing page, so a bad stretch of network leaves gaps that look like real data until the next run. | Code path. | Retry transient errors two or three times with backoff, keep the 1 second floor, and log the status code.  Closed 2026-11-17: `common.get_page()` retries timeouts, connection errors, and HTTP 429 and 5xx up to 3 attempts with growing backoff, keeps the 1 second pause after every request, and logs each failure with its status. |
| X-04 | Closed | Testability | repo | No tests and no saved sample pages.  The parse functions take HTML strings, so they're easy to test once fixtures exist. | No `tests/` folder. | Save fixture pages for the cases in the procedure plus the four wells in this review, and write `pytest` tests that pin current behavior before fixing anything.  Closed 2026-11-17: `tests/` holds 113 tests, including byte-for-byte regression tests over the full cache. |
| X-05 | Closed | Standards | all scripts | No type hints (26 ANN hits, 30 `mypy --strict` errors), 6 public functions without docstrings, `print` instead of `logging`, manual `sys.argv` handling, and defaults relative to the working directory. | ruff and mypy output. | Add type hints and Google-style docstrings, switch to `logging` and `argparse`, and resolve defaults from the script location.  Closed 2026-11-17: All four scripts have type hints and docstrings and pass `mypy --strict`; `logging` replaces `print`; `argparse` handles the command line; defaults resolve from the script location. |
| X-06 | Closed | Robustness | lines 93, 124 | Input CSVs are opened without a context manager. | ruff SIM115. | Use `with` or `Path.open()`.  Closed 2026-11-17: Files are opened with context managers. |
| X-07 | Closed | Robustness | output writes | CSVs are written in place.  A crash mid-write leaves a truncated file over the old one. | Code path. | Write to a temp file and rename.  Closed 2026-11-17: CSVs and cached pages are written to a temp file and renamed into place. |
| X-08 | Closed | Hygiene | both scrapers | The contact email is hard-coded in the User-Agent, and the README tells users to edit source to change it. | Lines 97 and 128. | Read it from an environment variable or a `--contact` argument.  Closed 2026-11-17: The contact comes from `--contact` or `ORPHAN_WELLS_CONTACT`; no address is in the code. |
| X-09 | Closed | Standards | all scripts | 9 lines over 88 characters, 3 files missing a final newline, 3 files `ruff format` would change, and the CLI's `3` argument count flagged as a magic number. | ruff output. | Run `ruff format` and fix the rest when the code is refactored.  Closed 2026-11-17: `ruff check .` and `ruff format --check .` pass with the settings in `pyproject.toml`. |

Efficiency wasn't a source of findings beyond CS-10.  Run time is set by the request delay, and nothing else costs more than a fraction of a second.

## Data notes

These are about the ECMC records, not the code.  They belong in the article series or the README limitations section.

- **D-01:** 29 wells on the unplugged list show scout status `PA` (plugged and abandoned) and 25 show `AB`.  23 of the `PA` wells have no casing on their scout card.
- **D-02:** 7 wells show PB depth greater than measured TD, and 3 show MD 0, exactly as on their scout cards.
- **D-03:** All 304 blank spud dates, 682 blank vertical TDs, 92 blank completion dates, and 137 blank PB depths are absent from the scout cards themselves.
- **D-04:** 22 wells have no casing records on their scout card (for example 05-045-06946).  The other 116 that show none in the output are parse failures (CS-12).
- **D-05:** 5 wells have only PLANNED casing on their scout card, so no record of casing actually run.

## Checks that passed

- `API_10` is well formed and unique for all 1,396 wells.  The ECMC list and the ranked list match exactly once `05-` is added to `APInumber`.
- Every status, spud, completion, and test date parses as a valid date.
- `fetched` is `True` for every well.
- Measured TD, vertical TD, PB depth, spud date, and elevation parsed correctly on all three wells checked live.
- No HTML entities leaked into parsed fields.
- Comments in both scrapers mostly explain why rather than what, and the module docstrings document the endpoints and the API number quirk clearly.

## Recommended order of work

1. (Done 2026-11-17.)  `tests/` holds 53 pytest tests on Python 3.13 with 9 fixture pages from the cache.  43 pass.  10 are strict xfail tests that state the correct result for CS-01, CS-02, CS-03, CS-04, CS-08, CS-12, BH-05 (two), BH-08, and JC-03, so each fix flips its test.  Three regression tests rerun each script over the full saved inputs and must reproduce the committed CSVs byte for byte.  Script backups are kept locally, outside the repo, and `.gitattributes` keeps CSVs and fixtures byte-exact.
2. (Done 2026-11-17.)  The article series hasn't used casing or cement values, so nothing published needs correcting.
3. (Done 2026-11-17.)  Fix the casing and cement parse as one change (CS-01 through CS-05 and CS-12) and replace the packed columns with a long table.  Rerun from the cache and record the before and after counts.
4. Separate fetch failures from empty results and add retrieval dates (BH-03, X-02, X-03).  For the current snapshot, `fetched_at` is 2026-08-05 for every well.
5. Settle the bradenhead definitions (BH-01, BH-02, BH-04, BH-05) and update the README and data dictionary to match.  BH-01 was done on 2026-11-17, ahead of the casing fix, at Steven's direction.  BH-04 is partly handled: the new flags normalize case and the two Down to 0 spellings, while the tests table keeps raw values.
6. Do the structural and standards cleanup (X-01, X-05 through X-09, CS-10, JC-01 through JC-04) and add `pyproject.toml` with the ruff and mypy settings.
7. Rerun the procedure's exit criteria.

Steps 3 and 5 change published output values, so each goes in its own commit with the counts in the message.

## Sources

- [Live scout card, 05-115-06072](https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=11506072)
- [Live scout card, 05-045-06947](https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=04506947)
- [Live scout card, 05-045-06287](https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=04506287)
- [Live scout card, 05-045-06946](https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=04506946)
- [ECMC Form 17 page, which lists the Form 17 Bradenhead Reporting Instructions (rev. March 22, 2017)](https://ecmc.colorado.gov/forms/form-17-bradenhead-test-report)

## Changes since the review

**2026-11-17, BH-01 and BH-07.**  `bradenhead_scraper.py` was edited before `git init`, with the original saved in a local backup.  Decisions by Steven: rename the flag to `bh_any_flow_observed`, add separate flags and an ordered flow class with descriptive labels, keep the order liquid flow, pressure persists or rebuilds, flow at end of test, flow bled off, no flow, and publish latest-test versions.  `op/bradenhead_summary.csv` was regenerated from the cache with no network requests.  `op/bradenhead_tests.csv` is unchanged.  Columns carried over from the old summary are identical for all 1,396 wells, and the renamed flag differs for one well, 05-045-05033, which moved from `N` to `U` because its only tests are Light records with blank flow fields.  The BH-01 tests that pinned the old definition were replaced; the suite is 88 passed, 10 xfailed.

**2026-11-17, CS-01 to CS-05, CS-08, CS-12.**  `cogis_scraper.py` was edited before `git init`, with the original in a local backup.  The new `parse_casing()` splits the page text at each casing, cement, Additional Cement, and section marker and reads every field by its label, so blank fields and weights containing commas no longer drop records.  `strip_tags()` now decodes HTML entities.  All 3,792 casing records and 71 Additional Cement records on the 1,396 cached pages parse, every casing record carries its own cement record, and the scalar fields (status, dates, depths, elevation, links) are identical to the previous output for every well.  Outputs: `cogis_scout_data.csv` drops the packed `casing_strings` and `cement` columns and adds `n_planned_casing_strings`, `surf_casing_size_in`, `surf_casing_depth_ft`, and `n_additional_cement`, with `n_casing_strings` now counting run records only.  New tables `cogis_casing.csv` (3,792 rows) and `cogis_additional_cement.csv` (71 rows).  The most common run casing size is now 4.5 in. (866 strings), where the old output's values were mostly bit sizes.  One defect in the first draft of the rewrite was caught by the marker count check: the number pattern could absorb the comma after a blank Bottom and drop the Determination Method that followed.  The pattern now refuses a leading or trailing comma, and a test covers it.  Suite: 101 passed, 4 xfailed.

Decided by Steven the same day: `n_casing_strings` and `n_planned_casing_strings` count strings of pipe only.  OPEN HOLE, STAGE TOOL, and S.C. stage cement records (129 in all, 107 of them run) stay in `cogis_casing.csv` with `is_casing_string` set to `N`.

**2026-11-17, Batch 1 (BH-02, BH-03, BH-05, BH-06, BH-08, X-02).**  Both scrapers edited; originals in a local backup.  `bradenhead_tests.csv` changed only in `doc_number` for the 68 Full and Light rows.  `bradenhead_summary.csv` adds `bh_fetched_at` and `bh_last_flow_start`; the tie rule changed the latest-test fields for the 35 tied wells and moved one well from class 4 to class 2 (rebuild 143 to 144; latest-test class 5 from 852 to 888).  `cogis_scout_data.csv` adds `fetched_at`.  README counts updated to match.  Suite: 125 passed, 1 xfailed (JC-03).

**2026-11-17, Batches 2 and 3 (CS-07, CS-09 to CS-11, BH-04, BH-09, BH-10, JC-01 to JC-04, X-01, X-03, X-05 to X-09).**  New `common.py` holds the shared fetch, cache, and output code; the three scripts were rewritten around it with type hints, docstrings, logging, and `argparse`.  New `pyproject.toml` (ruff, mypy, pytest settings), `requirements.txt`, and `requirements-dev.txt`.  New `tests/test_common.py` covers API conversion, file helpers, the contact setting, and the fetch loop with a fake session (retry, backoff, give-up, no caching of Not found pages).  Rerun over the full cache, five of six outputs are byte-identical; `bradenhead_tests.csv` differs only in the 189 `comments` cells fixed under BH-10.  Checks at close: `ruff check .` and `ruff format --check .` clean, `mypy --strict` clean on 10 files, `pytest` 149 passed.  The exit criteria in `docs/code_review_procedure.md` are met.
