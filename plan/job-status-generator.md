# Plan: Job Status Generator

> **Status: IMPLEMENTED**
>
> This document plans a program that maintains a static catalogue of job IDs
> and mutates each job's status randomly every **1 minute**, writing the
> current state to a JSON file consumed by monitoring or downstream systems.

---

## Overview

A Python script (`job_status_generator.py`) runs on the Azure VM every
**1 minute** via a `systemd` timer. On each tick it:

1. Loads the current status for every job from a persistent state file.
2. For each job, independently decides — based on configurable probabilities —
   whether to transition to a new status and which status to move to.
3. Writes the updated snapshot to `/var/jobs/status.json` (atomic rename so
   readers never see a partial file).
4. Appends a single-line NDJSON event to `/var/jobs/events.jsonl` recording
   every status change with a timestamp, enabling replay and audit.

The job catalogue (IDs + metadata) is **static** — it is defined at deploy
time via an environment variable or a seed file and never changes at runtime.
Only the *status* of each job evolves.

The generator is deployed as part of the existing `app/` repository, cloned
onto the VM during `cloud-init` provisioning, and managed by a `systemd`
timer so it survives reboots and runs on schedule.

---

## Goals

- Maintain a realistic, continuously changing job status dataset on the VM.
- Support an arbitrary number of jobs (default: 20) with human-readable IDs.
- Produce a state snapshot file that any downstream consumer (monitor, API,
  dashboard) can read without knowledge of previous states.
- Emit a structured event log for every transition so history is replayable.
- Run unattended with no external dependencies beyond the Python stdlib.
- Integrate with the existing `cloud-init` / `systemd` / Terraform deployment
  pattern already used by `restocking-file-generator`.

---

## Job Catalogue

### Static IDs

Jobs are defined once at deploy time. The default catalogue contains
**20 jobs** spanning typical warehouse/logistics domains:

| Job ID | Description |
|--------|-------------|
| `JOB-RCPT-001` | Goods receipt — dock A |
| `JOB-RCPT-002` | Goods receipt — dock B |
| `JOB-PICK-001` | Pick wave 1 — zone north |
| `JOB-PICK-002` | Pick wave 2 — zone south |
| `JOB-PICK-003` | Pick wave 3 — zone east |
| `JOB-PACK-001` | Pack & label — station 1 |
| `JOB-PACK-002` | Pack & label — station 2 |
| `JOB-SHIP-001` | Outbound shipment — carrier A |
| `JOB-SHIP-002` | Outbound shipment — carrier B |
| `JOB-INVT-001` | Inventory count — aisle 1 |
| `JOB-INVT-002` | Inventory count — aisle 2 |
| `JOB-INVT-003` | Inventory count — aisle 3 |
| `JOB-RPLN-001` | Replenishment — zone north |
| `JOB-RPLN-002` | Replenishment — zone south |
| `JOB-RETN-001` | Return processing — dock C |
| `JOB-XDCK-001` | Cross-dock transfer — hub 1 |
| `JOB-XDCK-002` | Cross-dock transfer — hub 2 |
| `JOB-AUDIT-001` | Compliance audit |
| `JOB-MAINT-001` | Equipment maintenance |
| `JOB-CLNP-001` | End-of-day cleanup |

Additional jobs can be injected via the `JOB_EXTRA_IDS` environment variable
(comma-separated). The combined list is deduplicated and sorted at startup.

---

## Status Model

### Status Values

Each job cycles through the following statuses:

| Status | Meaning |
|--------|---------|
| `PENDING` | Created, waiting to be scheduled |
| `SCHEDULED` | Accepted by the scheduler, not yet started |
| `RUNNING` | Actively being processed |
| `PAUSED` | Temporarily suspended (e.g. resource contention) |
| `COMPLETED` | Finished successfully |
| `FAILED` | Terminated with an error |
| `CANCELLED` | Aborted before completion |

### Transition Rules

Transitions are **probabilistic**, not strictly sequential. On every tick each
job independently draws from the allowed transitions for its current status:

| Current Status | Allowed Next Statuses | Notes |
|----------------|----------------------|-------|
| `PENDING` | `SCHEDULED`, `CANCELLED` | Usually advances; occasionally dropped |
| `SCHEDULED` | `RUNNING`, `CANCELLED` | Almost always starts |
| `RUNNING` | `COMPLETED`, `FAILED`, `PAUSED` | Main working state |
| `PAUSED` | `RUNNING`, `CANCELLED` | Usually resumes |
| `COMPLETED` | `PENDING` | Restarts for continuous simulation |
| `FAILED` | `PENDING` | Auto-retries for continuous simulation |
| `CANCELLED` | `PENDING` | Requeued for continuous simulation |

