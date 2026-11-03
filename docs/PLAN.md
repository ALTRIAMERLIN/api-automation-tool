# PLAN — API Automation & Data Integration Tool (v1)

Read SPEC.md, ACCEPTANCE.md and REVIEW.md completely before starting T00. SPEC defines **what** to build. ACCEPTANCE defines **how it is checked**. REVIEW defines **how the work is reviewed and published**. This file defines **the order of the work**.

Totals: 32 tasks (T00–T31), 6 review pushes (CP0–CP5). CP1–CP5 are the load-bearing review checkpoints.

---

## EXECUTION GUARDRAILS (mandatory, read twice)

- **G1 — Order.** Work task by task in the order below. Do not start a task until every task it depends on is done. Do not work on two tasks at once. One task = one commit on `review/v1`, with the message `T<NN>: <task title>`. Review fixes are separate commits (see REVIEW.md).
- **G2 — Gate before every commit.** Run `.venv\Scripts\python -m ruff format .`, then `.venv\Scripts\python -m ruff check .`, then `.venv\Scripts\python -m pytest -q`. All three must pass, with the whole test suite green, not only the new tests. If they do not pass, do not commit.
- **G3 — Never edit tests or expectations to force a pass.** A failing test means the production code is wrong. You may not change a test, a fixture, a file in `tests/fixtures/expected/`, or a value copied from ACCEPTANCE.md to make it pass. Report the failure instead (G5). The single exception: a test you wrote in the **current** task that contradicts ACCEPTANCE.md may be corrected to match ACCEPTANCE.md. Note that in the commit body.
- **G4 — Spec doubts.** If you believe SPEC.md or ACCEPTANCE.md is wrong, contradictory or incomplete, stop and escalate. Do not choose an interpretation yourself.
- **G5 — Two strikes.** If the same test fails on two consecutive test runs, with a fix attempt in between, stop work on that stretch and escalate. Do not try a third fix.
- **G6 — Independent expectations.** Every expected value in a test comes from ACCEPTANCE.md or SPEC.md by transcription, or is worked out by hand in the test file with a comment that shows the working. Never produce an expected value by running production code and pasting its output.
- **G7 — What goes to review.** Only tool code goes to the review remote: `src/`, `tests/`, `docs/`, `README.md`, `LICENSE`, `pyproject.toml`, `constraints.txt`, `.gitignore`, `.github/`. Demo-video code and assets never go there: scripts, recordings and edit projects live in `video/`, which is git-ignored. The same holds for `ops/` (review scripts, findings, logs) and `data/`. (The in-app demo mode under `src/apitool/demo/` **is** tool code and is reviewed.)
- **G8 — No early publishing.** Never push to GitHub, and never create any remote other than `entire`, until CP5 has zero open findings. The only exception is T31 itself.
- **G9 — History is append-only.** Never force-push, rebase, amend a pushed commit, delete branches, or move `baseline`. Never run `git reset --hard` or `git clean`.
- **G10 — No scope creep.** Do not add dependencies, features, settings, pages or endpoints that SPEC.md does not list. "Phased later" items (SPEC §4.2) stay unbuilt.
- **G11 — Secrets.** Use only the demo credentials and the test-only strings from ACCEPTANCE.md. Never put a real API key anywhere. Never print a secret to the terminal.
- **G12 — Offline tests.** No test may touch the network. The `conftest.py` network block (T01) stays in place.
- **G13 — Entire CLI.** Run `entire` commands and git commands against the `entire` remote **only** through the script files in `ops/` described in REVIEW.md. Each of those scripts sets `ENTIRE_TOKEN_STORE=file` inside itself. Use only the two `entire` subcommands that REVIEW.md lists.
- **G14 — Shell.** The shell is Windows PowerShell 5.1. Use `;` and not `&&`. Never redirect with `>` into files that must be ASCII or UTF-8, because `>` writes UTF-16. Use `Out-File -Encoding ascii` or `Set-Content -Encoding UTF8` instead. Never start long-running processes (`apitool serve`) from the agent shell except where a task says so explicitly, and then stop them when the task is done.

