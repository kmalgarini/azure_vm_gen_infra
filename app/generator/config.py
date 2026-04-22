import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratorConfig:
    inbound_dir: str
    state_file: str
    dtrs_per_batch: int
    fail_rate: float


def load_config() -> GeneratorConfig:
    fail_rate = float(os.getenv("RESTOCKING_FAIL_RATE", "0.05"))
    if not 0.0 <= fail_rate <= 1.0:
        raise ValueError(
            f"RESTOCKING_FAIL_RATE must be between 0.0 and 1.0, got {fail_rate}"
        )

    dtrs_per_batch = int(os.getenv("RESTOCKING_DTRS_PER_BATCH", "3"))
    if dtrs_per_batch < 1:
        raise ValueError(
            f"RESTOCKING_DTRS_PER_BATCH must be >= 1, got {dtrs_per_batch}"
        )

    return GeneratorConfig(
        inbound_dir=os.getenv("RESTOCKING_INBOUND_DIR", "/var/restocking/inbound"),
        state_file=os.getenv(
            "RESTOCKING_STATE_FILE", "/opt/app/generator_state.json"
        ),
        dtrs_per_batch=dtrs_per_batch,
        fail_rate=fail_rate,
    )
