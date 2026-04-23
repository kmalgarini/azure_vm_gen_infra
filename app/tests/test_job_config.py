import pytest

from job_generator.config import JobGeneratorConfig, load_config


def _clear(monkeypatch):
    for var in [
        "JOB_OUTPUT_DIR",
        "JOB_STATE_FILE",
        "JOB_HOLD_TICKS",
        "JOB_NO_CHANGE_PROB",
        "JOB_EXTRA_IDS",
        "JOB_RANDOM_SEED",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_defaults(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    assert str(cfg.output_dir) == "/var/jobs"
    assert str(cfg.state_file) == "/var/jobs/state.json"
    assert cfg.hold_ticks == 2
    assert cfg.no_change_prob == pytest.approx(0.40)
    assert cfg.extra_ids == []
    assert cfg.seed is None
    assert cfg.weight_overrides == {}


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("JOB_OUTPUT_DIR", "/tmp/jobs")
    monkeypatch.setenv("JOB_STATE_FILE", "/tmp/jobs/state.json")
    monkeypatch.setenv("JOB_HOLD_TICKS", "5")
    monkeypatch.setenv("JOB_NO_CHANGE_PROB", "0.25")
    monkeypatch.setenv("JOB_EXTRA_IDS", "JOB-X-001, JOB-X-002")
    monkeypatch.setenv("JOB_RANDOM_SEED", "99")
    cfg = load_config()
    assert str(cfg.output_dir) == "/tmp/jobs"
    assert str(cfg.state_file) == "/tmp/jobs/state.json"
    assert cfg.hold_ticks == 5
    assert cfg.no_change_prob == pytest.approx(0.25)
    assert cfg.extra_ids == ["JOB-X-001", "JOB-X-002"]
    assert cfg.seed == 99


def test_hold_ticks_negative_raises(monkeypatch):
    monkeypatch.setenv("JOB_HOLD_TICKS", "-1")
    with pytest.raises(ValueError, match="JOB_HOLD_TICKS"):
        load_config()


def test_hold_ticks_zero_allowed(monkeypatch):
    monkeypatch.setenv("JOB_HOLD_TICKS", "0")
    cfg = load_config()
    assert cfg.hold_ticks == 0


def test_no_change_prob_above_one_raises(monkeypatch):
    monkeypatch.setenv("JOB_NO_CHANGE_PROB", "1.0")
    with pytest.raises(ValueError, match="JOB_NO_CHANGE_PROB"):
        load_config()


def test_no_change_prob_negative_raises(monkeypatch):
    monkeypatch.setenv("JOB_NO_CHANGE_PROB", "-0.1")
    with pytest.raises(ValueError, match="JOB_NO_CHANGE_PROB"):
        load_config()


def test_no_change_prob_zero_allowed(monkeypatch):
    monkeypatch.setenv("JOB_NO_CHANGE_PROB", "0.0")
    cfg = load_config()
    assert cfg.no_change_prob == pytest.approx(0.0)


def test_seed_empty_is_none(monkeypatch):
    monkeypatch.setenv("JOB_RANDOM_SEED", "")
    cfg = load_config()
    assert cfg.seed is None


def test_weight_overrides_parsed(monkeypatch):
    monkeypatch.setenv("JOB_WEIGHT_RUNNING_FAILED", "0.30")
    monkeypatch.setenv("JOB_WEIGHT_RUNNING_STAY", "0.10")
    cfg = load_config()
    assert cfg.weight_overrides["RUNNING_FAILED"] == pytest.approx(0.30)
    assert cfg.weight_overrides["RUNNING_STAY"] == pytest.approx(0.10)


def test_config_is_frozen(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    with pytest.raises((AttributeError, TypeError)):
        cfg.hold_ticks = 99  # type: ignore[misc]


def test_extra_ids_empty_string(monkeypatch):
    monkeypatch.setenv("JOB_EXTRA_IDS", "")
    cfg = load_config()
    assert cfg.extra_ids == []


def test_extra_ids_whitespace_only(monkeypatch):
    monkeypatch.setenv("JOB_EXTRA_IDS", "  ,  , ")
    cfg = load_config()
    assert cfg.extra_ids == []
