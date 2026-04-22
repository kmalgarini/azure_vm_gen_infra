"""Tests for the per-DTR lifecycle state machine."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from random import Random

import pytest
from generator.lifecycle import advance_dtr

NOW = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)
DTR = "DTR-20260419-00001"
DTR_REGEX = re.compile(r"DTR[:\s]*(\S+)")


def _rng(value: float) -> Random:
    """Return a Random whose .random() always returns *value*."""
    r = Random()
    r.random = lambda: value  # type: ignore[method-assign]
    return r


# ---------------------------------------------------------------------------
# Happy-path state transitions (fail_rate=0)
# ---------------------------------------------------------------------------

def test_state_0_writes_940_advances_to_1(tmp_path):
    new_state = advance_dtr(0, DTR, str(tmp_path), NOW, fail_rate=0.0)
    assert new_state == 1
    files = list(tmp_path.glob("940_*.xml"))
    assert len(files) == 1
    assert ET.parse(files[0]).find(".//DTRNumber").text == DTR


def test_state_1_writes_zro_advances_to_2(tmp_path):
    new_state = advance_dtr(1, DTR, str(tmp_path), NOW, fail_rate=0.0)
    assert new_state == 2
    files = list(tmp_path.glob("ZRO_*.txt"))
    assert len(files) == 1
    assert DTR_REGEX.search(files[0].read_text()).group(1) == DTR


def test_state_2_writes_zdn_advances_to_3(tmp_path):
    new_state = advance_dtr(2, DTR, str(tmp_path), NOW, fail_rate=0.0)
    assert new_state == 3
    assert list(tmp_path.glob("ZDN_*.txt"))


def test_state_3_writes_945_advances_to_4(tmp_path):
    new_state = advance_dtr(3, DTR, str(tmp_path), NOW, fail_rate=0.0)
    assert new_state == 4
    assert list(tmp_path.glob("945_*.xml"))


def test_state_4_writes_945osr_retires(tmp_path):
    new_state = advance_dtr(4, DTR, str(tmp_path), NOW, fail_rate=0.0)
    assert new_state is None
    assert list(tmp_path.glob("945OSR_*.xml"))


# ---------------------------------------------------------------------------
# File absence for other states
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,glob", [
    (0, "940_*.xml"),
    (1, "ZRO_*.txt"),
    (2, "ZDN_*.txt"),
    (3, "945_*.xml"),
    (4, "945OSR_*.xml"),
])
def test_only_expected_file_is_written(tmp_path, state, glob):
    advance_dtr(state, DTR, str(tmp_path), NOW, fail_rate=0.0)
    assert len(list(tmp_path.glob(glob))) == 1
    assert len(list(tmp_path.iterdir())) == 1


# ---------------------------------------------------------------------------
# Unknown / out-of-range state
# ---------------------------------------------------------------------------

def test_unknown_state_returns_none_writes_nothing(tmp_path):
    result = advance_dtr(99, DTR, str(tmp_path), NOW)
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_negative_state_returns_none_writes_nothing(tmp_path):
    result = advance_dtr(-1, DTR, str(tmp_path), NOW)
    assert result is None
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Failure simulation
# ---------------------------------------------------------------------------

def test_fail_rate_1_abandons_at_state_0(tmp_path):
    new_state = advance_dtr(0, DTR, str(tmp_path), NOW, fail_rate=1.0, rng=_rng(0.0))
    assert new_state is None


def test_fail_rate_1_still_writes_940(tmp_path):
    advance_dtr(0, DTR, str(tmp_path), NOW, fail_rate=1.0, rng=_rng(0.0))
    assert list(tmp_path.glob("940_*.xml")), "940 must be written even when abandoned"


def test_fail_rate_0_never_abandons(tmp_path):
    new_state = advance_dtr(0, DTR, str(tmp_path), NOW, fail_rate=0.0, rng=_rng(0.0))
    assert new_state == 1


def test_fail_rate_boundary_equal_to_rate_no_abandon(tmp_path):
    # random() returns exactly fail_rate — condition is strict <, so no abandon
    new_state = advance_dtr(0, DTR, str(tmp_path), NOW, fail_rate=0.5, rng=_rng(0.5))
    assert new_state == 1


def test_fail_rate_does_not_affect_states_1_to_4(tmp_path):
    """Failure simulation only applies at state 0."""
    for state in [1, 2, 3]:
        d = tmp_path / f"s{state}"
        d.mkdir()
        result = advance_dtr(state, DTR, str(d), NOW, fail_rate=1.0, rng=_rng(0.0))
        assert result is not None, f"state {state} should not be affected by fail_rate"


def test_state_4_always_retires_regardless_of_fail_rate(tmp_path):
    result = advance_dtr(4, DTR, str(tmp_path), NOW, fail_rate=1.0, rng=_rng(0.0))
    assert result is None  # retired, not abandoned
    assert list(tmp_path.glob("945OSR_*.xml"))
