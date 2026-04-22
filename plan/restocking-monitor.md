# Plan: Restocking Process Monitor Check

> **Status: PLANNED**
>
> This document specifies the `restocking_monitor` check type: a Datadog custom Agent check
> that watches restocking files on disk, extracts DTR numbers, tracks their lifecycle in a
> SQLite database, computes DTR status using a truth table, and emits metrics and events.
>
> The files watched by this check are produced by the [Restocking File Generator](restocking-file-generator.md).
> The DTR/pick status truth table is defined in [dtr_pick_status.md](dtr_pick_status.md).

---

## Overview

The `restocking_monitor` check:

1. **Watches** multiple file patterns (`BCR_*.txt`, `940_*.xml`, `945_*.xml`, `945OSR_*.xml`,
   `ZRO_*.txt`, `ZDN_*.txt`) in configurable directories for creation or update.
2. **On each run**, resolves every pattern to **all** currently matching files and processes
   each file that is **new or updated** since the last run (tracked per file path).
3. **For each new/updated file**: parses it and extracts DTR number(s):
   - **`bcr_txt` files contain multiple DTR numbers** (one `DTR:` line per DTR). The check
     extracts **all** matches (`re.findall`) and upserts **one `dtr_records` row per DTR**,
     all with `source_path` pointing to the same BCR file.
   - All other file types (`zro_txt`, `zdn_txt`, `940_xml`, `945_xml`, `945osr_xml`) contain
     exactly **one DTR per file**; one row is upserted as before.
4. **After each run**: re-computes DTR status and pick status for every DTR seen this run using
   the [truth table](dtr_pick_status.md), applies the stale rule, and emits a per-DTR gauge
   metric and a Datadog event whenever a DTR's status is set or changed.

---

## File Types Monitored

| Pattern | File type key | Format | DTR extraction | Cardinality |
|---------|--------------|--------|----------------|-------------|
| `BCR_*.txt` | `bcr_txt` | Plain text | `re.findall(pattern, content)` — **all matches** | **Multiple DTRs per file** |
| `ZRO_*.txt` | `zro_txt` | Plain text | `re.search(pattern, content)` — first match | One DTR per file |
| `ZDN_*.txt` | `zdn_txt` | Plain text | `re.search(pattern, content)` — first match | One DTR per file |
| `940_*.xml` | `940_xml` | XML | XPath: `//DTRNumber/text()` | One DTR per file |
| `945_*.xml` | `945_xml` | XML | XPath: `//DTRNumber/text()` | One DTR per file |
| `945OSR_*.xml` | `945osr_xml` | XML | XPath: `//DTRNumber/text()` | One DTR per file |

> The `dtr_extraction` config for `bcr_txt` always uses **findall** semantics regardless of
> whether `type: regex` or `type: xpath` is configured. The `cardinality` field (defaulting to
> `multi` for `bcr_txt`, `single` for all other types) controls this behaviour and may be
> overridden per watch entry if needed.

---

## Configuration Schema

### Check registration

```yaml
- id: restocking-001
  name: Restocking Process Monitor
  type: restocking_monitor
  solution: Restocking
  business_process: Restocking
  business_process_step: Monitor
  criticality: high
  enabled: true
  config:
    database_url: "sqlite:///var/lib/datadog/restocking_dtr.db"
    state_file: "/var/lib/datadog/restocking_monitor_state.json"
    stale_threshold_hours: 24
    watches:
      - path: "/var/restocking/inbound"
        pattern: "BCR_*.txt"
        file_type: "bcr_txt"
      - path: "/var/restocking/inbound"
        pattern: "940_*.xml"
        file_type: "940_xml"
      - path: "/var/restocking/inbound"
        pattern: "945_*.xml"
        file_type: "945_xml"
      - path: "/var/restocking/inbound"
        pattern: "945OSR_*.xml"
        file_type: "945osr_xml"
      - path: "/var/restocking/inbound"
        pattern: "ZRO_*.txt"
        file_type: "zro_txt"
      - path: "/var/restocking/inbound"
        pattern: "ZDN_*.txt"
        file_type: "zdn_txt"
    dtr_extraction:
      bcr_txt:    { type: "regex", pattern: "DTR[:\\s]*(\\S+)" }
      zro_txt:    { type: "regex", pattern: "DTR[:\\s]*(\\S+)" }
      zdn_txt:    { type: "regex", pattern: "DTR[:\\s]*(\\S+)" }
      940_xml:    { type: "xpath", path: "//DTRNumber/text()" }
      945_xml:    { type: "xpath", path: "//DTRNumber/text()" }
      945osr_xml: { type: "xpath", path: "//DTRNumber/text()" }
    dtr_transform:
      bcr_txt:
        prepend: ""
        append:  ""
```

