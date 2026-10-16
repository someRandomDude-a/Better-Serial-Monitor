import numpy as np
import pytest

from serial_workspace.analysis import autocorrelation, moving_average, pulse_measurements, spectrum, statistics


@pytest.mark.parametrize("window", ["Hann", "Hamming", "Blackman", "Rectangular"])
def test_fft_frequency_and_coherent_gain(window):
    fs, size = 1024, 2048
    signal = 2.5 * np.sin(2 * np.pi * 64 * np.arange(size) / fs) + 3
    result = spectrum(signal, fs, size, window)
    assert result.peak_hz == pytest.approx(64)
    assert result.peak_amplitude == pytest.approx(2.5, rel=0.001)
    assert result.resolution == 0.5
    assert result.db[128] == pytest.approx(20 * np.log10(2.5), rel=0.001)


def test_dc_and_nyquist_are_not_doubled():
    result = spectrum(np.ones(256) * 3, 1024, 256, "Rectangular", False)
    assert result.amplitude[0] == pytest.approx(3)
    result = spectrum(2 * (-1.0) ** np.arange(256), 1024, 256, "Rectangular")
    assert result.amplitude[-1] == pytest.approx(2)


def test_fft_rejects_short_or_gapped_data():
    assert spectrum([1, 2], 1000, 256) is None
    assert spectrum([np.nan] * 256, 1000, 256) is None


def test_signal_statistics_and_crossing_frequency():
    values = np.sin(2 * np.pi * 20 * np.arange(2000) / 1000)
    result = statistics(values, 1000)
    assert result["RMS"] == pytest.approx(1 / np.sqrt(2))
    assert result["Frequency (Hz)"] == pytest.approx(20, rel=1e-5)
    assert result["Period (s)"] == pytest.approx(0.05)
    assert statistics([0, 0], 1000)["Crest factor"] is None
    assert statistics([0, np.nan, 1], 1000)["Frequency (Hz)"] is None


def test_transform_tools():
    np.testing.assert_allclose(moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
    assert not len(moving_average([1], 2))
    periodic = np.sin(2 * np.pi * np.arange(1000) / 20)
    correlation = autocorrelation(periodic)
    assert correlation[0] == pytest.approx(1)
    assert correlation[20] > 0.95
    assert not len(autocorrelation([1, np.nan]))


def test_pulse_measurements_and_gaps():
    values = np.tile(np.r_[np.linspace(0, 1, 101), np.linspace(1, 0, 101)], 3)
    result = pulse_measurements(values, 1000)
    assert result["Rise 10–90% (s)"] == pytest.approx(0.08)
    assert result["Fall 90–10% (s)"] == pytest.approx(0.08)
    assert result["Duty above midpoint (%)"] == pytest.approx(49.5, abs=1)
    assert pulse_measurements(np.array([0, np.nan, 1]), 1000)["Rise 10–90% (s)"] is None
