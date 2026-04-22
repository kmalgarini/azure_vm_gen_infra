import pytest
from generator.config import GeneratorConfig, load_config


def test_defaults(monkeypatch):
    for var in [
        "RESTOCKING_INBOUND_DIR",
        "RESTOCKING_STATE_FILE",
        "RESTOCKING_DTRS_PER_BATCH",
        "RESTOCKING_FAIL_RATE",
    ]:
        monkeypatch.delenv(var, raising=False)

    cfg = load_config()
    assert cfg.inbound_dir == "/var/restocking/inbound"
    assert cfg.state_file == "/opt/app/generator_state.json"
    assert cfg.dtrs_per_batch == 3
    assert cfg.fail_rate == 0.05


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("RESTOCKING_INBOUND_DIR", "/tmp/inbound")
    monkeypatch.setenv("RESTOCKING_STATE_FILE", "/tmp/state.json")
    monkeypatch.setenv("RESTOCKING_DTRS_PER_BATCH", "5")
    monkeypatch.setenv("RESTOCKING_FAIL_RATE", "0.1")

    cfg = load_config()
    assert cfg.inbound_dir == "/tmp/inbound"
    assert cfg.state_file == "/tmp/state.json"
    assert cfg.dtrs_per_batch == 5
    assert cfg.fail_rate == pytest.approx(0.1)


def test_fail_rate_above_one_raises(monkeypatch):
    monkeypatch.setenv("RESTOCKING_FAIL_RATE", "1.5")
    with pytest.raises(ValueError, match="RESTOCKING_FAIL_RATE"):
        load_config()


def test_fail_rate_below_zero_raises(monkeypatch):
    monkeypatch.setenv("RESTOCKING_FAIL_RATE", "-0.1")
    with pytest.raises(ValueError, match="RESTOCKING_FAIL_RATE"):
        load_config()


def test_dtrs_per_batch_zero_raises(monkeypatch):
    monkeypatch.setenv("RESTOCKING_DTRS_PER_BATCH", "0")
    with pytest.raises(ValueError, match="RESTOCKING_DTRS_PER_BATCH"):
        load_config()


def test_dtrs_per_batch_negative_raises(monkeypatch):
    monkeypatch.setenv("RESTOCKING_DTRS_PER_BATCH", "-1")
    with pytest.raises(ValueError, match="RESTOCKING_DTRS_PER_BATCH"):
        load_config()


def test_config_is_frozen():
    cfg = GeneratorConfig(
        inbound_dir="/x", state_file="/y", dtrs_per_batch=1, fail_rate=0.0
    )
    with pytest.raises((AttributeError, TypeError)):
        cfg.dtrs_per_batch = 99  # type: ignore[misc]
