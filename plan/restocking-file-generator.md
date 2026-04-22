# Plan: Restocking File Generator

> **Status: IMPLEMENTED**
>
> This document plans the program that generates synthetic restocking files on the Azure VM
> at a fixed 5-minute interval. The files are consumed by the `restocking_monitor` check
> (see [restocking-monitor.md](restocking-monitor.md)).

---

## Overview

A Python script (`restocking_file_generator.py`) runs on the Azure VM every **5 minutes**,
writing restocking files into `/var/restocking/inbound/`.

On each tick the generator:
1. Writes **one BCR batch file** that contains **multiple DTR numbers** (configurable, default 3).
2. For each DTR in the batch, independently advances that DTR's lifecycle state machine,
   writing exactly one downstream file per DTR per tick (ZRO, ZDN, 940, 945, or 945OSR).

This means one BCR file is the *source of record* for N DTRs, while all downstream files
remain **one file per DTR** — matching real-world EDI flows where a single Distribution Cycle
Run kicks off several individual warehouse orders in parallel.

The generator is deployed as part of the existing `app/` repository — cloned onto the VM
during cloud-init provisioning — and managed by a **systemd timer** unit so it survives
reboots and runs on schedule without cron.

---

## Goals

- Produce realistic files that match every pattern watched by `restocking_monitor`:
  `BCR_*.txt`, `ZDN_*.txt`, `ZRO_*.txt`, `940_*.xml`, `945_*.xml`, `945OSR_*.xml`
- Embed DTR numbers in the format each parser expects (regex for `.txt`, XPath for `.xml`)
- Drive the full DTR lifecycle so that monitor truth-table rows are exercised over time
- Run unattended, self-contained, with no external dependencies beyond the Python stdlib

> **Note on naming:** The user-facing term is **DCR** (Distribution Cycle Run).
> In file patterns and `restocking_monitor` config the prefix used is **BCR**
> (`BCR_*.txt`). The generator produces `BCR_` files; the business-level name remains DCR.

---

## File Types and Formats

### Directory layout on the VM

```
/var/restocking/
└── inbound/          ← all generated files land here
```

### BCR (DCR) — `BCR_<batch_id>_<ts>.txt`

**One file per batch tick; contains N DTR numbers** (one `DTR:` line per DTR).
The filename uses a batch identifier, not a single DTR number.

The `restocking_monitor` extracts **all** DTR values using `re.findall` on the
pattern `DTR[:\s]*(\S+)`, yielding one `bcr_txt` database row per matched DTR,
all pointing to the same `source_path`.

```
BCR DISTRIBUTION CYCLE RUN
BATCH: <batch_id>
GENERATED: <iso_timestamp>
DTR: <dtr_number_1>
DTR: <dtr_number_2>
DTR: <dtr_number_3>
STATUS: INITIATED
```

Example with real values (`RESTOCKING_DTRS_PER_BATCH = 3`):

```
BCR DISTRIBUTION CYCLE RUN
BATCH: BCR-20260419-001
GENERATED: 2026-04-19T10:00:00Z
DTR: DTR-20260419-00001
DTR: DTR-20260419-00002
DTR: DTR-20260419-00003
STATUS: INITIATED
```

> All downstream files (ZRO, ZDN, 940, 945, 945OSR) remain **one file per DTR**.
> The BCR file is the only multi-DTR file type.

### ZRO — `ZRO_<dtr>_<ts>.txt`

```
ZRO ZERO REPLENISHMENT ORDER
DTR: <dtr_number>
GENERATED: <iso_timestamp>
WAREHOUSE: WH-001
STATUS: ACKNOWLEDGED
```

### ZDN — `ZDN_<dtr>_<ts>.txt`

```
ZDN DELIVERY NOTE
DTR: <dtr_number>
GENERATED: <iso_timestamp>
CARRIER: CARRIER-42
TRACKING: TRK-<dtr_number>
STATUS: DISPATCHED
```

### 940 — `940_<dtr>_<ts>.xml`

