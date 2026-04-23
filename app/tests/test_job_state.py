import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_generator.state import INITIAL_STATUS, TERMINAL_STATUSES, JobState, StatusStore

_NOW = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
_JOBS = ["JOB-A", "JOB-B", "JOB-C"]


def _load_empty(tmp_path) -> StatusStore:
    return StatusStore.load(tmp_path / "state.json", _JOBS, _NOW)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def test_load_missing_file_initialises_pending(tmp_path):
    store = _load_empty(tmp_path)
    for jid in _JOBS:
        assert store.get(jid).status == INITIAL_STATUS


def test_load_missing_file_tick_zero(tmp_path):
    store = _load_empty(tmp_path)
    assert store.tick_number == 0


def test_load_initialises_all_catalogue_ids(tmp_path):
    store = StatusStore.load(tmp_path / "s.json", ["X", "Y", "Z"], _NOW)
    for jid in ["X", "Y", "Z"]:
        assert store.get(jid).status == INITIAL_STATUS


def test_load_corrupt_file_falls_back_to_fresh(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("not-json")
    store = StatusStore.load(p, _JOBS, _NOW)
    assert store.tick_number == 0
    assert store.get("JOB-A").status == INITIAL_STATUS


def test_load_restores_saved_state(tmp_path):
    p = tmp_path / "state.json"
    store = _load_empty(tmp_path)
    store.increment_tick()
    store.apply("JOB-A", "RUNNING", _NOW, hold_ticks=2)
    store.save(p)

    store2 = StatusStore.load(p, _JOBS, _NOW)
    assert store2.tick_number == 1
    assert store2.get("JOB-A").status == "RUNNING"
    assert store2.get("JOB-B").status == INITIAL_STATUS


def test_load_new_catalogue_id_initialised(tmp_path):
    p = tmp_path / "state.json"
    store = _load_empty(tmp_path)
    store.save(p)

    store2 = StatusStore.load(p, _JOBS + ["JOB-NEW"], _NOW)
    assert store2.get("JOB-NEW").status == INITIAL_STATUS


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def test_save_creates_parent_directory(tmp_path):
    p = tmp_path / "sub" / "dir" / "state.json"
    store = _load_empty(tmp_path)
    store.save(p)
    assert p.exists()


def test_save_produces_valid_json(tmp_path):
    p = tmp_path / "state.json"
    store = _load_empty(tmp_path)
    store.save(p)
    data = json.loads(p.read_text())
    assert "tick" in data
    assert "jobs" in data


def test_save_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    store = _load_empty(tmp_path)
    store.increment_tick()
    store.increment_tick()
    store.apply("JOB-B", "SCHEDULED", _NOW, hold_ticks=2)
    store.save(p)

    store2 = StatusStore.load(p, _JOBS, _NOW)
    assert store2.tick_number == 2
    assert store2.get("JOB-B").status == "SCHEDULED"


# ---------------------------------------------------------------------------
# increment_tick
# ---------------------------------------------------------------------------

def test_increment_tick(tmp_path):
    store = _load_empty(tmp_path)
    store.increment_tick()
    store.increment_tick()
    assert store.tick_number == 2


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def test_apply_changes_status(tmp_path):
    store = _load_empty(tmp_path)
    changed = store.apply("JOB-A", "SCHEDULED", _NOW, hold_ticks=2)
    assert changed is True
    assert store.get("JOB-A").status == "SCHEDULED"


def test_apply_sets_previous_status(tmp_path):
    store = _load_empty(tmp_path)
    store.apply("JOB-A", "SCHEDULED", _NOW, hold_ticks=2)
    assert store.get("JOB-A").previous_status == INITIAL_STATUS


def test_apply_increments_transitions(tmp_path):
    store = _load_empty(tmp_path)
    store.apply("JOB-A", "SCHEDULED", _NOW, hold_ticks=2)
    store.apply("JOB-A", "RUNNING", _NOW, hold_ticks=2)
    assert store.get("JOB-A").transitions == 2


def test_apply_resets_ticks_in_status(tmp_path):
    store = _load_empty(tmp_path)
    store.tick_no_change("JOB-A")
    store.tick_no_change("JOB-A")
    store.apply("JOB-A", "SCHEDULED", _NOW, hold_ticks=2)
    assert store.get("JOB-A").ticks_in_status == 0


def test_apply_same_status_returns_false(tmp_path):
    store = _load_empty(tmp_path)
    changed = store.apply("JOB-A", INITIAL_STATUS, _NOW, hold_ticks=2)
    assert changed is False


def test_apply_terminal_sets_hold_remaining(tmp_path):
    store = _load_empty(tmp_path)
    store.apply("JOB-A", "RUNNING", _NOW, hold_ticks=2)
    store.apply("JOB-A", "COMPLETED", _NOW, hold_ticks=2)
    assert store.get("JOB-A").hold_remaining == 2


def test_apply_non_terminal_hold_remaining_zero(tmp_path):
    store = _load_empty(tmp_path)
    store.apply("JOB-A", "SCHEDULED", _NOW, hold_ticks=3)
    assert store.get("JOB-A").hold_remaining == 0


# ---------------------------------------------------------------------------
# tick_no_change
# ---------------------------------------------------------------------------

def test_tick_no_change_increments_ticks_in_status(tmp_path):
    store = _load_empty(tmp_path)
    store.tick_no_change("JOB-A")
    store.tick_no_change("JOB-A")
    assert store.get("JOB-A").ticks_in_status == 2


def test_tick_no_change_decrements_hold_remaining(tmp_path):
    store = _load_empty(tmp_path)
    store.apply("JOB-A", "RUNNING", _NOW, hold_ticks=2)
    store.apply("JOB-A", "COMPLETED", _NOW, hold_ticks=2)
    assert store.get("JOB-A").hold_remaining == 2
    store.tick_no_change("JOB-A")
    assert store.get("JOB-A").hold_remaining == 1
    store.tick_no_change("JOB-A")
    assert store.get("JOB-A").hold_remaining == 0


def test_tick_no_change_hold_remaining_never_negative(tmp_path):
    store = _load_empty(tmp_path)
    store.tick_no_change("JOB-A")
    store.tick_no_change("JOB-A")
    assert store.get("JOB-A").hold_remaining == 0
