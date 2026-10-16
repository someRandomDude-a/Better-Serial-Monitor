# User guide

## 1. Getting started

You do not need to learn any signal-analysis terms to use this as a serial monitor. Start with reading and sending text. **What can I do?** offers five small steps: read/send → graph numbers → hold a scope capture → find repetition → measure/extract. The guide is non-modal, so you can try things while it is open. Demo signal is a safe way to learn without hardware.

Install the dependencies in `Requirements.txt` in a Python 3.10+ virtual environment, then run `Serial_Monitor.py`. A graphical desktop is required. The application opens disconnected; changing a selection never silently opens a port.

1. Connect the device and press **Refresh**. Device descriptions are available as port-dropdown tooltips. You can also type a device name, such as `COM4` or `/dev/ttyUSB0`.
2. Choose or type the baud rate. Valid input is an integer from 50 through 12,000,000; the device and driver must support the chosen rate. Custom rates used for connection attempts are saved.
3. If needed, set data bits, parity, stop bits, flow control, encoding and parser in Settings. Press **Apply & save**.
4. Set the device's actual numeric sample rate in Settings. It is the rate of complete numeric rows, not the baud rate.
5. Press **Connect**. Use **Disconnect** to release the port before flashing firmware or opening another serial program. Connection errors are shown in the bottom status bar.

**Demo signal** generates three CSV channels at 1,000 samples/s: a 50 Hz sine with a smaller 120 Hz component, a 25 Hz sine, and a slowly varying DC-offset signal. It uses the same acquisition/parser/buffer pipeline as a serial source. If incompatible parser/rate settings are active, you are asked to change them. Demo cannot transmit. Disconnect ends it.

**Electrical safety:** The application has no analog input or input protection. Connect signals only to a suitable acquisition device within its ratings. Never connect mains or unknown voltages directly to a serial adapter or microcontroller pin. Software cannot provide electrical isolation or protect a device from overvoltage.

## 2. Navigation and shared controls

The default **Monitor** detail shows Monitor, Plotter and Settings in the sidebar. **Explore** reveals Scope, Spectrum and Analysis; **Advanced** also opens spectral fine-tuning. The discovery buttons and Ctrl+1 through Ctrl+6 can open any view, revealing Explore automatically when needed. Changing detail never changes device configuration or clears samples. The menu button or Ctrl+B hides the sidebar. Settings → Appearance independently controls guidance and summary cards (hidden by default to give console text more space).

- **Connection bar:** port, refresh, baud, Connect/Disconnect, and Demo signal. Active sessions lock port and baud until disconnected. Serial I/O runs in a worker, not on the GUI thread.
- **Connection card:** Offline, Opening, Connected, or Demo live.
- **Receive rate:** actual bytes read per second, including line terminators, refreshed approximately twice a second. It is not the device's sample rate.
- **Samples in buffer:** retained numeric rows, up to the configured capacity.
- **Dropped records:** queue/framing losses and oversized input records. Hover for discarded/oversized/non-numeric counts and RX/TX byte totals. Counters restart on connection; ordinary ring-buffer eviction is not a dropped-input error.
- **Freeze view / Resume view:** suspends visual updates, not serial acquisition, triggering, or buffer eviction. Resume displays the latest retained data. Space toggles this when focus is not in a text/spin/combo control.
- **Export:** numeric buffer/capture CSV, retained console TXT, plot PNG, current processed/spectral result CSV, device timing CSV, measurement report JSON, or preferences JSON. File writes run in a background worker using snapshots. One export runs at a time. Finish it before closing.
- **Status bar:** errors, operational notes and export results. No modal dialogs are used for normal receive errors.

Disconnect retains samples, captures and console records for inspection. A new connection/demo clears numeric samples and held captures to avoid mixing acquisitions; console history stays until cleared or evicted.

## 3. Input formats and channel mapping

One complete input line is one numeric sample row. A line may end in LF (`\n`), CR (`\r`) or CRLF (`\r\n`); CRLF counts as one terminator, including across read chunks. Partial lines wait for a terminator; unterminated input does not display immediately. Decoding uses the selected encoding, replacing invalid byte sequences for display.

### CSV and whitespace

```text
0.1,2.5,-3e-2
0.2,2.6,-4e-2
```

