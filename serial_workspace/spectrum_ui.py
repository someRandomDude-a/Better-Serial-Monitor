"""A guided spectrum workspace: choose a question, then reveal tuning controls."""

import time
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets as W

from .computation import LatestComputation
from .signal_tools import fourier_details, harmonic_report, power_density, spectral_peaks, time_frequency


DESCRIPTIONS = {
    "Amplitude FFT": "Find repeating frequencies. Taller peaks mean stronger sinusoidal components; this is peak amplitude, not power.",
    "Phase": "See the angle of each Fourier component relative to the start of this window. Very weak bins are hidden; absolute phase moves as the window moves.",
    "Power density (Welch)": "Compare how signal power is spread over frequency. Averaging overlapping segments gives a steadier noise-floor view.",
    "Spectrogram": "See frequencies change over time: left to right is time; higher up is higher frequency; brighter colors mean more power.",
    "Spectral peaks": "Extract the strongest frequency peaks. Frequencies are interpolated estimates; amplitudes are measured at FFT bins. Fine-tune controls peak prominence.",
    "Harmonics & quality": "Estimate the fundamental, harmonics, THD, SNR and SINAD using a sinusoidal fit. These are model-based estimates, not calibrated instrument readings.",
}


class SpectrumPanel(W.QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.engine = LatestComputation(self)
        self.engine.ready.connect(self.finished)
        self.last_submit = 0
        self.last_key = None
        self.dirty = True
        self.result = None
        self.peak = None
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = W.QHBoxLayout()
        self.channel = workspace._channel_selector()
        self.channel.setMinimumWidth(140)
        row.addWidget(self.channel)
        self.view = W.QComboBox()
        self.view.addItems(list(DESCRIPTIONS))
        self.view.setCurrentText(workspace.settings.spectrum_view)
        row.addWidget(self.view, 1)
        row.addWidget(W.QLabel("Detail (FFT samples)"))
        self.size = W.QComboBox()
        self.size.addItems([str(n) for n in (256, 512, 1024, 2048, 4096, 8192, 16384)])
        self.size.setCurrentText(str(workspace.settings.fft_size))
        self.size.setToolTip("Larger windows separate nearby frequencies, but need more samples and update more slowly.")
        row.addWidget(self.size)
        self.tune = W.QPushButton("Fine-tune ▾")
        self.tune.setCheckable(True)
        row.addWidget(self.tune)
        layout.addLayout(row)
        timing_row = W.QHBoxLayout()
        self.rate_note = W.QLabel()
        self.rate_note.setObjectName("muted")
        timing_row.addWidget(self.rate_note, 1)
        rate_button = W.QPushButton("Set sample rate…")
        rate_button.clicked.connect(lambda: workspace.open_settings_tab(2))
        timing_row.addWidget(rate_button)
        layout.addLayout(timing_row)
        self.help = W.QLabel()
        self.help.setObjectName("muted")
        self.help.setWordWrap(True)
        layout.addWidget(self.help)

        self.options = W.QWidget()
        options = W.QGridLayout(self.options)
        options.setContentsMargins(0, 0, 0, 0)
        s = workspace.settings
        self.window = W.QComboBox()
        self.window.addItems(["Hann", "Hamming", "Blackman", "Rectangular"])
        self.window.setCurrentText(s.window)
        self.scale = W.QComboBox()
        self.scale.addItems(["dB", "Linear"])
        self.scale.setCurrentText(s.spectrum_scale)
        self.dc = W.QCheckBox("Remove average / DC")
        self.dc.setChecked(s.remove_dc)
        self.hold = W.QCheckBox("Peak hold")
        self.hold.setChecked(s.peak_hold)
        self.overlap = W.QSpinBox()
        self.overlap.setRange(0, 90)
        self.overlap.setValue(s.spectrum_overlap)
        self.overlap.setSuffix(" % overlap")
        self.fundamental = W.QDoubleSpinBox()
        self.fundamental.setRange(0, 5000000)
        self.fundamental.setDecimals(3)
        self.fundamental.setValue(s.fundamental)
        self.fundamental.setSpecialValueText("Auto fundamental")
        self.fundamental.setSuffix(" Hz")
        self.fundamental.setToolTip("Auto chooses the strongest non-DC component. Enter the known fundamental if a harmonic is stronger.")
        self.harmonics = W.QSpinBox()
        self.harmonics.setRange(2, 20)
        self.harmonics.setValue(s.harmonic_count)
        self.harmonics.setSuffix(" harmonics")
        self.prominence = W.QDoubleSpinBox()
        self.prominence.setRange(0, 120)
        self.prominence.setValue(s.spectral_prominence)
        self.prominence.setSuffix(" dB prominence")
        self.colormap = W.QComboBox()
        self.colormap.addItems(["viridis", "plasma", "inferno", "CET-L1"])
        self.colormap.setCurrentText(s.spectrogram_colormap)
        self.dynamic_range = W.QDoubleSpinBox()
        self.dynamic_range.setRange(20, 160)
        self.dynamic_range.setValue(s.spectrogram_range)
        self.dynamic_range.setSuffix(" dB color span")
        self.auto_levels = W.QCheckBox("Auto color levels")
        self.auto_levels.setChecked(s.spectrogram_auto_levels)
        self.auto_levels.setToolTip("Turn off to keep colorbar levels fixed. Drag its handles to compare captures on the same scale.")
        reset = W.QPushButton("Reset hold")
        reset.clicked.connect(self.invalidate)
        for i, widget in enumerate((self.window, self.scale, self.dc, self.hold, self.overlap, self.fundamental, self.harmonics, reset,
                                    self.prominence, self.colormap, self.dynamic_range, self.auto_levels)):
            options.addWidget(widget, i // 4, i % 4)
        layout.addWidget(self.options)
        self.stack = W.QStackedWidget()
        self.plot = workspace._new_plot("Frequency (Hz)", "Amplitude")
        self.curve = self.plot.plot(connect="finite")
        self.hold_curve = self.plot.plot()
        self.image = pg.ImageItem(axisOrder="col-major")
        self.plot.addItem(self.image)
        self.colorbar = pg.ColorBarItem(values=(s.spectrogram_min, s.spectrogram_max), colorMap=pg.colormap.get(s.spectrogram_colormap), interactive=True,
                                       label="dB re 1 unit²/Hz")
        self.colorbar.setImageItem(self.image, insert_in=self.plot.plotItem)
        self.colorbar.hide()
        self.image.hide()
        self.stack.addWidget(self.plot)
        harmonic_page = W.QWidget()
        harmonic_box = W.QVBoxLayout(harmonic_page)
        self.quality = W.QLabel()
        self.quality.setWordWrap(True)
        harmonic_box.addWidget(self.quality)
        self.table = W.QTableWidget(0, 5)
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        harmonic_box.addWidget(self.table)
        self.table_note = W.QLabel()
        self.table_note.setWordWrap(True)
        harmonic_box.addWidget(self.table_note)
        self.stack.addWidget(harmonic_page)
        layout.addWidget(self.stack, 1)
        self.note = W.QLabel("Choose a channel and collect a full window to begin.")
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        layout.addWidget(self.note)
        for widget in (self.view, self.size, self.window, self.scale, self.colormap):
            widget.currentTextChanged.connect(self.invalidate)
        for widget in (self.dc, self.hold, self.auto_levels):
            widget.toggled.connect(self.invalidate)
        for widget in (self.overlap, self.fundamental, self.harmonics, self.prominence, self.dynamic_range):
            widget.valueChanged.connect(self.invalidate)
        self.tune.toggled.connect(self.options.setVisible)
        self.options.hide()
        self.update_help()

    def update_help(self):
        view = self.view.currentText()
        self.help.setText(DESCRIPTIONS[view])
        self.help.setVisible(self.workspace.settings.show_tips)
        self.stack.setCurrentIndex(1 if view in ("Harmonics & quality", "Spectral peaks") else 0)
        for widget in (self.hold,):
            widget.setEnabled(view == "Amplitude FFT")
        self.scale.setEnabled(view in ("Amplitude FFT", "Power density (Welch)"))
        self.overlap.setEnabled(view in ("Power density (Welch)", "Spectrogram"))
        self.fundamental.setEnabled(view == "Harmonics & quality")
        self.harmonics.setEnabled(view == "Harmonics & quality")
        self.prominence.setEnabled(view == "Spectral peaks")
        for widget in (self.colormap, self.dynamic_range, self.auto_levels):
            widget.setEnabled(view == "Spectrogram")
        self.rate_note.setText(f"Timing: {self.workspace.settings.sample_rate:g} samples/s configured. This must match your device, not the serial baud rate.")

    def invalidate(self, *_):
        self.engine.invalidate()
        self.peak = None
        self.result = None
        self.curve.clear()
        self.hold_curve.clear()
        self.image.clear()
        self.table.setRowCount(0)
        self.quality.clear()
        self.dirty = True
        self.last_submit = 0
        self.last_key = None
        self.update_help()
        self.workspace.invalidate_plot()

    def render(self):
        now = time.monotonic()
        key = (self.workspace.buffer.total, self.engine.generation)
        if key == self.last_key:
            return
        if now - self.last_submit < 1 / self.workspace.settings.analysis_hz:
            return
        if self.engine.job is not None:
            return
        size = int(self.size.currentText())
        view = self.view.currentText()
        indices, matrix = self.workspace.buffer.snapshot(min(65536, size * (8 if view in ("Spectrogram", "Power density (Welch)") else 1)))
        values = matrix[:, self.workspace.settings.selected_channel]
        rate = self.workspace.settings.sample_rate
        continuity = self.workspace.timing.continuity_note(len(values))
        if continuity:
            self.last_key = key
            self.finished(None, continuity)
            return
        window, remove_dc = self.window.currentText(), self.dc.isChecked()
        overlap, fundamental, harmonics = self.overlap.value(), self.fundamental.value(), self.harmonics.value()
        prominence = self.prominence.value()
        origin = float(indices[0] / rate) if len(indices) else 0
        context = dict(channel=self.workspace.channel_name(self.workspace.settings.selected_channel),
                       sample_index_first=int(indices[0]) if len(indices) else None,
                       sample_index_last=int(indices[-1]) if len(indices) else None,
                       window=window, fft_size=size, remove_dc=remove_dc, overlap_percent=overlap,
                       fundamental_hz=fundamental, harmonic_count=harmonics, spectral_prominence_db=prominence)

        def calculate():
            if view == "Harmonics & quality":
                rows, metrics = harmonic_report(values, rate, fundamental, harmonics)
                return dict(view=view, rows=rows, metrics=metrics, count=len(values), rate=rate, context=context)
            if view == "Spectrogram":
                f, t, density = time_frequency(values, rate, size, window, overlap, remove_dc)
                return dict(view=view, f=f, t=t+origin, density=density, count=len(values), rate=rate, context=context)
            f, amplitude, phase = fourier_details(values, rate, size, window, remove_dc)
            result = dict(view=view, f=f, amplitude=amplitude, phase=phase, count=len(values), rate=rate, context=context)
            if view == "Spectral peaks":
                result["rows"] = spectral_peaks(f, amplitude, prominence)
            if view == "Power density (Welch)":
                result["f"], result["density"] = power_density(values, rate, size, window, overlap, remove_dc)
            return result

        self.last_submit = now
        self.last_key = key
        self.engine.submit(calculate)

    def finished(self, result, error):
        if self.workspace.frozen:
            self.dirty = True
            return
        if error:
            self.result = None
            self.curve.clear()
            self.hold_curve.clear()
            self.image.clear()
            self.table.setRowCount(0)
            self.quality.clear()
            self.note.setText(error + " Raw Monitor and Plotter remain available.")
            return
        self.result = result
        view = result["view"]
        self.image.setVisible(view == "Spectrogram")
        self.colorbar.setVisible(view == "Spectrogram")
        self.curve.clear()
        self.hold_curve.clear()
        if view in ("Harmonics & quality", "Spectral peaks"):
            headers = ["Harmonic", "Frequency (Hz)", "RMS amplitude", "dBc", "Phase (°, sine)"] if view == "Harmonics & quality" else ["Frequency estimate (Hz)", "Peak bin amplitude", "Relative dB", "Half-prominence width (Hz)", "FFT bin"]
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            self.table.setRowCount(len(result["rows"]))
            for r, row in enumerate(result["rows"]):
                for c, value in enumerate(row):
                    self.table.setItem(r, c, W.QTableWidgetItem(f"{value:.6g}"))
            self.quality.setText("  ·  ".join(f"{k}: {v:.5g}" for k,v in result.get("metrics", {}).items()))
            self.table_note.setText("Residual includes noise, unmodelled tones, drift and jitter. THD excludes harmonics above Nyquist. No full-scale or calibrated power reference is assumed." if view == "Harmonics & quality" else "Up to 50 peaks, strongest first, above −80 dB relative amplitude. Frequency interpolation cannot resolve tones narrower than the FFT resolution; widths are measured in dB at half prominence.")
        elif view == "Spectrogram":
            density = 10*np.log10(np.maximum(result["density"], 1e-24))
            self.image.setImage(density.T, autoLevels=False)
            t, f = result["t"], result["f"]
            dt = t[1]-t[0] if len(t)>1 else int(self.size.currentText())/result["rate"]
            self.image.setRect(QtCore.QRectF(float(t[0]-dt/2), 0, float(dt*len(t)), float(f[-1])))
            self.colorbar.setColorMap(pg.colormap.get(self.colormap.currentText()))
            if self.auto_levels.isChecked():
                maximum = float(density.max())
                self.colorbar.setLevels((maximum-self.dynamic_range.value(), maximum))
            self.plot.setLabel("bottom", "Sample time (s)")
            self.plot.setLabel("left", "Frequency (Hz)")
            self.plot.enableAutoRange()
        else:
            f = result["f"]
            if view == "Phase":
                y, caption = result["phase"], "Phase (degrees, cosine reference)"
            elif view == "Power density (Welch)":
                db = self.scale.currentText() == "dB"
                y = 10*np.log10(np.maximum(result["density"], 1e-24)) if db else result["density"]
                caption = "PSD (dB re 1 unit²/Hz)" if db else "PSD (unit²/Hz)"
            else:
                amplitude = result["amplitude"]
                db = self.scale.currentText() == "dB"
                y = 20*np.log10(np.maximum(amplitude, 1e-12)) if db else amplitude
                caption = "Amplitude (dB re 1 unit)" if db else f"Amplitude ({self.workspace.settings.unit})"
                if self.hold.isChecked():
                    self.peak = amplitude.copy() if self.peak is None else np.maximum(self.peak, amplitude)
                    self.hold_curve.setData(f, 20*np.log10(np.maximum(self.peak, 1e-12)) if db else self.peak)
            self.curve.setData(f, y, connect="finite")
            self.plot.setLabel("bottom", "Frequency (Hz)")
            self.plot.setLabel("left", caption)
        warning = " Device timing not supplied: uniform sampling is assumed." if not self.workspace.settings.timestamp_field else " Device timing checked; axes use the configured rate."
        peak_note = ""
        if "amplitude" in result:
            start = 1 if self.dc.isChecked() else 0
            peak = start + int(np.argmax(result["amplitude"][start:]))
            peak_note = f" Peak bin {result['f'][peak]:.4g} Hz / {result['amplitude'][peak]:.4g} {self.workspace.settings.unit}." if result["amplitude"][peak] > 1e-12 else " No significant varying component in this window."
        self.note.setText(f"{result['count']:,} input rows · {result['rate']:g} samples/s configured · Δf {result['rate']/int(self.size.currentText()):.4g} Hz · Nyquist {result['rate']/2:g} Hz." + peak_note + warning)

    def export_data(self):
        result = self.result
        if not result:
            return None
        if result["view"] == "Harmonics & quality":
            return ["harmonic", "frequency_hz", "rms_amplitude", "relative_dbc", "phase_sine_deg"], result["rows"]
        if result["view"] == "Spectral peaks":
            return ["frequency_estimate_hz", "peak_bin_amplitude", "relative_db", "half_prominence_width_hz", "fft_bin"], result["rows"]
        if result["view"] == "Spectrogram":
            rows = [[float(t), float(f), float(result["density"][i,j])] for j,t in enumerate(result["t"]) for i,f in enumerate(result["f"])]
            return ["sample_time_s", "frequency_hz", "power_density_unit2_per_hz"], rows
        columns = ["frequency_hz", "amplitude_peak", "phase_cosine_deg"]
        arrays = [result["f"], result["amplitude"], result["phase"]]
        if "density" in result:
            columns.append("power_density_unit2_per_hz")
            arrays.append(result["density"])
        return columns, np.column_stack(arrays).tolist()