EDI 940 Warehouse Shipping Order. DTR must be reachable via XPath `//DTRNumber/text()`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<WarehouseShippingOrder>
  <Header>
    <DocumentType>940</DocumentType>
    <GeneratedAt><iso_timestamp></GeneratedAt>
  </Header>
  <Order>
    <DTRNumber><dtr_number></DTRNumber>
    <WarehouseID>WH-001</WarehouseID>
    <ShipTo>DEST-001</ShipTo>
  </Order>
</WarehouseShippingOrder>
```

### 945 — `945_<dtr>_<ts>.xml`

EDI 945 Warehouse Shipping Advice.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<WarehouseShippingAdvice>
  <Header>
    <DocumentType>945</DocumentType>
    <GeneratedAt><iso_timestamp></GeneratedAt>
  </Header>
  <ShipmentDetail>
    <DTRNumber><dtr_number></DTRNumber>
    <ShipDate><iso_timestamp></ShipDate>
    <Carrier>CARRIER-42</Carrier>
  </ShipmentDetail>
</WarehouseShippingAdvice>
```

### 945OSR — `945OSR_<dtr>_<ts>.xml`

945 Order Status Response (final confirmation).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<OrderStatusResponse>
  <Header>
    <DocumentType>945OSR</DocumentType>
    <GeneratedAt><iso_timestamp></GeneratedAt>
  </Header>
  <Status>
    <DTRNumber><dtr_number></DTRNumber>
    <OrderStatus>COMPLETED</OrderStatus>
    <CompletedAt><iso_timestamp></CompletedAt>
  </Status>
</OrderStatusResponse>
```

---

## Naming Schemes

### DTR numbers

```
DTR-<YYYYMMDD>-<NNNNN>
```

- `YYYYMMDD` — current UTC date
- `NNNNN`   — zero-padded 5-digit counter, incremented **per DTR** (not per batch), reset daily

Examples: `DTR-20260419-00001`, `DTR-20260419-00002`, `DTR-20260419-00003`

A batch of 3 DTRs consumes three counter values. The counter is stored in
`/opt/app/generator_state.json` and resets to `00001` when the date changes.

### BCR batch ID

```
BCR-<YYYYMMDD>-<BBB>
```

- `BBB` — zero-padded 3-digit batch counter, incremented once per tick, reset daily

Example: `BCR-20260419-001`, `BCR-20260419-002`

### Downstream file names

All downstream files use the **individual DTR number**, not the batch ID:

```
ZRO_<dtr>_<ts>.txt        e.g.  ZRO_DTR-20260419-00001_20260419T1005.txt
ZDN_<dtr>_<ts>.txt
940_<dtr>_<ts>.xml
945_<dtr>_<ts>.xml
945OSR_<dtr>_<ts>.xml
```

This preserves the existing watch patterns in `restocking_monitor` config
(`ZRO_*.txt`, `940_*.xml`, etc.) unchanged.

---

## Lifecycle / State Machine

### Per-tick sequence

Each 5-minute tick the generator does **two things in order**:

```
Step A — Write one new BCR batch file
          → allocate N fresh DTR numbers
          → write BCR_<batch>_<ts>.txt with all N DTR lines
          → add all N DTRs to the active_dtrs registry at state 0

Step B — Advance every already-active DTR by one state
          → for each DTR at state 1–5, write its next downstream file
          → DTRs that reach state 5 (945OSR written) are retired from the registry
```

### Per-DTR state machine

Each DTR progresses through states independently:

```
State 0  (enrolled in BCR batch)
         ↓  tick +1
State 1  → write 940_<dtr>_<ts>.xml     (DTR in_progress / not_started)
         ↓  tick +2
State 2  → write ZRO_<dtr>_<ts>.txt     (DTR in_progress / in_progress)
         ↓  tick +3
State 3  → write ZDN_<dtr>_<ts>.txt     (DTR in_progress / in_progress)
         ↓  tick +4
State 4  → write 945_<dtr>_<ts>.xml     (DTR success     / complete)
         ↓  tick +5
State 5  → write 945OSR_<dtr>_<ts>.xml  (DTR success     / complete — confirmed)
         ↓
         retired from registry