### Top-level config fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `database_url` | string | yes | — | SQLite database path, e.g. `sqlite:///var/lib/datadog/restocking_dtr.db` |
| `state_file` | string | no | — | Path to JSON file for per-file-path state. If omitted, state is stored in a `state` table in the same DB. |
| `stale_threshold_hours` | number | no | `24` | If no `zdn_txt` nor `zro_txt` row for a DTR in the last N hours, DTR status → `stale`, pick status → `not_started`. |
| `watches` | list | yes | — | List of watch entries (see below). |
| `dtr_extraction` | object | no | built-in defaults | Per-`file_type` extraction override (regex or XPath). |
| `dtr_transform` | object | no | — | Per-`file_type` optional `prepend`/`append` applied to the extracted DTR before storage. |

### Watch entry fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes* | Directory; combined with `pattern` to form the full glob. |
| `pattern` | string | yes* | Glob, e.g. `BCR_*.txt`. All matching files are checked each run. |
| `path_pattern` | string | no | Alternative: full glob, e.g. `/var/restocking/inbound/BCR_*.txt`. Use instead of `path` + `pattern`. |
| `file_type` | string | yes | One of `bcr_txt`, `940_xml`, `945_xml`, `945osr_xml`, `zro_txt`, `zdn_txt`. |

\* Either `path` + `pattern` or `path_pattern` is required.

---

## State Management

State is tracked **per file path** within each watch (Option A from design decisions):

- **Key:** `(watch_key, file_path)` where `watch_key = path + "|" + pattern`
- **Value:** `last_mtime` (Unix timestamp of the file when last processed)
- **Logic:** A file is processed if its path is not in state or its current `mtime > state[file_path]`
- **Persistence:** Either a JSON file (`state_file`) or a `state` table in the same SQLite DB

State is saved after every successful parse so that each processed file is persisted and
never re-processed unless it changes on disk.

---

## Database Schema

### DTR table (`dtr_records`)

Composite primary key: `(dtr_number, source_type)`. One row per DTR per file type.

| Column | Type | Description |
|--------|------|-------------|
| `dtr_number` | TEXT (PK) | Extracted DTR value, after any `dtr_transform` applied |
| `source_type` | TEXT (PK) | File type: `bcr_txt`, `940_xml`, `945_xml`, `945osr_xml`, `zro_txt`, `zdn_txt` |
| `source_path` | TEXT | Full path of the file where DTR was last seen for this source_type |
| `updated_at` | TEXT (ISO 8601) | Timestamp when this row was last upserted |

Example rows — three DTRs from one BCR batch file, each independently progressing:

| dtr_number | source_type | source_path | updated_at |
|------------|-------------|-------------|------------|
| DTR-20260419-00001 | bcr_txt | /var/restocking/inbound/BCR_BCR-20260419-001_20260419T1000.txt | 2026-04-19T10:00:00Z |
| DTR-20260419-00002 | bcr_txt | /var/restocking/inbound/BCR_BCR-20260419-001_20260419T1000.txt | 2026-04-19T10:00:00Z |
| DTR-20260419-00003 | bcr_txt | /var/restocking/inbound/BCR_BCR-20260419-001_20260419T1000.txt | 2026-04-19T10:00:00Z |
| DTR-20260419-00001 | 940_xml | /var/restocking/inbound/940_DTR-20260419-00001_20260419T1005.xml | 2026-04-19T10:05:00Z |
| DTR-20260419-00002 | 940_xml | /var/restocking/inbound/940_DTR-20260419-00002_20260419T1005.xml | 2026-04-19T10:05:00Z |
| DTR-20260419-00001 | zro_txt | /var/restocking/inbound/ZRO_DTR-20260419-00001_20260419T1010.txt | 2026-04-19T10:10:00Z |

