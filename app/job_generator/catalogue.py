from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Job:
    id: str
    description: str


STATIC_JOBS: List[Job] = [
    Job("JOB-RCPT-001", "Goods receipt — dock A"),
    Job("JOB-RCPT-002", "Goods receipt — dock B"),
    Job("JOB-PICK-001", "Pick wave 1 — zone north"),
    Job("JOB-PICK-002", "Pick wave 2 — zone south"),
    Job("JOB-PICK-003", "Pick wave 3 — zone east"),
    Job("JOB-PACK-001", "Pack & label — station 1"),
    Job("JOB-PACK-002", "Pack & label — station 2"),
    Job("JOB-SHIP-001", "Outbound shipment — carrier A"),
    Job("JOB-SHIP-002", "Outbound shipment — carrier B"),
    Job("JOB-INVT-001", "Inventory count — aisle 1"),
    Job("JOB-INVT-002", "Inventory count — aisle 2"),
    Job("JOB-INVT-003", "Inventory count — aisle 3"),
    Job("JOB-RPLN-001", "Replenishment — zone north"),
    Job("JOB-RPLN-002", "Replenishment — zone south"),
    Job("JOB-RETN-001", "Return processing — dock C"),
    Job("JOB-XDCK-001", "Cross-dock transfer — hub 1"),
    Job("JOB-XDCK-002", "Cross-dock transfer — hub 2"),
    Job("JOB-AUDIT-001", "Compliance audit"),
    Job("JOB-MAINT-001", "Equipment maintenance"),
    Job("JOB-CLNP-001", "End-of-day cleanup"),
]


def load_catalogue(extra_ids: List[str]) -> List[Job]:
    """Return the full job catalogue (static + extras), deduplicated and sorted."""
    static_id_set = {j.id for j in STATIC_JOBS}
    extras = [
        Job(id=jid.strip(), description="(extra)")
        for jid in extra_ids
        if jid.strip() and jid.strip() not in static_id_set
    ]
    seen: set = set()
    deduped: List[Job] = []
    for job in STATIC_JOBS + extras:
        if job.id not in seen:
            seen.add(job.id)
            deduped.append(job)
    return sorted(deduped, key=lambda j: j.id)