The default separator is a comma. CSV mode and Auto also accept whitespace-separated values when the configured delimiter is absent. Change the single-character delimiter for semicolon/tab-separated records. This is numeric delimited data, not a general quoted CSV reader. Column headings are non-numeric console records, not channel-name definitions. A timestamp/sequence is another channel unless explicitly selected as metadata in Settings → Acquisition: use a **1-based CSV column**, or the exact JSON/label key. Selected metadata fields are excluded from plotted channels.

### Labeled values

```text
voltage:3.30,current:0.12
voltage=3.31;current=0.13
```

Separate fields using commas, semicolons, or tabs. Each value must be a number, with no appended unit suffix. Scientific notation is supported. A label may contain spaces, but not the field separators or `:`/`=` characters.

### JSON

```text
{"voltage":3.30,"current":0.12,"status":"ok"}
```

Only finite numeric members of a flat object become channels. Booleans, strings, nulls, arrays and nested objects are ignored. Objects without numeric members do not create samples. JSON non-finite values are ignored.

### Rules

- Auto recognizes JSON objects first, then labeled records containing `:`/`=`, otherwise numeric delimited data. Explicit CSV/Labels/JSON modes avoid ambiguous input.
- At most eight channels are retained. CSV uses column order. Named streams assign indices in first-seen order and keep those indices when fields are reordered.
- Missing named fields become NaN gaps, not zero. Time plots do not connect across gaps. FFT requires a full finite window. Correlation/integral/frequency estimates that need continuity are disabled on gapped windows.
- Keep one format and channel schema per acquisition. Reconnect to establish a fresh schema. Settings can override the display names without changing channel mapping.
- Empty lines do not create samples. Non-numeric diagnostic lines remain in Monitor, but do not advance the numeric time axis. If an invalid line was intended to represent a lost numeric sample, the application cannot infer that automatically.
- CSV/Labels reject non-finite numeric rows. Transmitted lines are logged as TX and are never directly sampled; an actual device/loopback echo is RX and can be sampled.
- Input records are limited to 65,536 bytes. Larger records are discarded through their terminator. Neighboring complete records in the same read chunk may also be discarded to avoid joining data across a detected gap.

For consistent sampling, firmware should sample on a device timer and stream complete frames without omitting samples. Host timestamps describe the arrival of read batches, not device acquisition instants.

Example timestamped JSON: `{"time_us":100000,"seq":100,"voltage":0.3}`. Select timestamp field `time_us`, Microseconds, and sequence field `seq`. Or, for CSV `100000,100,0.3`, select columns `1` and `2`. Leave fields blank for ordinary monitoring. One numeric row still represents one simultaneous sample across all signal channels. See [Signal analysis reference](SIGNAL_ANALYSIS.md) for exact timing diagnostics and limits.

## 4. Monitor

- **Filter:** case-insensitive substring search across formatted retained records, including RX/TX prefixes and displayed timestamps/hex. It does not modify samples or recorded data.
- **Timestamps:** local arrival time to milliseconds. Multiple records from one read batch share a timestamp.
- **Hex:** displays each framed record's bytes in hexadecimal. RX line terminators have already been removed by framing, so this is not a byte-perfect raw-traffic capture. TX records retain their transmitted bytes.
- **Follow:** follows new output. Turn it off to inspect older text without forcing the scroll position to the bottom.
- **Copy:** copies currently displayed, filtered text, including any display truncation. In a frozen view, it copies what is visible.
- **Clear / Ctrl+L:** clears console records only. It does not reset numeric samples, scope captures or byte counters. Incoming records can appear again immediately.
- **Transmit:** type text, choose a line ending, then Send or Enter. Text uses the selected encoding. CRLF is sent in the conventional `\r\n` order. Hex bytes mode accepts pairs such as `41 42 0d 0a`; it ignores the text line-ending selection. Transmit payloads are limited to 65,536 bytes. Failed/queued sends are not misreported as completed TX records; the worker logs successful writes.

Console retention is bounded by both the record limit and a 16 MiB raw-payload budget. Oldest records are evicted. Individual visible lines are capped at 4,096 characters; TXT export retains the complete record. This is retained history, not continuous disk logging.

## 5. Scope

The Scope is a software-triggered view of uniformly sampled values supplied by your device. It does not configure an ADC, set probe attenuation, supply analog bandwidth, or implement a hardware trigger. The source's numeric values and units must already have the desired calibration.

