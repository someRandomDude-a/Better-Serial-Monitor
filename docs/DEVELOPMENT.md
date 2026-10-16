# Architecture and development

## Environment

Python 3.10+ and a Qt-supported desktop are required. Development/tests were run on Windows with Python 3.11. Install runtime dependencies from `Requirements.txt`; `Requirements-dev.txt` additionally installs pytest and PyInstaller. No browser, web server, network service, or database is required.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r Requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python tools/benchmark.py
```

macOS/Linux use `.venv/bin/python`. Qt is selected through PySide6; do not mix PyQt/PySide bindings in the same environment. Dependency ranges specify compatible major releases, not a reproducible lockfile. For a release, capture the tested environment (`python -m pip freeze`) and verify it on the target platform.

## Modules

| File | Responsibility |
| --- | --- |
| `Serial_Monitor.py` | Stable executable entry point |
| `serial_workspace/app.py` | Main Qt window, navigation, view controls, timer-driven queue draining/rendering, preferences, export actions |
| `serial_workspace/scope_ui.py` | Oscilloscope control panel, per-channel vertical display transforms, cursors, held-capture rendering |
| `serial_workspace/scope.py` | UI-independent edge-trigger state machine and detached captures |
| `serial_workspace/transport.py` | Serial/demo worker, bounded input/output queues, counters, input-loss epochs |
| `serial_workspace/stream.py` | Incremental CR/LF framing, strict numeric parsers, preallocated NumPy ring buffer |
| `serial_workspace/analysis.py` | FFT normalization, statistics, pulse timing, smoothing, FFT autocorrelation |
| `serial_workspace/signal_tools.py` | SciPy Welch/STFT, phase, harmonics/noise estimates, Butterworth filtering, inverse-FFT extraction, envelope, rolling/peak/event tools |
| `serial_workspace/spectrum_ui.py` | Guided spectral view selection, progressive tuning, colorbar, harmonic/peak tables |
| `serial_workspace/processing_ui.py` | Task-specific processing controls, comparison overlays, extraction table |
| `serial_workspace/metadata.py` | Explicit device-time/sequence diagnostics and independent host throughput |
| `serial_workspace/computation.py` | Single in-flight DSP job per panel, parameter generations, stale-result rejection |
| `serial_workspace/exporting.py` | Qt thread-pool export jobs operating on detached snapshots |
| `serial_workspace/settings.py` | Dataclass defaults, validation, legacy migration, atomic JSON writes |
| `serial_workspace/themes.py` | Centralized Qt stylesheet and plot palettes |
| `tests/` | Deterministic core, worker loopback/demo, settings, and headless GUI tests |

## Acquisition and threading

```text
serial device / synthetic demo
    → acquisition thread: bounded byte reads, line framing, queued writes
    → bounded queue of packets with arrival timestamp and loss epoch
    → GUI timer: decode, strict parse, bounded log history, ring append
    → software trigger engine: detached held capture
    → active view only: console / scope / plotter / FFT / analysis
    → detached export snapshots → export thread → file
```

There is no widget access in acquisition, DSP or export workers. The GUI owns parsers, timing diagnostics, logs, the sample ring and rendering. `SampleBuffer` is intentionally not a concurrent data structure. Workers receive detached snapshots and primitive parameter/context dictionaries. Export functions do not reference widgets.

The serial worker uses `serial_for_url`, also allowing `loop://` for software tests. Serial reads are capped at 4,096 bytes with a 50 ms timeout. Up to eight queued writes are serviced between reads, each with a 200 ms write timeout, checking stop state between writes. Writes are recorded as TX only after successful completion. A daemon thread and context-managed connection close the device on exit/error. Shutdown normally joins within 750 ms. If a driver is still opening/closing, the session remains held and a new connection is refused until it exits. Faulty drivers can still stall; the application cannot forcibly repair a driver.

The incoming queue holds 256 packets. The outgoing queue holds 128 payloads. Neither blocks the UI waiting for capacity: input overflow is counted and drops new packets; output overflow rejects the new send. Queue size counts packets, not sample rows. Input framing rejects records over 65,536 bytes without allowing an unbounded partial-line allocation. A packet has a wall-clock arrival timestamp, direction, framed byte records and an epoch.

Queue overflow/oversized input advances the stream epoch. On receiving a new epoch, the GUI clears numeric data and the held scope capture before accepting more rows. This prevents intentionally analysing across a **known** input-loss boundary. Framing losses also discard complete neighboring records in that read chunk to avoid joining samples across the discarded oversized line. Console history stays available. This mechanism cannot detect device/USB/driver/protocol losses not exposed to the application. Non-numeric diagnostic lines are not automatically classified as lost numeric rows.

