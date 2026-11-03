# ACCEPTANCE — API Automation & Data Integration Tool (v1)

Each acceptance case (AC) maps to a PLAN task. A task is done only when all of its ACs pass and the stated evidence exists.

**Evidence** always means: the named test file and test function(s) exist, and `pytest -q` passes with them included. When a case also needs a manual check, the evidence is a short note in the task's commit message body, of the form `manual: <what was checked> -> <result>`.

**Independence rule.** Every expected value in this document was worked out by hand from the dataset in §2 and the rules in SPEC.md. It was not produced by running any code. The executor copies these values into `tests/fixtures/expected/*.json` or into test literals **by transcription**. Never generate them by running production code, and never "update" them to match what the code produces. If the code and this document disagree, the code is wrong. If you believe this document is wrong, stop and escalate (PLAN, Execution Guardrails G4).

---

## 1. Conventions used in the tests

- `DEMO = "https://demo.api-automation-tool.local"`.
- Engine-level tests build a `DemoApi(version)` and a `httpx.MockTransport(api.handle)`, and pass the transport in directly.
- The sleep stub `sleeps = []; sleep = sleeps.append` records requested delays without sleeping.
- `now` stub: a function that returns `datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)` and then 1 second later on each call.
- CSV read-back: `open(path, encoding="utf-8-sig", newline="")` and `list(csv.reader(f))`.
- XLSX read-back: `openpyxl.load_workbook(path)`, sheet `data`, `[list(r) for r in ws.iter_rows(values_only=True)]`. Compare every cell by value **and** by `type()`. Python treats `0 == False` as true, so a type check is required.
- Web tests: `TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000")`. The CSRF token is read from `app.state.csrf_token`.

---

## 2. Fixed demo fixture dataset

Copy each JSON block below **verbatim** (UTF-8, no BOM) into the named file in `src/apitool/demo/datasets/`. The non-ASCII characters (`ë`, `ü`, `山田太郎`) must be stored as UTF-8. The escape `\u0007` must stay as written.

### 2.1 Orders (page pagination, header API key)

Design: 11 records, served in pages of 4 (pages of 4, 4, 3). They contain an exact duplicate across pages (1004), a same-key record with different content (1002, the first occurrence must win), a record with no `id`, missing fields, nested objects at two depths, lists, `null`, an empty string, Unicode, a comma, quotes, a newline, a leading tab, a formula-injection string, strings starting with `-`, `@` and `+`, a leading-zero string, a negative float, a float with `.0`, and an integer zero.

`orders_v1.json`
```json
[
  {"id": 1001, "status": "paid", "total": 19.99, "currency": "USD", "customer": {"name": "Alice Smith", "email": "alice@example.com"}, "tags": ["new", "vip"], "shipped": true, "note": null},
  {"id": 1002, "status": "pending", "total": 5, "currency": "USD", "customer": {"name": "Bob, Jr.", "email": "bob@example.com"}, "tags": [], "shipped": false, "note": "Leave at \"back\" door"},
  {"id": 1003, "status": "paid", "total": 120.5, "currency": "EUR", "customer": {"name": "Zoë Müller", "email": "zoe@example.de"}, "tags": ["intl"], "shipped": true, "note": "Line one\nLine two"},
  {"id": 1004, "status": "refunded", "total": 0, "currency": "USD", "customer": {"name": "=HYPERLINK(\"http://evil.example\")", "email": "mallory@example.com"}, "tags": ["flagged"], "shipped": false, "note": "-discount applied"},
  {"id": 1004, "status": "refunded", "total": 0, "currency": "USD", "customer": {"name": "=HYPERLINK(\"http://evil.example\")", "email": "mallory@example.com"}, "tags": ["flagged"], "shipped": false, "note": "-discount applied"},
  {"id": 1005, "status": "paid", "total": 42.0, "currency": "JPY", "customer": {"name": "山田太郎", "email": "yamada@example.jp"}, "tags": ["intl", "vip"], "shipped": true, "note": "@mention"},
  {"status": "pending", "total": 7.25, "currency": "USD", "customer": {"name": "No Id Corp", "email": "noid@example.com"}, "tags": [], "shipped": false, "note": ""},
  {"id": 1006, "status": "paid", "total": 3.5, "currency": "USD", "customer": {"name": "Dana Lee"}, "tags": ["new"], "shipped": true},
  {"id": 1002, "status": "paid", "total": 5, "currency": "USD", "customer": {"name": "Bob, Jr.", "email": "bob@example.com"}, "tags": [], "shipped": true, "note": "Leave at \"back\" door"},
  {"id": 1007, "status": "paid", "total": 99.99, "currency": "USD", "customer": {"name": "Evan Ortiz", "email": "evan@example.com", "address": {"city": "Austin", "zip": "00731"}}, "tags": ["vip"], "shipped": true, "note": "+1 priority"},
  {"id": 1008, "status": "cancelled", "total": -12.5, "currency": "USD", "customer": {"name": "Fay Wong", "email": "fay@example.com"}, "tags": ["a", "b", "c"], "shipped": false, "note": "\tTabbed", "coupon": "SAVE10"}
]
```

`orders_v2_extra.json` (dataset v2 = v1 + these 3, giving 14 records and pages of 4, 4, 4, 2)
```json
[
  {"id": 1009, "status": "paid", "total": 15, "currency": "USD", "customer": {"name": "Gus Park", "email": "gus@example.com"}, "tags": [], "shipped": false, "note": "new in v2"},
  {"id": 1010, "status": "pending", "total": 8.75, "currency": "GBP", "customer": {"name": "Hana Ito", "email": "hana@example.co.uk"}, "tags": ["intl"], "shipped": false, "note": null},
  {"id": 1011, "status": "paid", "total": 250, "currency": "USD", "customer": {"name": "Ivy Chen", "email": "ivy@example.com"}, "tags": ["vip"], "shipped": true, "note": "bulk"}
]
```

