# API Automation Tool

Connect a REST API, pull every page, flatten the JSON and export CSV or Excel. A small local web UI makes it usable without writing code.

[![CI](https://github.com/ALTRIAMERLIN/api-automation-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/ALTRIAMERLIN/api-automation-tool/actions/workflows/ci.yml)

## What it does

- **Connects** to a REST API with an API key, bearer token or basic authentication.
- **Pages** through the results: page number, offset, cursor or a next-page URL.
- **Transforms** the JSON: finds the records, flattens nested objects, selects and renames columns.
- **Exports** the records to CSV (UTF-8 with BOM) or Excel (.xlsx).
- **Keeps a run history** with counts, warnings, errors and a download link for every export.

## Try it in 2 minutes (demo mode, no API key)

Demo mode has a built-in fake API, so nothing leaves your computer. You need Python 3.11 or 3.12.

PowerShell (Windows):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -c constraints.txt -e ".[dev]"
.venv\Scripts\apitool demo-setup
.venv\Scripts\apitool serve
```

bash (Linux or macOS):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt -e ".[dev]"
.venv/bin/apitool demo-setup
.venv/bin/apitool serve
```

Then open http://127.0.0.1:8000 in your browser. Click **Preview** on a demo job, then **Run**, and download the file.

`apitool demo-setup` creates five demo jobs. Use the **Demo data** panel on the jobs page to switch the fake API to a second dataset with three new orders. Running a job again then exports only the new records.

## Features

- Authentication: none, API key in a header, API key in the query string, bearer token, basic.
- Pagination: none, page number, offset and limit, cursor, next-page URL in the response.
- Records: a dotted path finds the list. Nested objects are flattened into columns such as `customer.name`.
- Columns: choose and order the columns, and rename them.
- Duplicates: remove repeated records by a key column.
- Incremental export: skip records that an earlier successful run exported.
- Retries: up to 3 retries with a 1, 2, 4 second backoff, or the `Retry-After` header when the API sends one.
- Run log: every run records its counts, warnings and error, and every export can be downloaded.
- Limits: at most 1000 records per page, at most 1000 pages, responses up to 10 MiB, and request timeouts from 1 to 120 seconds.

## Connect your own API

This example uses a fictional shop API, `https://api.shop-example.com/v1/orders`. The API returns this shape:

```json
{"data": [{"id": 1, "total": 19.5, "customer": {"name": "Ana"}}],
 "links": {"next": null}}
```

To export its orders:

1. Choose **New job** and enter the name `Shop orders` and the URL above.
2. Set **Authentication type** to *API key in a header*, **Key name** to `X-Shop-Key`, and enter your key as the secret. Type `env:SHOP_API_KEY` instead of the key to read it from an environment variable.
3. Set **Pagination type** to *Page number*. Set the page parameter to `page`, the page size parameter to `limit`, and the page size to `100`.
4. Set **Records path** to `data`. Set **Duplicate key column** to `id` if the API can repeat orders.
5. Choose **Create job**, then **Preview** and **Run**.

## Scheduling

The tool has no built-in scheduler. Run the job from the operating system scheduler.

Windows Task Scheduler, daily at 07:00:

```powershell
schtasks /Create /SC DAILY /ST 07:00 /TN "Orders export" /TR "<path>\apitool.exe --data-dir <path>\data run --job \"Orders\""
```

Linux or macOS cron, daily at 07:00:

```cron
0 7 * * * /path/to/.venv/bin/apitool --data-dir /path/to/data run --job "Orders"
```

The exit code is 0 on success, 1 when the run failed, 2 for a configuration problem and 3 for an internal error.

## How data is transformed

1. Each record is flattened: `{"a": {"b": 1}}` becomes the column `a.b`. Arrays are kept as compact JSON text.
2. If a duplicate key is set, the first record with each key is kept. Records with a missing or empty key are skipped and counted.
3. Columns are the fields you selected, in your order. Without a selection, they are every field found in the kept records, in the order first seen.
4. Values are written as text in CSV. Excel cells keep numbers and booleans as numbers. Integers of 10^15 or more are written as text, because Excel cannot store them exactly.
5. Text that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading apostrophe. This stops spreadsheet programs from running it as a formula. Numbers are not changed, so a negative amount such as `-12.5` stays as it is. Text such as `"-5"` gets the apostrophe.
6. Excel cells are limited to 32,767 characters. Longer text is cut and reported as a warning.

## Security

- The server listens on 127.0.0.1 only. It rejects requests whose Host header is not `127.0.0.1` or `localhost`.
- Every form has a token that the server checks. Responses set a strict Content-Security-Policy and other security headers. The page has no inline scripts.
- Secrets are stored in the local SQLite file under `data/`. They are not encrypted in this version. For a shared or scheduled machine, store `env:NAME` and set the variable in the environment instead.
- Secrets never appear in logs, run records, the command line output, the web pages or the export files.
- Logged URLs never include the query string.
- Redirects are not followed. A next-page URL must stay on the same scheme, host and port as the configured URL, so credentials are never sent elsewhere.
- TLS certificate checks are always on.

## Design decisions

- **FastAPI with server-rendered pages.** The UI is a few forms and tables. Server rendering needs no JavaScript build, and the tests use an in-process client.
- **Plain Python for the data, not pandas.** pandas guesses types, so `"00731"` becomes `731`. Plain Python keeps the values as the API sent them.
- **sqlite3, not an ORM.** Five small tables do not need SQLAlchemy.
- **httpx, not requests.** httpx has a mock transport, so the demo API and the tests use the same request code as real traffic.
- **Streamlit or Gradio were rejected.** Their rerun model makes long runs and form state awkward, and UI tests are weak.
- **Django was rejected.** It is too heavy for a single-user local tool.
- **HTMX or a single-page app was rejected.** Plain form posts are simpler to build and to test.

## Development

Run these from the repository root with the virtual environment active:

```text
ruff format .
ruff check .
pytest -q
```

Layout: `src/apitool/` holds the package. `config.py` and `pipeline.py` hold the rules, `http_client.py` and `pagination.py` fetch pages, `export.py` writes files, `storage.py` is the only module that runs SQL, `runner.py` runs a job, `web/` holds the UI, and `demo/` holds the fake API. `tests/` runs offline. The network is blocked in the test suite.

## Roadmap

Planned for later versions, not built yet:

- Phase 2: a built-in scheduler with cron expressions, watermark incremental sync (`updated_since`), `Link` header pagination, JSON and JSON Lines export, and a Docker image.
- Phase 3: OAuth2 client credentials, POST and GraphQL requests, destinations such as Google Sheets and PostgreSQL, encryption of stored secrets, failure notifications by email or webhook, and a background job queue with progress.

## License

MIT. See [LICENSE](LICENSE).