Note: `DTR-20260419-00001`, `DTR-20260419-00002`, and `DTR-20260419-00003` all share the same
`source_path` for `bcr_txt` — they were enrolled by the same BCR batch file. Their downstream
files are independent and may arrive at different ticks.

### DTR status table (`dtr_status`)

One row per DTR (primary key: `dtr_number`). Updated when DTR or pick status changes.

| Column | Type | Description |
|--------|------|-------------|
| `dtr_number` | TEXT (PK) | DTR number |
| `dtr_status` | TEXT | Current DTR status: `unknown`, `in_progress`, `success`, `failure`, `stale` |
| `pick_status` | TEXT | Current pick status: `unknown`, `not_started`, `in_progress`, `complete`, `failed` |
| `dtr_timestamp` | TEXT | ISO 8601 timestamp when this DTR was first seen (first insert) |
| `last_status_change_at` | TEXT | ISO 8601 timestamp of last status change |
| `status_change_reason` | TEXT | Human-readable reason for the last change |

### State table (`file_state`) — only when `state_file` is omitted

| Column | Type | Description |
|--------|------|-------------|
| `watch_key` | TEXT (PK) | `path + "|" + pattern` or `path_pattern` |
| `file_path` | TEXT (PK) | Full path of the processed file |
| `last_mtime` | REAL | Unix timestamp of the file at last processing |

---

## Check Execution Flow

```
1. Load config (watches, database_url, state_file, dtr_extraction, stale_threshold_hours)
2. Open DB connection; CREATE TABLE IF NOT EXISTS for all tables
3. Load state (JSON file or DB state table)
   → structure: { watch_key: { file_path: last_mtime } }

4. FOR EACH watch:
   a. Build full glob: path + "/" + pattern  (or path_pattern)
   b. Resolve glob → list of matching file paths; stat each for current mtime
   c. If no files match → increment restocking.watches_checked, skip
   d. FOR EACH matching file:
      - If file_path in state[watch_key] AND current_mtime == state[watch_key][file_path]:
          increment restocking.files_skipped; continue
      - Read file content
      - Extract DTR(s) using dtr_extraction rule for file_type:
          • bcr_txt → re.findall(pattern, content)  → list of 0..N DTR strings
          • other *_txt → re.search(pattern, content) → list of 0 or 1 DTR string
          • *_xml → XPath evaluation               → list of 0 or 1 DTR string
      - If list is empty → log warning, increment restocking.errors; do NOT update state; continue
      - FOR EACH extracted DTR string:
          • Apply dtr_transform if configured (prepend/append)
          • Upsert into dtr_records: (dtr_number, source_type, source_path=file_path, updated_at=now)
          • Increment restocking.dtr_upserted
          • Add dtr_number to "dtrs_seen_this_run" set for step 6
      - Update state: state[watch_key][file_path] = current_mtime
      - Increment restocking.files_processed

5. Persist state (JSON file or DB)

6. Re-compute DTR status for every DTR seen this run:
   a. Query dtr_records for all source_types present for this dtr_number
   b. Apply truth table (dtr_pick_status.md) → candidate dtr_status, pick_status
   c. Apply stale rule: if zdn_txt or zro_txt rows exist AND all updated_at > stale_threshold_hours ago
      → override dtr_status = "stale", pick_status = "not_started"
   d. Compare to dtr_status table:
      - If row does not exist OR dtr_status/pick_status changed:
          UPSERT dtr_status row with new statuses, last_status_change_at=now, reason
          Emit gauge: restocking.dtr.status (value = numeric encoding)
          Emit event: restocking_dtr_status_change

7. Submit check result: status, message, aggregated metrics
```

---

## Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `restocking.files_processed` | count | Files processed (new or updated) this run |
| `restocking.dtr_upserted` | count | DTR rows upserted this run. For `bcr_txt` files this equals the number of DTR lines in the file (N per file); for all other types it is 1 per file. |
| `restocking.errors` | count | Parse or DB errors |
| `restocking.watches_checked` | count | Watches evaluated this run |
| `restocking.files_skipped` | count | Files unchanged since last run |
| `restocking.dtr.status` | gauge | Per-DTR gauge; value = numeric DTR status encoding (see [dtr_pick_status.md](dtr_pick_status.md)); tags: `dtr_number`, `dtr_status`, `pick_status` + check-level tags |

