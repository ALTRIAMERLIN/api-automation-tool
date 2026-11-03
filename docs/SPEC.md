# SPEC — API Automation & Data Integration Tool (v1)

Status: frozen for execution. Source brief: `docs/BRIEF.md`.
Companion documents: `docs/PLAN.md` (tasks), `docs/ACCEPTANCE.md` (acceptance cases and the fixed demo dataset), `docs/REVIEW.md` (Entire review wiring).

Rule for the executor: every behavior below is a decision, not a suggestion. If something you need is not written here, stop and escalate (see PLAN.md, Execution Guardrails). Do not invent behavior.

---

## 1. Product summary

A local web tool, written in Python, that lets a non-technical user:

1. Describe a REST API connection in a form (URL, authentication, pagination, where the records are in the JSON).
2. Preview the first page of data as a table.
3. Run the job: fetch every page, flatten the JSON records into columns, optionally drop duplicates and already-exported records, and write a CSV or Excel file.
4. See a run history with counts, warnings and errors, and download each export.

A demo mode ships with a built-in fake API so the whole tool works without any real API key or network access.

Audience: Upwork clients evaluating the author for API export, Python automation and data-integration work. The repository must look and behave like a small, finished, professional deliverable.

---

## 2. Stack (exact versions)

| Component | Choice | Version (pin with `==`) | Why |
|---|---|---|---|
| Language | Python | 3.11 for development (the build machine has 3.11.9 at `C:\Program Files\Python311\python.exe`); `requires-python = ">=3.11,<3.13"`; CI tests 3.11 and 3.12 | Python 3.11 is supported upstream until October 2027, and it is the interpreter already installed, so the executor needs no install step. All chosen libraries support 3.11 and 3.12. Do not use syntax added in 3.12 (`type` statements, PEP 695 generics, PEP 701 nested f-string quotes). |
| Web framework | FastAPI | 0.115.12 | Widely requested on Upwork. `TestClient` gives fast, in-process UI tests. Sync route functions run in a threadpool, so a blocking run does not freeze the server. |
| ASGI server | uvicorn | 0.34.2 | Standard FastAPI server. Plain install (no `[standard]` extras). |
| Templates | Jinja2 | 3.1.6 | Server-rendered HTML, autoescaping, no JavaScript build chain. |
| Form parsing | python-multipart | 0.0.20 | Required by FastAPI for `Form(...)` and `request.form()`. |
| HTTP client | httpx | 0.28.1 | Sync client with `MockTransport`. The demo API and the tests plug in through a transport, so the real request code path is exercised with no network. |
| Excel | openpyxl | 3.1.5 | Writes `.xlsx` with typed cells, bold header, frozen header row, autofilter. |
| Validation | pydantic | 2.11.4 | Job configuration model with clear field errors. Already a FastAPI dependency. |
| Tests | pytest | 8.3.5 | Standard. |
| Lint/format | ruff | 0.11.8 | One fast tool for lint and format. |
| Storage | `sqlite3` (stdlib) | bundled | Jobs, secrets, run log, incremental state. No server, no ORM. |
| CSV | `csv` (stdlib) | bundled | Correct quoting with no extra dependency. |
| CLI | `argparse` (stdlib) | bundled | Avoids another dependency. |
| CSS/JS | Hand-written `style.css` and `app.js` | n/a | No CDN, no framework, no build step. Works offline. |

These versions are a known-compatible set. Do not upgrade them in v1. If `pip` cannot install this exact set, stop and escalate. Do not substitute other versions. A full transitive lock is generated once into `constraints.txt` (PLAN T01) and always used for installs.

Rejected alternatives (for the README "Design decisions" section):
- **Streamlit / Gradio**: fast to start, but the rerun model makes long runs and form state awkward, the look is generic, and UI tests are weak.
- **Django**: too heavy for a single-user local tool.
- **pandas**: large dependency, and its type inference silently damages data (for example, `"00731"` becomes `731`). Plain Python keeps exact values.
- **SQLAlchemy**: an ORM adds nothing for five small tables.
- **requests**: no built-in mock transport. httpx gives one client for real and demo traffic.
- **HTMX or a SPA framework**: not needed. Plain form posts are easier for the executor and easier to test.

---

## 3. Architecture

### 3.1 Repository layout (final)

```
api-automation-tool/
  .github/workflows/ci.yml
  .gitignore
  LICENSE                      (MIT, holder: "api-automation-tool contributors")
  README.md
  constraints.txt
  pyproject.toml
  docs/  BRIEF.md SPEC.md PLAN.md ACCEPTANCE.md REVIEW.md  images/ (screenshots, PNG)
  src/apitool/
    __init__.py               __version__ = "1.0.0"
    __main__.py               calls cli.main()
    errors.py                 exception types + exit codes
    redact.py                 secret redaction, URL stripping, log filter
    config.py                 JobConfig model, text-field parsers/formatters
    jsonpath.py               get_path(), MISSING sentinel
    http_client.py            URL building, auth, single request, retry
    pagination.py             page iterators for the 5 pagination styles
    transform.py              flatten, value rendering, sanitization
    pipeline.py               records -> filtered rows + columns + counts
    export.py                 CSV and XLSX writers, filenames, atomic write
    timeutil.py               utc timestamps: format_ts(), parse_ts()
    storage.py                SQLite schema and all queries
    runner.py                 orchestrates one run (fetch, transform, export, state, log)
    cli.py                    argparse CLI
    demo/
      __init__.py
      datasets/               orders_v1.json, orders_v2_extra.json, customers.json,
                              events_pages.json, products_pages.json
                              (JSON copied verbatim from ACCEPTANCE.md §2)
      data.py                 loads the datasets with importlib.resources
      api.py                  DemoApi: httpx MockTransport handler
      jobs.py                 demo job definitions
    web/
      __init__.py
      app.py                  create_app(), routes, middleware
      templates/              base.html, jobs.html, job_form.html, preview.html,
                              run.html, runs.html, error.html
      static/                 style.css, app.js
  tests/
    conftest.py
    fixtures/expected/        expected outputs (JSON), transcribed from ACCEPTANCE.md
    test_*.py
```

`data/`, `ops/`, `video/`, `.venv/` and `book-log.txt` are git-ignored and never committed (see §17).

### 3.2 Data flow of one run

```
JobConfig + secret ──> http_client.build_request ──> transport (real HTTPTransport, or DemoApi MockTransport)
                                 ^                              │
                                 │  next page params            ▼
                         pagination iterator  <── response JSON (validated, size-capped, retried)
                                 │
                                 ▼ raw records (list)
                     pipeline: flatten → key filter (missing / duplicate / already seen)
                               → columns → select → rename → rows
                                 │
                                 ▼
                     export: CSV or XLSX, atomic write to data/exports/
                                 │
                                 ▼
                     storage: commit seen keys (incremental) + finish run record
```

