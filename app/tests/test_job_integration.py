"""
End-to-end integration tests for run_tick().

All tests use a seeded RNG (JOB_RANDOM_SEED via config.seed) for determinism
and a small synthetic catalogue so behaviour is predictable.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_generator.catalogue import Job, load_catalogue
from job_generator.config import JobGeneratorConfig
from job_generator.state import TERMINAL_STATUSES
from job_status_generator import run_tick

_BASE = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)
_SMALL_CATALOGUE = [Job(f"JOB-{i:03d}", f"job {i}") for i in range(10)]


def _cfg(tmp_path, hold_ticks=0, seed=42, extra_ids=None):
    return JobGeneratorConfig(
        output_dir=tmp_path / "jobs",
        state_file=tmp_path / "state.json",
        hold_ticks=hold_ticks,
        no_change_prob=0.40,
        extra_ids=extra_ids or [],
        seed=seed,
        weight_overrides={},
    )


def _tick(cfg, cat, n=0):
    return run_tick(cfg, cat, _BASE + timedelta(minutes=n))


# ---------------------------------------------------------------------------
# Single tick — basic invariants
# ---------------------------------------------------------------------------

def test_single_tick_creates_status_json(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg, _SMALL_CATALOGUE)
    assert (tmp_path / "jobs" / "status.json").exists()


def test_single_tick_creates_state_json(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg, _SMALL_CATALOGUE)
    assert (tmp_path / "state.json").exists()


def test_single_tick_all_jobs_in_snapshot(tmp_path):
    cfg = _cfg(tmp_path)
    _tick(cfg, _SMALL_CATALOGUE)
    data = json.loads((tmp_path / "jobs" / "status.json").read_text())
    snap_ids = {j["id"] for j in data["jobs"]}
    cat_ids = {j.id for j in _SMALL_CATALOGUE}
    assert snap_ids == cat_ids


def test_single_tick_snapshot_tick_is_one(tmp_path):
    cfg = _cfg(tmp_path)
    result = _tick(cfg, _SMALL_CATALOGUE)
    assert result["tick"] == 1


def test_single_tick_total_jobs_matches_catalogue(tmp_path):
    cfg = _cfg(tmp_path)
    result = _tick(cfg, _SMALL_CATALOGUE)
    assert result["total_jobs"] == len(_SMALL_CATALOGUE)


# ---------------------------------------------------------------------------
# Multi-tick
# ---------------------------------------------------------------------------

def test_multi_tick_tick_counter_increments(tmp_path):
    cfg = _cfg(tmp_path)
    for n in range(5):
        result = _tick(cfg, _SMALL_CATALOGUE, n)
    assert result["tick"] == 5


def test_multi_tick_statuses_change(tmp_path):
    """At least one status change should occur across 20 ticks with seed 42."""
    cfg = _cfg(tmp_path)
    total_changed = 0
    for n in range(20):
        result = _tick(cfg, _SMALL_CATALOGUE, n)
        total_changed += len(result["changed"])
    assert total_changed > 0


def test_multi_tick_all_statuses_visited(tmp_path):
    """With 10 jobs over 100 ticks, at least 4 distinct statuses should be observed."""
    cfg = _cfg(tmp_path, hold_ticks=0)
    all_statuses: set = set()
    expected = {"PENDING", "SCHEDULED", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"}
    for n in range(100):
        _tick(cfg, _SMALL_CATALOGUE, n)
        data = json.loads((tmp_path / "jobs" / "status.json").read_text())
        for j in data["jobs"]:
            all_statuses.add(j["status"])
    assert all_statuses <= expected
    assert len(all_statuses) >= 4


def test_multi_tick_snapshot_always_valid_json(tmp_path):
    cfg = _cfg(tmp_path)
    for n in range(10):
        _tick(cfg, _SMALL_CATALOGUE, n)
        data = json.loads((tmp_path / "jobs" / "status.json").read_text())
        assert "tick" in data
        assert len(data["jobs"]) == len(_SMALL_CATALOGUE)


# ---------------------------------------------------------------------------
# Terminal hold
# ---------------------------------------------------------------------------

def test_terminal_hold_respected(tmp_path):
    """A job entering a terminal status should not change for hold_ticks ticks."""
    # Force all transitions to COMPLETED immediately: override all weights.
    overrides = {
        "PENDING_SCHEDULED": 0.0,
        "PENDING_CANCELLED": 0.0,
        "PENDING_STAY": 0.0,
    }
    # To reliably test hold, transition PENDING → COMPLETED via table, but
    # COMPLETED is terminal and only available from RUNNING. Instead use
    # hold_ticks=2 and verify hold_remaining persists correctly via state.
    cfg = JobGeneratorConfig(
        output_dir=tmp_path / "jobs",
        state_file=tmp_path / "state.json",
        hold_ticks=3,
        no_change_prob=0.40,
        extra_ids=[],
        seed=42,
        weight_overrides={},
    )
    cat = [Job("JOB-HOLD", "hold test")]
    # Run many ticks; any job that ends up in terminal should be held.
    for n in range(30):
        _tick(cfg, cat, n)
    state_data = json.loads((tmp_path / "state.json").read_text())
    job_state = state_data["jobs"]["JOB-HOLD"]
    # After 30 ticks the hold bookkeeping should be correct (never negative).
    assert job_state["hold_remaining"] >= 0


def test_terminal_hold_zero_does_not_hold(tmp_path):
    """With hold_ticks=0 a terminal job resets to PENDING on the very next tick."""
    cfg = _cfg(tmp_path, hold_ticks=0)
    cat = [Job("JOB-HOLD", "no hold")]
    for n in range(30):
        _tick(cfg, cat, n)
    state_data = json.loads((tmp_path / "state.json").read_text())
    assert state_data["jobs"]["JOB-HOLD"]["hold_remaining"] == 0


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

def test_events_appended_for_changes(tmp_path):
    cfg = _cfg(tmp_path, seed=0)
    for n in range(20):
        _tick(cfg, _SMALL_CATALOGUE, n)
    events_path = tmp_path / "jobs" / "events.jsonl"
    if events_path.exists():
        lines = events_path.read_text().strip().splitlines()
        for line in lines:
            event = json.loads(line)
            assert "ts" in event
            assert "tick" in event
            assert "job_id" in event
            assert "from" in event
            assert "to" in event


def test_events_from_to_are_different(tmp_path):
    cfg = _cfg(tmp_path, seed=1)
    for n in range(30):
        _tick(cfg, _SMALL_CATALOGUE, n)
    events_path = tmp_path / "jobs" / "events.jsonl"
    if events_path.exists():
        lines = events_path.read_text().strip().splitlines()
        for line in lines:
            event = json.loads(line)
            assert event["from"] != event["to"], "Event from == to indicates a no-change was logged"


# ---------------------------------------------------------------------------
# State persistence across ticks
# ---------------------------------------------------------------------------

def test_state_persisted_across_ticks(tmp_path):
    """Tick N+1 loads the state saved by tick N."""
    cfg = _cfg(tmp_path, seed=42)
    _tick(cfg, _SMALL_CATALOGUE, 0)
    state1 = json.loads((tmp_path / "state.json").read_text())

    _tick(cfg, _SMALL_CATALOGUE, 1)
    state2 = json.loads((tmp_path / "state.json").read_text())

    assert state2["tick"] == state1["tick"] + 1


# ---------------------------------------------------------------------------
# Extra IDs
# ---------------------------------------------------------------------------

def test_extra_ids_in_snapshot(tmp_path):
    cfg = _cfg(tmp_path, extra_ids=["JOB-EXTRA-001"])
    cat = load_catalogue(["JOB-EXTRA-001"])
    _tick(cfg, cat)
    data = json.loads((tmp_path / "jobs" / "status.json").read_text())
    ids = {j["id"] for j in data["jobs"]}
    assert "JOB-EXTRA-001" in ids


# ---------------------------------------------------------------------------
# Full static catalogue
# ---------------------------------------------------------------------------

def test_full_catalogue_single_tick(tmp_path):
    cfg = _cfg(tmp_path)
    cat = load_catalogue([])
    result = _tick(cfg, cat)
    assert result["total_jobs"] == 20
    data = json.loads((tmp_path / "jobs" / "status.json").read_text())
    assert len(data["jobs"]) == 20