For a first try, use Demo signal, open Scope, leave Auto selected, then press Stop to inspect a capture. Only opening Scope activates its background capture processing; afterwards it can keep capturing while hidden, until Stop is pressed. Explicitly selected device metadata is checked before new captures; discontinuous windows pause capture rather than fabricating a uniform timeline.

### Capture controls

| Control | Operation |
| --- | --- |
| Run / Stop | Run arms the software capture engine; Stop holds its last capture. It does not close the serial port or stop Monitor/Plotter acquisition. Re-arming waits for fresh trigger edges. |
| Single capture | Arms for the next eligible edge and stops after enough post-trigger samples arrive. The existing display remains until replacement. |
| s/div | Requested horizontal timebase across ten divisions. Capture length is timebase × 10 × sample rate, rounded to whole samples. |
| Auto | Uses an edge when available; otherwise refreshes an untriggered capture after roughly 300 ms while data arrives. |
| Normal | Waits for a valid edge and sufficient pre/post-trigger data; retains the last display while waiting. |
| Single | Like Normal, but stops after one completed capture. Press Single capture to re-arm. |
| Source | One of the eight numeric channels; missing values cannot cross a trigger. |
| Rising / Falling | Crosses the configured level upward/downward. Triggering always uses raw DC values, not AC-coupled or vertically scaled display data. |
| Level | Trigger threshold in input units. The dotted horizontal marker shows its position on the source's displayed DC scale. |
| Pre-trigger % | Capture fraction before the trigger sample, from 0 to 90%. More pre-trigger memory requires more history before an edge is eligible. |
| Holdoff (ms) | Minimum sample-index interval after a captured trigger before another trigger may be accepted. Converted using the configured sample rate. |

Capture length is bounded to **32–65,536 samples** and the numeric ring-buffer capacity. When the request is limited or rounded, the status reports the effective s/div. Trigger position is the first sample on the new side of the threshold, not an interpolated hardware timestamp. At high input rates, captures refresh at the configured visual refresh rate and are not a record of every possible trigger. Normal/Auto prefer a recent complete eligible trigger; Single uses the first eligible newly seen edge.

### Vertical controls

Select a **Vertical channel**, then change its **units/div**, **Offset (div)**, **DC/AC**, or **Visible** setting. Visibility is shared with Plotter. Each channel retains its own scale, offset and coupling.

Displayed divisions = `(value - captured mean if AC) / units_per_division + offset`.

- **DC** retains the incoming DC component.
- **AC** subtracts that channel's captured mean in software. It is not a physical high-pass filter and does not change raw data, FFT input, or trigger thresholds.
- **Auto scale** estimates per-channel scales from the current capture and resets offsets. It does not select a new timebase or trigger level.
- **Reset view** restores the held capture's horizontal extent and vertical range of −4 to +4 divisions.
- Drag/scroll to pan/zoom while stopped. Live completed captures restore the capture range. The axis is in displayed divisions because channels can use different scales. Grid spacing follows plot zoom; there is no calibrated physical screen graticule.

### Cursors and measurements

Enable **Cursors** to show two draggable time cursors and two horizontal amplitude cursors. Readouts show absolute Δt, 1/Δt, and absolute ΔV on the selected vertical channel. Horizontal cursors are in displayed divisions; ΔV uses that channel's units/div setting. These are independent cursors, not waveform-snapping probes. Offset/AC mean cancel in a difference. Raw Vpp and RMS of the selected channel's finite captured values are shown below the plot.

Export **Held scope capture · CSV** to save the held sample array, even if the acquisition ring has since overwritten those rows. Time zero is the trigger sample, or the notional pre-trigger position in an Auto untriggered capture. Values are raw input units, before display coupling, scale and offset. PNG export saves the current visible plot with cursors.

## 6. Plotter

All eight channel controls toggle visibility without stopping ingestion. Channel names are incoming labels or Settings overrides. Configure each color and the shared line width/grid in Settings.

- **Visible window (s):** requested recent sample-time span.
- **Live range:** advances the visible window as values arrive. Only the needed sample window is copied for rendering. Disable it to pan through the retained buffer without range resets.
- **Fit Y:** restores automatic vertical scaling.
- **Clear samples:** asks before clearing numeric samples and the held scope capture; it re-arms the scope. Console records remain.
- Mouse drag pans; wheel zooms; pyqtgraph's plot context menu provides range controls.