The GUI timer runs at 15 ms intervals and drains packets with an approximately 10 ms per-call budget, checked between packets. A single packet can take longer to parse. Visual refresh is independently limited to 5–60 Hz (default 20). Metrics update roughly twice a second. Only the active plot/console is rendered. Scope processing starts after the first Scope visit, then runs on refresh ticks while armed even if hidden/frozen; Stop disables capture processing. No busy-spin read loop is used.

Spectral/processing jobs are independently limited to 1–20 Hz (default 5). Each panel has a single-thread pool and at most one in-flight job; there is no waiting queue of data snapshots. Completed same-version results are cached. Parameter/source/FFT-length changes invalidate a generation; stale callbacks are ignored. Freeze also invalidates pending jobs without deleting the displayed result. Pool shutdown waits for active finite-window jobs before window destruction. SciPy/NumPy may internally use platform BLAS threads; there is no hard real-time CPU guarantee.

The default Monitor detail hides advanced navigation, guidance is optional, and summary cards are independently optional. Scope/DSP are not needed for ordinary monitoring. Explore/Advanced only change control visibility; no acquisition configuration is silently changed. Task-specific controls and explanations are defined beside their DSP panels; keep new tool descriptions synchronized with `ANALYSIS_TOOLS`.

## Buffer model

The numeric ring contains eight float64 values per row. Missing channels are NaN. A capacity of 32,768 rows uses 2 MiB for the base array; 1,000,000 rows uses about 61 MiB. Snapshots, held captures, plots, indices and Python objects require additional memory. `total` counts accepted rows in the current acquisition epoch and remains monotonic across ring wrap. Clearing/reconnecting/known loss starts a fresh epoch. Snapshots are chronological detached arrays.

The console uses a deque with the configured record cap and a 16 MiB raw-payload budget. Oldest entries are evicted; display pending-work is bounded and replaced by a rebuild when the page is hidden/frozen. Visible console lines are capped at 4,096 characters. Raw retained data is not truncated for TXT export. These are bounds on application data, not a bound on total process RSS; Qt, Python, allocator caches and snapshots have overhead.

Plotter live mode copies only the configured visible sample span; with Live range off it can snapshot the entire retained buffer for panning. pyqtgraph uses peak downsampling and clip-to-view. OpenGL and anti-aliasing are disabled at normal startup to avoid assuming GPU/driver support. FFT/statistical/processing windows are at most 16,384 rows; Welch/STFT use up to eight FFT lengths capped at 65,536 rows. STFT is capped at 128 time columns, increasing hop when necessary. Scope snapshots at most three capture lengths (or 4,096 rows for short captures), bounded by ring capacity; a held scope capture is capped at 65,536 rows. Device metadata deques separately retain 65,536 rows; summary calculations use 8,192, continuity checks the relevant recent window. Extraction tables show 500 rows, while result exports retain the full completed window.

CSV/TXT exports work on a detached snapshot in a single-thread export pool. Only one export may be active, avoiding unbounded queued snapshots. PNG rendering stays on the GUI thread because it renders Qt graphics items. Large snapshots, log formatting, image export, or dense full-buffer plots can still cause brief UI stalls; no hard real-time latency or throughput guarantee is made.

## Trigger engine

`ScopeEngine.process(buffer)` searches newly observed sample indices for a source crossing. It requires enough retained pre-trigger history, then holds a pending trigger until post-trigger data is available. If the pending pre-trigger span is overwritten, it is invalidated. NaNs never cross a trigger. Trigger position is integer-sample aligned; holdoff is expressed as sample count. Continuous modes can skip intermediate triggers in favor of a recent complete capture, while Single retains the first eligible edge and stops after capture.

Normal mode never free-runs. Auto can free-run after 300 ms as new rows are processed. Single capture can be armed independently of serial acquisition. The capture stores all eight raw channels and original sample indices. Vertical scaling/AC mean removal are purely display operations and do not modify capture or ring data. AC coupling does not affect DC trigger detection. Scope controls are not a substitute for analog hardware acquisition features.

## Measurement conventions

- Time = sample index / user-configured sample rate. Baud is not sample rate; arrival time is not acquisition time.
- FFT = `rfft(window * (signal - optional mean))`, scaled by `2/sum(window)` with DC/even-N Nyquist not doubled.
- dB references an amplitude of one input unit, not full scale, power, or noise density.
- Frequency uses mean-centered interpolated rising crossings; pulse rise/fall use window-min/max 10%/90% thresholds and median valid transition durations.
- Statistics use finite values where meaningful; continuity-dependent tools do not silently compress gaps.
- Correlation uses zero-padded FFT multiplication, normalized at zero lag, with no overlap-count correction.
- Integral is moving-window trapezoidal integration, not persistent accumulated charge/energy. Division by zero creates NaN gaps.
- Phase is cosine-referenced for the complex rFFT, with weak bins masked; harmonic-fit phase is sine-referenced.
- Welch/STFT density uses SciPy periodic windows, per-segment detrending when enabled, and unit²/Hz. This differs from amplitude FFT's symmetric-window coherent-gain normalization.
- Butterworth filters use SOS forward/backward window filtering, not persistent causal state; reconstruction masks rFFT bins and uses length-preserving irFFT.
- Harmonic/noise figures are stationary sinusoidal-model estimates; residual includes unmodelled content. No calibration or standard-compliance claim is made.
- Timestamp/sequence mapping is explicit. Host monotonic batch arrivals measure throughput only. Device estimates do not alter configured rate unless explicitly adopted.
- Selected missing/duplicate/reset/skipped metadata or >5% timestamp interval deviation blocks uniform-sampling tools, without hidden resampling. Raw serial data remains available.

