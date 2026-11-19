# Python code review procedure

This procedure reviews the three scripts in this repo (`json2csv.py`, `cogis_scraper.py`, `bradenhead_scraper.py`) and any Python added later.  It checks four things: whether the method produces correct data, whether the code is clean and maintainable, whether it wastes requests or time, and whether it meets the standards a team reviewer would hold it to, including docstrings and comments.

The review produces a findings file.  It doesn't change code.

## Ground rules

- Don't edit, reformat, or auto-fix any script during the review.  Run every tool in check or diff mode only.
- Keep tool caches and the virtual environment outside the repo folder so the review leaves nothing behind.
- Record every finding in the findings file, even small ones.  Triage happens after the review, not during it.
- Separate what the code does from what the data says.  A data problem (for example, plugged wells on an unplugged list) is logged as a data note, not a code defect.
- Don't fix anything until git is initialized.  Fixes then land as separate commits so each one can be checked against the baseline.

## Step 0: Set up a review environment

Create a scratch environment outside the repo and install the review tools.  Python 3.13 is the target.

```
python -m venv %USERPROFILE%\venvs\cow-review
%USERPROFILE%\venvs\cow-review\Scripts\pip install requests ruff mypy types-requests pytest
```

On macOS or Linux, use `~/venvs/cow-review/bin/` in place of the Windows path.

Run every command below from outside the repo, passing the repo path, or add the cache flags shown so no `.ruff_cache` or `.mypy_cache` folder appears in the repo.

## Step 1: Capture a baseline

Any later refactor has to reproduce today's outputs, so record them before anything changes.

1. Record row counts and a SHA-256 hash for each CSV in `op/`.
2. Record the blank count for every column in `cogis_scout_data.csv` and `bradenhead_summary.csv`.
3. Record the distinct values and counts for `bh_flow_start`, `bh_flow_end`, `fluid_type`, and `well_status`.
4. Save all of it to `docs/reviews/baseline_YYMMDD.md`.

The HTML caches aren't in this folder.  A true regression test (old code and new code parsing the same pages) needs them, so either copy `op/html_cache` and `op/bradenhead_cache` from a saved copy or run both scrapers once to rebuild them.  A fresh run takes about 47 minutes at the 1 second delay and may differ from the committed CSVs if ECMC has updated records, so the archive copy is the better baseline.

## Step 2: Automated checks

Tools find the mechanical problems fast.  Their output is evidence for the findings file, not the verdict.  Triage each rule hit as a real problem, a style preference, or noise.

The repo's `pyproject.toml` holds the rule set, docstring convention, and mypy settings below, so from the repo root the short forms `ruff check .`, `ruff format --check .`, and `mypy` run the same checks.  The full commands are kept here for reviewing code that doesn't have the config yet.

Lint, using a rule set close to what most Python teams enforce:

```
ruff check --no-cache --target-version py313 ^
  --select E,W,F,I,B,UP,SIM,PL,D,ANN,PTH,RET ^
  --config "lint.pydocstyle.convention='google'" ^
  --statistics <repo>\*.py
```

Drop `--statistics` to get line-level output for the findings file.

Formatting, diff only:

```
ruff format --no-cache --diff <repo>\*.py
```

Types:

```
mypy --python-version 3.13 --strict --cache-dir=%TEMP%\mypy_cache <repo>\*.py
```

`--strict` will fail on untyped code.  That's expected on a first pass.  Record the count, and treat full type hints as a target rather than a blocker.

What each rule group covers, so the triage is quick:

| Code | Covers |
|---|---|
| E, W | PEP 8 layout and whitespace |
| F | Pyflakes: unused imports, undefined names |
| I | Import order |
| B | Bugbear: likely bugs and risky patterns |
| UP | Syntax that has a newer equivalent in 3.13 |
| SIM | Code that can be simplified |
| PL | Pylint subset: magic numbers, complexity, too many branches |
| D | Docstrings (Google style) |
| ANN | Missing type hints |
| PTH | `os.path` and `open()` where `pathlib` fits |
| RET | Return statement consistency |

## Step 3: Manual review

Read each script top to bottom once for intent, then again against the checklist below.  Work in this order, since a methodology problem can make the style findings moot.

### 3.1 Methodology and data correctness