Time is `sample_index / configured_sample_rate`. A new acquisition/cleared buffer starts at index zero. Ring eviction preserves increasing indices. This is a relative sample timeline, not wall-clock time. Changing sample rate/parser/encoding/capacity clears the numeric buffer with confirmation.

## 7. Spectrum

Start with a channel and **Amplitude FFT** to find repeating frequencies. **Detail (FFT samples)** controls the tradeoff between frequency separation and the amount of data needed. Choose the question/view from the dropdown: Amplitude FFT, Phase, Power density (Welch), Spectrogram, Spectral peaks, or Harmonics & quality. A sentence explains each view. **Fine-tune** reveals window, scale, DC/hold, overlap, fundamental/harmonic count, peak prominence and spectrogram color controls; irrelevant options are disabled.

FFT length (256–16,384) and selected channel are shared with Analysis. A complete most-recent window of finite samples is required; missing values are not interpolated or removed to manufacture continuity. PSD/spectrogram use up to eight FFT lengths of retained data, capped at 65,536 rows; the spectrogram has at most 128 time columns. These tools are windowed views, not an indefinite history recorder. If the buffer is smaller than the FFT length, increase capacity or decrease the FFT length.

- **Hann:** useful default for reducing leakage.
- **Hamming:** different sidelobe/main-lobe tradeoff.
- **Blackman:** greater sidelobe suppression, broader peaks.
- **Rectangular:** no taper; useful for coherent sampling but more leakage otherwise.
- **Remove DC:** subtracts the window mean before the FFT and excludes bin zero from peak-bin selection.
- **Peak hold:** retains maximum amplitude per frequency bin across processed windows. Reset hold clears it; channel, FFT/window/scale/DC changes and new acquisitions also reset it. NaN gaps are not transformed.

Amplitudes are corrected for the window's coherent gain. The single-sided real FFT doubles interior bins, but not DC or an even-length Nyquist bin. A coherent sine of peak amplitude A should read approximately A in Linear view. This is **peak sinusoidal amplitude**, not RMS or power. Off-bin tones have leakage/scalloping. The ordinary peak-bin readout is not interpolated; the separate Spectral peaks table uses a local log-parabolic frequency estimate but retains actual bin amplitudes.

`dB = 20 × log10(amplitude / 1 input unit)`, floored at −240 dB to avoid log(0). This is not dBFS, dBm, PSD, SNR or a calibrated noise measurement. Resolution = sample rate / FFT length. Highest representable frequency = sample rate / 2. Actual useful bandwidth depends on the acquisition hardware and anti-alias filtering.

- **Phase:** Fourier phase in degrees (cosine reference) relative to the start of the latest window. Bins below −80 dB relative amplitude, or absolute amplitude below 1e-12, are hidden. This is not an automatic inter-channel phase measurement.
- **Power density (Welch):** unit²/Hz or `10 log10(PSD / 1 unit²/Hz)`. Overlapping segment averaging reduces variance. With only one full segment there is no multi-segment averaging.
- **Spectrogram:** sample time horizontally, frequency vertically, Welch-style density color scale. Choose viridis/plasma/inferno/grayscale (CET-L1), automatic dB span or fixed colorbar levels. Disable Auto color levels before dragging the colorbar handles if you want a fixed comparison scale. Saved color settings persist.
- **Spectral peaks:** up to 50 strongest local frequency peaks, controlled by dB prominence and an −80 dB relative-amplitude floor. Width is measured at half prominence in dB, not a calibrated bandwidth. CSV export includes interpolated frequency, bin amplitude, relative level, width and bin index.
- **Harmonics & quality:** sinusoidal least-squares model with DC and up to 2–20 requested harmonics below Nyquist. Auto uses the strongest non-DC tone; set the known fundamental if an overtone is stronger. Needs at least four fundamental cycles in the window. THD measures modelled harmonic RMS relative to the fundamental; SNR uses the residual after removing modelled tones/DC; SINAD combines harmonics and residual. Interharmonics, drift, jitter and unmodelled harmonics can count as residual. Do not treat estimates as calibrated instrument specifications.

