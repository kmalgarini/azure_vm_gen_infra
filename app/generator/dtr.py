"""
State store: DTR / batch counters and the active-DTR registry.

The state file is a JSON document written atomically (write-then-replace) so
a crash mid-write never leaves a corrupt file. All counters reset when the UTC
date changes.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class StateStore:
    date: str           # YYYYMMDD (UTC)
    dtr_counter: int    # last allocated DTR sequence number
    batch_counter: int  # last allocated BCR batch sequence number
    active_dtrs: Dict[str, int] = field(default_factory=dict)
    # active_dtrs: dtr_number → lifecycle state (0–4); absent when retired

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str, today: str) -> "StateStore":
        """Load from *path*; return a fresh store if file is missing, corrupt,
        or from a different calendar day."""
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("date") == today:
                return cls(
                    date=today,
                    dtr_counter=int(data["dtr_counter"]),
                    batch_counter=int(data["batch_counter"]),
                    active_dtrs={
                        k: int(v)
                        for k, v in data.get("active_dtrs", {}).items()
                    },
                )
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            pass
        return cls(date=today, dtr_counter=0, batch_counter=0)

    def save(self, path: str) -> None:
        """Write state to *path* atomically (temp-file + os.replace)."""
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "date": self.date,
                    "dtr_counter": self.dtr_counter,
                    "batch_counter": self.batch_counter,
                    "active_dtrs": self.active_dtrs,
                },
                fh,
                indent=2,
            )
        os.replace(tmp, path)

    # -------------------------------------------------------------------------
    # Allocation helpers
    # -------------------------------------------------------------------------

    def allocate_dtr_batch(self, n: int) -> List[str]:
        """Allocate *n* sequential DTR numbers and return them as a list."""
        dtrs: List[str] = []
        for _ in range(n):
            self.dtr_counter += 1
            dtrs.append(f"DTR-{self.date}-{self.dtr_counter:05d}")
        return dtrs

    def allocate_batch_id(self) -> str:
        """Allocate the next BCR batch ID for today."""
        self.batch_counter += 1
        return f"BCR-{self.date}-{self.batch_counter:03d}"