**Terminal statuses** (`COMPLETED`, `FAILED`, `CANCELLED`) automatically
cycle back to `PENDING` after a configurable **hold ticks** delay (default: 2
ticks = 2 minutes), so the dataset never runs dry.

### No-change probability

On each tick a job has a configurable probability of **staying in its current
status** (default: 40%). This prevents every job from changing every minute,
producing a more realistic mixed-state dataset.

---

## Transition Probability Table

Default weights (sum to 1.0 within each row):

| Current | → PENDING | → SCHEDULED | → RUNNING | → PAUSED | → COMPLETED | → FAILED | → CANCELLED | → (no change) |
|---------|-----------|-------------|-----------|----------|-------------|----------|-------------|--------------|
| PENDING | — | 0.70 | — | — | — | — | 0.10 | 0.20 |
| SCHEDULED | — | — | 0.75 | — | — | — | 0.05 | 0.20 |
| RUNNING | — | — | — | 0.10 | 0.50 | 0.15 | — | 0.25 |
| PAUSED | — | — | 0.55 | — | — | — | 0.05 | 0.40 |
| COMPLETED | 1.00* | — | — | — | — | — | — | — |
| FAILED | 1.00* | — | — | — | — | — | — | — |
| CANCELLED | 1.00* | — | — | — | — | — | — | — |

\* After `hold_ticks` have elapsed; otherwise stays in terminal status.

All weights are overridable via environment variables (see Configuration).

---

## Output Files

### `/var/jobs/status.json` — current snapshot

Written atomically on every tick (write to `.tmp`, then `os.replace`).
Always reflects the state after the most recent generator run.

```json
{
  "generated_at": "2026-04-19T14:05:00Z",
  "tick": 42,
  "jobs": [
    {
      "id": "JOB-PICK-001",
      "status": "RUNNING",
      "previous_status": "SCHEDULED",
      "status_since": "2026-04-19T14:04:00Z",
      "ticks_in_status": 1,
      "transitions": 7
    },
    {
      "id": "JOB-PACK-001",
      "status": "COMPLETED",
      "previous_status": "RUNNING",
      "status_since": "2026-04-19T14:05:00Z",
      "ticks_in_status": 0,
      "transitions": 12
    }
  ]
}
```

### `/var/jobs/events.jsonl` — event log

One JSON line appended per **status change** (no-change ticks produce no
line). File is never truncated by the generator; rotation is handled by
`logrotate` (see Deployment).

```jsonl
{"ts":"2026-04-19T14:04:00Z","tick":41,"job_id":"JOB-PICK-001","from":"SCHEDULED","to":"RUNNING"}
{"ts":"2026-04-19T14:05:00Z","tick":42,"job_id":"JOB-PACK-001","from":"RUNNING","to":"COMPLETED"}
```

### `/var/jobs/state.json` — internal generator state (not for consumers)

Persists tick counter, per-job status, `ticks_in_status`, and `hold_ticks`
counter for terminal statuses. Loaded at startup; written after every tick.

---

## Module Layout

```
app/
├── job_status_generator.py          ← entry point (run_tick + __main__)
└── job_generator/
    ├── __init__.py
    ├── config.py                    ← GeneratorConfig (env-var driven)
    ├── catalogue.py                 ← STATIC_JOBS list + load_catalogue()
    ├── state.py                     ← StatusStore: load/save/per-job state
    ├── transitions.py               ← build_transition_table(), next_status()
    └── writer.py                    ← write_snapshot(), append_event()
```

### `config.py`

```python
@dataclass
class JobGeneratorConfig:
    output_dir: Path          # JOB_OUTPUT_DIR,  default /var/jobs
    state_file: Path          # JOB_STATE_FILE,  default /var/jobs/state.json
    hold_ticks: int           # JOB_HOLD_TICKS,  default 2
    no_change_prob: float     # JOB_NO_CHANGE_PROB, default 0.40
    extra_ids: list[str]      # JOB_EXTRA_IDS,   default ""
    seed: int | None          # JOB_RANDOM_SEED, default None (non-deterministic)
```

### `state.py`

```python
@dataclass
class JobState:
    status: str
    previous_status: str | None
    status_since: str          # ISO-8601 UTC
    ticks_in_status: int
    transitions: int
    hold_remaining: int        # ticks before terminal status resets to PENDING

class StatusStore:
    def load(path: Path) -> StatusStore
    def save(path: Path) -> None
    def tick_number: int
    def get(job_id: str) -> JobState
    def apply(job_id: str, new_status: str, now: datetime) -> bool  # True if changed
```

### `transitions.py`

```python
def build_transition_table(config: JobGeneratorConfig) -> dict[str, list[tuple[str, float]]]
def next_status(current: str, table: TransitionTable, rng: Random) -> str | None
    # Returns None when no-change wins the draw, or the new status string.
```

