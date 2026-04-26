# DTR (Distribution / restocking identifiers)

This repository’s **restocking file generator** produces **synthetic** EDI-style files on the Azure VM so downstream checks (for example a `restocking_monitor` that you run elsewhere) can exercise BCR, 940, ZRO, ZDN, 945, and 945OSR handling. A **DTR** here is simply a **stable string identifier** for one restocking unit of work (for example `DTR-20260419-00001`).

---

## Where DTR artefacts live on the VM

| Item | Path / note |
|------|-------------|
| **Inbound directory** (all generated restocking files) | `/var/restocking/inbound` (`RESTOCKING_INBOUND_DIR`) |
| **Generator state** (which DTRs are active and at which step) | `/opt/app/generator_state.json` (`RESTOCKING_STATE_FILE`) |
| **Retention** | Old **files** in the inbound directory are removed by `dtr-cleanup.timer` (daily). Age threshold: `restocking_artefact_retention_days` / `RESTOCKING_ARTEFACT_RETENTION_DAYS` (see [configuration-reference](configuration-reference.md)). |

---

## How the generator uses DTRs

On each tick (every **5 minutes** via `restocking-generator.timer`):

1. **Step B — advance existing DTRs**  
   For every DTR still in the in-memory registry, the generator writes **one** downstream file and moves that DTR along a fixed **per-DTR lifecycle** (see below). DTRs that finish the sequence (or are **abandoned** when `restocking_fail_rate` applies) are **retired** from the registry.

2. **Step A — enrol new DTRs**  
   The generator allocates **N** new DTR numbers (`N` = `restocking_dtrs_per_batch`), writes **one BCR batch file** that lists all of them, and registers each new DTR at **state 0**.

So: **one BCR file per tick** can carry **multiple DTR lines**; every other file type is still **per DTR** (naming and content are implemented under `app/generator/writers/`).

---

## Generator logic (detailed)

Code entry point: `app/restocking_file_generator.py` → `run_tick` (one invocation per `restocking-generator` tick).

### State store

`app/generator/dtr.py` (`StateStore`) persists **`generator_state.json`**. It records:

| Field | Role |
|--------|------|
| `date` | UTC calendar day (`YYYYMMDD`). If the file on disk is from a **different** day, the store is **reset** (counters and active DTRs start empty for the new day). |
| `dtr_counter` | Increments for each new DTR string allocated; DTRs look like `DTR-YYYYMMDD-NNNNN`. |
| `batch_counter` | Increments for each BCR **batch** id: `BCR-YYYYMMDD-###`. |
| `active_dtrs` | Map **DTR string → integer state 0–4** while that DTR is in flight. If a DTR is **not** in the map, it is **retired** (lifecycle finished or abandoned). |

The file is written **atomically** (temp file + `os.replace`) to avoid a half-written JSON on crash.

### What happens in one tick (ordering)

**Step B runs before step A** on purpose: newly enrolled DTRs in step A are at state 0, but the **BCR** for that batch is just written. Advancing *those* DTRs in the same run would be wrong, because the intended timeline is: BCR first (batch announced), then on **later** ticks, each DTR’s pipeline advances one document at a time.

1. **Step B — progress every active DTR**  
   For each `(dtr, state)` in `active_dtrs` (a snapshot iteration), call `advance_dtr(...)`. It **always writes exactly one** downstream file (940, ZRO, ZDN, 945, or 945OSR, depending on `state`).  
   - If `advance_dtr` returns a **new integer state**, that DTR’s entry is updated.  
   - If it returns **`None`**, the DTR is **removed** from `active_dtrs` (finished successfully, or **abandoned** after 940; see below).

2. **Step A — new batch of DTRs**  
   Allocate `N` new DTR strings (`N` = `restocking_dtrs_per_batch`), allocate the next BCR `batch_id`, `write_bcr` **once** with all N lines, then set each of those DTRs to **state 0** in `active_dtrs`.  
   Finally, `save` writes the state file.

So each tick can both **advance** older DTRs by one file **and** **introduce** a new BCR and N new DTRs. Over time, many DTRs can be in different states in parallel; each is advanced by **at most one** file per tick when it is still active.

### `advance_dtr` (per state)

Implemented in `app/generator/lifecycle.py`. The mapping is:

- State **0** → write **940**; then, with probability `fail_rate`, **abandon** (return `None` — 940 is still on disk, but the DTR never gets ZRO…945OSR).  
- State **1** → ZRO, **2** → ZDN, **3** → 945, **4** → 945OSR.  
- After 945OSR, the function returns `None` (success completion); the DTR is no longer active.