Full metric names are prefixed with `datadog.custom_check.` in the Agent submission, e.g.
`datadog.custom_check.restocking.dtr.status`.

---

## Events

### `restocking_dtr_status_change`

Emitted when DTR status is first set, or when it changes.

| Field | Value |
|-------|-------|
| `alert_type` | `info` for `in_progress` / `unknown` / `success`; `warning` for `stale`; `error` for `failure` |
| `title` | `Restocking DTR <dtr_number> status changed to <dtr_status> / <pick_status>` |
| Payload | `dtr_number`, `dtr_status`, `pick_status`, `dtr_timestamp` (first-seen), `last_status_change_at`, `status_change_reason`, `files` (list of `{source_type, source_path}`) |
| Tags | `dtr_number:<n>`, `dtr_status:<s>`, `pick_status:<p>`, + check-level tags |

---

## DTR Status and Pick Status

See **[dtr_pick_status.md](dtr_pick_status.md)** for the full truth table, stale rule, status
encodings, and worked examples.

Key rules:
- Truth table is evaluated top-to-bottom; first matching row wins
- DTRs with no `bcr_txt` row are treated as if they had one (business rule)
- The stale rule overrides the table result when `zdn_txt`/`zro_txt` rows exist but are all older than `stale_threshold_hours`
- `failure` DTR status is not derived from file presence in v1 (reserved for future explicit failure file type or external signal)

---

## Implementation Outline

### Files to add/change

| File | Change |
|------|--------|
| `datadog_custom_checks.py` | Add `run_restocking_monitor_check(cfg)`, helpers for state, DB upsert, DTR extraction, status computation, event emission |
| `checks.d/conf.yaml.example` | Add example `restocking_monitor` block with all six patterns |
| `CHECKS.md` | Document check: config, watches, metrics, events, database schema |
| `README.md` | Short description + link to CHECKS.md |
| Tests | Unit tests: extraction (TXT/XML), state diff per file, DB upsert, truth table evaluation, stale rule, multi-file-per-pattern run |

### Key implementation modules

```
datadog_custom_checks/
├── restocking_monitor/
│   ├── __init__.py
│   ├── check.py           # run_restocking_monitor_check() entry point
│   ├── state.py           # State load/save (JSON or DB)
│   ├── db.py              # DB connection, table creation, upsert helpers
│   ├── extraction.py      # DTR extraction (regex TXT, XPath XML)
│   ├── status.py          # Truth table + stale rule evaluation
│   └── events.py          # Datadog event + gauge emission
```

### Dependencies

- `sqlite3` (stdlib) — database
- `xml.etree.ElementTree` (stdlib) — XML parsing
- `re` (stdlib) — regex DTR extraction
- `glob`, `os`, `pathlib` (stdlib) — file resolution
- No third-party packages required for v1

---

## Security and Operations

- **Paths:** The check reads files only under configured `path` directories; no arbitrary execution
- **Database:** Stored at `database_url`; must be writable by the Agent user (`dd-agent`)
- **State file:** Must be writable by `dd-agent`; document recommended location (`/var/lib/datadog/`)
- **Database URL:** Prefer environment variable or Agent-secure config; avoid plain YAML in repo for non-dev environments
- **File permissions:** `/var/restocking/inbound/` must be readable by `dd-agent`

---

## Open Decisions

| # | Decision | Options | Status |
|---|----------|---------|--------|
| 1 | State default | `state_file` JSON vs. state table in DB | Pending |
| 2 | `failure` status detection | File-presence-based vs. external override vs. extended stale threshold | Pending |
| 3 | State pruning | Keep all file paths vs. remove entries for deleted files | Pending |
| 4 | PostgreSQL support | SQLite only (v1) vs. SQLAlchemy abstraction for other DBs | Pending |
| 5 | Exact DTR regex/XPath defaults | Confirm from real file samples | Pending |
| 6 | `path_pattern` vs `path` + `pattern` | Support one or both in config | Pending |

---

## Related Documents

- [restocking-file-generator.md](restocking-file-generator.md) — generator that produces the files this check monitors
- [dtr_pick_status.md](dtr_pick_status.md) — truth table and status encodings
- [azure-linux-vm-python-deploy.md](azure-linux-vm-python-deploy.md) — VM provisioning plan