### `writer.py`

```python
def write_snapshot(store: StatusStore, output_dir: Path, catalogue: list[Job]) -> None
    # Atomic write: tmp file → os.replace
def append_event(job_id: str, from_s: str, to_s: str, tick: int, output_dir: Path) -> None
```

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `JOB_OUTPUT_DIR` | `/var/jobs` | Directory for `status.json` and `events.jsonl` |
| `JOB_STATE_FILE` | `/var/jobs/state.json` | Internal state persistence path |
| `JOB_HOLD_TICKS` | `2` | Ticks a terminal status is held before `PENDING` reset |
| `JOB_NO_CHANGE_PROB` | `0.40` | Probability a job does not change status on a given tick |
| `JOB_EXTRA_IDS` | `""` | Comma-separated additional job IDs |
| `JOB_RANDOM_SEED` | `""` | Integer seed for reproducibility (empty = non-deterministic) |
| `JOB_WEIGHT_<FROM>_<TO>` | *(see table)* | Override individual transition weight, e.g. `JOB_WEIGHT_RUNNING_FAILED=0.30` |

---

## Systemd Integration

### `job-status-generator.service`

```ini
[Unit]
Description=Job Status Generator (oneshot)
After=network.target

[Service]
Type=oneshot
User=appuser
Group=appuser
WorkingDirectory=/opt/app
EnvironmentFile=/opt/app/.env
ExecStart=/opt/app/.venv/bin/python /opt/app/job_status_generator.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=job-status-generator
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/app /var/jobs

[Install]
WantedBy=multi-user.target
```

### `job-status-generator.timer`

```ini
[Unit]
Description=Run Job Status Generator every minute
Requires=job-status-generator.service

[Timer]
OnCalendar=*:*:00
Persistent=true
AccuracySec=5s

[Install]
WantedBy=timers.target
```

---

## Deployment Integration

### cloud-init changes (`scripts/cloud-init.yaml`)

1. **`write_files`** — add `job-status-generator.service` and
   `job-status-generator.timer` unit files.
2. **`.env` block** — append `JOB_OUTPUT_DIR`, `JOB_STATE_FILE`,
   `JOB_HOLD_TICKS`, `JOB_NO_CHANGE_PROB`.
3. **`runcmd`** — add:
   ```bash
   mkdir -p /var/jobs
   chown appuser:appuser /var/jobs
   systemctl enable job-status-generator.timer
   systemctl start  job-status-generator.timer
   ```

### Terraform changes (`terraform/`)

- **`variables.tf`** — add `job_hold_ticks` and `job_no_change_prob`
  variables with defaults and validations.
- **`main.tf`**:
  - Pass new variables into `templatefile()` for `custom_data`.
  - Extend `null_resource.wait_for_app` remote-exec to assert
    `systemctl is-active job-status-generator.timer`.

### Log rotation (`/etc/logrotate.d/job-events`)

```
/var/jobs/events.jsonl {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
```

Added via a `write_files` entry in `cloud-init.yaml`.

---

## Testing Plan

Tests live in `app/tests/` alongside the existing restocking generator tests,
following the same `pytest` / `pytest-cov` setup.

| Test module | Coverage |
|-------------|---------|
| `test_job_config.py` | `GeneratorConfig` loading, validation, env-var overrides |
| `test_job_catalogue.py` | Static catalogue completeness, `JOB_EXTRA_IDS` merging, deduplication |
| `test_job_state.py` | `StatusStore` load/save, `apply()`, `hold_remaining` countdown, tick increment |
| `test_job_transitions.py` | `build_transition_table()` weight sum, `next_status()` distribution, seeded RNG determinism, custom weight env-vars |
| `test_job_writer.py` | Snapshot JSON schema, atomic write (no partial reads), event NDJSON format |
| `test_job_integration.py` | Full multi-tick runs: all statuses visited, terminal reset after hold, event log completeness, no-change probability range |

Target: ≥ 90% line coverage on all `job_generator/` modules.

---

## Acceptance Criteria

- [ ] `status.json` exists and is valid JSON within 1 minute of first deploy.
- [ ] Every job ID from the static catalogue appears in every snapshot.
- [ ] Over a 10-minute window all 7 statuses are observed across the job set.
- [ ] No `status.json` is ever written in a partial/corrupt state (atomic write).
- [ ] `events.jsonl` contains one line per status change with correct `from`/`to` fields.
- [ ] `systemctl is-active job-status-generator.timer` returns exit code 0 after deploy.
- [ ] All unit and integration tests pass (`pytest` green).
- [ ] `terraform apply` exits 0 and the `wait_for_app` probe confirms the timer is active.
