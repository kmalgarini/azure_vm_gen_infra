"""
Transition table and status-draw logic.

The table encodes, for each status, a list of (next_status, weight) pairs.
A next_status of None means "stay in current status" (no change).

Weights within a row are renormalised to sum to 1.0 after any overrides are
applied, so individual overrides do not need to be perfectly balanced.
"""
from random import Random
from typing import Dict, List, Optional, Tuple

TransitionTable = Dict[str, List[Tuple[Optional[str], float]]]

_TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})

# None in the (target, weight) pair means "no change / stay".
_DEFAULT_WEIGHTS: TransitionTable = {
    "PENDING": [
        ("SCHEDULED", 0.70),
        ("CANCELLED", 0.10),
        (None, 0.20),
    ],
    "SCHEDULED": [
        ("RUNNING", 0.75),
        ("CANCELLED", 0.05),
        (None, 0.20),
    ],
    "RUNNING": [
        ("COMPLETED", 0.50),
        ("FAILED", 0.15),
        ("PAUSED", 0.10),
        (None, 0.25),
    ],
    "PAUSED": [
        ("RUNNING", 0.55),
        ("CANCELLED", 0.05),
        (None, 0.40),
    ],
    # Terminal statuses always reset to PENDING (hold_remaining checked by caller).
    "COMPLETED": [("PENDING", 1.00)],
    "FAILED": [("PENDING", 1.00)],
    "CANCELLED": [("PENDING", 1.00)],
}


def build_transition_table(
    weight_overrides: Optional[Dict[str, float]] = None,
) -> TransitionTable:
    """Return a fully-normalised transition table.

    Override keys follow the pattern ``<FROM>_<TO>`` where the no-change entry
    uses the special token ``STAY``  (e.g. ``JOB_WEIGHT_RUNNING_STAY``).
    """
    overrides = weight_overrides or {}
    table: TransitionTable = {}
    for status, entries in _DEFAULT_WEIGHTS.items():
        new_entries: List[Tuple[Optional[str], float]] = []
        for target, weight in entries:
            key = f"{status}_{target if target is not None else 'STAY'}"
            new_weight = overrides.get(key, weight)
            if new_weight > 0:
                new_entries.append((target, new_weight))

        total = sum(w for _, w in new_entries)
        if total > 0:
            new_entries = [(t, w / total) for t, w in new_entries]

        table[status] = new_entries
    return table


def next_status(
    current: str, table: TransitionTable, rng: Random
) -> Optional[str]:
    """Draw the next status for a job.

    Returns the new status string, or ``None`` when the draw selects the
    no-change (stay) outcome.  Terminal statuses always return ``'PENDING'``
    (the caller is responsible for checking hold_remaining before calling).
    """
    entries = table.get(current, [])
    if not entries:
        return None

    targets = [t for t, _ in entries]
    weights = [w for _, w in entries]
    return rng.choices(targets, weights=weights, k=1)[0]