### 3.3 Module boundaries

- `http_client`, `pagination`, `transform`, `pipeline` and `export` are pure logic. They never touch SQLite and never read environment variables.
- `storage` is the only module that runs SQL.
- `runner` is the only module that combines storage with the engine.
- `web.app` and `cli` call `runner` and `storage`. They contain no fetch or transform logic.
- Time and sleep are injected: `runner.run_job(..., now=..., sleep=...)`, so tests run fast and give the same result every time.

---

## 4. Scope

### 4.1 In v1

- Job CRUD in the web UI. Jobs are stored in SQLite.
- GET requests only.
- Auth styles: `none`, `api_key_header`, `api_key_query`, `bearer`, `basic`.
- Pagination styles: `none`, `page`, `offset`, `cursor`, `next_url`.
- Records located by a dotted path. Nested JSON is flattened. Field selection and column renames.
- Export to CSV (UTF-8 with BOM) or Excel `.xlsx`.
- **Deduplication** by a key field, inside a run.
- **Incremental sync**, "seen keys" mode: export only records whose key was never exported by a previous successful run of the same job.
- **Retry** with exponential backoff and `Retry-After` support.
- **Run logging**: every run is recorded with status, counts, warnings, errors and the output file. History page and run detail page.
- Preview of the first page.
- CLI: `serve`, `run`, `list-jobs`, `demo-setup`, `--version`.
- **Scheduling, v1 form**: no built-in scheduler. The README documents how to schedule `apitool run --job "<name>"` with Windows Task Scheduler and with cron. That is documentation only, no code.
- Demo mode: built-in fake API, five demo jobs, dataset switch to show incremental sync.
- Security: secrets are never logged, rendered or committed. CSRF protection. Host-header check. Security headers. Loopback-only server.
- Automated tests and GitHub Actions CI.

### 4.2 Phased later (documented in the README as the roadmap, not built)

- Phase 2: built-in scheduler (cron expressions, in-app); watermark incremental mode (an `updated_since` query parameter fed from the last run); `Link` header pagination; JSON and JSON Lines export; Docker image.
- Phase 3: OAuth2 client-credentials; POST and GraphQL requests; destinations (Google Sheets, PostgreSQL); encryption of stored secrets; email or webhook notification on failure; background job queue with progress display.

### 4.3 Out of scope (never in v1, do not build)

Multi-user accounts or login; remote or network-exposed hosting; editing data; field type casting; per-field transforms or formulas; XML APIs; uploading files to APIs; internationalized UI (the UI is English only).

---

## 5. Job configuration

### 5.1 Model

`config.JobConfig` is a pydantic `BaseModel` with `model_config = ConfigDict(extra="forbid", frozen=True)`. The secret is **not** part of `JobConfig`. It is stored separately (see §13).

| Field | Type | Default | Rule |
|---|---|---|---|
| `name` | str | (required) | Stripped. 1–60 characters. Regex `^[A-Za-z0-9][A-Za-z0-9 _-]*$`. Unique case-insensitively (enforced by storage). |
| `url` | str | (required) | Stripped. At most 2000 characters. Scheme `http` or `https`. Non-empty host. Must contain no userinfo (`user:pass@`) and no `#` fragment. May contain a query string. |
| `query_params` | list[tuple[str,str]] | `[]` | From a textarea, one `key=value` per line (§5.2). |
| `headers` | list[tuple[str,str]] | `[]` | From a textarea, one `Name: value` per line (§5.2). Name regex `^[A-Za-z0-9-]+$`. |
| `auth_type` | Literal `none`, `api_key_header`, `api_key_query`, `bearer`, `basic` | `none` | |
| `auth_key_name` | str | `""` | Required (non-blank) for `api_key_header` and `api_key_query`. For `api_key_header` it must match the header name regex. For `api_key_query` it must contain no whitespace. |
| `auth_username` | str | `""` | Required for `basic`. Must not contain `:`. |
| `pagination_type` | Literal `none`, `page`, `offset`, `cursor`, `next_url` | `none` | |
| `page_param` | str | `"page"` | Required for `page`. |
| `page_size_param` | str | `"per_page"` | Required for `page`. Optional for `cursor` (blank means "do not send"). |
| `start_page` | int | `1` | 0–1,000,000. Used by `page`. |
| `offset_param` | str | `"offset"` | Required for `offset`. |
| `limit_param` | str | `"limit"` | Required for `offset`. |
| `cursor_param` | str | `"cursor"` | Required for `cursor`. |
| `cursor_path` | str | `""` | Required for `cursor`. A dotted path (§7). |
| `next_url_path` | str | `""` | Required for `next_url`. A dotted path. |
| `page_size` | int | `100` | 1–1000. |
| `records_path` | str | `""` | Dotted path to the list of records. Blank means the response root is the list. A non-blank path must not have empty segments (`a..b` is invalid). |
| `max_pages` | int | `50` | 1–1000. |
| `timeout_seconds` | int | `30` | 1–120. |
| `fields` | list[str] | `[]` | Comma-separated in the form (§5.2). Empty means all columns. |
| `renames` | list[tuple[str,str]] | `[]` | Textarea, one `old=new` per line (§5.2). |
| `dedup_key` | str | `""` | Flattened column name, before renaming (for example `id` or `customer.id`). Blank means no dedup. |
| `incremental` | bool | `False` | `True` requires a non-blank `dedup_key`. |
| `export_format` | Literal `csv`, `xlsx` | `csv` | |

Every validation failure raises `errors.ConfigError` with a list of `(field_name, message)` pairs. Each `field_name` equals the model field name. For text-field parse errors it is the textarea field (`query_params`, `headers`, `fields`, `renames`). Pagination fields that are not used by the chosen `pagination_type` are stored but ignored. Auth fields that are not used by the chosen `auth_type` are also stored but ignored.

### 5.2 Text field formats (form ⇄ model)

The parsers and formatters live in `config.py`. Each formatter is the exact inverse of its parser for valid input.

- `query_params`: split on `\n`. Strip each line. Skip blank lines. Split at the **first** `=`. Strip the key and the value. The key must be non-blank. The value may be blank. A line without `=` is an error: `"line N: expected key=value"` (N is 1-based and counts every raw line, blank lines included). Formatter: `key=value` lines joined with `\n`.
- `headers`: same as above, but split at the first `:`. Error: `"line N: expected Name: value"`. Formatter: `Name: value` lines.
- `fields`: split on `,`, strip each item, drop empty items. Duplicates are an error: `"duplicate field 'x'"`. Formatter: items joined with `", "`.
- `renames`: like `query_params` (split at the first `=`). The new name must be non-blank. Each old name may appear only once. Formatter: `old=new` lines.

