import numpy as np
import pytest

from serial_workspace.signal_tools import fourier_details, harmonic_report, power_density, process_signal, spectral_peaks, time_frequency


def test_fourier_amplitude_phase_and_weak_bin_mask():
    t = np.arange(2048) / 1024
    f, amplitude, phase = fourier_details(2*np.cos(2*np.pi*64*t + 0.4), 1024, 2048, "Rectangular")
    index = np.argmax(amplitude)
    assert f[index] == 64
    assert amplitude[index] == pytest.approx(2)
    assert phase[index] == pytest.approx(np.degrees(0.4))
    assert np.isnan(phase[20])


def test_welch_density_integrates_to_signal_power():
    fs = 1024
    values = np.sqrt(2)*np.sin(2*np.pi*64*np.arange(8192)/fs)
    f, psd = power_density(values, fs, 1024)
    assert np.sum(psd)*(f[1]-f[0]) == pytest.approx(1, rel=0.001)


def test_spectrogram_tracks_a_chirp_and_is_bounded():
    from scipy.signal import chirp

    t = np.arange(65536) / 1024
    values = chirp(t, f0=20, f1=200, t1=t[-1])
    f, times, density = time_frequency(values, 1024, 1024, overlap=90)
    dominant = f[np.argmax(density, axis=0)]
    assert dominant[0] < dominant[-1]
    assert len(times) <= 128
    assert density.shape == (len(f), len(times))


@pytest.mark.parametrize("tool,low,high,wanted", [
    ("Low-pass filter", 5, 60, 20), ("High-pass filter", 100, 200, 200),
    ("Band-pass filter", 10, 40, 20), ("Band-stop filter", 10, 40, 200),
])
def test_butterworth_filters_keep_the_requested_component(tool, low, high, wanted):
    t = np.arange(8192)/1024
    values = np.sin(2*np.pi*20*t) + np.sin(2*np.pi*200*t)
    result = process_signal(tool, t, values, 1024, low=low, high=high)
    expected = np.sin(2*np.pi*wanted*t)
    assert np.sqrt(np.mean((result.y[512:-512]-expected[512:-512])**2)) < 0.03
    np.testing.assert_allclose(values, np.sin(2*np.pi*20*t) + np.sin(2*np.pi*200*t))


def test_inverse_fft_band_reconstruction_even_and_odd():
    for size in (1024, 1023):
        t = np.arange(size)/size
        original = np.sin(2*np.pi*20*t) + 0.5*np.cos(2*np.pi*100*t)
        result = process_signal("FFT band reconstruction", t, original, size, low=19, high=21)
        np.testing.assert_allclose(result.y, np.sin(2*np.pi*20*t), atol=1e-12)


def test_harmonic_model_thd_snr_and_sinad():
    fs, count = 4096, 8192
    t = np.arange(count)/fs
    noise = np.random.default_rng(42).normal(scale=0.001, size=count)
    values = np.sin(2*np.pi*100*t) + 0.1*np.sin(2*np.pi*200*t) + noise
    rows, metrics = harmonic_report(values, fs, 100, 5)
    assert rows[0][2] == pytest.approx(1/np.sqrt(2), rel=0.001)
    assert metrics["THD (%)"] == pytest.approx(10, rel=0.01)
    assert metrics["SNR estimate (dB)"] == pytest.approx(57, abs=1)
    assert metrics["SINAD estimate (dB)"] == pytest.approx(20, abs=0.1)
    _, auto = harmonic_report(values, fs, count=5)
    assert auto["Fundamental (Hz)"] == pytest.approx(100, abs=0.01)


def test_rolling_statistics_have_valid_only_alignment():
    values = np.arange(10, dtype=float)
    result = process_signal("Rolling statistics", values/100, values, 100, width=4)
    assert len(result.y) == 7
    assert result.x[0] == 0.03
    assert result.y[0] == 1.5
    assert result.extra["RMS"][0] == pytest.approx(np.sqrt(3.5))
    assert result.extra["Standard deviation"][0] == pytest.approx(np.std(values[:4]))


def test_peak_extraction_and_threshold_partial_events():
    t = np.arange(1000)/1000
    values = np.sin(2*np.pi*10*t)
    peaks = process_signal("Peaks", t, values, 1000, prominence=1, distance=50)
    assert len(peaks.rows) == 10
    assert peaks.rows[0][1] == pytest.approx(0.025)
    assert peaks.rows[0][2] == pytest.approx(1)
    assert peaks.rows[0][4] > 0
    events = process_signal("Threshold events", t, values, 1000, threshold=0.5, hysteresis=0.2)
    assert len(events.rows) == 10
    assert events.rows[0][2] > 0
    clipped = process_signal("Threshold events", np.arange(10)/10, np.ones(10), 10)
    assert clipped.rows[0][-2:] == [True, True]


def test_envelope_and_input_validation():
    t = np.arange(1024)/1024
    result = process_signal("Envelope", t, 2*np.sin(2*np.pi*64*t), 1024)
    np.testing.assert_allclose(result.y, 2, atol=1e-12)
    with pytest.raises(ValueError, match="Nyquist"):
        process_signal("Band-pass filter", t, np.ones(1024), 1000, low=100, high=600)
    with pytest.raises(ValueError, match="finite"):
        process_signal("Peaks", t, np.full(1024, np.nan), 1000)
    with pytest.raises(ValueError, match="No AC"):
        harmonic_report(np.ones(1024), 1000)


def test_spectral_peak_extraction_is_sorted_and_frequency_refined():
    t = np.arange(8192)/1024
    f, amplitude, _ = fourier_details(np.sin(2*np.pi*50.03*t)+0.2*np.sin(2*np.pi*120*t), 1024, 8192)
    rows = spectral_peaks(f, amplitude, 10)
    assert rows[0][0] == pytest.approx(50.03, abs=0.01)
    assert rows[1][0] == pytest.approx(120, abs=0.01)
    assert rows[0][1] > rows[1][1]


def test_hysteresis_rejects_repeated_threshold_chatter():
    values = np.array([-1, 1, 0.1, -0.1, 0.1, -0.1, -1, -1], dtype=float)
    events = process_signal("Threshold events", np.arange(8)/10, values, 10, hysteresis=1)
    assert len(events.rows) == 1
    assert events.rows[0][0] == 0.1
    assert events.rows[0][1] == 0.6
