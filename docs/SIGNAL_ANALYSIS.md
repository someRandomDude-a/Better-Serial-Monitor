# Signal analysis reference

This reference describes the implemented finite-window algorithms, not a claim of calibrated measurement accuracy. For normal serial monitoring, none of these tools or metadata fields need to be configured. In the application, F1 opens the user guide; Spectrum and Analysis also show short explanations next to the controls.

## Suggested learning recipes

1. **Read first:** connect or start Demo signal in Monitor. Filter/copy/send as usual. Plain text stays plain text; numbers are only parsed from strict supported records.
2. **Graph values:** follow Plot numeric values. Hide unused channels and select a useful visible time span. No filtering has occurred.
3. **Find repetition:** open Spectrum → Amplitude FFT. On Demo channel 1, expect a strong tone near 50 Hz and a smaller 120 Hz component. Detail 2048 at 1000 samples/s separates bins by about 0.488 Hz; a peak need not land exactly on 50.
4. **See change over time:** choose Spectrogram. Bright horizontal bands are sustained tones; sloped bands indicate changing frequency. It shows retained recent data, not an unlimited recording.
5. **Smooth a value:** Analysis → Moving average, then try Rolling statistics. Increase smoothing samples to suppress short changes. This is a trailing window, not a forecast.
6. **Isolate a component:** Analysis → Band-pass filter; set lower 40, upper 60 Hz for Demo. Compare the result with the original. Try FFT band reconstruction with the same band and inspect edge ringing. Export the processed result, not the raw-sample CSV, if you want the filtered values.
7. **Extract observations:** Peaks finds local maxima; Threshold events finds above-threshold spans. Tune prominence/separation or threshold/hysteresis, inspect markers, then open Extracted rows. Partial-window events are labelled, not silently treated as complete pulses.
8. **Check acquisition timing:** use firmware that emits device timestamps/sequence numbers, explicitly select their fields in Settings, and inspect Analysis → Data quality. Do not use Demo's USB/host arrivals as an ADC-clock calibration.

## Fourier amplitude and phase

For N samples at configured sample rate fs, the amplitude view computes a real FFT of a symmetric Hann/Hamming/Blackman or rectangular window. Optional DC removal subtracts the entire window mean. Amplitude is `2 abs(rfft(x*w))/sum(w)`, with DC and even-N Nyquist halved. The output is single-sided **peak sinusoidal amplitude** in input units. It is not RMS, dBFS, dBm or power density. Ordinary amplitude dB is `20 log10(A / 1 unit)` with a −240 dB floor.

Phase is `arg(rfft(x*w))` in degrees with a cosine reference. A cosine `A cos(2πft+φ)` on a coherent bin reads φ. It is relative to the beginning of the current moving window. Phase is masked below both relative −80 dB and an absolute amplitude threshold of 1e-12. It is not unwrapped phase, group delay or cross-channel phase. The XY tool allows qualitative channel comparisons.

Resolution is fs/N, regardless of frequency interpolation. Spectral peaks uses local log-parabolic interpolation (at most half a bin) to estimate an isolated peak's center; it cannot separate unresolved tones. Its amplitude remains the actual bin amplitude. Prominence is in dB; the strongest 50 peaks above −80 dB relative amplitude are retained. Width is at half prominence in the dB spectrum, not a −3 dB bandwidth specification.

## Welch PSD and STFT spectrogram

Welch density uses SciPy `signal.welch`, configured fs, chosen periodic window, N-sample segments, 0–90% overlap, and optional per-segment mean removal. Scaling is **unit²/Hz**. Integrating density over frequency approximates variance for a mean-removed signal. The dB view is `10 log10(P / 1 unit²/Hz)`; it must not be confused with amplitude dB. PSD and the symmetric-window amplitude FFT are different estimators and need not have identical displayed peak heights.

The spectrogram uses SciPy's windowed PSD spectrogram with the same segment/window/overlap/DC conventions. The latest `min(8*N, 65536)` retained rows are used. Hop size is increased if necessary to keep at most 128 time columns. Thus requested high overlap can be reduced to preserve performance. X is sample-index time using configured fs, not arrival time; each column is centered on its segment. Only retained history is shown. Changing detail alters frequency/time resolution, and there is no zero-padding to invent missing startup data.