**Abandon** only runs when **current state is 0** and **after** the 940 file has been written, so a consumer still sees 940, then a missing pipeline — useful for **stale** / incomplete scenarios.

### Summary flow (text)

```text
[Load state] → for each active DTR: write next file, update or retire
             → allocate N new DTR ids + 1 BCR file with all N; enrol at state 0
             → [Save state]
```

---

## Per-DTR lifecycle (state machine)

The lifecycle is implemented in `app/generator/lifecycle.py`. In short:

| State | Meaning (simplified) | Next file written |
|-------|------------------------|-------------------|
| 0 | In BCR batch, 940 not yet written for this tick’s advance | 940 (XML) |
| 1 | 940 present | ZRO (`.txt`) |
| 2 | ZRO present | ZDN (`.txt`) |
| 3 | ZDN present | 945 (XML) |
| 4 | 945 present | 945OSR (XML) |
| *(retired)* | After 945OSR, or after abandon path | DTR removed from the active registry |

**Failure / abandon simulation:** `restocking_fail_rate` (env `RESTOCKING_FAIL_RATE`) can abandon a DTR **after** the 940 is written, so later files for that DTR are skipped. That is useful for testing **stale** / **not started** style outcomes in a monitor.

---

## DTR “status” (three layers)

The word **status** shows up in different places. They are **not** the same thing.

### 1. Generator state (this repository)

`active_dtrs` stores an **integer 0–4** per active DTR (see the table in the previous section). That value is an **internal pipeline step** only. It is **not** the same as “DTR status” in a monitor.

- When a DTR is **retired**, it disappears from `active_dtrs`; there is no separate “status string” in the state file for that DTR.

### 2. Status lines inside the generated files

The writers embed human-readable / workflow hints in the **synthetic** content (see `app/generator/writers/txt.py` and `xml.py`):

| File kind | Where “status” appears | Example value |
|-----------|-------------------------|----------------|
| BCR (batch) | `STATUS:` in the last line of the BCR file | `INITIATED` |
| ZRO | `STATUS:` | `ACKNOWLEDGED` |
| ZDN | `STATUS:` | `DISPATCHED` |
| 945OSR (XML) | `OrderStatus` under `Status` | `COMPLETED` |

These are **part of the play data** a downstream parser might read. They are **not** a separate global enum shared with a monitor’s “DTR status” unless you wire that in yourself.

### 3. DTR status and pick status (downstream monitor)

If you run a **separate** check (e.g. a `restocking_monitor` that is **not** in this repo) that **ingests** the same file types, it can derive **business** notions of:

- **DTR status** — e.g. `unknown`, `in_progress`, `success`, `failure`, `stale`  
- **Pick status** — e.g. `unknown`, `not_started`, `in_progress`, `complete`, `failed`  

from **which** document types exist for a given DTR (BCR, 940, ZRO, ZDN, 945, 945OSR), plus an optional **stale** rule if nothing updated recently. The full **truth table**, numeric encodings, and the stale override are in **[plan/dtr_pick_status.md](../plan/dtr_pick_status.md)**.

Rough alignment as the **generator** advances a DTR: after BCR-only you are in a “BCR / not yet 940” region of the table; after 940 only, a “not_started pick” style row; as ZRO, ZDN, 945, 945OSR land, the monitor moves toward `success` / `complete` on the last row. **Abandoned** lifecycles (940 then no ZRO) are meant to be observable as **gaps** in the file sequence so the monitor can show **in_progress** or, with time, **stale**, depending on your rules there.

**This** repository only **writes** files. It does **not** compute the truth-table DTR or pick status itself.

---

## Example output files

All files are written under **`/var/restocking/inbound`**. The **`_<ts>`** segment in each filename is the generation time: `YYYYMMDDTHHMMSS` in UTC (see `app/generator/writers/`). Below, `20260419T100000` and timestamps inside bodies are **illustrative**; a live VM will use the actual tick time.

### Filename patterns

| Kind | Pattern | Notes |
|------|---------|--------|
| BCR batch (multi-DTR) | `BCR_<batch_id>_<ts>.txt` | One file per tick; `batch_id` is like `BCR-20260419-001`. |
| 940 | `940_<dtr>_<ts>.xml` | `dtr` is the full string, e.g. `DTR-20260419-00001`. |
| ZRO | `ZRO_<dtr>_<ts>.txt` | |
| ZDN | `ZDN_<dtr>_<ts>.txt` | |
| 945 | `945_<dtr>_<ts>.xml` | |
| 945OSR | `945OSR_<dtr>_<ts>.xml` | Final step for a completed lifecycle. |

### BCR (batch — several DTR lines in one file)

`BCR_BCR-20260419-001_20260419T100000.txt`