```

With `RESTOCKING_DTRS_PER_BATCH = 3`, every tick writes:
- **1 BCR file** (contains 3 new DTR numbers)
- **≤ N × active_slots** downstream files (one per active DTR per tick)

One full DTR lifecycle spans 5 ticks = **25 minutes**. The BCR file is written at
tick 0 and the monitor sees the DTR immediately; all downstream files arrive over
the following ticks.

### Example timeline (3 DTRs per batch, `RESTOCKING_FAIL_RATE = 0`)

```
Tick 1  BCR-001 written  (DTR-001, DTR-002, DTR-003 enrolled)
Tick 2  BCR-002 written  (DTR-004, DTR-005, DTR-006 enrolled)
        940 written for DTR-001, DTR-002, DTR-003
Tick 3  BCR-003 written  (DTR-007, DTR-008, DTR-009 enrolled)
        ZRO written for DTR-001, DTR-002, DTR-003
        940 written for DTR-004, DTR-005, DTR-006
Tick 4  ...
Tick 6  945OSR written for DTR-001, DTR-002, DTR-003  → retired
```

### Failure simulation

When `RESTOCKING_FAIL_RATE > 0`, a DTR may be abandoned at state 1 (after 940 only).
The lifecycle stops; no ZRO/ZDN/945 files are written. After `stale_threshold_hours`
the monitor marks the DTR as `stale / not_started`, exercising that truth-table path.

The BCR file is **not modified** when a DTR is abandoned — it always lists all N
DTRs for the batch regardless of what happens downstream.

---

## Schedule and Process Management

The generator is run via a **systemd timer** (not cron), which provides:
- Precise 5-minute intervals (`OnCalendar=*:0/5`)
- Automatic restart after failure
- Journal integration for log capture

### Unit files

**`/etc/systemd/system/restocking-generator.service`**

```ini
[Unit]
Description=Restocking File Generator
After=network.target

[Service]
Type=oneshot
User=appuser
Group=appuser
WorkingDirectory=/opt/app
EnvironmentFile=/opt/app/.env
ExecStart=/opt/app/.venv/bin/python /opt/app/restocking_file_generator.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=restocking-generator
```

**`/etc/systemd/system/restocking-generator.timer`**

```ini
[Unit]
Description=Run Restocking File Generator every 5 minutes
Requires=restocking-generator.service

[Timer]
OnCalendar=*:0/5
Persistent=true
AccuracySec=10s

[Install]
WantedBy=timers.target
```

`Persistent=true` means a missed tick (e.g. VM was off) fires once on next boot.

---

## Application Structure (additions to `app/`)

```
app/
├── main.py                         # existing FastAPI app
├── requirements.txt
├── restocking_file_generator.py    # NEW — generator entry point
├── generator/
│   ├── __init__.py
│   ├── dtr.py                      # DTR counter + state file helpers
│   ├── lifecycle.py                # state machine (0 → 5)
│   ├── writers/
│   │   ├── __init__.py
│   │   ├── txt.py                  # BCR / ZRO / ZDN writers
│   │   └── xml.py                  # 940 / 945 / 945OSR writers
│   └── config.py                   # env-var driven config
├── systemd/
│   ├── app.service
│   ├── restocking-generator.service  # NEW
│   └── restocking-generator.timer    # NEW
└── .env.example
```

---

## Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `RESTOCKING_INBOUND_DIR` | `/var/restocking/inbound` | Directory where files are written |
| `RESTOCKING_STATE_FILE` | `/opt/app/generator_state.json` | Per-day counters + active DTR registry |
| `RESTOCKING_DTRS_PER_BATCH` | `3` | Number of DTR numbers written into each BCR batch file |
| `RESTOCKING_FAIL_RATE` | `0.05` | 0–1 probability a DTR cycle is abandoned at state 1 (no downstream files after 940; exercises `stale` monitor path) |

All variables are added to `/opt/app/.env.example` and written into `/opt/app/.env` by
the cloud-init `runcmd` step (same mechanism as existing `APP_ENV` / `APP_PORT`).

---

## Deployment Changes

### 1. `scripts/cloud-init.yaml` additions

Two `runcmd` steps added after the existing app startup steps:

```yaml
runcmd:
  # ... existing steps ...

  # Create the restocking inbound directory, owned by appuser.
  - mkdir -p /var/restocking/inbound
  - chown appuser:appuser /var/restocking/inbound

  # Register and start the systemd timer.
  - systemctl daemon-reload
  - systemctl enable restocking-generator.timer
  - systemctl start restocking-generator.timer