Uniform-sampling views pause on missing/non-monotonic device timestamps, sequence gaps/duplicates/resets, or interval deviations greater than 5% from the window's median. No resampling is performed. Axes still use the **configured** rate, clearly shown above the view. See Analysis → Data quality to compare/adopt the device estimate. Tables export to CSV/JSON rather than plot PNG.

## 8. Analysis

Measurements and transformations use the latest **FFT-size window** on selected channel A, including shorter startup windows. They do not use the frozen Scope capture. A reference channel B is used only for arithmetic and XY tools. Statistics ignore missing values where mathematically meaningful; timing-dependent estimates are disabled across gaps.

### Measurements

| Measurement | Definition |
| --- | --- |
| Samples | Finite values in the analysis window |
| Mean / DC | Arithmetic mean |
| RMS | Square root of mean square, including DC |
| AC RMS / Standard deviation | Population standard deviation (ddof=0); intentionally the same quantity |
| Minimum / Maximum / Peak to peak | Finite extrema and maximum minus minimum |
| Crest factor | Maximum absolute value divided by total RMS; undefined for a zero signal |
| Above mean (%) | Fraction of samples strictly above the window mean |
| Frequency / Period | Average interval of linearly interpolated, mean-centered rising crossings and its reciprocal; needs at least two crossings |
| Duty above midpoint (%) | Fraction strictly above `(window minimum + maximum) / 2`; a simple window estimate, not a protocol-aware pulse duty counter |
| Rise 10–90% / Fall 90–10% | Median threshold-transition duration using window min/max levels, with linear crossing interpolation; cancelled transitions are rejected |

Noise, ringing, partial cycles, quantization and outliers can strongly affect crossing/duty/rise/fall estimates. These do not implement standard-compliant pulse qualification, hysteresis, or bandwidth correction. Use sufficient samples per edge and inspect the waveform.

### Tools

| Tool | Output |
| --- | --- |
| Histogram | 4–64 bins of finite values; count versus input value |
| Autocorrelation | Mean-removed FFT autocorrelation, normalized at zero lag; up to 2,048 lags; no overlap-count/unbiased correction |
| Moving average | Trailing arithmetic average over 2–512 samples; valid-only output, no edge padding; gaps propagate |
| Derivative | First difference × sample rate; noisy signals are amplified; no additional smoothing |
| Integral | Cumulative trapezoidal integration with initial value zero; restarts at the beginning of each moving analysis window |
| A + B / A − B | Sample-aligned sum/difference in shared input units |
| A × B | Sample-aligned product in squared input units |
| A / B | Sample-aligned dimensionless ratio; zero divisors become gaps |
| XY / phase | Channel B on X, channel A on Y, preserving sample order; useful for qualitative phase/Lissajous inspection, not an automatic calibrated phase readout |
| Rolling statistics | Trailing mean, RMS and population standard deviation over 2–512 samples; no padding; colored curves and exportable columns |
| Low/high/band-pass/band-stop filter | Butterworth SOS forward/backward zero-phase filtering of the current window; lower/upper cutoff and prototype order 1–10; raw data unchanged |
| FFT band reconstruction | Keep bins inside the selected band and inverse-transform them to a time waveform; sharp masks can ring |
| Envelope | Hilbert analytic-signal magnitude after mean removal; edge artifacts possible |
| Peaks | Extract local maxima with minimum prominence and sample separation; timestamp/value/prominence/half-prominence width table |
| Threshold events | Extract above-threshold spans with optional hysteresis; start/end/duration/peak/mean and partial-window flags |
| Acquisition metadata | Open Data quality: configured/device/host rates, jitter, sequence losses/duplicates/resets and missing selected fields |

All channels currently share one configured amplitude unit label and sample rate. Math and transformations are display-only; they do not replace stored samples or create additional transmit channels.

The task explanation and only relevant parameter controls appear when you choose a tool. **Compare with original** overlays the unmodified channel for processing tools. **Extracted rows** shows the first 500 result rows; CSV includes all rows from the completed window. Events are window-local, not a continuous event database. Numerical filters are post-processing, not an analog anti-alias filter or real-time causal firmware filter. A forward/backward filter has squared magnitude response and edge transients. Detailed formulas and recipes are in [Signal analysis reference](SIGNAL_ANALYSIS.md).

### Acquisition metadata