### 2.2 Customers (offset pagination, bearer)

Design: 6 records with limit 3, so the third request (offset 6) returns an empty page. This tests the "exact multiple of page size" stop rule. It also contains an integer of 1e15 or more, a control character, an empty nested object, a `null` nested value, a list that contains an object, a bool, an integer zero and a negative float.

`customers.json`
```json
[
  {"id": "C-001", "name": "Acme Ltd", "active": true, "balance": 1250.75, "profile": {"tier": "gold", "since": "2021-04-01"}},
  {"id": "C-002", "name": "Beta LLC", "active": false, "balance": 0, "profile": {"tier": "silver", "since": "2022-11-15"}},
  {"id": "C-003", "name": "Gamma GmbH", "active": true, "balance": -40.5, "profile": {"tier": "bronze", "since": null}},
  {"id": "C-004", "name": "Delta & Sons", "active": true, "balance": 98765432101234567, "profile": {"tier": "gold", "since": "2020-01-31"}},
  {"id": "C-005", "name": "Epsilon\u0007Bell", "active": false, "balance": 12, "profile": {}},
  {"id": "C-006", "name": "Zeta Co", "active": true, "balance": 3.14159, "profile": {"tier": "silver", "since": "2023-06-30"}, "notes": ["a", {"b": 1}]}
]
```

### 2.3 Events (cursor pagination, query-string API key)

Design: 3 cursor pages. The last page repeats `evt_002`, a duplicate across pages. A later page introduces a new nested column (`payload.reason`). One value contains a comma. One payload is empty.

`events_pages.json`
```json
[
  {"results": [
    {"event_id": "evt_001", "type": "signup", "ts": "2026-10-01T09:00:00Z", "payload": {"plan": "pro", "seats": 5}},
    {"event_id": "evt_002", "type": "upgrade", "ts": "2026-10-02T12:30:00Z", "payload": {"plan": "team", "seats": 12}}
  ], "next_cursor": "c_2"},
  {"results": [
    {"event_id": "evt_003", "type": "login", "ts": "2026-10-03T08:15:00Z", "payload": {}},
    {"event_id": "evt_004", "type": "cancel", "ts": "2026-10-04T17:45:00Z", "payload": {"plan": "pro", "reason": "too expensive, for now"}}
  ], "next_cursor": "c_4"},
  {"results": [
    {"event_id": "evt_005", "type": "signup", "ts": "2026-10-05T10:00:00Z", "payload": {"plan": "free", "seats": 1}},
    {"event_id": "evt_002", "type": "upgrade", "ts": "2026-10-02T12:30:00Z", "payload": {"plan": "team", "seats": 12}}
  ], "next_cursor": null}
]
```

### 2.4 Products (next-URL pagination, basic auth)

Design: page 1 gives an **absolute** next URL, page 2 a **relative** one, page 3 `null`. There is an extra field that must be excluded by field selection, a missing field, a `+` formula-prefix string, and a comma in a title.

`products_pages.json`
```json
[
  {"items": [
    {"sku": "SKU-1", "title": "Desk Lamp", "price": {"amount": 24.5, "currency": "USD"}, "stock": 12, "internal_code": "X1"},
    {"sku": "SKU-2", "title": "Office Chair", "price": {"amount": 149, "currency": "USD"}, "stock": 0, "internal_code": "X2"}
  ], "links": {"next": "https://demo.api-automation-tool.local/v1/products?page=2"}},
  {"items": [
    {"sku": "SKU-3", "title": "USB-C Hub", "price": {"amount": 39.99, "currency": "EUR"}, "stock": 57},
    {"sku": "SKU-4", "title": "Notebook, A5", "price": {"amount": 3.2, "currency": "GBP"}}
  ], "links": {"next": "/v1/products?page=3"}},
  {"items": [
    {"sku": "SKU-5", "title": "+Plus Pen", "price": {"amount": 1.75, "currency": "USD"}, "stock": 300}
  ], "links": {"next": null}}
]
```

---

## 3. Expected outputs (computed by hand)

Copy each block into `tests/fixtures/expected/<file>`. Row arrays are what `csv.reader` returns. Index 0 is the header.

### 3.1 `orders_dedup_rows.json`: Demo Orders, dataset v1, first run (dedup on `id`)
How it was derived: 11 fetched. Record 5 (1004) and record 9 (1002) are duplicates (2). Record 7 has no `id` (1 missing). 8 exported. The columns are the union in first-appearance order: the 9 keys of record 1, then `customer.address.city` and `customer.address.zip` (record 10), then `coupon` (record 11). Strings starting with `=`, `-`, `@`, `+` or TAB get a `'` prefix. Floats use `repr`. Lists are compact JSON.
```json
[
  ["id","status","total","currency","customer.name","customer.email","tags","shipped","note","customer.address.city","customer.address.zip","coupon"],
  ["1001","paid","19.99","USD","Alice Smith","alice@example.com","[\"new\",\"vip\"]","true","","","",""],
  ["1002","pending","5","USD","Bob, Jr.","bob@example.com","[]","false","Leave at \"back\" door","","",""],
  ["1003","paid","120.5","EUR","Zoë Müller","zoe@example.de","[\"intl\"]","true","Line one\nLine two","","",""],
  ["1004","refunded","0","USD","'=HYPERLINK(\"http://evil.example\")","mallory@example.com","[\"flagged\"]","false","'-discount applied","","",""],
  ["1005","paid","42.0","JPY","山田太郎","yamada@example.jp","[\"intl\",\"vip\"]","true","'@mention","","",""],
  ["1006","paid","3.5","USD","Dana Lee","","[\"new\"]","true","","","",""],
  ["1007","paid","99.99","USD","Evan Ortiz","evan@example.com","[\"vip\"]","true","'+1 priority","Austin","00731",""],
  ["1008","cancelled","-12.5","USD","Fay Wong","fay@example.com","[\"a\",\"b\",\"c\"]","false","'\tTabbed","","","SAVE10"]
]
```

