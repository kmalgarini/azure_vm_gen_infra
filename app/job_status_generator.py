"""
Job Status Generator — entry point.

Invoked once per systemd timer tick (every 1 minute). Each run:

  1. Load persisted state for all jobs (or initialise from scratch on first run).
  2. For each job, independently draw a probabilistic status transition.
     - Jobs in terminal hold (hold_remaining > 0) are skipped; their hold
       counter is decremented.
     - Jobs that draw "no change" (None) have their ticks_in_status incremented.
  3. Write the updated snapshot atomically to <output_dir>/status.json.
  4. Append one NDJSON line per status change to <output_dir>/events.jsonl.
  5. Persist the new internal state to the state file.
"""
import logging
import sys
from datetime import datetime, timezone
from random import Random
from typing import Dict, List

from job_generator.catalogue import Job, load_catalogue
from job_generator.config import JobGeneratorConfig, load_config
from job_generator.state import StatusStore
from job_generator.transitions import build_transition_table, next_status
from job_generator.writer import append_event, write_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("job-status-generator")


def run_tick(
    config: JobGeneratorConfig,
    catalogue: List[Job],
    now: datetime,
) -> Dict:
    """Execute one generator tick and return a summary dict.

    Returns
    -------
    dict with keys:
        tick        — tick counter after this run
        changed     — list of job IDs whose status changed
        held        — list of job IDs skipped due to terminal hold
        total_jobs  — total number of jobs in the catalogue
    """
    config.output_dir.mkdir(parents=True, exist_ok=True)

    catalogue_ids = [j.id for j in catalogue]
    store = StatusStore.load(config.state_file, catalogue_ids, now)
    rng = Random(config.seed)
    table = build_transition_table(config.weight_overrides)

    store.increment_tick()

    changed_jobs: List[str] = []
    held_jobs: List[str] = []

    for job in catalogue:
        js = store.get(job.id)

        # Terminal-hold: skip transition, just count down.
        if js.hold_remaining > 0:
            store.tick_no_change(job.id)
            held_jobs.append(job.id)
            continue

        new_s = next_status(js.status, table, rng)

        if new_s is None:
            # No-change draw.
            store.tick_no_change(job.id)
        else:
            from_s = js.status
            changed = store.apply(job.id, new_s, now, config.hold_ticks)
            if changed:
                changed_jobs.append(job.id)
                append_event(job.id, from_s, new_s, store.tick_number, now, config.output_dir)
            else:
                store.tick_no_change(job.id)

    write_snapshot(store, config.output_dir, catalogue, now)
    store.save(config.state_file)

    return {
        "tick": store.tick_number,
        "changed": changed_jobs,
        "held": held_jobs,
        "total_jobs": len(catalogue),
    }


def main() -> None:
    config = load_config()
    catalogue = load_catalogue(config.extra_ids)
    now = datetime.now(timezone.utc)
    _log.info("tick start  time=%s  jobs=%d", now.isoformat(), len(catalogue))
    result = run_tick(config, catalogue, now)
    _log.info(
        "tick done  tick=%d  changed=%d  held=%d  total=%d",
        result["tick"],
        len(result["changed"]),
        len(result["held"]),
        result["total_jobs"],
    )


if __name__ == "__main__":
    main()