**How to escalate:** write `ops/ESCALATION.md` with: the task ID, the exact failing command, the failing output (the last 60 lines), what you tried, and your best explanation. Then stop and tell the human. Do not continue with later tasks.

**Python:** always use `.venv\Scripts\python` (created in T01 from `C:\Program Files\Python311\python.exe`).

---

## Module contracts (shared by the tasks below)

These signatures are fixed. Tests call them exactly as written. Use type hints. Python 3.11 syntax only.

```python
# errors.py: as SPEC §16. AppError.__init__(self, message: str); ConfigError.__init__(self, errors: list[tuple[str, str]])
#            HttpError.__init__(self, message: str, status_code: int)

# redact.py
def redact(text: str, secrets: Iterable[str]) -> str
def strip_query(url: str) -> str
def register_secrets(secrets: Iterable[str]) -> None
def unregister_secrets(secrets: Iterable[str]) -> None
class RedactingFilter(logging.Filter)          # uses the registered secrets
def install_filter() -> None                   # adds one RedactingFilter to logging.getLogger("apitool"); idempotent
# Every module logs through logging.getLogger("apitool") exactly. No child loggers.

# config.py
class JobConfig(BaseModel)                     # SPEC §5.1
def build_job_config(data: Mapping[str, Any]) -> JobConfig   # pydantic validation, then cross-field rules; raises ConfigError
def job_config_from_form(form: Mapping[str, str]) -> JobConfig  # parses textareas, ints, checkbox ("on" = True), calls build_job_config
def job_config_to_form(cfg: JobConfig) -> dict[str, str]
def parse_query_params(text: str) -> list[tuple[str, str]];  def format_query_params(pairs) -> str
def parse_headers(text: str) -> list[tuple[str, str]];       def format_headers(pairs) -> str
def parse_fields(text: str) -> list[str];                    def format_fields(items) -> str
def parse_renames(text: str) -> list[tuple[str, str]];       def format_renames(pairs) -> str

# jsonpath.py
MISSING: object
def get_path(obj: Any, path: str) -> Any

# http_client.py
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
BACKOFF = (1, 2, 4)
def build_url(cfg: JobConfig, secret: str | None, page_params: Mapping[str, str | int]) -> str
def add_auth_query(url: str, cfg: JobConfig, secret: str | None) -> str   # used for next_url follow-ups
def build_headers(cfg: JobConfig, secret: str | None) -> dict[str, str]
class Fetcher:
    def __init__(self, cfg: JobConfig, secret: str | None, transport: httpx.BaseTransport,
                 sleep: Callable[[float], None]): ...
    retries: int            # total retries so far
    last_status: int | None
    def get_json(self, url: str) -> Any       # one page, including retries (SPEC §6.4–6.5)
    def close(self) -> None                   # also usable as a context manager

# pagination.py
@dataclass class Progress: pages_fetched: int = 0; records_fetched: int = 0
@dataclass class FetchResult: records: list[Any]; warnings: list[str]
def fetch_all(cfg: JobConfig, fetcher: Fetcher, progress: Progress) -> FetchResult
def fetch_first_page(cfg: JobConfig, fetcher: Fetcher) -> list[Any]

# transform.py
def flatten(obj: dict, prefix: str = "") -> dict
def to_record(item: Any) -> dict                 # wraps non-dicts as {"value": item}, then flattens
def render_csv(v: Any) -> str
def render_xlsx(v: Any) -> Any
def sanitize_text(s: str) -> str
def csv_cell(v: Any) -> str                      # sanitize_text(v) if isinstance(v, str) else render_csv(v)
def clean_xlsx_text(s: str, sanitize: bool) -> tuple[str, bool]  # (cleaned, was_truncated), SPEC §9.5

# pipeline.py
@dataclass class PipelineResult:
    header: list[str]; rows: list[list[Any]]      # rows hold raw flattened values (not rendered)
    exported_keys: list[str]; duplicates_removed: int; records_missing_key: int
    already_seen_skipped: int; records_exported: int; warnings: list[str]
def build_rows(raw_records: list[Any], cfg: JobConfig, stored_keys: set[str]) -> PipelineResult

# export.py
def slugify(name: str) -> str
def export_filename(job_name: str, started_at: datetime, run_id: int, fmt: str) -> str
def safe_export_path(exports_dir: Path, name: str) -> Path | None
def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> list[str]    # returns warnings
def write_xlsx(path: Path, header: list[str], rows: list[list[Any]]) -> list[str]

# storage.py
@dataclass class JobRecord: id: int; name: str; config: JobConfig; created_at: str; updated_at: str
@dataclass class RunStats: pages_fetched=0; records_fetched=0; retries=0; duplicates_removed=0;
                           records_missing_key=0; already_seen_skipped=0; records_exported=0
@dataclass class RunRecord: (one attribute per `runs` column; warnings: list[str] decoded from warnings_json)
class Storage:
    def __init__(self, data_dir: Path)          # creates the dirs and the schema
    db_path: Path; exports_dir: Path
    def create_job(self, cfg: JobConfig, now: datetime) -> int
    def get_job(self, job_id: int) -> JobRecord | None
    def get_job_by_name(self, name: str) -> JobRecord | None      # case-insensitive
    def list_jobs(self) -> list[JobRecord]                          # sorted by name_key
    def update_job(self, job_id: int, cfg: JobConfig, now: datetime) -> bool   # returns state_reset
    def delete_job(self, job_id: int) -> None
    def set_secret(self, job_id: int, value: str) -> None
    def get_secret(self, job_id: int) -> str | None
    def delete_secret(self, job_id: int) -> None
    def start_run(self, job_id: int, job_name: str, trigger: str, now: datetime) -> int
    def finish_run_success(self, run_id: int, stats: RunStats, output_file: str | None, message: str,
                           warnings: list[str], finished_at: datetime,
                           job_id: int, exported_keys: list[str], incremental: bool) -> None
    def finish_run_failed(self, run_id: int, stats: RunStats, error_type: str, error_message: str,
                          finished_at: datetime) -> None
    def get_run(self, run_id: int) -> RunRecord | None
    def list_runs(self, limit: int = 100) -> list[RunRecord]
    def last_run_for_job(self, job_id: int) -> RunRecord | None
    def get_seen_keys(self, job_id: int) -> set[str]
    def reset_state(self, job_id: int) -> None
    def get_setting(self, name: str, default: str) -> str
    def set_setting(self, name: str, value: str) -> None

# runner.py
DEMO_HOST = "demo.api-automation-tool.local"
def utc_now() -> datetime
def format_ts(dt: datetime) -> str               # "2026-11-04T10:00:00Z"
def make_transport(url: str, dataset_version: int) -> httpx.BaseTransport
def resolve_secret(raw: str | None) -> str | None # env:NAME handling, raises ConfigError
@dataclass class RunResult: run_id: int; status: str; message: str | None; warnings: list[str];
                            error_type: str | None; error_message: str | None; exit_code: int
@dataclass class PreviewResult: records_count: int; columns: list[str]; rows: list[list[str]];
                                error_type: str | None; error_message: str | None
def run_job(storage, job_id, trigger, *, transport=None, sleep=None, now=None) -> RunResult
def preview_job(storage, job_id, *, transport=None, sleep=None) -> PreviewResult
# runner calls export.write_csv / export.write_xlsx / pipeline.build_rows through the module
# (`from apitool import export`, then `export.write_csv(...)`), so tests can monkeypatch them.

# demo/api.py:  class DemoApi: __init__(self, dataset_version: int = 1); handle(self, request) -> httpx.Response; requests: list[httpx.Request]
# demo/jobs.py: DEMO_JOBS: list[tuple[dict, str]]  (config data, secret); def setup_demo_jobs(storage, now) -> tuple[int, int]
# cli.py:       def main(argv: list[str] | None = None) -> int
# web/app.py:   def create_app(data_dir: Path) -> FastAPI
```