### 3.2 `orders_nodedup_rows.json`: orders v1 with `dedup_key=""` (all 11 records, same column order)
```json
[
  ["id","status","total","currency","customer.name","customer.email","tags","shipped","note","customer.address.city","customer.address.zip","coupon"],
  ["1001","paid","19.99","USD","Alice Smith","alice@example.com","[\"new\",\"vip\"]","true","","","",""],
  ["1002","pending","5","USD","Bob, Jr.","bob@example.com","[]","false","Leave at \"back\" door","","",""],
  ["1003","paid","120.5","EUR","Zoë Müller","zoe@example.de","[\"intl\"]","true","Line one\nLine two","","",""],
  ["1004","refunded","0","USD","'=HYPERLINK(\"http://evil.example\")","mallory@example.com","[\"flagged\"]","false","'-discount applied","","",""],
  ["1004","refunded","0","USD","'=HYPERLINK(\"http://evil.example\")","mallory@example.com","[\"flagged\"]","false","'-discount applied","","",""],
  ["1005","paid","42.0","JPY","山田太郎","yamada@example.jp","[\"intl\",\"vip\"]","true","'@mention","","",""],
  ["","pending","7.25","USD","No Id Corp","noid@example.com","[]","false","","","",""],
  ["1006","paid","3.5","USD","Dana Lee","","[\"new\"]","true","","","",""],
  ["1002","paid","5","USD","Bob, Jr.","bob@example.com","[]","true","Leave at \"back\" door","","",""],
  ["1007","paid","99.99","USD","Evan Ortiz","evan@example.com","[\"vip\"]","true","'+1 priority","Austin","00731",""],
  ["1008","cancelled","-12.5","USD","Fay Wong","fay@example.com","[\"a\",\"b\",\"c\"]","false","'\tTabbed","","","SAVE10"]
]
```

### 3.3 `orders_v2_new_rows.json`: Demo Orders incremental, third run (after v1, v1, then switch to v2)
How it was derived: 14 fetched over 4 pages. 1 missing key. 2 duplicates. 8 already seen (1001–1008). 3 exported. Only the kept records define the columns, so there are 9 columns.
```json
[
  ["id","status","total","currency","customer.name","customer.email","tags","shipped","note"],
  ["1009","paid","15","USD","Gus Park","gus@example.com","[]","false","new in v2"],
  ["1010","pending","8.75","GBP","Hana Ito","hana@example.co.uk","[\"intl\"]","false",""],
  ["1011","paid","250","USD","Ivy Chen","ivy@example.com","[\"vip\"]","true","bulk"]
]
```

### 3.4 `events_rows.json`: Demo Events (dedup on `event_id`)
```json
[
  ["event_id","type","ts","payload.plan","payload.seats","payload.reason"],
  ["evt_001","signup","2026-10-01T09:00:00Z","pro","5",""],
  ["evt_002","upgrade","2026-10-02T12:30:00Z","team","12",""],
  ["evt_003","login","2026-10-03T08:15:00Z","","",""],
  ["evt_004","cancel","2026-10-04T17:45:00Z","pro","","too expensive, for now"],
  ["evt_005","signup","2026-10-05T10:00:00Z","free","1",""]
]
```

### 3.5 Events exact CSV bytes (for AC-21)
The file is exactly the 3 bytes `EF BB BF` followed by these 6 lines, each ending in `\r\n` (CR LF), with nothing after the last one:
```
event_id,type,ts,payload.plan,payload.seats,payload.reason
evt_001,signup,2026-10-01T09:00:00Z,pro,5,
evt_002,upgrade,2026-10-02T12:30:00Z,team,12,
evt_003,login,2026-10-03T08:15:00Z,,,
evt_004,cancel,2026-10-04T17:45:00Z,pro,,"too expensive, for now"
evt_005,signup,2026-10-05T10:00:00Z,free,1,
```
Write this in the test as a Python bytes literal: `b"\xef\xbb\xbf" + b"\r\n".join([...lines as bytes...]) + b"\r\n"`.

Raw-line checks on the orders dedup CSV file (substring of the decoded text, `\r\n` shown explicitly):
- `1003,paid,120.5,EUR,Zoë Müller,zoe@example.de,"[""intl""]",true,"Line one\nLine two",,,\r\n` (the embedded newline is a single LF inside quotes)
- `1004,refunded,0,USD,"'=HYPERLINK(""http://evil.example"")",mallory@example.com,"[""flagged""]",false,'-discount applied,,,\r\n`
- `1002,pending,5,USD,"Bob, Jr.",bob@example.com,[],false,"Leave at ""back"" door",,,\r\n`

### 3.6 `customers_xlsx.json`: Demo Customers (no dedup), XLSX values. JSON `true`/`false`/`null` mean Python `True`/`False`/`None`.
How it was derived: 98765432101234567 is ≥ 10^15, so it is written as a string. `\u0007` is removed. `profile: {}` adds no columns. `notes` first appears on C-006 and is rendered as compact JSON.
```json
[
  ["id","name","active","balance","profile.tier","profile.since","notes"],
  ["C-001","Acme Ltd",true,1250.75,"gold","2021-04-01",null],
  ["C-002","Beta LLC",false,0,"silver","2022-11-15",null],
  ["C-003","Gamma GmbH",true,-40.5,"bronze",null,null],
  ["C-004","Delta & Sons",true,"98765432101234567","gold","2020-01-31",null],
  ["C-005","EpsilonBell",false,12,null,null,null],
  ["C-006","Zeta Co",true,3.14159,"silver","2023-06-30","[\"a\",{\"b\":1}]"]
]
```
Formatting expectations: sheet title `data`; `A1:G1` bold; `freeze_panes == "A2"`; `auto_filter.ref == "A1:G7"`; column widths A=10 (`id`), B=10, C=10, D=10, E=14 (`profile.tier`, 12+2), F=15 (`profile.since`, 13+2), G=10. openpyxl may merge neighbouring columns of equal width into one entry when it saves. Read the widths back by going through `ws.column_dimensions.values()` and giving each entry's `width` to every column index from `dim.min` to `dim.max`. Do not index `ws.column_dimensions["B"]` directly.