### 5.3 Secret input rules (web form)

- Form field `secret` (password input). It is never pre-filled and never rendered back.
- On create: required when `auth_type != "none"`. Error field `secret`, message `"required for this authentication type"`.
- On edit: blank means keep the stored secret. The checkbox `clear_secret` deletes the stored secret. After an edit, if `auth_type != "none"` and no secret would remain, it is a validation error on `secret`.
- A secret of the form `env:NAME` (NAME matches `^[A-Za-z_][A-Za-z0-9_]*$`) is stored as that literal text. At run time the value is read from environment variable `NAME`. If the variable is unset or empty, the run fails with `ConfigError("environment variable NAME is not set")`.
- When `auth_type == "none"`, any stored secret is deleted on save.

---

## 6. HTTP client behavior (`http_client.py`)

### 6.1 Transport

- One `httpx.Client` per run: `httpx.Client(transport=..., timeout=httpx.Timeout(timeout_seconds), follow_redirects=False, headers={"User-Agent": "api-automation-tool/1.0.0", "Accept": "application/json"})`.
- Transport selection (`runner`): if the configured URL host equals `demo.api-automation-tool.local` (case-insensitive), use `httpx.MockTransport(DemoApi(dataset_version).handle)`. A new `DemoApi` instance is created for each run. Otherwise use `httpx.HTTPTransport()` (TLS verification on, which is the httpx default; it is never disabled).
- Tests pass their own transport through the same parameter.

### 6.2 Building the request URL

The URL is built explicitly. Never pass `params=` to httpx.

1. Parse the configured `url` with `urllib.parse.urlsplit`.
2. Start an ordered dict from `parse_qsl(url.query, keep_blank_values=True)`. When a key repeats, the last value wins.
3. Update it with `query_params` in order.
4. Update it with the pagination parameters for this page (§8).
5. If `auth_type == "api_key_query"`, set `auth_key_name` to the secret.
6. Rebuild the URL with `urlencode(list(dict.items()))` as the query (this uses `quote_plus`, so a space becomes `+` and `&` becomes `%26`). Scheme, host and path are unchanged. No fragment. If the query is empty, the URL has no `?`.

Pagination parameters are added in this order: `page`: `page_param`, then `page_size_param`. `offset`: `offset_param`, then `limit_param`. `cursor`: `cursor_param` (pages after the first), then `page_size_param` (if non-blank). When a key already exists from an earlier step, it keeps its original position and only its value changes (normal `dict` assignment).

Later steps overwrite earlier ones when a key is the same. For `next_url` follow-up pages, see §8.5.

### 6.3 Headers and auth

- Start with the client defaults (§6.1), then apply `headers` in order (a later duplicate overwrites), then apply auth. Auth always wins over a same-named custom header.
- `api_key_header`: header `auth_key_name: <secret>`.
- `bearer`: `Authorization: Bearer <secret>`.
- `basic`: `Authorization: Basic base64(username:secret)`, UTF-8.
- `api_key_query`: see §6.2.

### 6.4 Response handling (one attempt)

In order:
1. A transport exception (`httpx.TransportError`, which includes timeouts and connection errors) is retryable. If it is not retried, raise `NetworkError`.
2. Status 300–399: raise `InvalidResponseError("unexpected redirect (STATUS) from URL")`. Not retried.
3. Status 429, 500, 502, 503, 504: retryable. If not retried, raise `HttpError("HTTP STATUS from URL")`.
4. Any other status outside 200–299: raise `HttpError("HTTP STATUS from URL")` immediately. Not retried.
5. Body size: if `len(response.content) > 10 * 1024 * 1024` (constant `MAX_RESPONSE_BYTES`), raise `InvalidResponseError("response too large (> 10 MiB) from URL")`.
6. Decode the body as UTF-8 (invalid bytes make the body invalid JSON) and parse with `json.loads(text, parse_constant=<function that raises ValueError>)`. This rejects `NaN`, `Infinity` and `-Infinity`. On failure: `InvalidResponseError("response is not valid JSON from URL")`.

In every message, `URL` means the request URL **without its query string** (`scheme://host[:port]/path`), produced by `redact.strip_query()`.

### 6.5 Retry policy

- At most 3 retries, so at most 4 attempts per page.
- Delay before retry n (n = 1, 2, 3): if the response has a `Retry-After` header that is a non-negative integer (only digits after stripping), the delay is `min(int(value), 30)`. Otherwise the delay is `[1, 2, 4][n-1]` seconds. Transport errors have no header, so they always use the backoff list.
- Sleep goes through the injected `sleep` function.
- Each retry adds 1 to the run's `retries` counter. Each retry is logged at WARNING: `retry N/3 after DELAY s: REASON (URL)`, where REASON is `HTTP 503` or the exception class name.
- When attempts run out, raise the error from the last attempt.

---

## 7. Dotted paths (`jsonpath.py`)

`get_path(obj, path) -> value | MISSING`

- `path == ""` returns `obj`.
- Otherwise split on `.`. For each segment: if the current value is a dict, take `current[segment]` when the key exists, else return `MISSING`. If the current value is a list and the segment is all digits, take `current[int(segment)]` when the index is in range, else return `MISSING`. Any other case returns `MISSING`.
- `MISSING` is a unique sentinel object (not `None`). A present JSON `null` returns `None`.
- Keys that contain a literal `.` cannot be addressed. This limit is documented.

---

## 8. Pagination (`pagination.py`)

All styles share these rules:
- Pages are fetched one after another. Page index `i` starts at 0.
- From each response body, `records = get_path(body, records_path)`. If the result is `MISSING`: `InvalidResponseError("records_path 'P' not found in response")`. If it is not a list: `InvalidResponseError("records_path 'P' did not point to a list (got TYPE)")`, where TYPE is `object`, `string`, `number`, `boolean` or `null`.
- `pages_fetched` counts successful page responses.
- Max pages: stop after `max_pages` pages. If the style's stop condition was **not** met on that last page, add the warning `max_pages_reached: stopped after N pages; more data may exist`.

### 8.1 `none`
One request. No pagination parameters.

### 8.2 `page`
Request `i` sends `page_param = start_page + i` and `page_size_param = page_size`. Stop after a page where `len(records) < page_size` (this includes 0).

### 8.3 `offset`
Request `i` sends `offset_param = i * page_size` and `limit_param = page_size`. The stop rule is the same as for `page`.

