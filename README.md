# Serial Monitor

A local desktop serial workspace with a text monitor, software oscilloscope, live plots, Fourier analysis, and signal extraction. Built with Qt (PySide6), pyqtgraph, NumPy, SciPy, and pyserial. No accounts, telemetry, or cloud processing.

## Run

Requires **Python 3.10+**, a graphical desktop, and a supported Qt platform. Python 3.11 is the tested development version.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r Requirements.txt
.venv\Scripts\python Serial_Monitor.py
```

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python` instead. On Windows with a differently named Python installation, use its interpreter path to create the environment. No activation is required. Linux may need system Qt/XCB libraries and serial-device permissions.

Select a port, enter a baud rate, and **Connect**, or choose **Demo signal** without hardware. Set your device's actual sample rate in **Settings → Signal & performance** before making timing measurements.

New to signal tools? The default **Monitor** workspace keeps everyday serial controls in focus. Use **What can I do?** for a non-modal learning path or follow **Plot numeric values →**. **Explore** reveals the full navigation; **Advanced** opens tuning controls. You can hide guidance, show summary cards, change spacing/fonts/themes, and return to the simple workspace at any time without losing data.

## Workspace

| View | Features |
| --- | --- |
| Monitor | Case-insensitive filter, arrival timestamps, hex display, follow scrolling, copy, text/hex transmit, LF/CR/CRLF endings, retained-log export |
| Scope | Auto/Normal/Single edge triggers, rising/falling edges, trigger level/source, pre-trigger position, holdoff, run/stop, timebase, per-channel scale/offset, software AC/DC coupling, cursors, raw capture CSV |
| Plotter | Up to eight channels, visibility controls, pan/zoom, live range, configurable time window, colors and names |
| Spectrum | Amplitude/phase FFT, Welch power spectral density, STFT spectrogram, spectral-peak extraction, harmonic table and THD/SNR/SINAD estimates; configurable windows, overlap, color maps/ranges |
| Analysis | Measurements, rolling mean/RMS/deviation, histogram, autocorrelation, derivatives/integrals, channel math/XY, Butterworth filters, inverse-FFT band reconstruction, Hilbert envelope, peak/event extraction |
| Data quality (Analysis tab) | Configured rate versus device-time rate estimate and host throughput; timestamp jitter, sequence gaps, duplicates, resets and missing metadata; explicit rate adoption |
| Settings | **Light, Dark, AMOLED, Liquid Glass**; beginner/exploration detail, guidance/cards, fonts/spacing, navigation, channel colors, framing/parser/metadata fields, sample rate, memory/refresh limits, JSON import/export |

CSV, numeric key/value pairs, and flat JSON objects are supported. For example:

```text
0.125,1.25,-0.5
voltage:0.125,current:1.25
{"voltage":0.125,"current":1.25}
```

Use one consistent channel schema per connection. Each received record needs an LF, CR, or CRLF terminator.

**Measurement limits:** This is a software scope for values supplied by a device, not an analog front end or calibrated hardware oscilloscope. Time is calculated from sample index and the configured sample rate, not USB arrival timestamps. There is no hardware trigger, anti-alias filter, raw binary protocol decoder, or guaranteed lossless continuous recording. Missing input detected by the application resets measurement buffers. Device-side losses cannot be detected without a protocol that exposes them. Liquid Glass is a portable, opaque visual style, not native window blur.

Optional device timestamp/sequence fields are selected explicitly in Settings; they are never guessed from numbers in diagnostic text. Timing violations pause uniform-sampling tools until the selected window is continuous. Filters/reconstruction work on detached windows and do not alter raw records. Harmonic/noise figures are model-dependent estimates, not calibrated instrument specifications.

## Documentation

- [User guide](docs/USER_GUIDE.md): setup, every view/control, scope operation, formats, measurements, settings, shortcuts, export, troubleshooting. Also available with **F1** in the app.
- [Signal analysis reference](docs/SIGNAL_ANALYSIS.md): Fourier/PSD/STFT conventions, filtering, extraction, metadata, limits and reproducible recipes.
- [Architecture and development](docs/DEVELOPMENT.md): threading, buffer limits, testing, performance, packaging, limitations.
- [Arduino synthetic signal example](examples/signal_source/signal_source.ino): two numeric channels at 200 samples/s, 115200 baud.
- [Timestamped Arduino example](examples/timestamped_signal/timestamped_signal.ino): adds device microsecond timestamps and sequence numbers for timing diagnostics.

## Test and build

```powershell
.venv\Scripts\python -m pip install -r Requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m PyInstaller --noconfirm serial_monitor.spec
```

The Windows build is written to `dist/Serial_Monitor.exe`. The spec includes the documentation and disables the console window and UPX. Build separately on each target OS; this is not a cross-compiler. Generated executables are not committed.

Preferences are stored under `%APPDATA%/SerialMonitor/settings.json` on Windows or `~/.config/SerialMonitor/settings.json` otherwise. Set `SERIAL_MONITOR_SETTINGS` for a different location. Legacy `./settings.json` is read if the new location is absent; existing files are not deleted.

If security software flags a downloaded executable, verify its provenance or build from source. Do not disable antivirus protection or blindly whitelist it.