This section matters most because the outputs feed a published article series.

- Does each parsed field match the live page?  Pick 10 wells at random, plus 5 with a blank in a field that should usually be populated, and compare every output column against the page by hand.
- When a field is blank, is it absent on the page or did the regex miss it?  A silent miss is a defect.  An honest absence isn't.
- Are derived fields defined so a reader would agree with them?  Check every flag and summary column against its README definition and against the distinct values found in Step 1.
- Are values normalized consistently (case, units, `--` for blank)?  Mixed case in a category field splits counts downstream.
- Does each output record when the data was retrieved?  Without a retrieval date per well, the snapshot can't be cited precisely.
- Is a failed fetch distinguishable from a well with no records?  Both currently produce a row; check whether the output tells them apart.
- Are join keys built the same way in every script?

### 3.2 Structure and duplication

- Logic repeated across scripts: constants, session setup, API number conversion, the fetch-and-cache loop, the CLI block.  Each repeat is a place for the scripts to drift apart.
- Functions doing more than one job.  `main()` in both scrapers reads input, fetches, parses, summarizes, and writes.
- Module-level code that runs on import.  Every script should be importable without side effects so tests can call its functions.
- Dead or one-time code still in the run path, such as migration logic for an earlier version.
- Hard-coded paths that assume the working directory.  Paths should resolve from the script location or from arguments.

### 3.3 Robustness and error handling

- Files opened without a context manager.
- Crashes on empty input (for example, indexing the first row of an empty list).
- Network errors: is a timeout retried?  Are HTTP 429 and 5xx responses treated differently from a 404?  Does a transient failure get logged in a way that's easy to find after a 47 minute run?
- Encoding: where is `errors='replace'` used, and could it hide a real problem?
- Partial writes: if a run dies while writing a CSV, is the old file lost?
- Input validation: what happens with a malformed `API_10`?

### 3.4 Efficiency

Runtime is set by the 1 second delay, not by parsing.  Two scrapers over 1,396 wells is about 47 minutes of waiting and a few seconds of CPU.  Efficiency review here means not making requests that aren't needed and not doing repeated work at startup.  It doesn't mean concurrency, which would break the rate limit and isn't in scope.

- Does every run do work proportional to the cache size before fetching anything (for example, reading every cached file to purge stale ones)?
- Are failed fetches retried on the next run, and is that the intended behavior?
- Are regexes compiled once where they run in a loop?  Minor here, but reviewers notice.
- Is the whole input held in memory when streaming would do?  At 1,396 rows this is fine; note it only if the design should scale.

### 3.5 Standards and readability

- PEP 8 layout, enforced by `ruff format`.
- Names that say what a value is.  Single letters are fine for short loops, not for values that live across a function.
- Magic numbers and strings pulled into named constants with a short reason (`DELAY` already does this well).
- `argparse` in place of manual `sys.argv` handling, with `--help` text.
- `logging` in place of `print` for progress and errors, so verbosity can be controlled.
- Configuration that a user must change (the User-Agent contact address) read from an argument or environment variable, not edited in source.
- Type hints on every function signature.

### 3.6 Docstrings and comments

Team reviews fail code for missing docstrings and for noisy comments about equally often.  The target is useful annotation, not more annotation.

- Every module has a docstring stating what it does, its inputs, its outputs, and how to run it.  `json2csv.py` has none today.
- Every public function has a Google-style docstring with Args, Returns, and Raises where they apply.
- Comments explain why, not what.  `# seconds between requests; stay polite` is a good comment.  A comment restating the line below it isn't.
- Non-obvious regexes carry a comment showing an example of the text they match.
- Docstrings and comments are accurate to the current code.  Check version notes ("v2", "fix from v1") and decide whether they belong in a public repo or in the git history.
- No commented-out code.

### 3.7 Public repo hygiene

- No credentials, tokens, or personal paths in code or comments.
- The contact email in the User-Agent is intentional and acceptable to publish.
- Every tool or library named in the README is actually used in the code.

### 3.8 Testability

- Can each parse function be tested against a saved HTML file with no network?
- Which functions need a sample page fixture, and which pages make good fixtures (normal well, well with no bradenhead tests, "could Not be found" page, well with odd casing records)?
- List the tests that should exist in `tests/` under `pytest` before any refactor starts.