### 3.7 `products_xlsx.json`: Demo Products (field selection plus renames)
```json
[
  ["sku","title","price","currency","stock"],
  ["SKU-1","Desk Lamp",24.5,"USD",12],
  ["SKU-2","Office Chair",149,"USD",0],
  ["SKU-3","USB-C Hub",39.99,"EUR",57],
  ["SKU-4","Notebook, A5",3.2,"GBP",null],
  ["SKU-5","'+Plus Pen",1.75,"USD",300]
]
```
`auto_filter.ref == "A1:E6"`.

### 3.8 `run_stats.json`: counters per demo job (first run, dataset v1, fresh database)
```json
{
  "Demo Orders":       {"pages_fetched": 3, "records_fetched": 11, "retries": 0, "duplicates_removed": 2, "records_missing_key": 1, "already_seen_skipped": 0, "records_exported": 8},
  "Demo Customers":    {"pages_fetched": 3, "records_fetched": 6,  "retries": 0, "duplicates_removed": 0, "records_missing_key": 0, "already_seen_skipped": 0, "records_exported": 6},
  "Demo Events":       {"pages_fetched": 3, "records_fetched": 6,  "retries": 0, "duplicates_removed": 1, "records_missing_key": 0, "already_seen_skipped": 0, "records_exported": 5},
  "Demo Products":     {"pages_fetched": 3, "records_fetched": 5,  "retries": 0, "duplicates_removed": 0, "records_missing_key": 0, "already_seen_skipped": 0, "records_exported": 5},
  "Demo Flaky Orders": {"pages_fetched": 3, "records_fetched": 11, "retries": 3, "duplicates_removed": 2, "records_missing_key": 1, "already_seen_skipped": 0, "records_exported": 8}
}
```
Warnings expected: Demo Orders and Demo Flaky Orders have exactly `["missing_key: 1 records skipped because key field 'id' was missing or empty"]`. All other jobs have `[]`.

### 3.9 Incremental scenario (Demo Orders, incremental on)
| Step | Dataset | pages | fetched | dup | missing | already seen | exported | output file | seen_keys rows after |
|---|---|---|---|---|---|---|---|---|---|
| Run 1 | v1 | 3 | 11 | 2 | 1 | 0 | 8 | rows = §3.1 | 8 (`1001`…`1008`) |
| Run 2 | v1 | 3 | 11 | 2 | 1 | 8 | 0 | none (`output_file` NULL, message `No records to export`) | 8 |
| switch to v2 | | | | | | | | | |
| Run 3 | v2 | 4 | 14 | 2 | 1 | 8 | 3 | rows = §3.3 | 11 |
| Reset state, Run 4 | v2 | 4 | 14 | 2 | 1 | 0 | 11 | 11 rows: §3.1's 8 data rows in order, then §3.3's 3 data rows (header = §3.1 header) | 11 |

For Run 4, write a separate expected file `orders_v2_full_rows.json`. Its header is §3.1's 12-column header. Its rows are §3.1 rows 1–8 followed by the §3.3 rows, each padded with 3 trailing `""` for the address and coupon columns (the new records lack them). All rows have 12 cells.

---

## 4. Acceptance cases

Test files are named in brackets. Unless stated otherwise, "error X" means the raised (or recorded) `error_type` is X **and** the message contains the quoted text.

### Foundation
**AC-01** (T01) [tests/test_smoke.py] `import apitool; apitool.__version__ == "1.0.0"`. `cli.main(["--version"])` prints `apitool 1.0.0` and returns 0. `ruff check .` and `ruff format --check .` exit 0.

**AC-02** (T03) [tests/test_errors_redact.py]
- Exit codes: `ConfigError`, `JobNotFoundError`, `JobBusyError` → 2. `HttpError`, `NetworkError`, `InvalidResponseError`, `PaginationError`, `TransformError`, `ExportError` → 1.
- `redact("token abc and abcdef", ["abc", "abcdef"]) == "token *** and ***"` (the longer secret is replaced first).
- `redact("x", [""]) == "x"` (empty secrets are ignored).
- `strip_query("https://h.example:8443/a/b?api_key=s&x=1") == "https://h.example:8443/a/b"`.
- `RedactingFilter`: with secret `s3cr3t` registered, `logger.info("value=%s", "s3cr3t")` produces the text `value=***` (check with `caplog`). After unregistering, the same call logs `value=s3cr3t`.

### Engine (checkpoint CP1)
**AC-03** (T04) [tests/test_config.py] The five demo job configs from SPEC §19.3 build without error. Each case in the table below raises `ConfigError` whose `.errors` contains the listed field:

| # | Change from a valid `page` config | Field |
|---|---|---|
| 1 | name `""` | name |
| 2 | name `"a/b"` | name |
| 3 | name of 61 × `a` | name |
| 4 | url `"ftp://x.example/a"` | url |
| 5 | url `"https://user:pw@x.example/a"` | url |
| 6 | url `"https://x.example/a#frag"` | url |
| 7 | auth `api_key_header` with auth_key_name `""` | auth_key_name |
| 8 | auth `basic` with auth_username `""` | auth_username |
| 9 | page_size 0, and separately 1001 | page_size |
| 10 | max_pages 0, and separately 1001 | max_pages |
| 11 | timeout_seconds 0, and separately 121 | timeout_seconds |
| 12 | incremental true with dedup_key `""` | incremental |
| 13 | pagination `cursor` with cursor_path `""` | cursor_path |
| 14 | pagination `next_url` with next_url_path `""` | next_url_path |
| 15 | export_format `"json"` | export_format |
| 16 | records_path `"a..b"` | records_path |

