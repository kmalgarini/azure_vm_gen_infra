"""
Restocking File Generator — entry point.

Invoked once per systemd timer tick (every 5 minutes). Each run:

  Step B  Advance every already-active DTR by one lifecycle state,
          writing the appropriate downstream file (940, ZRO, ZDN, 945, 945OSR).
          DTRs that complete or are abandoned are retired from the registry.

  Step A  Allocate N fresh DTR numbers, write one BCR batch file containing
          all of them, and enrol them in the active registry at state 0.

Step B runs before Step A so newly enrolled DTRs are not advanced in the same
tick they are created — matching the timeline in the plan.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from generator.config import GeneratorConfig, load_config
from generator.dtr import StateStore
from generator.lifecycle import advance_dtr
from generator.writers.txt import write_bcr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("restocking-generator")


def run_tick(config: GeneratorConfig, now: datetime) -> Dict:
    """Execute one generator tick and return a summary dict.

    Returns
    -------
    dict with keys:
        batch_id       — BCR batch identifier written this tick
        dtrs_enrolled  — DTR numbers added to the registry (state 0)
        dtrs_advanced  — DTR numbers that moved to a higher state
        dtrs_retired   — DTR numbers removed from the registry this tick
        files_written  — absolute paths of all files created
    """
    today = now.strftime("%Y%m%d")
    Path(config.inbound_dir).mkdir(parents=True, exist_ok=True)

    state = StateStore.load(config.state_file, today)

    files_written: List[str] = []
    dtrs_advanced: List[str] = []
    dtrs_retired: List[str] = []

    # --- Step B: advance DTRs already active from previous ticks --------------
    to_retire: List[str] = []
    for dtr, current_state in list(state.active_dtrs.items()):
        new_state = advance_dtr(
            state=current_state,
            dtr=dtr,
            outdir=config.inbound_dir,
            now=now,
            fail_rate=config.fail_rate,
        )
        if new_state is None:
            to_retire.append(dtr)
            dtrs_retired.append(dtr)
        else:
            state.active_dtrs[dtr] = new_state
            dtrs_advanced.append(dtr)

    for dtr in to_retire:
        del state.active_dtrs[dtr]

    # --- Step A: write BCR batch, enrol fresh DTRs at state 0 -----------------
    dtr_numbers = state.allocate_dtr_batch(config.dtrs_per_batch)
    batch_id = state.allocate_batch_id()
    bcr_path = write_bcr(config.inbound_dir, batch_id, dtr_numbers, now)
    files_written.append(str(bcr_path))

    for dtr in dtr_numbers:
        state.active_dtrs[dtr] = 0

    state.save(config.state_file)

    return {
        "batch_id": batch_id,
        "dtrs_enrolled": dtr_numbers,
        "dtrs_advanced": dtrs_advanced,
        "dtrs_retired": dtrs_retired,
        "files_written": files_written,
    }


def main() -> None:
    config = load_config()
    now = datetime.now(timezone.utc)
    _log.info("tick start  time=%s  inbound=%s", now.isoformat(), config.inbound_dir)
    result = run_tick(config, now)
    _log.info(
        "tick done  batch=%s  enrolled=%d  advanced=%d  retired=%d",
        result["batch_id"],
        len(result["dtrs_enrolled"]),
        len(result["dtrs_advanced"]),
        len(result["dtrs_retired"]),
    )


if __name__ == "__main__":
    main()