```

The systemd unit files are written by a `write_files` block in the same cloud-init template.

### 2. `terraform/main.tf`

The `restocking_null_resource` wait step (already present as `null_resource.wait_for_app`)
can be extended to verify the timer is active:

```hcl
provisioner "remote-exec" {
  inline = [
    "cloud-init status --wait --long",
    "systemctl is-active --quiet app && echo '✓ app service is active'",
    "systemctl is-active --quiet restocking-generator.timer && echo '✓ restocking-generator.timer is active'",
  ]
}
```

### 3. `terraform/variables.tf` additions

```hcl
variable "restocking_dtrs_per_batch" {
  description = "Number of DTR numbers included in each BCR batch file."
  type        = number
  default     = 3
}

variable "restocking_fail_rate" {
  description = "Probability (0–1) that a DTR lifecycle is abandoned after state 1 (simulates stale DTR path in monitor)."
  type        = number
  default     = 0.05
}
```

---

## Testing the Generator Locally

```bash
# Create the output directory
mkdir -p /tmp/restocking/inbound

# Run one tick
RESTOCKING_INBOUND_DIR=/tmp/restocking/inbound \
RESTOCKING_STATE_FILE=/tmp/restocking_state.json \
python app/restocking_file_generator.py

# Inspect output
ls -lh /tmp/restocking/inbound/
```

To simulate a full lifecycle (BCR batch + 5 downstream ticks) without waiting:

```bash
# Tick 1: BCR written (3 DTRs enrolled, state 0)
# Ticks 2–6: downstream files written, one state advance per DTR per tick
for i in $(seq 1 6); do
  python app/restocking_file_generator.py
  sleep 1
done

ls /tmp/restocking/inbound/
# Expected:
#   BCR_BCR-<date>-001_<ts>.txt          ← 1 batch file, 3 DTR lines
#   940_DTR-<date>-00001_<ts>.xml        ← one 940 per DTR
#   940_DTR-<date>-00002_<ts>.xml
#   940_DTR-<date>-00003_<ts>.xml
#   ZRO_DTR-<date>-00001_<ts>.txt        ← and so on through 945OSR
#   ...
```

---

## Verification Checklist (post-deploy)

- [ ] Timer is active: `make ssh` → `systemctl status restocking-generator.timer`
- [ ] BCR file appears within 5 minutes of first tick (`BCR_BCR-*_*.txt` in inbound dir)
- [ ] BCR file contains `RESTOCKING_DTRS_PER_BATCH` lines matching `DTR: DTR-...`
- [ ] All six file types present in `/var/restocking/inbound/` after ~30 min
- [ ] Downstream files (`ZRO_`, `ZDN_`, `940_`, `945_`, `945OSR_`) are named per-DTR, not per-batch
- [ ] XML files contain `<DTRNumber>` reachable via XPath `//DTRNumber/text()`
- [ ] Generator logs: `journalctl -u restocking-generator --since "5 min ago"`
- [ ] `restocking_monitor` creates one `bcr_txt` row in `dtr_records` **per DTR line** in the BCR file (not one per file)

---

## Open Decisions

| # | Decision | Options | Status |
|---|----------|---------|--------|
| 1 | File retention / cleanup | Generator never deletes old files vs. rotate after N days | Pending |
| 2 | Failure simulation granularity | Random per-DTR fail rate vs. deterministic schedule | Pending |
| 3 | DTRs per batch variability | Fixed `RESTOCKING_DTRS_PER_BATCH` vs. random count per tick (min/max range) | Pending |
| 4 | Generator restart on config change | Taint VM vs. `systemctl restart restocking-generator.timer` | Pending |
| 5 | BCR file re-use across ticks | New BCR file per tick vs. append new DTRs to existing open batch | Pending |

---

## Related Documents

- [restocking-monitor.md](restocking-monitor.md) — monitor check spec and config reference
- [dtr_pick_status.md](dtr_pick_status.md) — DTR/pick status truth table the monitor evaluates
- [azure-linux-vm-python-deploy.md](azure-linux-vm-python-deploy.md) — VM provisioning plan