The color scale is density dB, with viridis, plasma, inferno, or CET-L1 (grayscale). Auto color levels place the upper bound at the strongest displayed density and show the selected 20–160 dB span (default 80). Disable Auto to preserve/drag fixed colorbar limits; manual levels persist. There is no claim of calibrated noise floor or dynamic range. Aliasing cannot be undone by any view.

## Harmonic and noise estimates

The harmonic model fits a DC term plus sine/cosine terms at f0, 2f0, … through the selected harmonic count, excluding terms at/above Nyquist. Auto selects the strongest non-DC periodogram peak and refines its frequency using a bounded single-tone least-squares residual; it can mistake a strong overtone for the fundamental. Enter a known f0 when necessary. At least four cycles of the fundamental must fit in the analysis window. The model is finite-window and assumes a stationary, uniformly sampled signal.

Each harmonic amplitude is `hypot(sine_coefficient, cosine_coefficient)/sqrt(2)` (RMS). Phase in the harmonic table uses a **sine reference**, unlike the cosine-referenced FFT phase. Relative level is dBc against fundamental amplitude.

- **THD:** root-sum-square RMS of modelled harmonics 2…H divided by fundamental RMS; percent or `20 log10` ratio.
- **Residual RMS:** RMS after subtracting all modelled harmonic/DC terms.
- **SNR estimate:** `20 log10(fundamental_RMS / residual_RMS)`.
- **SINAD estimate:** `20 log10(fundamental_RMS / hypot(harmonic_RMS, residual_RMS))`.

A numerical floor of 1e-15 prevents divide/log singularities; near-perfect synthetic tones may therefore produce physically meaningless very large ratios. Unmodelled harmonics, interharmonics, amplitude/frequency drift, timing jitter, aliasing and other model errors contribute to residual. There is no calibrated bandwidth integration, instrument noise correction, full-scale reference, standard-compliant qualification or guaranteed ADC ENOB. Report these as **estimates with the model/window/rate settings**, not instrument specifications.

## Filtering and reconstruction

Butterworth filters use SciPy second-order sections and `sosfiltfilt`: forward/backward **zero-phase finite-window** filtering. Low-pass uses the upper cutoff; high-pass uses the lower; bands use both. All cutoffs must satisfy 0 < cutoff < fs/2, with lower < upper. Prototype order is 1–10; band transformations double the transfer-function order and forward/backward application doubles it again. The combined magnitude is squared relative to a single pass. Short windows can be rejected for inadequate padding. Boundary transients remain possible even when accepted.

These are not streaming causal filters and do not keep state between windows. They do not change original samples, fix aliasing, reconfigure the device, or filter other views. The original overlay is for comparison. Filtered output CSV contains the completed processed window.

FFT band reconstruction retains rFFT bins between lower and upper bounds (inclusive) and applies `irfft(..., n=original_length)`, correctly preserving both odd and even lengths. Bounds may include DC (zero) and Nyquist. It uses unwindowed raw samples so reconstructing the entire band returns the original. A brick-wall mask assumes periodic extension; sharp transitions and noncoherent boundaries can ring. This is frequency-component extraction/inverse FFT, not a frequency-domain editor or deconvolution tool.

Envelope is the magnitude of `hilbert(x - mean(x))`; finite-window endpoints may be distorted. It is most interpretable for a narrowband oscillatory signal, not arbitrary DC or multitone waveforms.

## Rolling and event extraction

Moving average and Rolling statistics use valid trailing windows of 2–512 samples with no edge padding. At width W, the first output is aligned to original sample W−1. Rolling mean = E[x]; RMS = sqrt(E[x²]); population deviation = sqrt(max(E[x²]−E[x]²,0)). The rolling-statistics view requires a finite contiguous input window. It exports mean, RMS and deviation columns; the ordinary moving-average view can show propagated gaps.

Peaks uses `scipy.signal.find_peaks` with minimum prominence in input units and minimum distance in samples. Width comes from `peak_widths(..., rel_height=0.5)` divided by fs: half **prominence**, not half absolute peak height or a rise-time measurement. Only maxima are detected; negate a signal externally to inspect minima. Endpoints are not local peaks. Export includes window index, sample time, value, prominence and width.