### 8.4 `cursor`
- Request 0 sends no cursor parameter. Later requests send `cursor_param = <cursor>`. If `page_size_param` is non-blank, every request also sends `page_size_param = page_size`.
- After each page, `next = get_path(body, cursor_path)`. Stop if `next` is `MISSING`, `None` or `""`, or if `len(records) == 0`.
- `next` must be a str or an int (not a bool). Otherwise: `InvalidResponseError("cursor_path 'P' must be a string or integer")`. Use `str(next)` as the cursor.
- If a cursor value repeats one already used in this run: `PaginationError("cursor repeated: pagination loop detected")`.

### 8.5 `next_url`
- Request 0 uses the URL built by §6.2 with no pagination parameters.
- After each page, `next = get_path(body, next_url_path)`. Stop if `next` is `MISSING`, `None` or `""`, or if `len(records) == 0`. A `next` that is not a string: `InvalidResponseError("next_url_path 'P' must be a string")`.
- Resolve with `urllib.parse.urljoin(<current request URL>, next)`.
- The resolved URL must have the same scheme, host and port (after defaulting the port: 80 for http, 443 for https) as the configured `url`. Otherwise: `PaginationError("next URL points to a different host; refusing to send credentials")`.
- Follow-up request URL: the resolved URL exactly as given (its own query string), plus only the auth query parameter if `auth_type == "api_key_query"` (set or overwrite). Configured `query_params` are **not** added again.
- If a resolved URL repeats one already requested (compare full strings, before the auth parameter is added): `PaginationError("next URL repeated: pagination loop detected")`.

---

## 9. Records and JSON transform (`transform.py`, `pipeline.py`)

### 9.1 Flatten
```
def flatten(obj: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten(v, key))   # an empty dict adds no columns
        else:
            out[key] = v                  # list, str, int, float, bool, None
    return out
```
- A record that is not a dict (string, number, bool, null, list) becomes `{"value": item}` before flattening.
- Key collisions (a literal key `"a.b"` next to nested `a.b`): the value assigned later wins. This is the natural result of the code above. Do not add special handling.
- Lists are not flattened. They are rendered as JSON text (§9.3).

### 9.2 Pipeline (exact order)
Input: all raw records from all pages, in page order. `records_fetched = len(all records)`.
1. Flatten every record.
2. If `dedup_key` is set, go through the records in order:
   a. `v = rec.get(dedup_key, MISSING)`. If `v` is `MISSING` or `None`, or `render_csv(v) == ""`: `records_missing_key += 1`, drop the record.
   b. `k = render_csv(v)`. Values are therefore compared by their CSV text, so `1` and `"1"` are the same key. This is documented.
   c. If `k` was already seen in this run: `duplicates_removed += 1`, drop. The first occurrence wins, even if a later record with the same key has different content.
   d. Add `k` to this run's seen set.
   e. If `incremental` and `k` is in the job's stored seen keys: `already_seen_skipped += 1`, drop.
   f. Keep the record and remember `k` as an exported key.
3. If `records_missing_key > 0`, add the warning `missing_key: N records skipped because key field 'K' was missing or empty`.
4. Columns: if `fields` is non-empty, columns = `fields` in the given order (a field that never appears gives an empty column, not an error). Otherwise columns = the union of the kept records' keys, in order of first appearance (record order, then key order inside each record).
5. Rows: for each kept record, `[rec.get(c, None) for c in columns]`.
6. Header: `[renames_map.get(c, c) for c in columns]`. If the header has a duplicate name: `TransformError("duplicate column name after rename: 'X'")`.
7. `records_exported = len(rows)`.

Invariant (checked in tests): `records_fetched == records_missing_key + duplicates_removed + already_seen_skipped + records_exported`.

### 9.3 Value rendering
`render_csv(v)` returns a str:
| Python value | Output |
|---|---|
| `None` | `""` |
| `bool` (check before int) | `"true"` / `"false"` |
| `int` | `str(v)` |
| `float` | `repr(v)` (for example `42.0`, `19.99`, `-12.5`) |
| `str` | `v` unchanged |
| `list` | `json.dumps(v, ensure_ascii=False, separators=(",", ":"))` |

`render_xlsx(v)` returns a value for openpyxl:
| Python value | Output |
|---|---|
| `None` | `None` (empty cell) |
| `bool` | `bool` |
| `int` with `abs(v) < 10**15` | `int` |
| `int` with `abs(v) >= 10**15` | `str(v)` (Excel cannot hold more than 15 significant digits exactly) |
| `float` | `float` |
| `str` | `v` |
| `list` | same JSON text as CSV |

### 9.4 Spreadsheet formula-injection protection
`sanitize_text(s)`: if `s` is non-empty and `s[0]` is one of `=`, `+`, `-`, `@`, `\t`, `\r`, return `"'" + s`. Otherwise return `s`.
- Applied to every cell whose **original value is a `str`**, and to every header name, in both CSV and XLSX. The decision depends on the original type, not on the rendered text.
- Never applied to values that were numbers, bools or lists before rendering. This includes big ints that XLSX writes as text: `-(10**15)` becomes `"-1000000000000000"` with no prefix. A negative number such as `-12.5` stays unchanged. A string `"-5"` becomes `"'-5"`. This trade-off is documented in the README.
- JSON-rendered lists start with `[` and are therefore never changed.

### 9.5 XLSX-only text cleanup (order matters)
For each XLSX cell whose rendered value is a str, and for each header: (1) remove characters matching `[\x00-\x08\x0b\x0c\x0e-\x1f]`; (2) apply `sanitize_text` **only** if the original value was a `str`, or the cell is a header; (3) if the length is over 32767, cut it to 32767 and count it. `clean_xlsx_text(s, sanitize: bool)` implements steps 1–3. If the count is above 0, add the warning `excel_truncated: N cell values longer than 32767 characters were truncated`. CSV keeps control characters and long values unchanged.

---

## 10. Deduplication and incremental sync

- Dedup only (`dedup_key` set, `incremental` false): rules 2a–2d and 2f of §9.2. No state is read or written.
- Incremental (`incremental` true): the full rules of §9.2. Stored state is table `seen_keys(job_id, key)`.
- **State commit rule**: the exported keys are inserted into `seen_keys` only after the export file has been written and renamed into place. This happens in the same SQLite transaction that marks the run `success`. If anything fails before that point, `seen_keys` is unchanged.
- A run with 0 exported records writes **no file**. `output_file` is NULL, the status is `success`, and the message is `No records to export`. No keys are added.
- Each run still fetches every page. Incremental filtering happens on the client.
- Updated records whose key was already exported are **not** exported again. This is documented. Watermark mode is in phase 2.
- Reset: the "Reset sync state" action (UI) deletes all `seen_keys` rows for the job.
- Automatic reset: saving an edit that changes `url`, `records_path`, `dedup_key` or `incremental` deletes the job's `seen_keys`, and the UI shows the notice `state_reset_auto`.

---

## 11. Export (`export.py`)

