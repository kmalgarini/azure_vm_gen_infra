"""
End-to-end integration tests for run_tick().

Each test uses a fresh tmp_path so state never bleeds between tests.
The fixture hard-codes fail_rate=0.0 for deterministic results; separate
tests exercise the failure path.
"""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from generator.config import GeneratorConfig
from restocking_file_generator import run_tick

_BASE = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)
DTR_REGEX = re.compile(r"DTR[:\s]*(\S+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(tmp_path, dtrs_per_batch=3, fail_rate=0.0):
    return GeneratorConfig(
        inbound_dir=str(tmp_path / "inbound"),
        state_file=str(tmp_path / "state.json"),
        dtrs_per_batch=dtrs_per_batch,
        fail_rate=fail_rate,
    )


def _tick(cfg, n=0):
    return run_tick(cfg, _BASE + timedelta(minutes=n * 5))


def _inbound(cfg):
    return Path(cfg.inbound_dir)


# ---------------------------------------------------------------------------
# Single tick
# ---------------------------------------------------------------------------

def test_tick1_writes_exactly_one_bcr(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg)
    assert len(list(_inbound(cfg).glob("BCR_*.txt"))) == 1


def test_tick1_bcr_contains_n_dtr_lines(tmp_path):
    cfg = _cfg(tmp_path, dtrs_per_batch=4)
    _tick(cfg)
    bcr = next(_inbound(cfg).glob("BCR_*.txt"))
    found = DTR_REGEX.findall(bcr.read_text())
    assert len(found) == 4


def test_tick1_no_downstream_files(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg)
    inbound = _inbound(cfg)
    assert not list(inbound.glob("940_*.xml"))
    assert not list(inbound.glob("ZRO_*.txt"))
    assert not list(inbound.glob("ZDN_*.txt"))
    assert not list(inbound.glob("945_*.xml"))
    assert not list(inbound.glob("945OSR_*.xml"))


def test_tick1_result_contains_enrolled_dtrs(tmp_path):
    cfg = _cfg(tmp_path)
    result = _tick(cfg)
    assert len(result["dtrs_enrolled"]) == 3
    assert result["dtrs_advanced"] == []
    assert result["dtrs_retired"] == []


def test_tick1_enrolled_dtrs_saved_at_state_0(tmp_path):
    cfg = _cfg(tmp_path)
    result = _tick(cfg)
    state = json.loads(Path(cfg.state_file).read_text())
    for dtr in result["dtrs_enrolled"]:
        assert state["active_dtrs"][dtr] == 0


def test_tick1_batch_id_in_result(tmp_path):
    cfg = _cfg(tmp_path)
    result = _tick(cfg)
    assert result["batch_id"].startswith("BCR-20260419-")


# ---------------------------------------------------------------------------
# Two ticks
# ---------------------------------------------------------------------------

def test_tick2_writes_940s_for_first_batch(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg, 0)
    _tick(cfg, 1)
    assert len(list(_inbound(cfg).glob("940_*.xml"))) == 3


def test_tick2_writes_second_bcr(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg, 0)
    _tick(cfg, 1)
    assert len(list(_inbound(cfg).glob("BCR_*.txt"))) == 2


def test_tick2_advances_first_batch_to_state_1(tmp_path):
    cfg = _cfg(tmp_path)
    first = _tick(cfg, 0)
    _tick(cfg, 1)
    state = json.loads(Path(cfg.state_file).read_text())
    for dtr in first["dtrs_enrolled"]:
        assert state["active_dtrs"][dtr] == 1


def test_tick2_newly_enrolled_still_at_state_0(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg, 0)
    second = _tick(cfg, 1)
    state = json.loads(Path(cfg.state_file).read_text())
    for dtr in second["dtrs_enrolled"]:
        assert state["active_dtrs"][dtr] == 0


# ---------------------------------------------------------------------------
# Full 6-tick lifecycle
# ---------------------------------------------------------------------------

def test_six_ticks_all_file_types_present(tmp_path):
    cfg = _cfg(tmp_path)
    for i in range(6):
        _tick(cfg, i)
    inbound = _inbound(cfg)
    assert list(inbound.glob("BCR_*.txt"))
    assert list(inbound.glob("940_*.xml"))
    assert list(inbound.glob("ZRO_*.txt"))
    assert list(inbound.glob("ZDN_*.txt"))
    assert list(inbound.glob("945_*.xml"))
    assert list(inbound.glob("945OSR_*.xml"))


def test_six_ticks_first_batch_dtrs_retired(tmp_path):
    cfg = _cfg(tmp_path)
    first = _tick(cfg, 0)
    for i in range(1, 6):
        _tick(cfg, i)
    state = json.loads(Path(cfg.state_file).read_text())
    for dtr in first["dtrs_enrolled"]:
        assert dtr not in state["active_dtrs"]


def test_six_ticks_each_xml_has_exactly_one_dtr_number(tmp_path):
    cfg = _cfg(tmp_path)
    for i in range(6):
        _tick(cfg, i)
    for xml_file in _inbound(cfg).glob("*.xml"):
        nodes = ET.parse(xml_file).findall(".//DTRNumber")
        assert len(nodes) == 1, f"{xml_file.name}: expected 1 DTRNumber, got {len(nodes)}"
        assert nodes[0].text.startswith("DTR-")


def test_six_ticks_txt_dtr_regex_extractable(tmp_path):
    cfg = _cfg(tmp_path)
    for i in range(6):
        _tick(cfg, i)
    for txt_file in _inbound(cfg).glob("*.txt"):
        if txt_file.name.startswith("BCR_"):
            found = DTR_REGEX.findall(txt_file.read_text())
            assert len(found) >= 1, f"{txt_file.name}: no DTR found"
        else:
            match = DTR_REGEX.search(txt_file.read_text())
            assert match, f"{txt_file.name}: DTR regex did not match"
            assert match.group(1).startswith("DTR-")


def test_six_ticks_downstream_files_named_by_dtr_not_batch(tmp_path):
    cfg = _cfg(tmp_path)
    for i in range(6):
        _tick(cfg, i)
    for f in _inbound(cfg).glob("*.xml"):
        assert "BCR-" not in f.name, f"{f.name} should not contain the batch ID"
    for f in _inbound(cfg).glob("ZRO_*.txt"):
        assert "BCR-" not in f.name
    for f in _inbound(cfg).glob("ZDN_*.txt"):
        assert "BCR-" not in f.name


# ---------------------------------------------------------------------------
# Failure simulation
# ---------------------------------------------------------------------------

def test_fail_rate_1_no_zro_zdn_945_files(tmp_path):
    cfg = _cfg(tmp_path, fail_rate=1.0)
    for i in range(6):
        _tick(cfg, i)
    inbound = _inbound(cfg)
    assert not list(inbound.glob("ZRO_*.txt"))
    assert not list(inbound.glob("ZDN_*.txt"))
    assert not list(inbound.glob("945_*.xml"))
    assert not list(inbound.glob("945OSR_*.xml"))


def test_fail_rate_1_940s_are_still_written(tmp_path):
    """The 940 is always written, even when a DTR is abandoned."""
    cfg = _cfg(tmp_path, fail_rate=1.0)
    for i in range(3):
        _tick(cfg, i)
    assert list(_inbound(cfg).glob("940_*.xml"))


def test_fail_rate_1_dtrs_retired_after_state_0(tmp_path):
    cfg = _cfg(tmp_path, fail_rate=1.0)
    first = _tick(cfg, 0)
    _tick(cfg, 1)  # this tick abandons the first batch
    state = json.loads(Path(cfg.state_file).read_text())
    for dtr in first["dtrs_enrolled"]:
        assert dtr not in state["active_dtrs"]


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_dtr_counter_accumulates_across_ticks(tmp_path):
    cfg = _cfg(tmp_path, dtrs_per_batch=3)
    _tick(cfg, 0)
    _tick(cfg, 1)
    state = json.loads(Path(cfg.state_file).read_text())
    assert state["dtr_counter"] == 6  # 3 per tick × 2 ticks


def test_batch_counter_accumulates_across_ticks(tmp_path):
    cfg = _cfg(tmp_path)
    for i in range(4):
        _tick(cfg, i)
    state = json.loads(Path(cfg.state_file).read_text())
    assert state["batch_counter"] == 4


# ---------------------------------------------------------------------------
# Date rollover
# ---------------------------------------------------------------------------

def test_date_rollover_resets_counters(tmp_path):
    cfg = _cfg(tmp_path, dtrs_per_batch=3)
    run_tick(cfg, _BASE)  # date 20260419

    next_day = _BASE + timedelta(days=1)  # 20260420
    run_tick(cfg, next_day)

    state = json.loads(Path(cfg.state_file).read_text())
    assert state["date"] == "20260420"
    assert state["dtr_counter"] == 3   # fresh counter, one batch
    assert state["batch_counter"] == 1


def test_date_rollover_dtrs_use_new_date(tmp_path):
    cfg = _cfg(tmp_path, dtrs_per_batch=2)
    next_day = _BASE + timedelta(days=1)
    result = run_tick(cfg, next_day)
    for dtr in result["dtrs_enrolled"]:
        assert "20260420" in dtr


# ---------------------------------------------------------------------------
# Configurable dtrs_per_batch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 5, 10])
def test_bcr_contains_exactly_n_dtrs(tmp_path, n):
    cfg = _cfg(tmp_path, dtrs_per_batch=n)
    _tick(cfg)
    bcr = next(_inbound(cfg).glob("BCR_*.txt"))
    found = DTR_REGEX.findall(bcr.read_text())
    assert len(found) == n