Threshold events enters when the signal crosses strictly above `threshold + hysteresis/2` and exits at/below `threshold − hysteresis/2`. A signal already above the upper boundary at window start is a clipped-start event; an active span at window end is clipped-end. Boundaries are sample-aligned, with no edge interpolation. Start/end time, duration, peak and mean (inclusive endpoints) are exported along with clipping flags. Durations of partial events are **observed portions**, not full pulse widths.

Extraction operates on a moving finite analysis window, not a session event database. The first 500 rows are displayed; all result rows from that completed window are exported. Overlapping windows can contain the same peak/event, so concatenating exported windows will create duplicates unless you deduplicate externally.

## Timing metadata

### Explicit input mapping

Select exact JSON/labeled keys or **1-based** CSV columns for a device timestamp and/or sequence counter in Settings → Acquisition. Timestamp units are Seconds/Milliseconds/Microseconds. Fields are excluded from signal channels only when explicitly selected; no key names are guessed. A stream like `{"time_us":2000,"seq":1,"voltage":0.5}` uses `time_us`, Microseconds, and `seq`. For CSV `2000,1,0.5`, use columns `1` and `2`.

Sequences must be non-negative integers exactly representable in float64 (≤2^53−1). No wrap modulus is assumed. Clock/counter rollover and resets are flagged, not automatically unwrapped. Timestamp precision must be adequate for the sample interval. Missing chosen metadata is counted even when signal values remain valid; monitoring raw text never depends on valid timing.

### What each rate means

- **Configured rate:** the user setting used for time/frequency axes. It does not configure device sampling.
- **Device nominal rate:** reciprocal of the median valid positive per-sample timestamp interval. If sequence is supplied, a time difference is divided by the positive sequence step to avoid calling a known dropped frame a slower clock.
- **Host accepted rows/s:** accepted numeric rows over the recent approximately 10-second arrival window (at least 0.5 seconds to estimate), based on monotonic host batch arrival times. It becomes zero after a second without arrivals. This measures throughput, not device sampling or serial baud.

Jitter RMS is deviation of valid per-step intervals from their median, not oscillator phase noise, Allan deviation or calibrated timebase uncertainty. Min/max intervals use the same per-step normalization. Summary estimates use up to 8,192 recent metadata rows; up to 65,536 are retained/exportable. Counters show positive sequence jumps minus one, duplicates, nonpositive time/reset conditions, and missing selected metadata. A simultaneous time and sequence reset can increment both reset conditions. Clearing/reconnecting/known input loss starts a fresh diagnostic epoch.

Continuity checks use the exact recent sample window: selected missing/duplicate/skipped/reset sequences, missing/nonincreasing times, or any interval deviation over 5% of the median pauses uniform-sampling tools. There is **no implicit interpolation or resampling**. Raw Monitor/Plotter remains usable; its relative sample timeline should not be mistaken for real elapsed time across gaps. The scope holds/waits instead of taking a new invalid capture. Incompatible device metadata windows also suppress crossing-derived timing statistics.

**Use measured device sample rate…** is an explicit adoption action, with confirmation and numeric/capture reset. It never silently uses USB arrivals or continuously changes axes while you inspect a capture. Rate adoption is still a device-clock estimate, not calibration against a reference.

## Export and reproducibility

Use raw sample CSV for original values, held Scope CSV for triggered captures, result CSV for filters/peaks/events/FFT/PSD/spectrograms/harmonics, device timing CSV for timestamps/sequences, and report JSON for settings/statistics/quality and completed extraction/harmonic results. Missing/non-finite export fields are blank in CSV or null in JSON. Report sections can come from different recent windows during live acquisition; the report records that limitation. For a stable comparison, stop the source or disconnect before computing/exporting; Freeze view alone does not stop ring retention.

Processing results are cached by data version and parameter generation. Only one job can be in flight per spectral/processing panel, and old parameter-generation results are discarded. Analysis runs at 1–20 Hz (default 5), independently of plot refresh. Increasing refresh does not increase acquisition bandwidth. Settings, not raw data/result arrays, persist on exit.

## Deliberate limits

This is not an analog front end, hardware-triggered scope, raw binary protocol decoder or lossless long-term recorder. There is no nonuniform resampler, calibrated phase/noise analyzer, arbitrary FFT-bin editor, transfer-function/coherence measurement, deconvolution, system identification, machine-learning classifier, causal filter pipeline or standard-compliant metrology package. The implemented tools have explicit conventions and limits rather than claiming to include every possible signal-analysis technique.