---

## Phase 0 — Repository and wiring

### T00 — Empty skeleton, baseline branch, review branch
- Depends on: nothing (the planning commits are already on `main`).
- Inputs: SPEC §17.8.
- Steps:
  1. On `main`, create `.gitignore` with exactly the SPEC §17.8 lines, `README.md` containing `# API Automation Tool` and a blank line, an empty `src/apitool/.gitkeep`, and an empty `tests/.gitkeep`.
  2. `git add .gitignore README.md src/apitool/.gitkeep tests/.gitkeep`, then `git commit -m "chore: empty project skeleton"`.
  3. `git branch baseline`, then `git switch -c review/v1`.
- Outputs: branches `main`, `baseline` (same commit) and `review/v1`.
- Done when: `git ls-tree -r --name-only baseline` prints exactly `.gitignore`, `README.md`, `docs/ACCEPTANCE.md`, `docs/BRIEF.md`, `docs/PLAN.md`, `docs/REVIEW.md`, `docs/SPEC.md`, `src/apitool/.gitkeep`, `tests/.gitkeep`. `git rev-list --max-parents=0 review/v1` equals `git rev-list --max-parents=0 baseline` (one shared root). `git status` shows that `book-log.txt` is ignored, not untracked.

### T01 — Packaging, tooling, smoke test
- Depends on: T00.
- Steps:
  1. `& "C:\Program Files\Python311\python.exe" -m venv .venv`.
  2. Write `pyproject.toml` exactly as in the box below.
  3. Create `src/apitool/__init__.py` (`__version__ = "1.0.0"`), `src/apitool/__main__.py` (`import sys; from apitool.cli import main; sys.exit(main())`), and a minimal `src/apitool/cli.py` with `main(argv=None) -> int` that supports only `--version` for now (argparse; prints `apitool 1.0.0`; returns 0). Delete both `.gitkeep` files.
  4. `.venv\Scripts\python -m pip install -e ".[dev]"`.
  5. `.venv\Scripts\python -m pip freeze --exclude-editable | Out-File -Encoding ascii constraints.txt`.
  6. `tests/conftest.py`: an autouse fixture that monkeypatches `httpx.HTTPTransport.handle_request` to raise `RuntimeError("network disabled in tests")`.
  7. `tests/test_smoke.py` for AC-01.
