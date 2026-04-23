import pytest
from random import Random

from job_generator.transitions import (
    TransitionTable,
    _DEFAULT_WEIGHTS,
    _TERMINAL,
    build_transition_table,
    next_status,
)

_ALL_STATUSES = list(_DEFAULT_WEIGHTS.keys())


# ---------------------------------------------------------------------------
# build_transition_table
# ---------------------------------------------------------------------------

def test_table_covers_all_statuses():
    table = build_transition_table()
    for s in _ALL_STATUSES:
        assert s in table


def test_table_weights_sum_to_one():
    table = build_transition_table()
    for status, entries in table.items():
        total = sum(w for _, w in entries)
        assert total == pytest.approx(1.0, abs=1e-9), f"{status} weights sum to {total}"


def test_terminal_statuses_only_lead_to_pending():
    table = build_transition_table()
    for s in _TERMINAL:
        entries = table[s]
        assert len(entries) == 1
        assert entries[0][0] == "PENDING"


def test_non_terminal_has_none_entry():
    table = build_transition_table()
    for s in _ALL_STATUSES:
        if s not in _TERMINAL:
            targets = [t for t, _ in table[s]]
            assert None in targets, f"{s} has no no-change (None) entry"


def test_weight_overrides_applied():
    overrides = {"RUNNING_FAILED": 0.50, "RUNNING_STAY": 0.05}
    table = build_transition_table(overrides)
    running = dict(table["RUNNING"])
    assert running["FAILED"] == pytest.approx(0.50 / sum(overrides.get(f"RUNNING_{t if t else 'STAY'}", w) for t, w in _DEFAULT_WEIGHTS["RUNNING"]), rel=1e-6)


def test_weight_override_renormalises():
    overrides = {"PENDING_SCHEDULED": 0.50, "PENDING_CANCELLED": 0.50}
    table = build_transition_table(overrides)
    total = sum(w for _, w in table["PENDING"])
    assert total == pytest.approx(1.0, abs=1e-9)


def test_zero_weight_override_removes_option():
    overrides = {"SCHEDULED_CANCELLED": 0.0}
    table = build_transition_table(overrides)
    targets = [t for t, _ in table["SCHEDULED"]]
    assert "CANCELLED" not in targets


# ---------------------------------------------------------------------------
# next_status
# ---------------------------------------------------------------------------

def test_next_status_seeded_deterministic():
    table = build_transition_table()
    rng1 = Random(42)
    rng2 = Random(42)
    results1 = [next_status("RUNNING", table, rng1) for _ in range(20)]
    results2 = [next_status("RUNNING", table, rng2) for _ in range(20)]
    assert results1 == results2


def test_next_status_terminal_always_pending():
    table = build_transition_table()
    rng = Random(0)
    for _ in range(50):
        for s in _TERMINAL:
            result = next_status(s, table, rng)
            assert result == "PENDING", f"{s} should always → PENDING"


def test_next_status_pending_never_reaches_completed_or_failed():
    """PENDING can reach CANCELLED (allowed) but never COMPLETED or FAILED."""
    table = build_transition_table()
    rng = Random(7)
    for _ in range(200):
        result = next_status("PENDING", table, rng)
        assert result not in ("COMPLETED", "FAILED")


def test_next_status_running_distribution(monkeypatch):
    """Over many draws the observed distribution is close to the expected weights."""
    table = build_transition_table()
    rng = Random(42)
    counts: dict = {}
    n = 10_000
    for _ in range(n):
        s = next_status("RUNNING", table, rng)
        counts[s] = counts.get(s, 0) + 1

    expected = dict(table["RUNNING"])
    for target, weight in expected.items():
        observed = counts.get(target, 0) / n
        assert abs(observed - weight) < 0.03, (
            f"RUNNING→{target}: expected ~{weight:.2f}, got {observed:.2f}"
        )


def test_next_status_none_outcome_possible_for_non_terminal():
    table = build_transition_table()
    rng = Random(0)
    results = [next_status("PENDING", table, rng) for _ in range(500)]
    assert None in results, "No-change (None) outcome should appear over 500 draws"


def test_next_status_unknown_status_returns_none():
    table = build_transition_table()
    rng = Random(0)
    assert next_status("UNKNOWN_STATUS", table, rng) is None
