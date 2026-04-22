# DTR Status and Pick Status Truth Table

> **Referenced by:** [restocking-monitor.md](restocking-monitor.md)

This document defines the truth table used by `restocking_monitor` to derive **DTR status**
and **pick status** from the set of file types in which a given DTR has been observed.

---

## File Type Presence Flags

| Flag | Source file type | Meaning |
|------|-----------------|---------|
| `B`  | `bcr_txt`       | BCR (Distribution Cycle Run) received |
| `X9` | `940_xml`       | EDI 940 Warehouse Shipping Order sent |
| `R`  | `zro_txt`       | Zero Replenishment Order acknowledged |
| `D`  | `zdn_txt`       | Delivery Note dispatched |
| `F`  | `945_xml`       | EDI 945 Warehouse Shipping Advice received |
| `O`  | `945osr_xml`    | 945 Order Status Response (final) received |

> **Business rule:** DTRs that never appear in `bcr_txt` are treated as if they did
> (i.e. `B` is assumed `true` when evaluating the table for a DTR with no BCR file).
> This allows 940-first flows to be tracked without a spurious `unknown` status.

---

## Status Encodings

### DTR Status

| Value (numeric) | Name | Meaning |
|-----------------|------|---------|
| 0 | `unknown` | Insufficient information to determine status |
| 1 | `in_progress` | Process is running, outcome not yet known |
| 2 | `success` | Process completed successfully |
| 3 | `failure` | Process ended in a failure state |
| 4 | `stale` | No activity seen within `stale_threshold_hours` |

### Pick Status

| Value (numeric) | Name | Meaning |
|-----------------|------|---------|
| 0 | `unknown` | Pick state indeterminate |
| 1 | `not_started` | Pick has not started yet |
| 2 | `in_progress` | Pick is actively being worked |
| 3 | `complete` | Pick completed successfully |
| 4 | `failed` | Pick ended in failure |

---

## Truth Table (16 rows, first match wins)

Columns B, X9, R, D, F, O: `1` = file type present for this DTR, `0` = not present, `*` = don't care.

> Rows are evaluated **top-to-bottom**; the first row whose conditions all match is used.
> The final default row (`*` for all flags) is always matched if no earlier row matches.

| Row | B | X9 | R | D | F | O | DTR Status  | Pick Status  | Rationale |
|-----|---|----|---|---|---|---|-------------|--------------|-----------|
| 1   | * | *  | * | * | * | 1 | `success`   | `complete`   | 945OSR received → confirmed end-to-end |
| 2   | * | *  | * | * | 1 | 0 | `success`   | `complete`   | 945 shipping advice → shipment confirmed |
| 3   | * | *  | * | 1 | 0 | 0 | `in_progress`| `in_progress`| ZDN dispatched but no 945 yet |
| 4   | * | *  | 1 | 0 | 0 | 0 | `in_progress`| `in_progress`| ZRO acknowledged → pick in progress |
| 5   | * | 1  | 0 | 0 | 0 | 0 | `in_progress`| `not_started`| 940 sent to warehouse; awaiting pick |
| 6   | 1 | 0  | 0 | 0 | 0 | 0 | `in_progress`| `not_started`| BCR only → order created, not yet sent |
| 7   | * | *  | * | * | * | * | `unknown`   | `unknown`    | Default — no actionable files seen |

> **16-row note:** The table above condenses logically equivalent rows using `*` wildcards.
> An implementation that requires a fully expanded 16-row bitmap should enumerate all
> combinations of the 6 flags; the 7 logical rules above cover all 64 combinations when
> applied in order. The result is semantically identical.

---

## Stale Rule (applied after table lookup)

The stale rule **overrides** the table result when a DTR has gone quiet:

```
IF the DTR has at least one zdn_txt OR zro_txt row in the database
AND none of those rows have updated_at within the last stale_threshold_hours hours
THEN dtr_status  ← "stale"
     pick_status ← "not_started"
```

DTRs that have **never** had a `zdn_txt` or `zro_txt` row are **not** marked stale
(they may still be waiting for the warehouse to acknowledge).

The `stale_threshold_hours` value is configurable per check instance (default: 24 h).

---

## Failure Detection

The truth table does not currently encode a `failure` DTR status from file presence alone.
Failure is derived from:

1. **Explicit failure file** (future): a dedicated failure-notification file type, if added
   to the watch list, could trigger row-level failure detection.
2. **External signal** (future): the check could accept an override table or a DB flag set
   by another process.
3. **Stale + context** (current): extremely stale DTRs (e.g. `stale_threshold_hours × 2`)
   may be promoted to `failure` by a second configurable threshold — left as an open decision.

For now, `failure` is reserved for internal check errors (parse errors, DB errors), not
for business-process failures detected from file presence.

---

## Numeric Encoding for Metric

The `restocking.dtr.status` gauge uses the numeric value from the DTR Status table above:

| Gauge value | DTR status |
|-------------|------------|
| 0 | `unknown` |
| 1 | `in_progress` |
| 2 | `success` |
| 3 | `failure` |
| 4 | `stale` |

Tags on the gauge: `dtr_number`, `dtr_status` (string), `pick_status` (string), plus
the standard check-level tags (`check_id`, `check_name`, `solution`, etc.).

---

## Example Evaluations

The examples below reflect the **multi-DTR BCR model**: DTR-001, DTR-002, and DTR-003 were
all enrolled by the same BCR batch file (`BCR_BCR-20260419-001_*.txt`). Each is tracked
independently; they happen to be at different lifecycle stages here.

| DTR | `bcr_txt` source file | Other files present | Row matched | DTR status | Pick status |
|-----|-----------------------|---------------------|-------------|------------|-------------|
| DTR-001 | BCR-20260419-001 | 940_xml, zro_txt, zdn_txt, 945_xml, 945osr_xml | 1 | success | complete |
| DTR-002 | BCR-20260419-001 | 940_xml, zro_txt, zdn_txt | 3 | in_progress | in_progress |
| DTR-003 | BCR-20260419-001 | 940_xml | 5 | in_progress | not_started |
| DTR-004 | BCR-20260419-002 | *(none yet)* | 6 | in_progress | not_started |
| DTR-005 | BCR-20260419-002 | 940_xml, zro_txt | 4 | in_progress | in_progress |
| DTR-006 | BCR-20260419-002 | all downstream files | 1 | success | complete |
| DTR-007 | *(no BCR — business rule: B=true)* | 940_xml only | 5 | in_progress | not_started |
| DTR-008 | *(no BCR, no other files)* | *(none)* | 7 | unknown | unknown |
| DTR-009 | BCR-20260419-003 | zro_txt — last updated > 24 h ago | stale rule | stale | not_started |

Key observation: DTR-001, DTR-002, DTR-003 share the same `source_path` in the `bcr_txt`
row of `dtr_records` (all point to `BCR_BCR-20260419-001_*.txt`), but their DTR status and
pick status are entirely independent — each is evaluated against only its own set of file types.
