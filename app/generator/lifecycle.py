"""
Per-DTR lifecycle state machine.

States
------
  0  Enrolled in BCR batch (BCR already written)
  1  940 written
  2  ZRO written
  3  ZDN written
  4  945 written
  retired (None) — 945OSR written, or abandoned after 940

Transition logic
----------------
``advance_dtr`` writes the next file and returns the new state integer,
or ``None`` when the DTR should be removed from the active registry:

  state 0 → write 940 → state 1  (or None if abandoned by fail_rate)
  state 1 → write ZRO → state 2
  state 2 → write ZDN → state 3
  state 3 → write 945 → state 4
  state 4 → write 945OSR → None  (lifecycle complete)

Failure simulation
------------------
When ``fail_rate > 0``, a DTR at state 0 may be abandoned *after* the 940 is
written. The 940 file is always produced; only the subsequent files are skipped.
Pass a seeded ``random.Random`` instance via *rng* for deterministic tests.
"""
import random as _random_module
from datetime import datetime
from pathlib import Path
from random import Random
from typing import Callable, Optional

from generator.writers.txt import write_zro, write_zdn
from generator.writers.xml import write_940, write_945, write_945osr

# Maps current state → the writer function to call on that transition.
_WRITERS: dict[int, Callable[[str, str, datetime], Path]] = {
    0: write_940,
    1: write_zro,
    2: write_zdn,
    3: write_945,
    4: write_945osr,
}

# State after which a DTR is retired (inclusive upper bound).
_RETIRE_AFTER = 4


def advance_dtr(
    state: int,
    dtr: str,
    outdir: str,
    now: datetime,
    fail_rate: float = 0.05,
    rng: Optional[Random] = None,
) -> Optional[int]:
    """Write the next lifecycle file and return the new state, or ``None``
    when the DTR should be retired from the active registry.

    Parameters
    ----------
    state:
        Current lifecycle state of *dtr* (0–4).
    dtr:
        DTR number string, e.g. ``"DTR-20260419-00001"``.
    outdir:
        Directory where the output file is written.
    now:
        Timestamp used in file names and file content.
    fail_rate:
        Probability in [0, 1] that a state-0 DTR is abandoned after its 940.
    rng:
        Optional seeded ``random.Random`` for deterministic testing.
        Defaults to the module-level ``random`` functions.
    """
    writer = _WRITERS.get(state)
    if writer is None:
        return None

    writer(outdir, dtr, now)

    _rng: object = rng if rng is not None else _random_module
    if state == 0 and _rng.random() < fail_rate:  # type: ignore[attr-defined]
        return None  # 940 written but lifecycle abandoned

    new_state = state + 1
    return None if new_state > _RETIRE_AFTER else new_state