Data quality labels three different quantities: the user-configured rate used for axes, an automatically calculated nominal device rate (only when timestamps were selected), and host accepted numeric rows/s over an arrival window (never used as the sampling clock). Timestamps are scaled from Seconds/Milliseconds/Microseconds. Sequence values must be non-negative exact integers ≤ 2^53−1; no rollover modulus is assumed.

The nominal device interval is the median positive time difference divided by sequence step, if available. RMS interval jitter is measured relative to that median; min/max intervals use the same per-step normalization. Missing sequence counts are positive jumps minus one; duplicate/reset/missing-field counters are session diagnostics. Timestamp resolution must be sufficient: repeated millisecond stamps at a kilohertz or faster rate cannot establish a reliable sampling clock. Host idle throughput becomes zero after one second without arrivals.

**Use measured device sample rate…** explicitly adopts a valid continuous-window estimate for future axes, after confirmation that numeric buffers/captures will clear. This does not reprogram or calibrate the device. The software does not silently replace your rate with an arrival-time guess or continuously rescale held captures.

## 9. Settings and persistence

**Apply & save** validates the form, saves atomically and applies it. Unapplied edits are not silently applied on exit. **Restore defaults** resets the form only; apply it to activate those form settings. **Import** validates a JSON object into the form; **Export settings** saves active preferences, excluding unapplied edits. Import intentionally does not activate port/baud, quick-view settings or geometry from another machine. Unknown fields are ignored; invalid fields fall back to defaults.

### Appearance

| Setting | Range/default |
| --- | --- |
| Theme | Light, Dark (default), AMOLED, Liquid Glass |
| Workspace detail | Monitor (default), Explore, Advanced; changes visibility, not acquisition |
| Plain-language guidance | On by default; discovery and tool explanations can be hidden/restored |
| Summary cards | Off by default to maximize console/plot space; enable independently |
| Accent | Six-digit RGB hex; default `#38bdf8` |
| Interface font size | 8–18 pt; default 10 |
| Compact spacing | Off by default |
| Navigation sidebar | On by default; also Ctrl+B |
| Plot grid | On by default |
| Plot line width | 0.5–5; default 1.5 |

AMOLED uses black workspace/plot backgrounds with near-black controls. Liquid Glass uses light layered surfaces and rounded panels, **not transparency, native acrylic, vibrancy or OS blur**. Custom colors are used as provided; choose contrasting colors, especially on Light/Glass. Native file/color dialogs can follow OS styling rather than the application palette.

### Acquisition

Defaults: 8 data bits, no parity, 1 stop bit, no flow control, UTF-8, Auto parser and comma delimiter. Choices: data bits 5/6/7/8; parity None/Even/Odd/Mark/Space; stop bits 1/1.5/2; flow None/RTS-CTS/XON-XOFF; encoding UTF-8/ASCII/Latin-1. Hardware/driver support varies. Port and baud are set in the connection bar, default baud 115200.

Optional metadata fields: exact JSON/label key or 1-based CSV column for device time and sequence, plus timestamp units. Fields must differ; blank means no extraction. Disconnect before changing framing, encoding, parser, delimiter, metadata mapping or configured sample rate through the form. The separate device-rate adoption action is an explicit axes-only update with buffer reset. Settings do not expose DTR/RTS manual controls; opening a port may reset boards that use those lines for reset. There is no automatic reconnect or automatic connection on startup.

### Signal and performance

| Setting | Range/default | Notes |
| --- | --- | --- |
| Sample rate | 0.01–10,000,000 samples/s; 1000 default | Theoretical configuration range, not a promised device/application throughput |
| Unit label | Text; `units` default | Label only; no calibration or scaling is performed |
| Visual refresh | 5–60 Hz; 20 default | Acquisition polling remains independent; lower for slower machines |
| Analysis updates | 1–20 Hz; 5 default | Limits CPU work independently of visual refresh; one in-flight job per DSP panel |
| Sample buffer | 1,024–1,000,000 rows; 32,768 default | Eight float64 channels use about 64 bytes/row before snapshots and display overhead |
| Console limit | 100–100,000 records; 5,000 default | Also limited by 16 MiB raw payload; line display capped at 4,096 characters |