## Step 4: Items to confirm in this codebase

These came up in a first read of the code and outputs on 2026-11-17.  They're starting points for the reviewer to confirm or rule out, not settled findings.

- `bh_ever_flow` counts any value other than `NO FLOW`, `--`, or blank as flow.  The tests table includes `DOWN TO 0` (813 values) and `Down to Zero` (130), which may describe a pressure bleed-down rather than a flow.  Decide what the flag should mean and whether those values belong in it.
- Flow values come in mixed case (`WHISPER` and `Whisper`, `CONTINUOUS` and `Continuous`).
- `cogis_scraper.py` `strip_tags` doesn't decode HTML entities, while the bradenhead version decodes `&nbsp;` and `&amp;`.  Check whether any field in the scout output is blank because an entity sat between a label and its value.
- Blank counts in `cogis_scout_data.csv`: `vertical_td_ft` 682, `cement` 597, `spud_date` 304, `pb_depth_ft` 137, `casing_strings` 138.  Sample each against live pages to separate parser misses from absent data.
- The `well_status` regex runs with `re.I`, so `[A-Z]{2}` matches any two letters.
- 29 wells show status `PA` (plugged and abandoned) on the unplugged list.  This is a data note for the article series, not a code defect, but the review should log it.
- `related_links` is cut to 5 entries with no explanation.
- `bh_max_surf_casing_psi` truncates with `int()` rather than rounding.
- `json2csv.py` builds its column list from the first feature only.  A later feature with an extra key would raise an error.  Esri date attributes, if present, are written as epoch milliseconds.
- `json2csv.py` opens the JSON without an explicit encoding, which matters on Windows.
- Both scrapers index `summaries[0]` or assume a non-empty well list.
- The v1 cache purge in `cogis_scraper.py` reads every cached page on every run.
- Default paths are relative to the working directory, so the scripts only run correctly from the repo root.
- The automated pass on 2026-11-17 found 59 lint hits with the rule set above (mostly missing type hints, long lines, `open()` without `pathlib`, and missing docstrings), 3 files that `ruff format` would change, and 30 `mypy --strict` errors.

## Step 5: Record findings

Write findings to `docs/reviews/YYMMDD_code_review.md`, one table per script.  The row below shows the format only; it isn't a confirmed finding.

| ID | Severity | Category | Location | Finding | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| CS-01 | Major | Methodology | `cogis_scraper.py:41` | Entities not decoded before regex parse | 3 sampled wells blank on page-present field | Decode with `html.unescape` before matching |

Severity:

- **Blocker**: produces wrong data in a published output, or crashes on expected input.
- **Major**: a likely defect, a silent failure path, or a gap a team reviewer would reject the code over (no tests, no docstrings on public functions, duplicated core logic).
- **Minor**: works but falls short of standard practice (no type hints, `print` for logging, manual argv parsing).
- **Nit**: style or naming preference.

Category is one of: Methodology, Structure, Robustness, Efficiency, Standards, Documentation, Hygiene, Testability, Data note.

End the findings file with a short list of recommended changes in the order they should be made.

## Step 6: Exit criteria

The code is ready for a team review when all of these hold:

- No Blocker or Major findings open.
- `ruff check` with the Step 2 rule set reports zero errors, or each remaining rule is disabled in `pyproject.toml` with a one-line reason.
- `ruff format --check` passes.
- `mypy --strict` passes, or plain `mypy` passes with `disallow_untyped_defs = true`.
- `pytest` passes with parse tests against saved HTML fixtures for both scrapers and for `json2csv.py`.
- Rerunning the refactored scrapers against the baseline cache reproduces the baseline CSVs exactly, or every difference is listed and explained in the commit that caused it.
- Every module and public function has an accurate docstring.

## Step 7: After the review

1. Wait for git to be initialized before changing any code.
2. Add `pyproject.toml` with the ruff and mypy settings from Step 2 so the checks run the same way every time.
3. Write the tests first, against the current code, so they pin today's behavior.
4. Make one group of related fixes per commit, rerun the tests and the baseline diff after each, and reference the finding IDs in the commit message.
5. Methodology changes that alter output values (for example, redefining `bh_ever_flow`) go in their own commit, with the before and after counts in the message and a matching update to the README and data dictionary.
