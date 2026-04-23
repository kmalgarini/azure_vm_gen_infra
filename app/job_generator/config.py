import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class JobGeneratorConfig:
    output_dir: Path
    state_file: Path
    hold_ticks: int
    no_change_prob: float
    extra_ids: List[str]
    seed: Optional[int]
    weight_overrides: Dict[str, float] = field(default_factory=dict)


def load_config() -> JobGeneratorConfig:
    output_dir = Path(os.getenv("JOB_OUTPUT_DIR", "/var/jobs"))
    state_file = Path(os.getenv("JOB_STATE_FILE", "/var/jobs/state.json"))

    hold_ticks = int(os.getenv("JOB_HOLD_TICKS", "2"))
    if hold_ticks < 0:
        raise ValueError(f"JOB_HOLD_TICKS must be >= 0, got {hold_ticks}")

    no_change_prob = float(os.getenv("JOB_NO_CHANGE_PROB", "0.40"))
    if not 0.0 <= no_change_prob < 1.0:
        raise ValueError(
            f"JOB_NO_CHANGE_PROB must be in [0.0, 1.0), got {no_change_prob}"
        )

    raw_extra = os.getenv("JOB_EXTRA_IDS", "").strip()
    extra_ids = [x.strip() for x in raw_extra.split(",") if x.strip()]

    seed_str = os.getenv("JOB_RANDOM_SEED", "").strip()
    seed: Optional[int] = int(seed_str) if seed_str else None

    prefix = "JOB_WEIGHT_"
    weight_overrides: Dict[str, float] = {
        key[len(prefix):]: float(val)
        for key, val in os.environ.items()
        if key.startswith(prefix)
    }

    return JobGeneratorConfig(
        output_dir=output_dir,
        state_file=state_file,
        hold_ticks=hold_ticks,
        no_change_prob=no_change_prob,
        extra_ids=extra_ids,
        seed=seed,
        weight_overrides=weight_overrides,
    )
