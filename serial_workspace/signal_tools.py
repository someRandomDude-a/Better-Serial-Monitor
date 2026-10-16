"""Finite-window DSP, extraction and estimates. Functions never mutate source samples."""

from dataclasses import dataclass, field
import numpy as np
from scipy import optimize, signal

from .analysis import moving_average


WINDOWS = {"Hann": "hann", "Hamming": "hamming", "Blackman": "blackman", "Rectangular": "boxcar"}


def finite_signal(values, rate, minimum=4):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError("Set a positive sample rate first.")
    if len(values) < minimum:
        raise ValueError(f"Need at least {minimum} samples; {len(values)} available.")
    if not np.all(np.isfinite(values)):
        raise ValueError("This tool needs consecutive finite samples. Missing values are not interpolated.")
    return values


def fourier_details(values, rate, size, window="Hann", remove_dc=True):
    values = finite_signal(values, rate, size)[-size:]
    centered = values - values.mean() if remove_dc else values.copy()
    weights = signal.get_window(WINDOWS[window], size, fftbins=False)
    transformed = np.fft.rfft(centered * weights)
    amplitude = 2 * np.abs(transformed) / weights.sum()
    amplitude[0] *= 0.5
    if size % 2 == 0:
        amplitude[-1] *= 0.5
    phase = np.angle(transformed, deg=True)
    # Phase of bins below -80 dB relative to the strongest bin is not useful.
    phase[amplitude < max(float(amplitude.max()) * 1e-4, 1e-12)] = np.nan
    return np.fft.rfftfreq(size, 1 / rate), amplitude, phase


def power_density(values, rate, size=2048, window="Hann", overlap=50, remove_dc=True):
    values = finite_signal(values, rate, size)
    return signal.welch(values, fs=rate, window=WINDOWS[window], nperseg=size,
                        noverlap=int(size * overlap / 100), detrend="constant" if remove_dc else False,
                        scaling="density")


def time_frequency(values, rate, size=1024, window="Hann", overlap=50, remove_dc=True):
    values = finite_signal(values, rate, size)
    # Bound the time-frequency grid to 128 columns, regardless of requested overlap.
    hop = max(1, round(size * (1 - overlap / 100)), int(np.ceil(max(1, len(values) - size) / 127)))
    hop = min(size, hop)
    frequency, times, density = signal.spectrogram(values, fs=rate, window=WINDOWS[window],
                                                 nperseg=size, noverlap=size - hop,
                                                 detrend="constant" if remove_dc else False,
                                                 scaling="density", mode="psd")
    return frequency, times, density


def spectral_peaks(frequency, amplitude, prominence_db=10):
    db = 20*np.log10(np.maximum(amplitude, 1e-12))
    peaks, _ = signal.find_peaks(db, prominence=prominence_db)
    peaks = peaks[amplitude[peaks] >= max(float(amplitude.max()) * 1e-4, 1e-12)]
    peaks = peaks[np.argsort(amplitude[peaks])[::-1]][:50]
    widths = signal.peak_widths(db, peaks, rel_height=0.5)[0] if len(peaks) else []
    step = frequency[1] - frequency[0]
    rows = []
    for index, width in zip(peaks, widths):
        left, center, right = db[index-1:index+2]
        curvature = left - 2*center + right
        shift = np.clip(0.5*(left-right)/curvature, -0.5, 0.5) if curvature else 0
        rows.append([float(frequency[index] + shift*step), float(amplitude[index]),
                     float(db[index] - db.max()), float(width*step), int(index)])
    return rows