- `pyproject.toml`:
  ```toml
  [build-system]
  requires = ["setuptools==75.8.0"]
  build-backend = "setuptools.build_meta"

  [project]
  name = "api-automation-tool"
  version = "1.0.0"
  description = "Connect REST APIs, handle pagination, flatten JSON and export CSV or Excel from a simple local web UI."
  readme = "README.md"
  license = {text = "MIT"}
  requires-python = ">=3.11,<3.13"
  dependencies = [
    "fastapi==0.115.12",
    "uvicorn==0.34.2",
    "jinja2==3.1.6",
    "python-multipart==0.0.20",
    "httpx==0.28.1",
    "openpyxl==3.1.5",
    "pydantic==2.11.4",
  ]

  [project.optional-dependencies]
  dev = ["pytest==8.3.5", "ruff==0.11.8"]

  [project.scripts]
  apitool = "apitool.cli:main"

  [tool.setuptools.packages.find]
  where = ["src"]

  [tool.setuptools.package-data]
  apitool = ["web/templates/*.html", "web/static/*", "demo/datasets/*.json"]

  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["src"]
  addopts = "-ra"

  [tool.ruff]
  line-length = 100
  target-version = "py311"

  [tool.ruff.lint]
  select = ["E", "F", "I", "B", "UP", "S"]

  [tool.ruff.lint.per-file-ignores]
  "tests/**" = ["S101", "S105", "S106", "S603", "S607"]
  "src/apitool/demo/**" = ["S105", "S106"]
  ```
- Done when: AC-01 passes. `constraints.txt` is ASCII and lists `fastapi==0.115.12`, `httpx==0.28.1` and `openpyxl==3.1.5`. If any install fails, escalate (SPEC §2).