**AC-04** (T04) [tests/test_config.py] Text parsers:
- `parse_query_params("a=1\n\n b = x=y \n")` returns `[("a","1"),("b","x=y")]`.
- `parse_query_params("a=1\nbad")` → error message `line 2: expected key=value`.
- `parse_headers("X-Test: one: two")` returns `[("X-Test","one: two")]`.
- `parse_headers("NoColon")` → `line 1: expected Name: value`.
- `parse_fields(" a, b ,,c ")` returns `["a","b","c"]`.
- `parse_fields("a,a")` → `duplicate field 'a'`.
- `parse_renames("price.amount=price\nx=")` → error, because the new name is blank.
- Round trip: `parse_X(format_X(v)) == v` for the parsed values above.

**AC-05** (T05) [tests/test_jsonpath.py] With `obj = {"a": {"b": [{"c": 1}], "n": None}}`: `get_path(obj,"") is obj`; `"a.b.0.c"` → 1; `"a.n"` → `None`; `"a.x"`, `"a.b.5"`, `"a.b.c"`, `"a.b.0.c.d"` → `MISSING`; `get_path([10, 20], "1")` → 20.

**AC-06** (T06) [tests/test_demo_api.py] DemoApi auth: each authed endpoint returns 401 with no credential, with a wrong credential and with the right credential in the wrong place, and returns 200 with the correct credential. Unknown path → 404. `/v1/orders?per_page=0` → 400. `/v1/events?cursor=zzz` → 400. `/v1/products?page=4` → 400.

**AC-07** (T06) [tests/test_demo_api.py] DemoApi shapes: `/v1/orders?page=3&per_page=4` (v1) returns 3 records whose ids are `[1002, 1007, 1008]` and `meta.total == 11`. With version 2, `meta.total == 14`. `/v1/customers?offset=6&limit=3` returns `customers == []`. `/v1/products?page=2` returns `links.next == "/v1/products?page=3"`. On one instance, the first call to `/v1/flaky-orders?page=1` returns 503 with `Retry-After: 0` and the second returns 200. `api.requests` records every call.

**AC-08** (T07) [tests/test_expected_fixtures.py] Every file listed in §3 exists in `tests/fixtures/expected/` and parses as JSON. Row counts including the header: orders_dedup 9, orders_nodedup 12, orders_v2_new 4, orders_v2_full 12, events 6, customers 7, products 6. Every row in a file has the same number of cells as its header. This test must not import any `apitool` module.

**AC-09** (T08) [tests/test_http_client.py] URL building: config url `https://api.example.com/v1/items?a=1&b=2`, query_params `[("b","3"),("c","x y")]`, page params `{"page": 1, "per_page": 50}`, auth `api_key_query` key `key` secret `s3cr&t` → exactly `https://api.example.com/v1/items?a=1&b=3&c=x+y&page=1&per_page=50&key=s3cr%26t`. With url `https://api.example.com/v1/items`, no params and auth `none` → exactly `https://api.example.com/v1/items` (no `?`).

**AC-10** (T08) [tests/test_http_client.py] Auth headers on the sent request: `api_key_header` gives `X-API-Key: demo-key-123`; `bearer` gives `Authorization: Bearer demo-token-456`; `basic` demo/demo-pass gives `Authorization: Basic ZGVtbzpkZW1vLXBhc3M=`. A custom header `Authorization: custom` combined with bearer auth is overwritten by the bearer value. Every request carries `User-Agent: api-automation-tool/1.0.0`.

**AC-11** (T08) [tests/test_http_client.py] Response validation against the demo API, with the stub sleep:
- `/v1/not-json` → InvalidResponseError `not valid JSON`, 1 request.
- `/v1/nan` → InvalidResponseError `not valid JSON`.
- `/v1/too-large` → InvalidResponseError `response too large`.
- `/v1/redirect` → InvalidResponseError `unexpected redirect (302)`, 1 request.
- `/v1/orders` with a wrong key → HttpError `HTTP 401`, `status_code == 401`, 1 request, `sleeps == []`.
- An unknown path → HttpError `HTTP 404`, 1 request.
- No error message contains `?`.

**AC-12** (T09) [tests/test_retry.py]
| Case | Requests | sleeps | retries | Result |
|---|---|---|---|---|
| `/v1/flaky-orders?page=1` (one page fetch) | 2 | `[0]` | 1 | 200 |
| `/v1/rate-limited` | 3 | `[2, 2]` | 2 | 200 |
| `/v1/retry-after-big` | 2 | `[30]` | 1 | 200 |
| `/v1/always-500` | 4 | `[1, 2, 4]` | 3 | HttpError `HTTP 500` |
| Transport raising `httpx.ConnectError("boom")` every time | 4 | `[1, 2, 4]` | 3 | NetworkError |
| Response 503 with `Retry-After: soon` then 200 | 2 | `[1]` | 1 | 200 |

**AC-13** (T10) [tests/test_pagination.py] Exact request URLs (taken from `api.requests`, in order):
- Demo Orders config, v1: `DEMO/v1/orders?page=1&per_page=4`, `...?page=2&per_page=4`, `...?page=3&per_page=4` (3 requests, 11 records).
- Demo Orders with page_size 11: `page=1&per_page=11`, `page=2&per_page=11` (2 requests. Page 1 is full, page 2 is empty).
- Demo Customers: `DEMO/v1/customers?offset=0&limit=3`, `?offset=3&limit=3`, `?offset=6&limit=3` (3 requests, 6 records).
- Demo Events: `DEMO/v1/events?limit=2&api_key=demo-key-123`, `?cursor=c_2&limit=2&api_key=demo-key-123`, `?cursor=c_4&limit=2&api_key=demo-key-123` (3 requests, 6 records).
- Demo Products: `DEMO/v1/products`, `DEMO/v1/products?page=2`, `DEMO/v1/products?page=3` (3 requests, 5 records).
- `none` pagination against `/v1/rate-limited` (records_path `data`): 1 page, 1 record.