### 11.1 Location and file name
- Directory: `<data_dir>/exports/`, created if missing.
- File name: `{slug}_{YYYYMMDD-HHMMSS}_run{run_id}.{csv|xlsx}`. The timestamp is the run's `started_at` in UTC.
- `slug`: lowercase the job name. Replace each run of characters outside `[a-z0-9]` with one `-`. Strip leading and trailing `-`. If the result is empty, use `job`. Example: `"Demo Orders"` gives `demo-orders`.
- The database stores the file **name only** (no directory).

### 11.2 Atomic write
Write to `<final>.tmp` in the same directory, close it, then `os.replace(tmp, final)`. On any exception, delete the `.tmp` file if it exists and raise `ExportError("could not write export: <exception class name>")`.

### 11.3 CSV
`open(tmp, "w", encoding="utf-8-sig", newline="")` with `csv.writer(f)` in the default `excel` dialect (`,` delimiter, `"` quote, doubled quotes, `\r\n` line ending, QUOTE_MINIMAL). First row: the header (sanitized). Then one row per record. Each cell is `csv_cell(v)`, defined in `transform.py` as `sanitize_text(v) if isinstance(v, str) else render_csv(v)`. The decision depends on the **original** value's type: a float `-12.5` is written as `-12.5`, while a string `"-5"` is written as `'-5`. Embedded newlines stay inside quoted fields as written.

### 11.4 XLSX
- `openpyxl.Workbook()`. The active sheet is renamed to `data`.
- Row 1 holds the header cells, bold (`Font(bold=True)`).
- Data starts in row 2. Values come from `render_xlsx` plus the §9.5 cleanup for strings.
- `ws.freeze_panes = "A2"`. `ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}{nrows+1}"`.
- Column width: `ws.column_dimensions[letter].width = min(50, max(10, len(header) + 2))`.
- If `nrows + 1 > 1_048_576`: `ExportError("too many rows for Excel")`, checked before writing.
- Save to the `.tmp` path, then rename as in §11.2. Because the temp name ends in `.xlsx.tmp`, save through an open binary file handle (`wb.save(fh)`), not through the path string.

---

## 12. Runs, run log, concurrency

### 12.1 Run lifecycle (`runner.run_job(storage, job_id, trigger, *, transport=None, sleep=None, now=None) -> RunResult`)

Defaults are resolved **at call time**: `sleep=None` means `lambda s: time.sleep(s)`, and `now=None` means `utc_now`. This lets tests monkeypatch `time.sleep`. `transport=None` means `make_transport(url, dataset_version)`. That is a module-level function in `runner`, and the web layer and the CLI never bypass it, so tests can monkeypatch `apitool.runner.make_transport`. `runner.preview_job(storage, job_id, *, transport=None, sleep=None) -> PreviewResult` follows the same rules.
1. Load the job. If it is not found: `JobNotFoundError` (no run record).
2. Start the run in one `BEGIN IMMEDIATE` transaction:
   a. Any `running` run of this job with `started_at` older than 2 hours becomes `failed`, with `error_type="Interrupted"` and `error_message="run did not finish (process stopped)"`.
   b. If a `running` run of this job remains: `JobBusyError` (no run record).
   c. Insert a run with `status='running'`.
3. Resolve the secret (`env:` handling). Fetch all pages, run the pipeline, export.
4. Success: in one transaction, update the run (counts, `output_file`, `message`, `warnings_json`, `finished_at`, `status='success'`) and insert the exported keys if incremental.
5. Failure (`AppError` subclass): update the run with `status='failed'`, the counts reached so far, `error_type` = the class name, `error_message` = the redacted message, and `finished_at`. Return the result. Do not raise.
6. Unexpected exception: record the run as failed with `error_type="InternalError"` and the message `unexpected error: <class name>` (never `str(exc)`, which might contain data). Log the traceback at ERROR level through the redacting logger, then re-raise.
7. `message` on success: `Exported N records to FILENAME` or `No records to export`.

Timestamps: UTC, ISO 8601 with seconds and a `Z` suffix (`2026-11-04T10:00:00Z`).

### 12.2 Counters on every run
`pages_fetched, records_fetched, retries, duplicates_removed, records_missing_key, already_seen_skipped, records_exported`.

### 12.3 Concurrency
Only one run per job at a time (step 2 above). Different jobs may run at the same time. The UI runs a job inside the POST request (a sync route in the threadpool). There is no background queue in v1.

---

## 13. Storage (`storage.py`)

- Database file: `<data_dir>/apitool.db`. `data_dir` comes from the CLI `--data-dir` option, else environment variable `APITOOL_DATA_DIR`, else `./data` (relative to the current working directory). It is created if missing.
- Each operation opens a new connection: `sqlite3.connect(path, timeout=10)`, then `PRAGMA foreign_keys=ON`. `PRAGMA journal_mode=WAL` is set once at init.
- Schema (created with `CREATE TABLE IF NOT EXISTS` at init):

```sql
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,          -- lower(name)
  config_json TEXT NOT NULL,              -- JobConfig.model_dump_json()
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE secrets (
  job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  value TEXT NOT NULL
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
  job_name TEXT NOT NULL,
  trigger TEXT NOT NULL CHECK (trigger IN ('ui','cli')),
  status TEXT NOT NULL CHECK (status IN ('running','success','failed')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  pages_fetched INTEGER NOT NULL DEFAULT 0,
  records_fetched INTEGER NOT NULL DEFAULT 0,
  retries INTEGER NOT NULL DEFAULT 0,
  duplicates_removed INTEGER NOT NULL DEFAULT 0,
  records_missing_key INTEGER NOT NULL DEFAULT 0,
  already_seen_skipped INTEGER NOT NULL DEFAULT 0,
  records_exported INTEGER NOT NULL DEFAULT 0,
  output_file TEXT,
  message TEXT,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  error_type TEXT,
  error_message TEXT
);
CREATE TABLE seen_keys (
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  first_run_id INTEGER NOT NULL,
  PRIMARY KEY (job_id, key)
);
CREATE TABLE settings (
  name TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```
- Settings used: `demo_dataset_version` (`"1"` or `"2"`, default `"1"`).
- Deleting a job removes its secret and seen keys (cascade). Its runs keep `job_name` and get `job_id = NULL`. Export files are not deleted.
- Every SQL statement uses `?` parameters. No string formatting of SQL.

---

## 14. Web UI (`web/app.py`)

### 14.1 App factory
`create_app(data_dir: Path) -> FastAPI`. It stores `app.state.storage`, and `app.state.csrf_token = secrets.token_urlsafe(32)` (new for each process). Templates use `Jinja2Templates` with autoescape on.