### T02 — Entire review wiring (CP0, wiring only)
- Depends on: T01.
- Steps: follow REVIEW.md §3 (create the `ops/` scripts), §4 (add the remote, push `baseline` and `review/v1`, create the trail, record the trail number) and §5 (wait for findings once). Fix any findings that relate to T00–T01 using the REVIEW.md §6 loop.
- Outputs (local only, git-ignored): `ops/*.ps1`, `ops/trail-number.txt`, `ops/review-log.md`, `ops/findings/*.json`, `ops/findings-schema-notes.md`.
- Done when: the trail exists, its number is in `ops/trail-number.txt`, and the open-findings count is 0.

---

## Phase 1 — Core fetch and transform engine → **REVIEW CHECKPOINT CP1**

### T03 — errors.py and redact.py
- Depends on: T01. Inputs: SPEC §16, §17.2–17.4. Output: `src/apitool/errors.py`, `src/apitool/redact.py`, `tests/test_errors_redact.py`.
- Done when: AC-02 passes.

### T04 — config.py (JobConfig, validation, text parsers)
- Depends on: T03. Inputs: SPEC §5. Output: `src/apitool/config.py`, `tests/test_config.py`.
- Notes: Range rules use `Field(ge=..., le=...)`. Single-field rules (name regex, url rules, header-name regex, records_path segments) use `field_validator`. Cross-field rules (auth requirements, pagination requirements, incremental requires dedup_key) run in `build_job_config` after model validation, each producing `(field, message)`. Map pydantic errors to `(str(err["loc"][0]), err["msg"])`. `JobConfig` stores pairs as tuples, and `model_dump_json()` turns them into JSON arrays. `build_job_config` must accept that JSON form back (lists of 2-item lists), so that round trips work.
- Done when: AC-03 and AC-04 pass.

### T05 — jsonpath.py
- Depends on: T01. Inputs: SPEC §7. Output: `src/apitool/jsonpath.py`, `tests/test_jsonpath.py`.
- Done when: AC-05 passes.

### T06 — Demo datasets and DemoApi
- Depends on: T05. Inputs: SPEC §19.1–19.2, ACCEPTANCE §2.
- Output: `src/apitool/demo/__init__.py`, `demo/datasets/*.json` (copied verbatim from ACCEPTANCE §2, UTF-8 **without** BOM; write them with your file-writing tool, not with PowerShell `Set-Content`/`Out-File`, which add a BOM or use UTF-16), `demo/data.py`, `demo/api.py`, `tests/test_demo_api.py`.
- Notes: DemoApi routes on `request.url.path`. Query values come from `request.url.params`. A non-integer value where an int is expected → 400. Each response is `httpx.Response(status, json=...)`, except the special bodies listed in SPEC §19.2 (`content=` with an explicit `Content-Type`). Per-instance counters live on `self`.
- Done when: AC-06 and AC-07 pass.

### T07 — Expected fixture files (transcription only)
- Depends on: T00. Inputs: ACCEPTANCE §3.
- Output: `tests/fixtures/expected/` with `orders_dedup_rows.json`, `orders_nodedup_rows.json`, `orders_v2_new_rows.json`, `orders_v2_full_rows.json`, `events_rows.json`, `customers_xlsx.json`, `products_xlsx.json`, `run_stats.json`; and `tests/test_expected_fixtures.py`.
- Rule: write these by hand from ACCEPTANCE.md. `orders_v2_full_rows.json` is built by hand as ACCEPTANCE §3.9 describes. Do not import or run `apitool` here.
- Done when: AC-08 passes.

### T08 — http_client.py: URL, headers, single-request validation
- Depends on: T04, T06. Inputs: SPEC §6.1–6.4. Output: `src/apitool/http_client.py`, `tests/test_http_client.py`.
- Notes: `Fetcher` creates the `httpx.Client` (SPEC §6.1). `get_json` calls `self._client.get(url, headers=...)`. The User-Agent and Accept headers are set on the client, and `build_headers` returns only the custom and auth headers. Size check: `len(response.content)`. The retry loop arrives in T09. In this task, implement `get_json` with the full retry loop structure but cover only single-attempt behaviors with tests. Pass a sleep stub everywhere.
- Done when: AC-09, AC-10 and AC-11 pass.

### T09 — Retry policy
- Depends on: T08. Inputs: SPEC §6.5. Output: retry logic finished in `http_client.py`, `tests/test_retry.py`.
- Done when: AC-12 passes, and AC-11 still passes.