**AC-14** (T10) [tests/test_pagination.py]
- `/v1/loop-cursor` (cursor, records_path `results`, cursor_path `next_cursor`) → PaginationError `pagination loop detected`, after exactly 2 requests.
- `/v1/offsite-next` (next_url, records_path `items`, next_url_path `links.next`) → PaginationError `different host`. Exactly 1 request is made, and no request ever goes to `evil.example`.
- `/v1/object-records` (records_path `data`) → InvalidResponseError `did not point to a list (got object)`.
- Demo Orders with records_path `items` → InvalidResponseError `records_path 'items' not found`.

**AC-15** (T10) [tests/test_pagination.py] Demo Orders with max_pages 2 → 2 requests, 8 records, warning `max_pages_reached: stopped after 2 pages; more data may exist`. Demo Orders with max_pages 3 → 3 requests and no warning.

**AC-16** (T11) [tests/test_transform.py] Flatten and render:
- `flatten({"a": 1, "b": {"c": {"d": 2}, "e": {}}, "f": [1, {"g": 2}]}) == {"a": 1, "b.c.d": 2, "f": [1, {"g": 2}]}`, and the key order is `a, b.c.d, f`.
- `render_csv`: `None`→`""`, `True`→`"true"`, `False`→`"false"`, `0`→`"0"`, `42.0`→`"42.0"`, `-12.5`→`"-12.5"`, `"x"`→`"x"`, `[]`→`"[]"`, `["é", 1]`→`"[\"é\",1]"`.
- `render_xlsx`: `True` → `True` (type bool), `10**15 - 1` → int, `10**15` → `"1000000000000000"`, `-(10**15)` → `"-1000000000000000"`, `1.5` → `1.5`, `None` → `None`.
- Non-dict records: the pipeline wraps `"abc"` as `{"value": "abc"}`.

**AC-17** (T11) [tests/test_transform.py] `sanitize_text`: `"=1+1"`→`"'=1+1"`, `"+x"`→`"'+x"`, `"-x"`→`"'-x"`, `"@x"`→`"'@x"`, `"\tx"`→`"'\tx"`, `"\rx"`→`"'\rx"`, `"a=b"`→`"a=b"`, `""`→`""`, `"[1]"`→`"[1]"`.

**AC-18** (T12) [tests/test_pipeline.py] Pipeline on `ORDERS_V1` with dedup_key `id`, not incremental: the header (`sanitize_text` on each name) plus the rows rendered with `csv_cell` equal `orders_dedup_rows.json`. `csv_cell` sanitizes only values whose original type is `str`, so the float `-12.5` stays `-12.5`. Counts are 11/2/1/0/8 (fetched/dup/missing/seen/exported), and the missing_key warning is present. The invariant from SPEC §9.2 holds.

**AC-19** (T12) [tests/test_pipeline.py] Pipeline on `ORDERS_V1` with no dedup_key equals `orders_nodedup_rows.json`. Counts are 11/0/0/0/11 and there are no warnings.

**AC-20** (T12) [tests/test_pipeline.py] Pipeline on the raw products (all `PRODUCTS_PAGES` items concatenated, in page order) with the Demo Products fields and renames: the header is `["sku","title","price","currency","stock"]`, and the CSV-rendered row 4 is `["SKU-4","Notebook, A5","3.2","GBP",""]`. Field `missing_col` in `fields` gives an all-empty column, not an error. Renames `{"sku": "title"}` with no fields → TransformError `duplicate column name after rename: 'title'`.

**AC-21** (T12) [tests/test_pipeline.py] Incremental filtering: `ORDERS_V2` with stored keys `{"1001",…,"1008"}` gives rows equal to `orders_v2_new_rows.json`, counts 14/2/1/8/3, and exported keys `["1009","1010","1011"]`. Key text comparison: records `[{"id": 1}, {"id": "1"}]` with dedup_key `id` → 1 exported, 1 duplicate.

### Export (checkpoint CP2)
**AC-22** (T13) [tests/test_export_csv.py] Writing the pipeline output of Demo Events produces exactly the bytes in §3.5. Writing orders dedup produces a file whose read-back equals `orders_dedup_rows.json` and whose decoded text contains the three raw-line substrings from §3.5.

**AC-23** (T13) [tests/test_export_csv.py] Atomic write: when `csv.writer(...).writerow` is monkeypatched to raise `OSError` on the 3rd row, `ExportError` `could not write export: OSError` is raised, and the exports directory contains neither the final file nor any `.tmp` file.

**AC-24** (T14) [tests/test_export_xlsx.py] Customers output read back equals `customers_xlsx.json` (value and type per cell). Products output equals `products_xlsx.json`. The formatting expectations in §3.6 and §3.7 hold.

**AC-25** (T14) [tests/test_export_xlsx.py] Edge cases. Header `["=bad", "x"]`, rows `[["a\x01b", "y" * 40000], [10**15, -(10**15) + 1]]` → A1 `"'=bad"`, A2 `"ab"`, B2 length 32767, A3 `"1000000000000000"` (str), B3 `-999999999999999` (int). The returned warnings equal `["excel_truncated: 1 cell values longer than 32767 characters were truncated"]`. Atomic failure behaves as in AC-23 (monkeypatch `Workbook.save` to raise).