### 14.2 Middleware (every response)
- **Host check**: the `Host` header's hostname (port removed) must be `127.0.0.1` or `localhost`. Otherwise the response is `400` with plain text `invalid host`. This protects against DNS rebinding. Tests use `TestClient(app, base_url="http://127.0.0.1:8000")`.
- **Security headers**: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- No inline `<script>` or `style=` attributes anywhere (the CSP would block them).

### 14.3 CSRF
Every POST form has a hidden input `csrf_token`. Every POST route compares it with `hmac.compare_digest`. If it is missing or wrong: `403` with the error page `Invalid or missing form token. Reload the page and try again.`

### 14.4 Routes
| Method | Path | Behavior |
|---|---|---|
| GET | `/` | Jobs page. A table with name, URL host, pagination type, format, last run (status badge and finished time) and actions (Preview, Run, Edit, Delete; plus Reset sync state when `incremental`). With no jobs, an empty state with a "Load demo jobs" button. Always a "Demo data" panel: the current dataset version and buttons "Use dataset v1" / "Simulate new orders (v2)". |
| GET | `/jobs/new` | Empty form with defaults. |
| POST | `/jobs` | Create. Valid: 303 to `/?notice=job_created`. Invalid: 400, the form re-rendered with field errors and entered values, except `secret`. A duplicate name is an error on `name`: `"a job with this name already exists"`. |
| GET | `/jobs/{id}/edit` | Pre-filled form. The secret field is empty. If a secret is stored, the help text says `A secret is saved. Leave blank to keep it.` |
| POST | `/jobs/{id}` | Update. Same rules as create. 303 to `/?notice=job_updated`, or to `/?notice=state_reset_auto` when an automatic reset happened. |
| POST | `/jobs/{id}/delete` | 303 to `/?notice=job_deleted`. |
| POST | `/jobs/{id}/preview` | Fetches the first page only (same client, auth and retry; no dedup, no state, no run record, no file). 200 page showing the sentence `Page 1 returned N records.`, the detected columns, and the first 10 flattened records as an HTML table (values from `render_csv`, autoescaped). On `AppError`: 200 page with an error box showing the error type and redacted message. |
| POST | `/jobs/{id}/run` | Runs the job (`trigger='ui'`), then 303 to `/runs/{run_id}` whether it succeeded or failed. `JobBusyError`: 409 error page `This job is already running.` |
| POST | `/jobs/{id}/reset-state` | 303 to `/?notice=state_reset`. |
| GET | `/runs` | The latest 100 runs, newest first: id, job, status, started, records exported, link. |
| GET | `/runs/{id}` | Status badge, all counters (§12.2) with plain-English labels, warnings list, error type and message, "Download" button when `output_file` is set, "Run again" button when the job still exists. |
| GET | `/runs/{id}/download` | 404 if there is no `output_file`, if the file is missing, or if `(exports_dir / output_file).resolve()` is not inside `exports_dir.resolve()`. Otherwise `FileResponse` with `filename=output_file`. |
| POST | `/demo/setup` | Creates any demo jobs whose names do not exist yet (idempotent). 303 to `/?notice=demo_loaded`. |
| POST | `/demo/dataset` | Form field `version` must be `1` or `2` (else 400). Saves the setting. 303 to `/?notice=dataset_v1` or `dataset_v2`. |
| GET | `/healthz` | JSON `{"status": "ok"}`. |
| GET | `/static/*` | `StaticFiles`. |

- Unknown job id or run id: 404 error page `Not found.`
- POST routes that must read the whole form (`/jobs`, `/jobs/{id}`) are `async def` and use `await request.form()`. Routes that run network work (`/run`, `/preview`) are plain `def` with `csrf_token: str = Form("")`, so FastAPI runs them in the threadpool.
- Notices: the `notice` query parameter is looked up in a fixed dict of messages. Unknown codes are ignored. The parameter text is never rendered. Codes and texts: `job_created` "Job created.", `job_updated` "Job saved.", `job_deleted` "Job deleted.", `demo_loaded` "Demo jobs are ready.", `state_reset` "Sync state cleared. The next run exports all records again.", `state_reset_auto` "Job saved. Sync state was cleared because the connection or key settings changed.", `dataset_v1` "Demo API now serves dataset v1.", `dataset_v2` "Demo API now serves dataset v2 (3 new orders)."

### 14.5 Job form layout
Four `<fieldset>` sections: **Connection** (name, URL, query parameters, extra headers, timeout), **Authentication** (auth type, key name, username, secret, clear secret), **Pagination** (type, all pagination fields, page size, max pages, records path), **Output** (fields, renames, dedup key, incremental checkbox, export format). Every input has a `<label>` and a one-line help text. The auth and pagination fields carry `data-show-for="<type1> <type2>"`. `app.js` hides fields that do not apply to the selected type. Without JavaScript all fields stay visible and the form still works.

### 14.6 Visual style
System font stack, max content width 1100px, white cards on a `#f5f6f8` background, one accent color `#2563eb`, status badges with the texts `Success` (green `#15803d`), `Failed` (red `#b91c1c`) and `Running` (amber `#b45309`), tables with zebra rows. App title "API Automation Tool" in the header with nav links "Jobs" and "Run history". `app.js` also adds a `confirm()` prompt to forms with a `data-confirm` attribute (delete and reset).

---

## 15. CLI (`cli.py`)

Entry points: `apitool = "apitool.cli:main"` and `python -m apitool`.

Global option `--data-dir PATH` (placed before the subcommand).

| Command | Behavior |
|---|---|
| `apitool --version` | Prints `apitool 1.0.0`, exit 0. |
| `apitool serve [--port N]` | Port 1024–65535, default 8000. Runs `uvicorn.run(create_app(data_dir), host="127.0.0.1", port=N, log_level="info")`. There is no host option. Prints `Open http://127.0.0.1:N in your browser`. |
| `apitool run --job NAME` | NAME matches case-insensitively. Runs with `trigger='cli'`. On success, stdout shows `Run ID success: MESSAGE`, plus one stdout line `warning: TEXT` per warning. On failure, stderr shows `Run ID failed: ERROR_TYPE: ERROR_MESSAGE`. |
| `apitool list-jobs` | One line per job: `NAME\t<pagination_type>\t<export_format>`, sorted by name case-insensitively. |
| `apitool demo-setup` | Same as `POST /demo/setup`. Prints `Demo jobs ready: N created, M already existed`. |

Exit codes:
| Code | Meaning |
|---|---|
| 0 | Success (this includes "No records to export" and runs with warnings). |
| 1 | The run failed: `HttpError`, `NetworkError`, `InvalidResponseError`, `PaginationError`, `TransformError`, `ExportError`. |
| 2 | Usage or config problem: bad arguments (argparse default), `JobNotFoundError`, `JobBusyError`, `ConfigError` (including a missing `env:` variable). |
| 3 | Unexpected internal error. stderr shows `internal error: <class name>`. |

