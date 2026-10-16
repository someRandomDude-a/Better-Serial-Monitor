import numpy as np
import pytest

from serial_workspace.metadata import TimingTracker
from serial_workspace.settings import Settings
from serial_workspace.stream import NumericParser


@pytest.mark.parametrize("mode,line,time_key,seq_key", [
    ("CSV", "1000,10,3.25,2.5", "1", "2"),
    ("Labels", "time_us:1000,seq:10,value:3.25,other:2.5", "time_us", "seq"),
    ("JSON", '{"time_us":1000,"seq":10,"value":3.25,"other":2.5}', "time_us", "seq"),
])
def test_metadata_fields_are_explicit_and_not_signal_channels(mode, line, time_key, seq_key):
    parser = NumericParser(mode, timestamp_field=time_key, sequence_field=seq_key, timestamp_unit="Microseconds")
    parsed = parser.parse(line)
    assert parsed.device_time == 0.001
    assert parsed.sequence == 10
    assert parsed.values[:2] == (3.25, 2.5)
    assert len(parser.names) == 2


def test_timestamp_like_fields_are_not_guessed():
    parser = NumericParser()
    parsed = parser.parse('{"time":123,"value":10}')
    assert parsed.device_time is None
    assert parser.names == ["time", "value"]


def test_timing_rate_jitter_sequence_loss_and_continuity():
    tracker = TimingTracker(True, True)
    for i in range(1000):
        tracker.observe(i/1000, i, i/1000+10)
    summary = tracker.summary(500, now=11)
    assert summary["Device nominal sample rate (Hz)"] == pytest.approx(1000)
    assert summary["Device interval jitter RMS (s)"] < 1e-12
    assert summary["Host accepted rows/s (not sample clock)"] == pytest.approx(1000)
    assert not tracker.continuity_note(512)
    tracker.observe(1.002, 1002, 11.002)
    assert tracker.missing_sequence == 2
    assert "sequence" in tracker.continuity_note(512)
    tracker.observe(1.002, 1002, 11.004)
    assert tracker.duplicates == 1
    assert tracker.resets == 1


def test_host_batch_bursts_do_not_define_device_sample_rate():
    tracker = TimingTracker(True, False)
    for i in range(1000):
        tracker.observe(i/200, None, 1 + (i//100)*0.1)
    metrics = tracker.summary(1000, now=2)
    assert metrics["Device nominal sample rate (Hz)"] == pytest.approx(200)
    assert metrics["Host accepted rows/s (not sample clock)"] == pytest.approx(1000)


def test_jitter_resets_and_missing_metadata_are_not_silently_resampled():
    tracker = TimingTracker(True, False)
    for t in (0, 0.001, 0.002, 0.005):
        tracker.observe(t, None, t)
    assert "5%" in tracker.continuity_note(4)
    tracker.observe(None, None, 0.006)
    assert tracker.missing_metadata == 1
    assert "timestamp" in tracker.continuity_note(3)
    assert len(tracker.recent(0)[0]) == 0


def test_settings_validate_new_fields():
    settings = Settings.from_dict({"analysis_hz": 200, "experience": "invalid", "filter_order": -1,
                                   "timestamp_field": " time ", "sequence_field": "time", "fundamental": np.inf})
    assert settings.experience == "Monitor"
    assert settings.analysis_hz == 5
    assert settings.filter_order == 4
    assert settings.timestamp_field == "time"
    assert settings.sequence_field == ""
    assert settings.fundamental == 0


def test_non_finite_device_intervals_fail_continuity_checks():
    tracker = TimingTracker(True, False)
    tracker.observe(-1e308, None, 0)
    tracker.observe(1e308, None, 1)
    with np.errstate(over="ignore"):
        assert "numeric range" in tracker.continuity_note(2)