def harmonic_report(values, rate, fundamental=0.0, count=5):
    """Least-squares sinusoidal model. Residual is an estimate, not calibrated noise."""
    values = finite_signal(values, rate, 64)
    n = len(values)
    resolution = rate / n
    centered = values - values.mean()
    if np.std(centered) < 1e-12:
        raise ValueError("No AC signal to analyse. Choose a varying channel.")
    t = np.arange(n) / rate
    if fundamental <= 0:
        freq, density = signal.periodogram(centered, rate, window="hann")
        peak = int(np.argmax(density[1:])) + 1
        guess = float(freq[peak])

        def residual(f):
            design = np.column_stack((np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t), np.ones(n)))
            fit = design @ np.linalg.lstsq(design, values, rcond=None)[0]
            return float(np.mean((values - fit)**2))

        lower, upper = max(resolution, guess - resolution), min(rate / 2 - resolution * 0.01, guess + resolution)
        if upper <= lower:
            raise ValueError("Fundamental is too close to Nyquist for a stable estimate.")
        fundamental = float(optimize.minimize_scalar(residual, bounds=(lower, upper), method="bounded").x)
    if not 4 * resolution <= fundamental < rate / 2:
        raise ValueError("Use at least four cycles per window and a fundamental below Nyquist. Increase the window or set the fundamental explicitly.")
    harmonics = [h for h in range(1, count + 1) if h * fundamental < rate / 2]
    design = [np.ones(n)]
    for h in harmonics:
        design.extend((np.sin(2 * np.pi * h * fundamental * t), np.cos(2 * np.pi * h * fundamental * t)))
    matrix = np.column_stack(design)
    coefficients = np.linalg.lstsq(matrix, values, rcond=None)[0]
    amplitudes = np.hypot(coefficients[1::2], coefficients[2::2]) / np.sqrt(2)
    if amplitudes[0] < 1e-12:
        raise ValueError("Fundamental amplitude is too small for distortion ratios.")
    residual_rms = float(np.sqrt(np.mean((values - matrix @ coefficients)**2)))
    distortion = float(np.linalg.norm(amplitudes[1:]))
    floor = 1e-15
    rows = []
    for i, h in enumerate(harmonics):
        phase = float(np.degrees(np.arctan2(coefficients[2 + 2*i], coefficients[1 + 2*i])))
        rows.append([h, h * fundamental, float(amplitudes[i]), float(20*np.log10(max(amplitudes[i], floor)/amplitudes[0])), phase])
    metrics = {"Fundamental (Hz)": fundamental, "Fundamental RMS": float(amplitudes[0]),
               "THD (%)": distortion / amplitudes[0] * 100,
               "THD (dB)": float(20*np.log10(max(distortion, floor)/amplitudes[0])),
               "Residual RMS": residual_rms,
               "SNR estimate (dB)": float(20*np.log10(amplitudes[0]/max(residual_rms, floor))),
               "SINAD estimate (dB)": float(20*np.log10(amplitudes[0]/max(np.hypot(residual_rms, distortion), floor))),
               "Modelled harmonics": len(harmonics), "Window duration (s)": n / rate}
    return rows, metrics


@dataclass
class Processed:
    x: np.ndarray
    y: np.ndarray
    x_label: str = "Sample time (s)"
    y_label: str = "Value"
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    markers: tuple | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)


