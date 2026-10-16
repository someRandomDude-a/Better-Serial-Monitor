"""Uniformly sampled signal tools; amplitudes are in input units, not calibrated dBFS."""

from dataclasses import dataclass
import numpy as np


@dataclass
class Spectrum:
    frequency: np.ndarray
    amplitude: np.ndarray
    db: np.ndarray
    peak_hz: float
    peak_amplitude: float
    resolution: float


def spectrum(values, sample_rate, size=2048, window="Hann", remove_dc=True):
    values = np.asarray(values, dtype=float)
    if sample_rate <= 0 or size < 4:
        raise ValueError("Sample rate must be positive and FFT size at least four.")
    if len(values) < size or not np.all(np.isfinite(values[-size:])):
        return None
    segment = values[-size:].copy()
    if remove_dc:
        segment -= segment.mean()
    windows = {"Hann": np.hanning, "Hamming": np.hamming, "Blackman": np.blackman,
               "Rectangular": np.ones}
    weights = windows[window](size)
    amplitude = np.abs(np.fft.rfft(segment * weights)) * (2.0 / weights.sum())
    amplitude[0] *= 0.5
    if size % 2 == 0:
        amplitude[-1] *= 0.5
    frequency = np.fft.rfftfreq(size, 1.0 / sample_rate)
    start = 1 if remove_dc else 0
    peak = start + int(np.argmax(amplitude[start:]))
    return Spectrum(frequency, amplitude, 20 * np.log10(np.maximum(amplitude, 1e-12)),
                    float(frequency[peak]), float(amplitude[peak]), sample_rate / size)


def statistics(values, sample_rate):
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {}
    mean = float(finite.mean())
    rms = float(np.sqrt(np.mean(finite ** 2)))
    peak = float(np.max(np.abs(finite)))
    # Do not bridge missing values when estimating a period.
    frequency = None
    if len(finite) == len(values) and len(values) > 2:
        centered = values - mean
        rising = np.flatnonzero((centered[:-1] < 0) & (centered[1:] >= 0))
        if len(rising) > 1:
            crossings = rising - centered[rising] / (centered[rising + 1] - centered[rising])
            frequency = float(sample_rate / np.mean(np.diff(crossings)))
    result = {
        "Samples": len(finite), "Mean / DC": mean, "RMS": rms,
        "AC RMS": float(np.std(finite)), "Minimum": float(finite.min()),
        "Maximum": float(finite.max()), "Peak to peak": float(np.ptp(finite)),
        "Standard deviation": float(np.std(finite)),
        "Crest factor": peak / rms if rms > 0 else None,
        "Above mean (%)": float(np.mean(finite > mean) * 100),
        "Frequency (Hz)": frequency,
        "Period (s)": 1 / frequency if frequency else None,
    }
    result.update(pulse_measurements(values, sample_rate))
    return result


def pulse_measurements(values, sample_rate):
    """Window min/max define 10/90% levels. Results are estimates, not de-noised edges."""
    empty = {"Duty above midpoint (%)": None, "Rise 10–90% (s)": None, "Fall 90–10% (s)": None}
    if len(values) < 3 or not np.all(np.isfinite(values)) or np.ptp(values) == 0:
        return empty
    low = float(np.min(values))
    span = float(np.ptp(values))

    def crossings(level, rising):
        mask = ((values[:-1] < level) & (values[1:] >= level)) if rising else ((values[:-1] > level) & (values[1:] <= level))
        index = np.flatnonzero(mask)
        return index + (level - values[index]) / (values[index + 1] - values[index])

    def edge_time(start, finish, cancel):
        if not len(start) or not len(finish):
            return None
        end_positions = np.searchsorted(finish, start, side="right")
        valid = end_positions < len(finish)
        start = start[valid]
        ends = finish[end_positions[valid]]
        # Reject a transition if it returned through the starting threshold first.
        cancellation = np.searchsorted(cancel, start, side="right")
        cancellation_times = np.r_[cancel, np.inf][cancellation]
        durations = (ends - start)[ends < cancellation_times]
        return float(np.median(durations) / sample_rate) if len(durations) else None

    up_low, up_high = crossings(low + 0.1 * span, True), crossings(low + 0.9 * span, True)
    down_high, down_low = crossings(low + 0.9 * span, False), crossings(low + 0.1 * span, False)
    return {
        "Duty above midpoint (%)": float(np.mean(values > low + 0.5 * span) * 100),
        "Rise 10–90% (s)": edge_time(up_low, up_high, down_low),
        "Fall 90–10% (s)": edge_time(down_high, down_low, up_high),
    }


def moving_average(values, width=16):
    values = np.asarray(values, dtype=float)
    if len(values) < width:
        return np.array([])
    return np.convolve(values, np.ones(width) / width, mode="valid")


def autocorrelation(values, max_lags=2048):
    values = np.asarray(values, dtype=float)
    if len(values) < 2 or not np.all(np.isfinite(values)):
        return np.array([])
    values = values - values.mean()
    size = 1 << (2 * len(values) - 1).bit_length()
    transformed = np.fft.rfft(values, size)
    result = np.fft.irfft(transformed * transformed.conj(), size)[:min(len(values), max_lags)]
    return result / result[0] if result[0] > 0 else np.zeros_like(result)
