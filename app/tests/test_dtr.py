import json
import os
import pytest
from generator.dtr import StateStore

TODAY = "20260419"
TOMORROW = "20260420"


# ---------------------------------------------------------------------------
# Fresh state
# ---------------------------------------------------------------------------

def test_load_missing_file_returns_fresh_state():
    store = StateStore.load("/nonexistent/path/state.json", TODAY)
    assert store.date == TODAY
    assert store.dtr_counter == 0
    assert store.batch_counter == 0
    assert store.active_dtrs == {}


def test_load_corrupt_file_returns_fresh_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not valid json {{{")
    store = StateStore.load(str(path), TODAY)
    assert store.dtr_counter == 0
    assert store.batch_counter == 0


def test_load_empty_json_returns_fresh_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{}")
    store = StateStore.load(str(path), TODAY)
    assert store.dtr_counter == 0


# ---------------------------------------------------------------------------
# DTR allocation
# ---------------------------------------------------------------------------

def test_allocate_dtr_batch_correct_format():
    store = StateStore(date=TODAY, dtr_counter=0, batch_counter=0)
    batch = store.allocate_dtr_batch(3)
    assert batch == [
        f"DTR-{TODAY}-00001",
        f"DTR-{TODAY}-00002",
        f"DTR-{TODAY}-00003",
    ]


def test_allocate_dtr_batch_increments_counter():
    store = StateStore(date=TODAY, dtr_counter=0, batch_counter=0)
    store.allocate_dtr_batch(3)
    assert store.dtr_counter == 3


def test_allocate_dtr_batch_continues_from_existing_counter():
    store = StateStore(date=TODAY, dtr_counter=7, batch_counter=0)
    batch = store.allocate_dtr_batch(2)
    assert batch == [f"DTR-{TODAY}-00008", f"DTR-{TODAY}-00009"]
    assert store.dtr_counter == 9


def test_allocate_dtr_batch_single_item():
    store = StateStore(date=TODAY, dtr_counter=0, batch_counter=0)
    batch = store.allocate_dtr_batch(1)
    assert len(batch) == 1
    assert batch[0] == f"DTR-{TODAY}-00001"


# ---------------------------------------------------------------------------
# Batch ID allocation
# ---------------------------------------------------------------------------

def test_allocate_batch_id_correct_format():
    store = StateStore(date=TODAY, dtr_counter=0, batch_counter=0)
    assert store.allocate_batch_id() == f"BCR-{TODAY}-001"


def test_allocate_batch_id_sequential():
    store = StateStore(date=TODAY, dtr_counter=0, batch_counter=0)
    ids = [store.allocate_batch_id() for _ in range(3)]
    assert ids == [
        f"BCR-{TODAY}-001",
        f"BCR-{TODAY}-002",
        f"BCR-{TODAY}-003",
    ]
    assert store.batch_counter == 3


# ---------------------------------------------------------------------------
# Persistence (save / load roundtrip)
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "state.json")
    original = StateStore(
        date=TODAY,
        dtr_counter=12,
        batch_counter=4,
        active_dtrs={"DTR-20260419-00001": 2, "DTR-20260419-00002": 0},
    )
    original.save(path)

    loaded = StateStore.load(path, TODAY)
    assert loaded.date == TODAY
    assert loaded.dtr_counter == 12
    assert loaded.batch_counter == 4
    assert loaded.active_dtrs == {
        "DTR-20260419-00001": 2,
        "DTR-20260419-00002": 0,
    }


def test_save_writes_valid_json(tmp_path):
    path = str(tmp_path / "state.json")
    StateStore(date=TODAY, dtr_counter=1, batch_counter=1).save(path)
    data = json.loads(open(path).read())
    assert data["date"] == TODAY
    assert data["dtr_counter"] == 1


def test_save_is_atomic_no_tmp_file_left(tmp_path):
    path = str(tmp_path / "state.json")
    StateStore(date=TODAY, dtr_counter=0, batch_counter=0).save(path)
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "deep" / "nested" / "state.json")
    StateStore(date=TODAY, dtr_counter=0, batch_counter=0).save(path)
    assert os.path.exists(path)


# ---------------------------------------------------------------------------
# Date rollover
# ---------------------------------------------------------------------------

def test_date_rollover_resets_all_counters(tmp_path):
    path = str(tmp_path / "state.json")
    StateStore(
        date=TODAY,
        dtr_counter=99,
        batch_counter=10,
        active_dtrs={"DTR-20260419-00001": 3},
    ).save(path)

    loaded = StateStore.load(path, TOMORROW)
    assert loaded.date == TOMORROW
    assert loaded.dtr_counter == 0
    assert loaded.batch_counter == 0
    assert loaded.active_dtrs == {}