`ConfigError` raised during a run (a missing env variable) is recorded on the run **and** gives exit code 2.

---

## 16. Errors (`errors.py`)

```
AppError(Exception)             exit_code = 1, base for all expected errors; .message (str)
  ConfigError                   exit_code = 2; .errors: list[tuple[str, str]]
  JobNotFoundError              exit_code = 2
  JobBusyError                  exit_code = 2
  HttpError                     exit_code = 1; .status_code
  NetworkError                  exit_code = 1
  InvalidResponseError          exit_code = 1
  PaginationError               exit_code = 1
  TransformError                exit_code = 1
  ExportError                   exit_code = 1
```
`str(err)` returns `.message`. `ConfigError.message` is `"; ".join(f"{field}: {msg}")`. Every message that reaches the UI, the CLI, the database or the logs passes through `redact.redact(text, secrets)` first.

---

## 17. Security rules (mandatory)

1. A secret value never appears in: log output, run records (`error_message`, `message`, `warnings_json`), CLI output, HTML responses (including the edit form and the preview page), export files, exception messages or test snapshots. The only place it exists is the `secrets` table.
2. `redact.redact(text, secrets)` replaces every occurrence of each non-empty secret with `***`. Longer secrets are replaced first. For `basic` auth, the base64 `username:secret` value is also in the list. `runner` builds the list once per run and applies it to every message it stores or logs.
3. Logged and stored URLs never include a query string (`redact.strip_query`). Request headers are never logged.
4. `redact.RedactingFilter` is a `logging.Filter` on the `apitool` logger. It applies `redact` to `record.getMessage()` using the registered secrets, then sets `record.msg` to the redacted text and `record.args = ()`. The runner registers the secrets at run start and unregisters them in a `finally` block.
5. Secrets travel only in POST bodies. No route accepts a secret in a query string.
6. The server binds to `127.0.0.1` only. Host-header check, CSRF token and security headers as in §14.
7. No redirects are followed (§6.1). `next_url` must stay on the configured origin (§8.5). TLS verification is never disabled.
8. `.gitignore` (created in the skeleton task) contains exactly these lines:
   ```
   .venv/
   __pycache__/
   *.pyc
   .pytest_cache/
   .ruff_cache/
   *.egg-info/
   build/
   dist/
   data/
   ops/
   video/
   .env
   *.log
   book-log.txt
   ```
9. Demo credentials (`demo-key-123`, `demo-token-456`, `demo` / `demo-pass`) are **public, non-secret constants**. They live only in `src/apitool/demo/api.py` and `src/apitool/demo/jobs.py`, with the comment `# Public demo credential for the built-in fake API. Not a secret.` They only work against the in-process demo transport.
10. Secrets are stored unencrypted in the local SQLite file under the git-ignored `data/`. The README states this, and recommends `env:NAME` for scheduled or shared machines. Encryption is phase 3.
11. Before every commit, the executor runs the secret scan from PLAN T30 (it is also part of CI as a test). A finding blocks the commit.

---

## 18. Logging

- Logger name `apitool`. Default level INFO. Format `%(asctime)s %(levelname)s %(name)s: %(message)s`. Output to stderr. Configured in `cli.main()`.
- INFO per page: `GET URL page=N status=CODE records=M` (URL without query).
- INFO per run: `run ID started job=NAME` and `run ID finished status=STATUS exported=N`.
- WARNING per retry (§6.5) and per run warning.
- ERROR for failed runs: `run ID failed: TYPE: MESSAGE` (redacted).
- No log files are written in v1. The run log lives in SQLite.

---

## 19. Demo mode

### 19.1 Demo host and transport
- Base URL `https://demo.api-automation-tool.local`. `.local` is a reserved name, so no real request can ever reach it. The runner routes it to `DemoApi` (§6.1).
- `DemoApi(dataset_version: int)` has `.handle(request) -> httpx.Response` and `.requests: list[httpx.Request]` (every request received, used by the tests).
- Responses use `Content-Type: application/json` unless noted. The auth check comes before everything else on authed endpoints. A failed auth check returns `401 {"error": "unauthorized"}`. An unknown path returns `404 {"error": "not found"}`. A bad parameter returns `400 {"error": "bad request"}`.

### 19.2 Endpoints
The datasets are defined in ACCEPTANCE.md §2. Each JSON block there is copied **verbatim** into its file in `src/apitool/demo/datasets/`. `demo/data.py` exposes `ORDERS_V1` (orders_v1.json), `ORDERS_V2` (`ORDERS_V1 + orders_v2_extra.json`), `CUSTOMERS`, `EVENTS_PAGES` and `PRODUCTS_PAGES`, loaded with `json.loads(importlib.resources.files("apitool.demo").joinpath("datasets/<file>").read_text("utf-8"))`. Package data is declared in `pyproject.toml`: `[tool.setuptools.package-data] apitool = ["web/templates/*.html", "web/static/*", "demo/datasets/*.json"]`.

| Path | Auth | Behavior |
|---|---|---|
| `/v1/orders` | header `X-API-Key: demo-key-123` | Query `page` (int ≥ 1, default 1) and `per_page` (int 1–100, default 4). Dataset `ORDERS_V1` or `ORDERS_V2` by version. Returns `{"data": dataset[(page-1)*pp : page*pp], "meta": {"page": page, "per_page": pp, "total": len(dataset)}}`. |
| `/v1/flaky-orders` | as `/v1/orders` | Same as `/v1/orders`, but the **first** request for each distinct `page` value on this `DemoApi` instance returns `503 {"error": "temporarily unavailable"}` with header `Retry-After: 0`. |
| `/v1/customers` | `Authorization: Bearer demo-token-456` | Query `offset` (int ≥ 0, default 0) and `limit` (int 1–100, default 3). Returns `{"customers": CUSTOMERS[offset:offset+limit], "total": 6}`. |
| `/v1/events` | query `api_key=demo-key-123` | Query `cursor` is absent, `c_2` or `c_4`. Any other value gives 400. The `limit` parameter is ignored. Returns `{"results": EVENTS_PAGES[k]["results"], "next_cursor": EVENTS_PAGES[k]["next_cursor"]}` with k = 0, 1, 2 for absent, `c_2`, `c_4`. |
| `/v1/products` | Basic `demo:demo-pass` | Query `page` is 1, 2 or 3 (default 1, else 400). Returns `{"items": ..., "links": {"next": ...}}` from `PRODUCTS_PAGES[page-1]`. |
| `/v1/always-500` | none | Always `500 {"error": "server error"}`. |
| `/v1/rate-limited` | none | Requests 1 and 2 on this instance: `429` with `Retry-After: 2`. Later requests: `200 {"data": [{"id": 1}]}`. |
| `/v1/retry-after-big` | none | Request 1: `503` with `Retry-After: 120`. Later: `200 {"data": [{"id": 1}]}`. |
| `/v1/not-json` | none | `200`, `Content-Type: text/html`, body `<html>oops</html>`. |
| `/v1/nan` | none | `200`, body `{"data": [{"v": NaN}]}` (literal text). |
| `/v1/loop-cursor` | none | Always `{"results": [{"id": 1}], "next_cursor": "same"}`. |
| `/v1/offsite-next` | none | `{"items": [{"id": 1}], "links": {"next": "https://evil.example/steal"}}`. |
| `/v1/object-records` | none | `{"data": {"id": 1}}`. |
| `/v1/redirect` | none | `302`, header `Location: /v1/orders`, empty body. |
| `/v1/too-large` | none | `200`, body of `10 * 1024 * 1024 + 1` space bytes. |