```
BCR DISTRIBUTION CYCLE RUN
BATCH: BCR-20260419-001
GENERATED: 2026-04-19T10:00:00Z
DTR: DTR-20260419-00001
DTR: DTR-20260419-00002
DTR: DTR-20260419-00003
STATUS: INITIATED
```

Downstream tools often match DTRs with: `DTR[:\s]*(\S+)`.

### ZRO and ZDN (plain text, one DTR per file)

`ZRO_DTR-20260419-00001_20260419T100000.txt`

```
ZRO ZERO REPLENISHMENT ORDER
DTR: DTR-20260419-00001
GENERATED: 2026-04-19T10:00:00Z
WAREHOUSE: WH-001
STATUS: ACKNOWLEDGED
```

`ZDN_DTR-20260419-00001_20260419T100000.txt`

```
ZDN DELIVERY NOTE
DTR: DTR-20260419-00001
GENERATED: 2026-04-19T10:00:00Z
CARRIER: CARRIER-42
TRACKING: TRK-DTR-20260419-00001
STATUS: DISPATCHED
```

### 940, 945, 945OSR (XML)

Element **`DTRNumber`** is what XPath `//DTRNumber/text()` targets.

`940_DTR-20260419-00001_20260419T100000.xml` — 940 *Warehouse Shipping Order*:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<WarehouseShippingOrder>
  <Header>
    <DocumentType>940</DocumentType>
    <GeneratedAt>2026-04-19T10:00:00Z</GeneratedAt>
  </Header>
  <Order>
    <DTRNumber>DTR-20260419-00001</DTRNumber>
    <WarehouseID>WH-001</WarehouseID>
    <ShipTo>DEST-001</ShipTo>
  </Order>
</WarehouseShippingOrder>
```

`945_DTR-20260419-00001_20260419T100000.xml` — 945 *Warehouse Shipping Advice*:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<WarehouseShippingAdvice>
  <Header>
    <DocumentType>945</DocumentType>
    <GeneratedAt>2026-04-19T10:00:00Z</GeneratedAt>
  </Header>
  <ShipmentDetail>
    <DTRNumber>DTR-20260419-00001</DTRNumber>
    <ShipDate>2026-04-19T10:00:00Z</ShipDate>
    <Carrier>CARRIER-42</Carrier>
  </ShipmentDetail>
</WarehouseShippingAdvice>
```

`945OSR_DTR-20260419-00001_20260419T100000.xml` — *Order Status Response* (end of lifecycle):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<OrderStatusResponse>
  <Header>
    <DocumentType>945OSR</DocumentType>
    <GeneratedAt>2026-04-19T10:00:00Z</GeneratedAt>
  </Header>
  <Status>
    <DTRNumber>DTR-20260419-00001</DTRNumber>
    <OrderStatus>COMPLETED</OrderStatus>
    <CompletedAt>2026-04-19T10:00:00Z</CompletedAt>
  </Status>
</OrderStatusResponse>
```

The **authoritative** layout is in `app/generator/writers/xml.py` and `txt.py` (the VM may re-indent XML). On a running VM: `ls -1 /var/restocking/inbound | head` and `head /var/restocking/inbound/940_*.xml`.

---

## Systemd and logs

| Unit | Role |
|------|------|
| `restocking-generator.timer` | Runs `restocking_file_generator.py` on the 5-minute schedule. |
| `dtr-cleanup.timer` | Runs daily cleanup of old inbound files (not subdirectories; `maxdepth 1` in the unit). |

Logs:

```bash
journalctl -u restocking-generator -n 100 --no-pager
sudo journalctl -u dtr-cleanup -n 50 --no-pager
```

---

## Configuration

Terraform and `/opt/app/.env` drive the same knobs documented in the restocking section of [configuration-reference.md](configuration-reference.md):

- `restocking_dtrs_per_batch` — DTRs per BCR batch per tick.  
- `restocking_fail_rate` — probability of abandoning a DTR after 940.  
- `restocking_artefact_retention_days` — how long to keep old inbound files.

---

## Further reading (in-repo)

| Document | Content |
|----------|---------|
| [plan/restocking-file-generator.md](../plan/restocking-file-generator.md) | Original design: BCR batch model, filename patterns, monitor alignment. |
| [plan/dtr_pick_status.md](../plan/dtr_pick_status.md) | Truth table for DTR / pick **status** when a separate monitor ingests these files. |
| [plan/dtr-artefact-cleanup.md](../plan/dtr-artefact-cleanup.md) | Cleanup behaviour and failure modes. |

These plan docs describe **integration** with a not-in-repo `restocking_monitor`; the VM in this repository only **generates** the files.
