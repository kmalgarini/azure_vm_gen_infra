"""
Output writers: atomic snapshot file and append-only event log.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

from .catalogue import Job
from .state import StatusStore


def write_snapshot(
    store: StatusStore,
    output_dir: Path,
    catalogue: List[Job],
    now: datetime,
) -> None:
    """Write ``status.json`` atomically (tmp → os.replace)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "status.json"
    tmp = str(out) + ".tmp"

    jobs_list = []
    for job in catalogue:
        js = store.get(job.id)
        jobs_list.append(
            {
                "id": job.id,
                "status": js.status,
                "previous_status": js.previous_status,
                "status_since": js.status_since,
                "ticks_in_status": js.ticks_in_status,
                "transitions": js.transitions,
            }
        )

    payload = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tick": store.tick_number,
        "jobs": jobs_list,
    }
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, str(out))


def append_event(
    job_id: str,
    from_s: str,
    to_s: str,
    tick: int,
    now: datetime,
    output_dir: Path,
) -> None:
    """Append a single NDJSON line to ``events.jsonl``."""
    event = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tick": tick,
        "job_id": job_id,
        "from": from_s,
        "to": to_s,
    }
    events_path = output_dir / "events.jsonl"
    with open(events_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