### T10 — pagination.py
- Depends on: T09. Inputs: SPEC §8. Output: `src/apitool/pagination.py`, `tests/test_pagination.py`.
- Notes: log one INFO line per page (SPEC §18) with `strip_query(url)`. Update `progress` after each successful page. For next_url, keep a set of requested URLs and a set of used cursors.
- Done when: AC-13, AC-14 and AC-15 pass.

### T11 — transform.py
- Depends on: T01. Inputs: SPEC §9.1, §9.3–9.5. Output: `src/apitool/transform.py`, `tests/test_transform.py`.
- Done when: AC-16 and AC-17 pass.

### T12 — pipeline.py
- Depends on: T05, T07, T11. Inputs: SPEC §9.2, §10. Output: `src/apitool/pipeline.py`, `tests/test_pipeline.py`.
- Notes: in the tests, render each row as `[csv_cell(v) for v in row]` and the header as `[sanitize_text(h) for h in header]`, then compare with the expected JSON files. `csv_cell` sanitizes only values whose original type is `str`, so floats such as `-12.5` are never prefixed (SPEC §11.3).
- Done when: AC-18 to AC-21 pass.

### ▶ CP1 — Review checkpoint: core fetch/transform engine
Self-check before pushing: reread SPEC §6–§9 and tick each rule off against the code. Then follow REVIEW.md §5–§6 (push, wait, fix, re-push until zero open findings). Do not start T13 until CP1 is clean.

---

## Phase 2 — Export correctness → **REVIEW CHECKPOINT CP2**

### T13 — CSV writer
- Depends on: T12. Inputs: SPEC §11.2–11.3. Output: `write_csv` in `src/apitool/export.py`, `tests/test_export_csv.py`.
- Done when: AC-22 and AC-23 pass.

### T14 — XLSX writer
- Depends on: T13. Inputs: SPEC §9.5, §11.2, §11.4. Output: `write_xlsx`, `tests/test_export_xlsx.py`.
- Done when: AC-24 and AC-25 pass.

