"""Tests for core.config — load/save round-trip and password obfuscation."""
import pytest


@pytest.fixture
def fresh_config(tmp_path, monkeypatch):
    """Redirect config storage to a tmp dir and reload the module."""
    import core.config as config

    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".movewriter")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / ".movewriter" / "config.json")
    return config


def test_defaults_returned_when_no_file(fresh_config):
    cfg = fresh_config.load()
    assert cfg["ip"] == "10.11.99.1"
    assert cfg["setup_complete"] is False
    assert cfg["keyboard_mac"] == ""


def test_save_then_load_roundtrip(fresh_config):
    cfg = fresh_config.load()
    cfg["keyboard_mac"] = "AA:BB:CC:DD:EE:FF"
    cfg["keyboard_name"] = "Test Keyboard"
    cfg["setup_complete"] = True
    fresh_config.save(cfg)

    reloaded = fresh_config.load()
    assert reloaded["keyboard_mac"] == "AA:BB:CC:DD:EE:FF"
    assert reloaded["keyboard_name"] == "Test Keyboard"
    assert reloaded["setup_complete"] is True


def test_password_roundtrip_through_b64(fresh_config):
    """get_password should reverse the base64 encoding stored in config."""
    import base64

    cfg = fresh_config.load()
    cfg["password_b64"] = base64.b64encode(b"hunter2").decode("ascii")
    assert fresh_config.get_password(cfg) == "hunter2"


def test_password_empty_when_missing(fresh_config):
    cfg = fresh_config.load()
    assert fresh_config.get_password(cfg) == ""


def test_password_empty_on_corrupt_b64(fresh_config):
    cfg = fresh_config.load()
    cfg["password_b64"] = "not!valid!base64!!!"
    # Should not raise — returns empty string on decode failure
    assert fresh_config.get_password(cfg) == ""


def test_missing_keys_filled_from_defaults(fresh_config, tmp_path):
    """If the saved file is missing newer keys, load() merges in defaults."""
    import json
    cfg_dir = tmp_path / ".movewriter"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({"ip": "1.2.3.4"}))

    cfg = fresh_config.load()
    assert cfg["ip"] == "1.2.3.4"
    # Keys absent from file should fall back to defaults
    assert cfg["keyboard_layout"] == "US English"
    assert cfg["setup_complete"] is False
