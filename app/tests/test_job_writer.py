import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_generator.catalogue import Job, load_catalogue
from job_generator.state import StatusStore
from job_generator.writer import append_event, write_snapshot

_NOW = datetime(2026, 4, 19, 14, 5, 0, tzinfo=timezone.utc)
_CATALOGUE = [Job("JOB-A", "desc A"), Job("JOB-B", "desc B")]
_IDS = [j.id for j in _CATALOGUE]


def _store(tmp_path) -> StatusStore:
    return StatusStore.load(tmp_path / "state.json", _IDS, _NOW)


# ---------------------------------------------------------------------------
# write_snapshot
# ---------------------------------------------------------------------------

def test_write_snapshot_creates_file(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    assert (tmp_path / "status.json").exists()


def test_write_snapshot_valid_json(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    data = json.loads((tmp_path / "status.json").read_text())
    assert "generated_at" in data
    assert "tick" in data
    assert "jobs" in data


def test_write_snapshot_all_jobs_present(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    data = json.loads((tmp_path / "status.json").read_text())
    ids = [j["id"] for j in data["jobs"]]
    assert set(ids) == {"JOB-A", "JOB-B"}


def test_write_snapshot_job_schema(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    data = json.loads((tmp_path / "status.json").read_text())
    for job_entry in data["jobs"]:
        for field in ("id", "status", "previous_status", "status_since", "ticks_in_status", "transitions"):
            assert field in job_entry, f"Missing field: {field}"


def test_write_snapshot_generated_at_matches_now(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    data = json.loads((tmp_path / "status.json").read_text())
    assert data["generated_at"] == "2026-04-19T14:05:00Z"


def test_write_snapshot_tick_matches_store(tmp_path):
    store = _store(tmp_path)
    store.increment_tick()
    store.increment_tick()
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    data = json.loads((tmp_path / "status.json").read_text())
    assert data["tick"] == 2


def test_write_snapshot_atomic_no_tmp_left(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    assert not (tmp_path / "status.json.tmp").exists()


def test_write_snapshot_overwrites_previous(tmp_path):
    store = _store(tmp_path)
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    store.increment_tick()
    write_snapshot(store, tmp_path, _CATALOGUE, _NOW)
    data = json.loads((tmp_path / "status.json").read_text())
    assert data["tick"] == 1


def test_write_snapshot_creates_output_dir(tmp_path):
    out = tmp_path / "deep" / "nested"
    store = StatusStore.load(tmp_path / "s.json", _IDS, _NOW)
    write_snapshot(store, out, _CATALOGUE, _NOW)
    assert (out / "status.json").exists()


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------

def test_append_event_creates_file(tmp_path):
    append_event("JOB-A", "PENDING", "SCHEDULED", 1, _NOW, tmp_path)
    assert (tmp_path / "events.jsonl").exists()


def test_append_event_valid_ndjson(tmp_path):
    append_event("JOB-A", "PENDING", "SCHEDULED", 1, _NOW, tmp_path)
    line = (tmp_path / "events.jsonl").read_text().strip()
    event = json.loads(line)
    assert event["job_id"] == "JOB-A"
    assert event["from"] == "PENDING"
    assert event["to"] == "SCHEDULED"
    assert event["tick"] == 1
    assert event["ts"] == "2026-04-19T14:05:00Z"


def test_append_event_appends_multiple_lines(tmp_path):
    append_event("JOB-A", "PENDING", "SCHEDULED", 1, _NOW, tmp_path)
    append_event("JOB-B", "SCHEDULED", "RUNNING", 2, _NOW, tmp_path)
    lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_append_event_does_not_truncate(tmp_path):
    for i in range(5):
        append_event("JOB-A", "PENDING", "SCHEDULED", i, _NOW, tmp_path)
    lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 5
