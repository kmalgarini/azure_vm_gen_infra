"""
Status store: per-job state and tick counter.

The state file is a JSON document written atomically (write-then-replace) so
a crash mid-write never leaves a corrupt file.  Jobs missing from the file
(e.g. first run, or new catalogue entries) are initialised at PENDING.
"""
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
INITIAL_STATUS = "PENDING"


@dataclass
class JobState:
    status: str
    previous_status: Optional[str]
    status_since: str       # ISO-8601 UTC timestamp
    ticks_in_status: int
    transitions: int
    hold_remaining: int     # ticks to stay in terminal before → PENDING reset


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fresh(now: datetime) -> JobState:
    return JobState(
        status=INITIAL_STATUS,
        previous_status=None,
        status_since=_iso(now),
        ticks_in_status=0,
        transitions=0,
        hold_remaining=0,
    )


class StatusStore:
    def __init__(self, tick_number: int, jobs: Dict[str, JobState]) -> None:
        self.tick_number = tick_number
        self._jobs = jobs

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    @classmethod
    def load(
        cls, path: Path, catalogue_ids: List[str], now: datetime
    ) -> "StatusStore":
        """Load from *path*; missing or corrupt files start fresh."""
        tick_number = 0
        raw_jobs: Dict[str, dict] = {}
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            tick_number = int(data.get("tick", 0))
            raw_jobs = data.get("jobs", {})
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            pass

        jobs: Dict[str, JobState] = {}
        for job_id in catalogue_ids:
            if job_id in raw_jobs:
                r = raw_jobs[job_id]
                try:
                    jobs[job_id] = JobState(
                        status=r["status"],
                        previous_status=r.get("previous_status"),
                        status_since=r["status_since"],
                        ticks_in_status=int(r.get("ticks_in_status", 0)),
                        transitions=int(r.get("transitions", 0)),
                        hold_remaining=int(r.get("hold_remaining", 0)),
                    )
                except (KeyError, ValueError):
                    jobs[job_id] = _fresh(now)
            else:
                jobs[job_id] = _fresh(now)

        return cls(tick_number=tick_number, jobs=jobs)

    def save(self, path: Path) -> None:
        """Write state to *path* atomically (temp-file + os.replace)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".tmp"
        payload = {
            "tick": self.tick_number,
            "jobs": {
                jid: {
                    "status": js.status,
                    "previous_status": js.previous_status,
                    "status_since": js.status_since,
                    "ticks_in_status": js.ticks_in_status,
                    "transitions": js.transitions,
                    "hold_remaining": js.hold_remaining,
                }
                for jid, js in self._jobs.items()
            },
        }
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, str(path))

    # -------------------------------------------------------------------------
    # Mutation
    # -------------------------------------------------------------------------

    def increment_tick(self) -> None:
        self.tick_number += 1

    def get(self, job_id: str) -> JobState:
        return self._jobs[job_id]

    def apply(
        self, job_id: str, new_status: str, now: datetime, hold_ticks: int
    ) -> bool:
        """Transition job to *new_status*.  Returns True if status actually changed."""
        js = self._jobs[job_id]
        if js.status == new_status:
            self._jobs[job_id] = replace(js, ticks_in_status=js.ticks_in_status + 1)
            return False
        hold = hold_ticks if new_status in TERMINAL_STATUSES else 0
        self._jobs[job_id] = replace(
            js,
            status=new_status,
            previous_status=js.status,
            status_since=_iso(now),
            ticks_in_status=0,
            transitions=js.transitions + 1,
            hold_remaining=hold,
        )
        return True

    def tick_no_change(self, job_id: str) -> None:
        """Advance time without changing status: increment ticks_in_status and
        decrement hold_remaining if the job is in a terminal hold."""
        js = self._jobs[job_id]
        new_hold = max(0, js.hold_remaining - 1)
        self._jobs[job_id] = replace(
            js,
            ticks_in_status=js.ticks_in_status + 1,
            hold_remaining=new_hold,
        )
