"""Plain-text file writers: BCR (multi-DTR batch), ZRO, ZDN."""
from datetime import datetime
from pathlib import Path
from typing import List


def _ts(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%S")


def _iso(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_bcr(
    outdir: str, batch_id: str, dtr_numbers: List[str], now: datetime
) -> Path:
    """Write one BCR batch file containing all *dtr_numbers*.

    The file embeds every DTR on its own ``DTR: <value>`` line so that
    ``restocking_monitor`` can extract all values with a single ``re.findall``.
    """
    dtr_lines = "\n".join(f"DTR: {d}" for d in dtr_numbers)
    content = (
        f"BCR DISTRIBUTION CYCLE RUN\n"
        f"BATCH: {batch_id}\n"
        f"GENERATED: {_iso(now)}\n"
        f"{dtr_lines}\n"
        f"STATUS: INITIATED\n"
    )
    path = Path(outdir) / f"BCR_{batch_id}_{_ts(now)}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def write_zro(outdir: str, dtr: str, now: datetime) -> Path:
    """Write a Zero Replenishment Order file for *dtr*."""
    content = (
        f"ZRO ZERO REPLENISHMENT ORDER\n"
        f"DTR: {dtr}\n"
        f"GENERATED: {_iso(now)}\n"
        f"WAREHOUSE: WH-001\n"
        f"STATUS: ACKNOWLEDGED\n"
    )
    path = Path(outdir) / f"ZRO_{dtr}_{_ts(now)}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def write_zdn(outdir: str, dtr: str, now: datetime) -> Path:
    """Write a Delivery Note file for *dtr*."""
    content = (
        f"ZDN DELIVERY NOTE\n"
        f"DTR: {dtr}\n"
        f"GENERATED: {_iso(now)}\n"
        f"CARRIER: CARRIER-42\n"
        f"TRACKING: TRK-{dtr}\n"
        f"STATUS: DISPATCHED\n"
    )
    path = Path(outdir) / f"ZDN_{dtr}_{_ts(now)}.txt"
    path.write_text(content, encoding="utf-8")
    return path
