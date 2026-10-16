import json

from serial_workspace.settings import Settings


def test_round_trip(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    settings = Settings(theme="AMOLED", custom_baud_rates=[250000], scope_scales=[0.2] * 8)
    settings.save(path)
    loaded, warning = Settings.load(path)
    assert not warning
    assert loaded == settings
    assert not list(path.parent.glob("*.tmp"))


def test_invalid_values_and_legacy_fields():
    settings = Settings.from_dict({"theme": "light", "custom_accent_color": "#123456",
                                   "sample_rate": float("nan"), "refresh_hz": 500,
                                   "font_size": "huge", "channel_colors": ["oops"] * 8,
                                   "custom_baud_rates": [250000, 250000, -2, True, "9600"],
                                   "scope_scales": [-1] * 8, "scope_mode": "unsafe"})
    assert settings.theme == "Light"
    assert settings.accent == "#123456"
    assert settings.sample_rate == 1000
    assert settings.refresh_hz == 20
    assert settings.font_size == 10
    assert settings.custom_baud_rates == [250000]
    assert settings.scope_scales == [1] * 8
    assert settings.scope_mode == "Auto"


def test_corrupt_file_and_non_object(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{")
    loaded, warning = Settings.load(path)
    assert warning
    assert loaded == Settings()
    path.write_text(json.dumps([1, 2, 3]))
    loaded, _ = Settings.load(path)
    assert loaded == Settings()


def test_legacy_migration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("SERIAL_MONITOR_SETTINGS", raising=False)
    (tmp_path / "settings.json").write_text('{"theme":"dark","custom_baud_rates":[250000]}')
    loaded, _ = Settings.load()
    assert loaded.custom_baud_rates == [250000]
    loaded.save()
    assert (tmp_path / "appdata" / "SerialMonitor" / "settings.json").exists()


def test_extreme_integers_and_numeric_choice_types():
    settings = Settings.from_dict({"sample_rate": 10 ** 400, "scope_scales": [10 ** 400] * 8,
                                   "fft_size": 2048.0, "scope_timebase": 1})
    assert settings.sample_rate == 1000
    assert settings.scope_scales == [1] * 8
    assert type(settings.fft_size) is int
    assert type(settings.scope_timebase) is float


def test_explicit_override_does_not_read_legacy_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "settings.json").write_text('{"theme":"AMOLED"}')
    monkeypatch.setenv("SERIAL_MONITOR_SETTINGS", str(tmp_path / "isolated.json"))
    loaded, warning = Settings.load()
    assert not warning
    assert loaded.theme == "Dark"