Changing parser, delimiter, encoding, metadata fields, sample rate or numeric capacity clears the numeric buffer/capture with confirmation. Reducing console retention evicts old history. Rendering is limited to the active page. Scope processing starts on first visiting Scope, and afterwards continues while armed even if hidden/frozen. Heavy spectral/processing tools use bounded background workers; superseded parameter results are discarded. OpenGL and anti-aliasing are off by default for portable predictable rendering; pyqtgraph peak downsampling limits dense-plot work.

### Channels and quick controls

Eight optional display names (40 characters each) and eight RGB colors are stored. Empty names use parsed labels or channel numbers. Visibility is shared between Scope and Plotter.

Also saved on exit: window geometry, port/baud, custom rates, sidebar, timestamps, Follow, Hex, transmit line ending, plot window, spectral view/FFT/window/DC/scale/peak hold/overlap/prominence, fundamental/harmonic count, spectrogram colors/ranges, selected analysis/spectrum channel, analysis tool/reference/smoothing/filter cutoffs/order/peak/event parameters, scope timebase/mode/edge/source/level/pre-trigger/holdoff and each scope channel's scale/offset/coupling. Defaults: overlap 50%, fundamental Auto, 5 harmonics, spectral prominence 10 dB, viridis/80 dB automatic color span, filter edges 10/100 Hz and order 4, peak prominence 0.1/separation 10 samples, event threshold/hysteresis zero. Capture data, running/armed state, cursor positions, console search, transmit text/mode, current page, manual zoom ranges and original-overlay visibility are not saved. Single mode is restored armed when Scope processing is first activated.

### Location and migration

- Windows: `%APPDATA%/SerialMonitor/settings.json`.
- Other systems: `~/.config/SerialMonitor/settings.json`.
- Override: set environment variable `SERIAL_MONITOR_SETTINGS` to an absolute JSON path before launch.
- If the normal location is absent, legacy `./settings.json` is read. Supported legacy theme/accent/custom-baud fields are migrated. Legacy background/foreground overrides and the old Custom theme are replaced by the new theme system. Old files are never deleted. A malformed file falls back to defaults with a status note and can be replaced when preferences are saved.

Preferences are atomically replaced via a temporary file in the same directory. A write failure is reported rather than claiming success. Sessions are local; there is no autosaved measurement project or continuous recording file.

## 10. Export formats

- **Buffered samples CSV:** chronological retained samples, `sample_index`, `sample_time_s`, then known channels. Evicted samples cannot be recovered. NaN is an empty field. Values are raw input values. Export time is relative to the beginning of the current numeric acquisition epoch.
- **Held Scope CSV:** `time_from_trigger_s`, then eight channels. It is the actual held capture, not the live acquisition ring. Raw values are unaffected by display coupling/offset/scale.
- **Monitor TXT:** all retained records, ignoring the search filter, using current timestamp/hex formatting. It is not raw wire bytes; RX framing terminators were removed.
- **Current plot PNG:** Scope, Plotter, Spectrum or Analysis view at the current pan/zoom/cursor range. It does not include surrounding workspace controls.
- **Analysis / spectral result CSV:** the last completed displayed transformation, extraction or spectral table. FFT exports peak amplitude and cosine phase; PSD adds linear unit²/Hz; spectrogram uses time/frequency/density rows. NaN is empty. Harmonic/event tables have explicit column names. Tables are exported as data, not PNG.
- **Device timing CSV:** up to the latest 65,536 accepted numeric rows, with epoch sample index, device timestamp in seconds and sequence. Unselected/missing metadata is empty. This timing history is separately bounded from the numeric ring.
- **Measurement report JSON:** current raw statistics, timing diagnostics/continuity warning, active settings and most recently completed harmonic/processed extraction results. Live result sections may describe earlier windows than the current raw statistics; the report states this. Non-finite values become JSON null. Local device names may be included.
- **Settings JSON:** active configuration. Can contain local serial-device names; review before sharing.

Exports overwrite an existing file only after the save dialog's normal confirmation. CSV/TXT export works on a detached snapshot while acquisition continues. Closing waits for an active export to finish; do not forcibly terminate a file write. No export format promises uninterrupted acquisition to disk. External device/driver losses may be undetectable.

## 11. Shortcuts