See the user guide for formulas and caveats. Do not relabel these as calibrated measurements without adding and testing a calibration/acquisition model.

## Preferences

`Settings.from_dict` whitelists keys and choices, bounds numeric fields, requires finite values, validates RGB hex colors and eight-channel arrays, and ignores unknown keys. The settings form covers appearance, serial/parser/performance settings and channel names/colors. Quick-view controls are persisted separately at exit. Import intentionally populates the settings form only, avoiding silently connecting to a machine-specific port or restoring remote geometry.

`Settings.save` writes a temporary file in the destination directory and uses `os.replace` for atomic replacement. A failure is surfaced to the UI. Existing malformed preferences are not deleted during load. Legacy cwd settings are read only if the new per-user path is absent. Unit labels are descriptive only; no sample calibration is implied.

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

Tests include framing/parsers/ring wrap; synthetic FFT/phase/PSD/STFT and harmonic ratios; filter pass/stop behavior; odd/even inverse reconstruction; rolling/peak/hysteretic event extraction; explicit metadata mapping, host-vs-device rates, jitter/discontinuity checks; trigger history/holdoff; migration/validation; software serial loopback/demo; beginner navigation/customization; all GUI spectral/processing views; generation-invalidated worker results; cursors and background exports. Physical calibration is not tested.

GUI tests set `QT_QPA_PLATFORM=offscreen` before importing Qt and use isolated temporary preferences. They test widget construction/data paths, **not pixel-perfect appearance**. On Windows the offscreen Qt plugin can have an empty system-font database; native-platform visual inspection is still necessary. Run the app normally to inspect fonts, focus, contrast, DPI scaling, native dialogs and minimum window sizes. Tests do not validate physical serial hardware, platform-specific drivers, an ADC's timing, electrical safety, or calibration.

Suggested manual checks:

1. Launch without preferences; verify no auto-connect and clear startup instructions.
2. Demo, Monitor filter/hex, each navigation shortcut, all themes and compact spacing.
3. Scope Auto, Normal with an unreachable level, Single, holdoff, pre-trigger, Stop/Run, vertical coupling and cursors.
4. Spectrum: peak near 50 Hz and a smaller peak near 120 Hz at 1 ksample/s; window/FFT/DC/hold changes.
5. Settings save/restart; each export format; close during a pending export.
6. Physical device: framing, sends/endings, upload after Disconnect, unplug errors, OS permissions and baud mismatch.
7. Long/high-rate sessions: monitor memory, loss counters, responsiveness and loss-epoch buffer reset.

## Benchmark

`tools/benchmark.py` reports local parsing/ring/FFT timings on deterministic synthetic inputs. It does not open a port or render a GUI and is **not** a serial-bandwidth or sustained application-throughput claim. Include Python/NumPy/platform details when comparing runs. Profile real workloads and choose memory/refresh limits appropriately.

## Packaging

```powershell
.venv\Scripts\python -m pip install -r Requirements-dev.txt
.venv\Scripts\python -m PyInstaller --noconfirm serial_monitor.spec
```

The spec builds a one-file windowed executable, includes `docs/` and `README.md`, and explicitly includes pyserial's software-loop URL handler. Qt/NumPy/SciPy/pyqtgraph hooks collect runtime dependencies and color maps. UPX is disabled; a smaller download is not worth requiring a separate compressor or increasing avoidable false-positive risk. Build on the target OS/architecture. Native dependencies and package size remain substantially larger than the former Tk-only monitor.

Test the built executable from a different working directory: navigate every page, start/stop demo, open F1 (bundled Markdown), export data, save settings, close and relaunch. One-file startup extracts dependencies to a temporary directory and may be slower than running from source. For signing/distribution, use an appropriate code-signing process and publish build provenance/checksums; the repository does not contain a signing identity. Never instruct users to disable security software to run an unsigned executable.

## Extending safely

Keep protocol/analysis logic independent of Qt where possible. Preserve strict parsing rather than extracting arbitrary digits from diagnostic strings. Add tests before expanding channel schemas, binary framing, calibration, trigger types or continuous recording. Avoid unbounded queues, full console replacement on every packet, worker-thread widget calls, and replacing device timing with host arrival timing. A future recorder needs explicit backpressure/loss semantics and disk-error handling; an Export button is not a lossless recorder.