### 19.3 Demo jobs (`demo/jobs.py`, created by `demo-setup`)
Every field not listed uses its §5.1 default.

| Name | URL | Auth | Pagination | Records path | Output |
|---|---|---|---|---|---|
| `Demo Orders` | `https://demo.api-automation-tool.local/v1/orders` | `api_key_header`, key name `X-API-Key`, secret `demo-key-123` | `page`, page_param `page`, page_size_param `per_page`, page_size 4 | `data` | dedup_key `id`, incremental true, csv |
| `Demo Customers` | `.../v1/customers` | `bearer`, secret `demo-token-456` | `offset`, `offset`/`limit`, page_size 3 | `customers` | xlsx |
| `Demo Events` | `.../v1/events` | `api_key_query`, key name `api_key`, secret `demo-key-123` | `cursor`, cursor_param `cursor`, cursor_path `next_cursor`, page_size_param `limit`, page_size 2 | `results` | dedup_key `event_id`, csv |
| `Demo Products` | `.../v1/products` | `basic`, username `demo`, secret `demo-pass` | `next_url`, next_url_path `links.next` | `items` | fields `sku, title, price.amount, price.currency, stock`; renames `price.amount=price` and `price.currency=currency`; xlsx |
| `Demo Flaky Orders` | `.../v1/flaky-orders` | as Demo Orders | as Demo Orders | `data` | dedup_key `id`, csv |

### 19.4 Dataset switch
`POST /demo/dataset` sets `demo_dataset_version`. The runner reads it at run start and passes it to `DemoApi`. Version 2 appends three new orders (ACCEPTANCE §2.1), so the incremental story in the video works: run → run again (0 new) → switch to v2 → run (3 new).

---

## 20. Tests and CI

- `pytest` with `testpaths = ["tests"]` and `pythonpath = ["src"]` in `pyproject.toml`. No network: tests use `DemoApi` or their own `httpx.MockTransport`. A global `conftest.py` fixture monkeypatches `httpx.HTTPTransport.handle_request` to raise `RuntimeError("network disabled in tests")`.
- Expected outputs live in `tests/fixtures/expected/*.json`. They are transcribed by hand from ACCEPTANCE.md and **never** generated by running production code.
- Ruff: `line-length = 100`, `target-version = "py311"`, lint rules `["E", "F", "I", "B", "UP", "S"]`. In `tests/` the rules `S101` (assert), `S105`/`S106` (hard-coded passwords in demo constants) and `S603`/`S607` (the repo hygiene test runs `git`) are ignored. In `src/apitool/demo/`, `S105`/`S106` are ignored. No other ignores.
- CI `.github/workflows/ci.yml`: on `push` and `pull_request`; matrix `os: [ubuntu-latest, windows-latest]` × `python-version: ["3.11", "3.12"]`; `actions/checkout@v4`, `actions/setup-python@v5`; steps: `pip install -c constraints.txt -e ".[dev]"`, `ruff check .`, `ruff format --check .`, `pytest -q`.

---

## 21. Portfolio presentation

### 21.1 README.md outline (in this order)
1. Title and one-sentence pitch. CI badge.
2. Screenshot of the jobs page (`docs/images/jobs.png`).
3. "What it does": five bullets (connect, paginate, transform, export, history).
4. "Try it in 2 minutes (demo mode, no API key)": install, `apitool demo-setup`, `apitool serve`, open the browser.
5. Feature list: auth styles, pagination styles, transform rules, dedup, incremental sync, retry, run log.
6. "Connect your own API": a short worked example with a fictional API.
7. "Scheduling": Windows Task Scheduler (`schtasks /Create /SC DAILY /ST 07:00 /TN "Orders export" /TR "<path>\apitool.exe --data-dir <path>\data run --job \"Orders\""`) and a cron line.
8. "How data is transformed": the rules from §9 in plain language, including the formula-injection prefix.
9. "Security": §17 in plain language.
10. "Design decisions": §2 rejected alternatives, briefly.
11. "Development": tests, ruff, project layout.
12. "Roadmap": §4.2.
13. Demo video link (only if the human provided it; see PLAN T29).
14. License.

Screenshots (PNG, at most 1400px wide, in `docs/images/`): `jobs.png`, `job-form.png`, `preview.png`, `run-detail.png`, `excel-export.png`. They are captured from demo mode only.

### 21.2 60-second video storyboard
| Time | Shot |
|---|---|
| 0–5 s | Title card: "API → CSV/Excel in a few clicks". |
| 5–12 s | Empty jobs page → "Load demo jobs" → five jobs listed. |
| 12–22 s | Edit "Demo Orders": URL, API-key auth, page pagination, dedup key, incremental. |
| 22–30 s | Preview: the first page as a table. |
| 30–40 s | Run: run page shows 3 pages, 11 records fetched, 2 duplicates, 1 missing key, 8 exported → Download → CSV opened in Excel. |
| 40–50 s | Run again: "No records to export". "Simulate new orders (v2)" → Run: 3 exported. |
| 50–56 s | Run "Demo Flaky Orders": 3 retries, success. Run history page. |
| 56–60 s | End card: GitHub URL and "Python · FastAPI · httpx · tested". |

Recording tooling (scripts, raw footage, edit projects) lives in `video/` at the repo root, which is git-ignored. It is never committed, never pushed to the review remote and never pushed to GitHub.

---

## 22. Glossary (one term per concept)
- **Job**: a saved API connection plus its output settings.
- **Run**: one execution of a job.
- **Record**: one item of the list found at `records_path`.
- **Key**: the CSV-rendered value of `dedup_key` for a record.
- **Sync state**: the set of keys exported by earlier successful runs of a job (`seen_keys`).
- **Demo API**: the in-process fake API at `demo.api-automation-tool.local`.