def process_signal(tool, times, values, rate, *, width=16, low=10, high=100, order=4,
                   prominence=0.1, distance=10, threshold=0, hysteresis=0):
    values = finite_signal(values, rate)
    times = np.asarray(times, dtype=float)
    result = Processed(times.copy(), values.copy())
    if tool == "Rolling statistics":
        if len(values) < width:
            raise ValueError(f"Need {width} samples for this rolling window.")
        mean = moving_average(values, width)
        square = moving_average(values**2, width)
        result.x, result.y = times[width-1:], mean
        result.extra = {"RMS": np.sqrt(np.maximum(square, 0)),
                        "Standard deviation": np.sqrt(np.maximum(square - mean**2, 0))}
        result.columns = ["sample_time_s", "mean", "rms", "standard_deviation"]
        result.rows = np.column_stack((result.x, mean, result.extra["RMS"], result.extra["Standard deviation"])).tolist()
        result.note = "Trailing windows without padding: mean, RMS and population standard deviation."
    elif tool.endswith(" filter"):
        kind = {"Low-pass filter": "lowpass", "High-pass filter": "highpass", "Band-pass filter": "bandpass", "Band-stop filter": "bandstop"}[tool]
        cutoff = high if kind == "lowpass" else low if kind == "highpass" else [low, high]
        edges = np.atleast_1d(cutoff)
        if np.any(edges <= 0) or np.any(edges >= rate / 2) or len(edges) == 2 and low >= high:
            raise ValueError(f"Cutoffs must satisfy 0 < low < high < Nyquist ({rate/2:g} Hz). Low-pass uses high; high-pass uses low.")
        sos = signal.butter(order, cutoff, btype=kind, fs=rate, output="sos")
        try:
            result.y = signal.sosfiltfilt(sos, values)
        except ValueError as exc:
            raise ValueError("This window is too short for the filter order. Collect more samples or reduce the order.") from exc
        result.note = f"Butterworth order {order}, forward/backward zero-phase window filtering. Effective order doubles; inspect edge transients. Raw data is unchanged."
    elif tool == "FFT band reconstruction":
        if not 0 <= low < high <= rate / 2:
            raise ValueError(f"Select 0 ≤ low < high ≤ {rate/2:g} Hz.")
        bins = np.fft.rfft(values)
        frequency = np.fft.rfftfreq(len(values), 1/rate)
        bins[(frequency < low) | (frequency > high)] = 0
        result.y = np.fft.irfft(bins, n=len(values))
        result.note = "Inverse real FFT of only the selected band. Brick-wall bin masking is periodic and can ring at discontinuities; this is not a causal filter."
    elif tool == "Envelope":
        result.y = np.abs(signal.hilbert(values - values.mean()))
        result.note = "Magnitude of the analytic (Hilbert) signal after mean removal. Window edges may contain artifacts."
    elif tool == "Peaks":
        peaks, properties = signal.find_peaks(values, prominence=prominence, distance=distance)
        widths = signal.peak_widths(values, peaks, rel_height=0.5)[0] if len(peaks) else []
        result.markers = (times[peaks], values[peaks])
        result.columns = ["window_index", "sample_time_s", "value", "prominence", "width_half_prominence_s"]
        result.rows = [[int(i), float(times[i]), float(values[i]), float(p), float(w/rate)]
                       for i, p, w in zip(peaks, properties["prominences"], widths)]
        result.note = f"{len(peaks)} local maxima; prominence ≥ {prominence:g}, separation ≥ {distance} samples. Width is at half prominence, not a pulse rise time."
    elif tool == "Threshold events":
        lo, hi = threshold - hysteresis / 2, threshold + hysteresis / 2
        active = values[0] > hi
        start = 0 if active else None
        events = []
        for i in range(1, len(values)):
            if not active and values[i-1] <= hi < values[i]:
                start, active = i, True
            elif active and values[i] <= lo < values[i-1]:
                events.append((start, i, start == 0, False))
                start, active = None, False
        if active:
            events.append((start, len(values)-1, start == 0, True))
        result.columns = ["start_s", "end_s", "duration_s", "peak", "mean", "clipped_start", "clipped_end"]
        result.rows = [[float(times[a]), float(times[b]), float(times[b]-times[a]), float(values[a:b+1].max()),
                        float(values[a:b+1].mean()), bool(left), bool(right)] for a,b,left,right in events]
        indices = [a for a, _, _, _ in events]
        result.markers = (times[indices], values[indices])
        result.note = f"{len(events)} above-threshold events. Enter > {hi:g}, exit ≤ {lo:g}. Boundaries are sample-aligned; partial events are flagged."
    else:
        raise ValueError(f"Unknown processing tool: {tool}")
    if not result.columns:
        result.columns = ["sample_time_s", "processed_value"]
        result.rows = np.column_stack((result.x, result.y)).tolist()
    return result