| Keys | Action |
| --- | --- |
| Ctrl+1 … Ctrl+6 | Monitor, Scope, Plotter, Spectrum, Analysis, Settings |
| Ctrl+, | Settings |
| Ctrl+B | Toggle sidebar |
| Ctrl+K | Monitor filter |
| Ctrl+L | Clear monitor records |
| Ctrl+E | Export buffered numeric samples |
| F1 | Open this guide |
| Enter in transmit field | Send |
| Space outside editable controls | Freeze/resume visual updates |

## 12. Troubleshooting and measurement limits

**Port missing:** Refresh after plugging in, install the manufacturer's driver, check the cable supports data, and verify device permissions. On Linux, access often requires membership in `dialout` or an equivalent device-access group. Do not run as administrator/root as a routine workaround.

**Port busy:** Disconnect other monitors/IDEs. Use Disconnect here before firmware upload. Opening/closing a serial driver can take time; a new session is not opened while the previous worker still holds the port. Driver failures are reported in the status bar.

**No output:** Check baud/framing/flow settings and line terminators. Binary streams without terminators need protocol-specific firmware/adaptation; Hex is a display/transmit option, not a binary sample decoder.

**Garbled characters:** Check baud, parity and encoding. Hex helps inspect bytes; invalid UTF-8 is replaced in decoded text.

**Text but no samples:** Numeric lines must match the selected parser and use finite values. Remove unit suffixes and quoted CSV fields. Diagnostic strings are deliberately not turned into numbers by extracting arbitrary digits.

**No scope trigger:** Confirm Run/armed state, correct source, a level inside the signal range, a suitable edge, enough pre-trigger history and enough post-trigger samples. Auto mode can display a flat signal without a crossing. Single capture waits for a fresh edge after arming.

**Wrong frequency/time:** Set the actual device sample rate, not baud. One numeric row must represent one uniformly sampled instant across all channels. Host batch timestamps do not measure the device's clock. Serial buffering causes arrival bursts. Software does not detect all device-side dropped samples.

**Aliasing:** Frequencies above half the sample rate fold into the displayed band. Choose appropriate hardware sampling and anti-alias filtering; the application cannot remove already-aliased content.

**Spectrum waiting:** Choose a populated channel, wait for the full FFT length, reduce FFT size, increase capacity, or eliminate missing fields. The FFT does not compress gaps or pad startup samples to imply a valid measurement.

**Filter rejected:** Check that cutoffs are below Nyquist and lower < upper for a band. Low-pass uses only the upper cutoff; high-pass uses only the lower. Butterworth cutoffs must be strictly positive; FFT band reconstruction may include zero. Reduce filter order or collect a longer window if it is too short for forward/backward filtering.

**Timing tools paused:** Check metadata keys/1-based column numbers and units. Duplicates, resets, selected missing fields or >5% interval variation block tools that assume uniform time. There is no hidden timestamp unwrapping or resampling. Inspect/export Data quality and device timing CSV; fix the source clock/protocol rather than assigning the host receive rate as a sample clock.

**Drops or lag:** Reduce the device's text rate/precision, lower refresh to 10–20 Hz, hide unused channels, shorten visible windows/FFT sizes, reduce console retention, or stop scope triggering when not needed. ASCII and JSON formatting consume bandwidth. With 8-N-1 serial framing, a rough upper payload limit is baud/10 bytes/s before other overhead. At 115200 baud, 30 bytes per row allow fewer than roughly 384 rows/s. USB CDC devices may not use the nominal baud in the same way.

Queue overflow or oversized framing causes an acquisition epoch change. The numeric measurement buffer and held capture reset at that boundary to avoid analysing across known missing input. Console history and loss counters remain. This does not detect errors inside the device, driver or custom protocol; for metrology use device timestamps/sequence numbers and a suitable acquisition format/tool.

**Known scope limits:** no hardware trigger, trigger hysteresis, pulse-width/video/protocol triggers, segmented acquisition, calibrated probe compensation, per-channel sample rates/units, logic-bus decoding, mask testing, or guaranteed equivalent-time/real-time capture bandwidth. Rise/fall/frequency tools are basic software estimates. The UI's broad numeric configuration ranges are not hardware capability claims.

**Settings not saved:** Check the indicated path and write permissions. Use `SERIAL_MONITOR_SETTINGS` to select a writable directory. Export preferences before sharing/changing installations.

**Security software warnings:** Verify the source/distributor or build locally; do not blindly whitelist executables or disable protection.