**AC-26** (T15) [tests/test_export_names.py] `slugify("Demo Orders") == "demo-orders"`, `slugify("  --Ünïcode!! Job__ ") == "n-code-job"`, `slugify("!!!") == "job"`. `export_filename("Demo Orders", datetime(2026,11,4,10,0,0,tzinfo=utc), 7, "csv") == "demo-orders_20261104-100000_run7.csv"`. `safe_export_path(exports_dir, "../x.csv")` and `safe_export_path(exports_dir, "C:\\x.csv")` return `None`. `safe_export_path(exports_dir, "a.csv")` returns `exports_dir / "a.csv"` (resolved).

(How the second slug was derived: lowercasing gives `"  --ünïcode!! job__ "`. The runs of non-`[a-z0-9]` characters are `"  --ü"`, `"ï"`, `"!! "`, `"__ "`, which leaves `n`, `code`, `job`. Joined with `-` that is `n-code-job`. Lowercasing does not remove the accents, so `ü` and `ï` count as non-`[a-z0-9]`.)

### State, runs and incremental sync (checkpoint CP3)
**AC-27** (T16) [tests/test_storage_jobs.py] Create, get, update, list and delete jobs. A duplicate name in a different case (`demo orders` vs `Demo Orders`) → ConfigError on `name`. Set and get secret. Deleting a job removes its secret and seen_keys, and its runs keep `job_name` with `job_id` NULL. `config_json` round-trips to an equal `JobConfig`.

**AC-28** (T17) [tests/test_storage_runs.py] `start_run` inserts a `running` row. `finish_run_success` and `finish_run_failed` set every column. A second `start_run` for the same job while one is running → JobBusyError. A `running` row whose `started_at` is 2 h 1 min before `now` is marked failed `Interrupted`, and the new run starts. A row 1 h 59 min old still blocks. `list_runs(limit=100)` is newest first.

**AC-29** (T18) [tests/test_storage_state.py] `get_seen_keys(job_id)` is empty at first. `add_seen_keys` inside a success-finish transaction persists the keys. `reset_state(job_id)` empties them. Keys are per job: two jobs with the same key do not affect each other.

**AC-30** (T19) [tests/test_runner.py] On a fresh database with the demo jobs, running each of the 5 demo jobs once (stub sleep, stub now) gives counters equal to `run_stats.json` and warnings equal to §3.8. Output files read back equal: Demo Orders = §3.1, Demo Events = §3.4, Demo Customers = §3.6, Demo Products = §3.7, Demo Flaky Orders = §3.1. The flaky run's sleeps are `[0, 0, 0]`. Output file names follow AC-26 and live in `data_dir/exports`.

**AC-31** (T19) [tests/test_runner.py] Failed runs: a job pointing at `/v1/always-500` gives a failed run with `error_type` `HttpError`, `retries == 3`, `output_file` NULL and no file in exports. `/v1/offsite-next` gives `PaginationError`. A job with secret `env:APITOOL_TEST_MISSING_VAR` (variable not set) gives a failed run with `ConfigError`, `environment variable APITOOL_TEST_MISSING_VAR is not set`. The same job with that variable set to `demo-key-123` (monkeypatch) succeeds.

**AC-32** (T19) [tests/test_runner.py] Redaction. Demo Orders with secret `super-secret-XYZ-123` (wrong key) → failed run `HttpError`, message `HTTP 401 from https://demo.api-automation-tool.local/v1/orders`. Demo Events with secret `query-secret-ABC-789` → failed, and the message contains neither `api_key` nor `?`. For both: the secret string does not occur in any column of the `runs` row, in `caplog.text` (level DEBUG), or in the CLI stdout or stderr (when run through `cli.main`).

**AC-33** (T19) [tests/test_runner.py] An unexpected exception (monkeypatch `pipeline.build_rows` to raise `ZeroDivisionError`) leaves a run row with `status='failed'`, `error_type='InternalError'` and `error_message='unexpected error: ZeroDivisionError'`, and the exception propagates out of `run_job`.

**AC-34** (T20) [tests/test_incremental.py] The §3.9 scenario, step by step, with every value in the table checked (counters, output rows, `output_file` NULL on run 2, `message == "No records to export"`, seen_keys count). Run 4's file equals `orders_v2_full_rows.json`.

**AC-35** (T20) [tests/test_incremental.py] Export failure does not commit state. With incremental Demo Orders and `export.write_csv` monkeypatched to raise `ExportError`, the run fails with `ExportError` and seen_keys stays at 0 rows. After removing the patch, the next run exports 8.

**AC-36** (T18, T24) [tests/test_storage_state.py, tests/test_web_jobs.py] `update_job` reports `state_reset=True` and clears seen_keys when `url`, `records_path`, `dedup_key` or `incremental` changes. It reports False and keeps the keys when only `name`, `export_format` or `max_pages` changes.

**AC-37** (T21) [tests/test_cli.py] All calls go through `cli.main([...])` with `--data-dir tmp_path`:
- `demo-setup` → 0, stdout `Demo jobs ready: 5 created, 0 already existed`. Calling it again → `0 created, 5 already existed`.
- `list-jobs` → 5 lines, sorted: `Demo Customers`, `Demo Events`, `Demo Flaky Orders`, `Demo Orders`, `Demo Products` (tab-separated as in SPEC §15).
- `run --job "demo orders"` → 0, stdout starts with `Run 1 success: Exported 8 records to demo-orders_` and has the line `warning: missing_key: 1 records skipped because key field 'id' was missing or empty`.
- Running it again → 0, `Run 2 success: No records to export`.
- `run --job "Nope"` → 2. `run` with no `--job` → 2 (argparse).
- A job on `/v1/always-500` → 1, stderr `Run N failed: HttpError: HTTP 500 from https://demo.api-automation-tool.local/v1/always-500`.
- A missing env secret → 2.
- `ZeroDivisionError` monkeypatched as in AC-33 → 3, stderr `internal error: ZeroDivisionError`.
- The CLI tests never wait for the real backoff. They use `monkeypatch.setattr(time, "sleep", fake)`. This works because the runner calls `time.sleep` at call time (PLAN T19).