### T15 — File names and safe paths
- Depends on: T13. Inputs: SPEC §11.1, §14.4 (download). Output: `slugify`, `export_filename`, `safe_export_path`, `tests/test_export_names.py`.
- Notes: `safe_export_path` returns `None` if `name` is empty, contains `/` or `\`, is absolute, or if the resolved path is not inside `exports_dir.resolve()` (use `Path.is_relative_to`). Otherwise it returns the resolved path.
- Done when: AC-26 passes.

### ▶ CP2 — Review checkpoint: export correctness
Self-check: reread SPEC §9.3–9.5 and §11. Open one CSV in a text editor and one XLSX through openpyxl in a REPL to confirm the formatting. Then follow REVIEW.md §5–§6. Do not start T16 until CP2 is clean.

---

## Phase 3 — State, run log, incremental sync, CLI → **REVIEW CHECKPOINT CP3**

### T16 — storage.py: schema, jobs, secrets, settings
- Depends on: T04. Inputs: SPEC §13. Output: `src/apitool/storage.py` (partial), `tests/test_storage_jobs.py`.
- Notes: a duplicate `name_key` → catch `sqlite3.IntegrityError` and raise `ConfigError([("name", "a job with this name already exists")])`. All SQL uses `?` placeholders.
- Done when: AC-27 passes.

### T17 — storage.py: runs
- Depends on: T16. Inputs: SPEC §12.1 step 2, §12.3, §13. Output: run methods, `tests/test_storage_runs.py`.
- Notes: `start_run` uses `BEGIN IMMEDIATE` on a connection opened with `isolation_level=None` and does stale-marking, the busy check and the insert inside it. Timestamps are stored with `runner.format_ts`. To avoid an import cycle, put `format_ts` and `parse_ts` in a small `src/apitool/timeutil.py` and re-export `format_ts` from runner.
- Done when: AC-28 passes.

### T18 — storage.py: sync state and automatic reset
- Depends on: T17. Inputs: SPEC §10. Output: seen-key methods, `update_job` reset logic, the seen-key insert in `finish_run_success` (same transaction; `INSERT OR IGNORE` with `first_run_id = run_id`), `tests/test_storage_state.py`.
- Done when: AC-29 passes, and the storage half of AC-36 passes (calling `update_job` directly).

### T19 — runner.py and demo jobs
- Depends on: T10, T12, T14, T15, T18. Inputs: SPEC §12, §17.2–17.4, §18, §19.3. Output: `src/apitool/runner.py`, `src/apitool/demo/jobs.py`, `tests/test_runner.py`.
- Notes: build the redaction list from the resolved secret, plus the base64 basic token when auth is `basic`. Call `register_secrets` at the start and `unregister_secrets` in `finally`. Close the Fetcher in `finally`. `make_transport` reads nothing from storage; `run_job` reads `demo_dataset_version` and passes it in. `RunResult.exit_code` is `0` on success and `error.exit_code` on failure. For the success path, write the file **before** calling `finish_run_success`. `setup_demo_jobs` creates the missing demo jobs and their secrets.
- Done when: AC-30 to AC-33 pass.

### T20 — Incremental sync in the runner
- Depends on: T19. Inputs: SPEC §10, ACCEPTANCE §3.9. Output: incremental path in `run_job` (load stored keys when `incremental`; pass exported keys to `finish_run_success`), `tests/test_incremental.py`.
- Done when: AC-34 and AC-35 pass.

### T21 — Full CLI
- Depends on: T20. Inputs: SPEC §15, §18. Output: finished `src/apitool/cli.py`, `tests/test_cli.py`.
- Notes: `main` configures logging (SPEC §18) and calls `install_filter()`. Data dir order: `--data-dir`, then `APITOOL_DATA_DIR`, then `./data`. Wrap the dispatch in `try/except AppError` (stderr message, return `exit_code`) and `except Exception` (stderr `internal error: <ClassName>`, return 3). `serve` is not run in tests; only its argument parsing is tested (`--port 80` → 2).
- Done when: AC-37 passes.

### ▶ CP3 — Review checkpoint: state and incremental sync
Self-check: reread SPEC §10, §12, §13, §15 and §17. Confirm by reading the code that the state commit happens only in `finish_run_success`, after the file rename. Then follow REVIEW.md §5–§6. Do not start T22 until CP3 is clean.

---

## Phase 4 — Web UI wiring → **REVIEW CHECKPOINT CP4**

### T22 — App factory, middleware, CSRF, base layout
- Depends on: T21. Inputs: SPEC §14.1–14.3, §14.6. Output: `src/apitool/web/__init__.py`, `web/app.py`, `templates/base.html`, `templates/error.html`, `static/style.css` (base styles), `static/app.js` (empty placeholder with a comment), `GET /healthz`, `tests/test_web_security.py`.
- Notes: use one `@app.middleware("http")` function that rejects bad hosts and adds the security headers to **every** response, including its own 400. CSRF is a helper `check_csrf(request_token: str)` that raises `HTTPException(403)`. A custom exception handler renders `error.html` for 403, 404, 409 and 400 with the SPEC texts.
- Done when: AC-38 and AC-39 pass (AC-39 covers the POST routes that exist at this point; extend the test in later tasks as routes are added).

### T23 — Jobs page and demo actions
- Depends on: T22. Inputs: SPEC §14.4 (`/`, `/demo/setup`, `/demo/dataset`), §19.4. Output: `templates/jobs.html`, routes, `tests/test_web_jobs.py` (part).
- Done when: AC-40 passes.

### T24 — Job create, edit and delete forms
- Depends on: T23. Inputs: SPEC §5.2–5.3, §14.4, §14.5. Output: `templates/job_form.html`, routes, more `tests/test_web_jobs.py`.
- Done when: AC-41 and the web half of AC-36 pass.

### T25 — Preview
- Depends on: T24. Inputs: SPEC §14.4 (preview). Output: `runner.preview_job`, `templates/preview.html`, route, `tests/test_web_preview.py`.
- Done when: AC-42 passes.

### T26 — Run trigger, run detail, history, download
- Depends on: T25. Inputs: SPEC §14.4 (runs). Output: `templates/run.html`, `templates/runs.html`, routes, `tests/test_web_runs.py`.
- Done when: AC-43 passes.

### T27 — Field toggling JS and visual polish
- Depends on: T26. Inputs: SPEC §14.5–14.6. Output: final `static/app.js` and `static/style.css`, `tests/test_web_render.py`.
- Notes: `app.js` runs on `DOMContentLoaded`. For each `select[name=auth_type]` and `select[name=pagination_type]`, it shows elements whose `data-show-for` contains the selected value and hides the rest (`hidden` attribute). Forms with `data-confirm` get a submit listener that calls `confirm(form.dataset.confirm)`. The manual check is the only time you may start `apitool serve` (G14). Stop it afterwards.
- Done when: AC-44 passes and the `manual:` line is in the commit body.

### ▶ CP4 — Review checkpoint: UI wiring
Self-check: reread SPEC §14 and §17. Confirm that no template prints a secret, every POST form has `csrf_token`, and no template uses inline script or style. Then follow REVIEW.md §5–§6. Do not start T28 until CP4 is clean.

---

## Phase 5 — Showcase, release gate, publish → **REVIEW CHECKPOINT CP5 (final)**

### T28 — Demo video (outside the repository; never reviewed, never committed)
- Depends on: T27 (CP4 clean). Inputs: SPEC §21.2.
- Steps: create `video/` (git-ignored). Write the shot list to `video/shotlist.md`. Start `apitool --data-dir video\data serve` and follow the storyboard. Recording is done by the human with a screen recorder. Your job is to prepare the data dir, the shot list and the exact click order in `video/shotlist.md`, and to stop the server afterwards. Ask the human for the uploaded video URL. If no URL is given, the README leaves out the video section.
- Done when: `video/shotlist.md` exists, `git status --porcelain` shows nothing from `video/`, and you have asked the human for the URL.

### T29 — README, LICENSE, CI, screenshots
- Depends on: T27. Inputs: SPEC §20 (CI), §21.1.
- Output: `README.md` (full), `LICENSE` (MIT, year 2026, holder `api-automation-tool contributors`), `.github/workflows/ci.yml`, `docs/images/*.png` (from demo mode, at most 1400 px wide, no personal data visible), `tests/test_readme.py`.
- Notes: the CI workflow cannot run until T31. Check it carefully against SPEC §20. Commands in the README must be copy-paste correct for PowerShell, with bash equivalents for Linux and macOS.
- Done when: AC-45 passes (the README walkthrough done manually in a fresh venv in a temporary folder, noted with a `manual:` line).

### T30 — Final release gate
- Depends on: T29. Output: `tests/test_repo_hygiene.py`.
- Steps: run the full gate (G2). Then, in a fresh temp data dir, run `apitool demo-setup` and `apitool run --job "<name>"` for each of the 5 demo jobs. Paste the outputs into the commit body.
- Done when: AC-46 and AC-47 pass.

### ▶ CP5 — Final review checkpoint: whole project
Follow REVIEW.md §5–§6 with the final-checkpoint settle rule (3 identical polls). Record the clean commit SHA in `ops/review-log.md` (AC-48).

### T31 — Publish to GitHub
- Depends on: CP5 clean.
- Steps: REVIEW.md §7 exactly.
- Done when: AC-49 holds.

---

## Dependency summary

```
T00 → T01 → T02(CP0)
T01 → T03 → T04 → T08 → T09 → T10 ─┐
T01 → T05 → T06 → T08               ├→ T12 → CP1 → T13 → T14, T15 → CP2
T00 → T07 ──────────────────────────┤
T01 → T11 ──────────────────────────┘
T04 → T16 → T17 → T18 → T19 → T20 → T21 → CP3 → T22 → T23 → T24 → T25 → T26 → T27 → CP4
CP4 → T28 (video, outside repo) ; T27 → T29 → T30 → CP5 → T31
```
Follow the strict numeric order even where the graph would allow parallel work (G1). T16 is numbered after CP2 on purpose: storage must not be started before export is reviewed.