### UI (checkpoint CP4)
**AC-38** (T22) [tests/test_web_security.py] `GET /` with `Host: evil.example` → 400 `invalid host`. With `Host: localhost:8000` → 200. Every response (200, 303, 400, 403, 404) has the four security headers from SPEC §14.2 with their exact values. No template contains `<script>` without `src=`, and none contains ` style=` (a test greps `src/apitool/web/templates/*.html`).

**AC-39** (T22) [tests/test_web_security.py] Every POST route, sent without `csrf_token` and with a wrong one → 403. With the right token → not 403.

**AC-40** (T23) [tests/test_web_jobs.py] On a fresh app, `GET /` shows `Load demo jobs`. `POST /demo/setup` → 303 to `/?notice=demo_loaded`. `GET /` then lists the 5 demo names and shows `Demo jobs are ready.`. Calling setup twice still gives 5 jobs. `POST /demo/dataset` with version `2` → the setting is `"2"`, and the page shows `dataset v2`. Version `3` → 400. `GET /?notice=<script>` renders no `<script>` text from the parameter.

**AC-41** (T24) [tests/test_web_jobs.py]
- Creating a valid job → 303, and the job is stored.
- An invalid URL → 400, the page contains the url error and the entered name.
- A duplicate name → 400 with `a job with this name already exists`.
- Bearer auth with no secret on create → 400 `required for this authentication type`.
- Edit page for a job with secret `zz-secret-zz` → the HTML does not contain `zz-secret-zz` and does contain `A secret is saved. Leave blank to keep it.`.
- Edit with a blank secret keeps the stored secret. `clear_secret` together with auth `none` removes it.
- Delete → 303, and the job is gone.
- Changing the url on edit → redirect `notice=state_reset_auto`.

**AC-42** (T25) [tests/test_web_preview.py] Preview of Demo Orders → 200, page shows `4 records`. Table headers are `id, status, total, currency, customer.name, customer.email, tags, shipped, note` in this order. The cell text `=HYPERLINK(&#34;http://evil.example&#34;)` or `=HYPERLINK(&quot;http://evil.example&quot;)` appears escaped (no raw `"` inside a tag attribute). The demo API received exactly 1 request. The test monkeypatches `apitool.runner.make_transport` to return a MockTransport over a DemoApi instance it holds (PLAN T19). No run row is created. Preview against `/v1/always-500` with the stub sleep → 200 page containing `HttpError`.

**AC-43** (T26) [tests/test_web_runs.py]
- `POST /jobs/{id}/run` for Demo Orders → 303 to `/runs/1`. That page shows `Success`, `8` for exported records, the missing_key warning and a Download link.
- `GET /runs/1/download` → 200, body equals the file bytes, and `content-disposition` contains `demo-orders_`.
- `GET /runs` lists run 1.
- A failed run page shows the error type and message.
- `/runs/999` → 404.
- A run row whose `output_file` is `../apitool.db` (set directly in the database) → download 404.
- While a run row of the job is `running` → `POST /run` returns 409 `This job is already running.`

**AC-44** (T27) [tests/test_web_render.py] Every GET page (`/`, `/jobs/new`, `/jobs/1/edit`, `/runs`, `/runs/1`) returns 200 and includes `/static/style.css` and `/static/app.js`. The job form contains every field name from SPEC §5.1 plus `secret`, `clear_secret` and `csrf_token`. The auth and pagination inputs have `data-show-for` attributes. `GET /static/app.js` → 200. Manual: in a browser on `apitool serve` with the demo jobs, switching the auth type and the pagination type hides and shows the matching fields, and delete asks for confirmation. Evidence: a `manual:` line in the commit body, and the screenshots from T29.

### Release (checkpoint CP5)
**AC-45** (T29) [manual + tests/test_readme.py] README.md contains these section headings: `What it does`, `Try it in 2 minutes`, `Connect your own API`, `Scheduling`, `How data is transformed`, `Security`, `Design decisions`, `Development`, `Roadmap`, `License`. The test checks the headings and that every image path referenced in README exists. Manual: following "Try it in 2 minutes" from a fresh clone, in a fresh venv, works.

**AC-46** (T30) [tests/test_repo_hygiene.py]
- `git ls-files` contains no path under `data/`, `ops/` or `video/`, and none ending in `.db`, `.xlsx`, `.csv` or `.log`.
- No tracked text file contains any of: `super-secret`, `query-secret`, `zz-secret`, `ENTIRE_TOKEN`, `BEGIN PRIVATE KEY`, `ghp_`, `github_pat_`. Exception: files under `tests/`, and `docs/ACCEPTANCE.md` and `docs/REVIEW.md`, may contain the three test-only strings and `ENTIRE_TOKEN`. The test must not flag itself.
- The demo credentials appear only in `src/apitool/demo/`, `tests/`, `docs/` and `README.md`.
- `.gitignore` equals SPEC §17.8 line for line.
- If `git` is not on PATH, the test is skipped with a reason (CI always has git).

**AC-47** (T30) Full gate: `pytest -q` passes, `ruff check .` and `ruff format --check .` pass, and the end-to-end demo smoke works on a fresh data dir: `apitool --data-dir <tmp> demo-setup` then `run` for each of the 5 demo jobs, all exit 0. Evidence: command output pasted into the T30 commit body.

**AC-48** (CP5) The Entire review of trail `review/v1` has zero open findings for the commit that will be published. Evidence: `ops/findings/` contains the final findings JSON, and the published commit SHA is recorded in `ops/review-log.md` (both stay local and are never committed).

**AC-49** (T31) The public GitHub repo `api-automation-tool` exists. Its `main` HEAD SHA equals the commit recorded in AC-48. It has no other branches. CI on GitHub is green. Evidence: the `gh` command output in `ops/review-log.md`.
