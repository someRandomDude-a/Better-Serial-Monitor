"""Oscilloscope controls and capture rendering, separate from the acquisition worker."""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets as W

from .scope import ScopeEngine


class ScopePanel(W.QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.engine = ScopeEngine()
        self.last_total = -1
        self.last_capture = -1
        self.dirty = True
        self.scales = workspace.settings.scope_scales.copy()
        self.offsets = workspace.settings.scope_offsets.copy()
        self.couplings = workspace.settings.scope_couplings.copy()
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        toolbar = W.QHBoxLayout()
        self.run = W.QPushButton("Stop")
        self.run.clicked.connect(self.toggle_run)
        toolbar.addWidget(self.run)
        self.single = W.QPushButton("Single capture")
        self.single.clicked.connect(self.single_capture)
        toolbar.addWidget(self.single)
        toolbar.addWidget(W.QLabel("s/div"))
        self.timebase = W.QComboBox()
        self.timebase.addItems([str(v) for v in (0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005,
                                                0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10)])
        self.timebase.setCurrentText("0.01")
        self.timebase.currentTextChanged.connect(self.configure)
        toolbar.addWidget(self.timebase)
        toolbar.addWidget(W.QLabel("Trigger"))
        self.mode = W.QComboBox()
        self.mode.addItems(["Auto", "Normal", "Single"])
        self.mode.currentTextChanged.connect(self.configure)
        toolbar.addWidget(self.mode)
        self.source = W.QComboBox()
        self.source.addItems([f"CH {i + 1}" for i in range(8)])
        self.source.currentIndexChanged.connect(self.configure)
        toolbar.addWidget(self.source)
        self.edge = W.QComboBox()
        self.edge.addItems(["Rising", "Falling"])
        self.edge.currentTextChanged.connect(self.configure)
        toolbar.addWidget(self.edge)
        self.level = W.QDoubleSpinBox()
        self.level.setRange(-1e9, 1e9)
        self.level.setDecimals(4)
        self.level.setSingleStep(0.1)
        self.level.setPrefix("Level ")
        self.level.valueChanged.connect(self.configure)
        toolbar.addWidget(self.level)
        layout.addLayout(toolbar)

        secondary = W.QHBoxLayout()
        secondary.addWidget(W.QLabel("Pre-trigger %"))
        self.pretrigger = W.QSpinBox()
        self.pretrigger.setRange(0, 90)
        self.pretrigger.setValue(30)
        self.pretrigger.valueChanged.connect(self.configure)
        secondary.addWidget(self.pretrigger)
        secondary.addWidget(W.QLabel("Holdoff (ms)"))
        self.holdoff = W.QDoubleSpinBox()
        self.holdoff.setRange(0, 100000)
        self.holdoff.setValue(0)
        self.holdoff.valueChanged.connect(self.configure)
        secondary.addWidget(self.holdoff)
        secondary.addStretch()
        self.cursor_check = W.QCheckBox("Cursors")
        self.cursor_check.toggled.connect(self.cursors_changed)
        secondary.addWidget(self.cursor_check)
        self.autoscale = W.QPushButton("Auto scale")
        self.autoscale.clicked.connect(self.auto_scale)
        secondary.addWidget(self.autoscale)
        self.reset_view = W.QPushButton("Reset view")
        self.reset_view.clicked.connect(self.reset_range)
        secondary.addWidget(self.reset_view)
        layout.addLayout(secondary)
        self.plot = workspace._new_plot("Time from trigger (s)", "Divisions (per-channel scale / offset)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setYRange(-4, 4, padding=0)
        self.curves = [self.plot.plot(connect="finite") for _ in range(8)]
        self.trigger_line = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen("#e3a442", style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.trigger_line)
        self.trigger_level = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#e3a442", style=QtCore.Qt.PenStyle.DotLine))
        self.plot.addItem(self.trigger_level)
        self.cursors = [pg.InfiniteLine(pos=0, angle=angle, movable=True,
                                       pen=pg.mkPen("#91a4b9", style=QtCore.Qt.PenStyle.DashLine))
                        for angle in (90, 90, 0, 0)]
        for cursor in self.cursors:
            self.plot.addItem(cursor)
            cursor.hide()
            cursor.sigPositionChanged.connect(self.cursor_readout)
        layout.addWidget(self.plot, 1)

        controls = W.QHBoxLayout()
        controls.addWidget(W.QLabel("Vertical channel"))
        self.vertical_channel = W.QComboBox()
        self.vertical_channel.addItems([f"CH {i + 1}" for i in range(8)])
        self.vertical_channel.currentIndexChanged.connect(self.load_vertical)
        controls.addWidget(self.vertical_channel)
        controls.addWidget(W.QLabel("units/div"))
        self.scale = W.QDoubleSpinBox()
        self.scale.setDecimals(6)
        self.scale.setRange(0.000001, 1e9)
        self.scale.setValue(1)
        self.scale.valueChanged.connect(self.save_vertical)
        controls.addWidget(self.scale)
        controls.addWidget(W.QLabel("Offset (div)"))
        self.offset = W.QDoubleSpinBox()
        self.offset.setRange(-1000, 1000)
        self.offset.setSingleStep(0.25)
        self.offset.valueChanged.connect(self.save_vertical)
        controls.addWidget(self.offset)
        self.coupling = W.QComboBox()
        self.coupling.addItems(["DC", "AC"])
        self.coupling.setToolTip("AC subtracts each captured channel's mean in software. Triggering always uses raw DC values.")
        self.coupling.currentTextChanged.connect(self.save_vertical)
        controls.addWidget(self.coupling)
        self.channel_on = W.QCheckBox("Visible")
        self.channel_on.setChecked(True)
        self.channel_on.toggled.connect(self.visibility_changed)
        controls.addWidget(self.channel_on)
        layout.addLayout(controls)
        self.readout = W.QLabel("Cursors off · Drag enabled cursors to measure time and amplitude on the selected vertical channel.")
        self.readout.setObjectName("muted")
        self.readout.setWordWrap(True)
        layout.addWidget(self.readout)
        self.status = W.QLabel("Waiting for samples · Software trigger, not a hardware oscilloscope.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        settings = workspace.settings
        for widget, value in [(self.timebase, settings.scope_timebase), (self.mode, settings.scope_mode),
                              (self.edge, settings.scope_edge)]:
            widget.blockSignals(True)
            widget.setCurrentText(f"{value:g}" if isinstance(value, float) else str(value))
            widget.blockSignals(False)
        for widget, value in [(self.source, settings.scope_source), (self.level, settings.scope_level),
                              (self.pretrigger, settings.scope_pretrigger), (self.holdoff, settings.scope_holdoff)]:
            widget.blockSignals(True)
            if isinstance(widget, W.QComboBox):
                widget.setCurrentIndex(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        self.load_vertical(0)
        self.configure()

    def configure(self, *_):
        settings = self.workspace.settings
        requested = round(float(self.timebase.currentText()) * 10 * settings.sample_rate)
        self.engine.size = min(settings.sample_capacity, 65536, max(32, requested))
        self.engine.pretrigger = self.pretrigger.value() / 100
        self.engine.channel = self.source.currentIndex()
        self.engine.edge = self.edge.currentText()
        self.engine.mode = self.mode.currentText()
        self.engine.level = self.level.value()
        self.engine.holdoff = round(self.holdoff.value() * settings.sample_rate / 1000)
        was_running = self.engine.running
        self.engine.arm()
        self.engine.running = was_running
        self.dirty = True

    def reset(self):
        self.engine.reset()
        self.configure()
        self.last_total = -1
        self.last_capture = -1
        self.run.setText("Stop")
        for curve in self.curves:
            curve.clear()

    def toggle_run(self):
        if self.engine.running:
            self.engine.running = False
        else:
            self.engine.arm()
            # Run waits for fresh samples, rather than retriggering on a held capture.
            self.engine.scanned = self.workspace.buffer.total - 1
        self.run.setText("Stop" if self.engine.running else "Run")
        self.dirty = True

    def single_capture(self):
        self.mode.setCurrentText("Single")
        self.engine.arm()
        self.engine.scanned = self.workspace.buffer.total - 1
        self.run.setText("Stop")
        self.dirty = True

    def process(self):
        if self.workspace.timing.continuity_note(min(self.engine.size, self.workspace.buffer.count)):
            self.dirty = True
            return
        if self.workspace.buffer.total != self.last_total:
            self.last_total = self.workspace.buffer.total
            if self.engine.process(self.workspace.buffer):
                self.dirty = True
                self.run.setText("Stop" if self.engine.running else "Run")

    def load_vertical(self, index):
        for widget in (self.scale, self.offset, self.coupling, self.channel_on):
            widget.blockSignals(True)
        self.scale.setValue(self.scales[index])
        self.offset.setValue(self.offsets[index])
        self.coupling.setCurrentText(self.couplings[index])
        self.channel_on.setChecked(self.workspace.channel_checks[index].isChecked())
        for widget in (self.scale, self.offset, self.coupling, self.channel_on):
            widget.blockSignals(False)
        self.cursor_readout()

    def save_vertical(self, *_):
        index = self.vertical_channel.currentIndex()
        self.scales[index] = self.scale.value()
        self.offsets[index] = self.offset.value()
        self.couplings[index] = self.coupling.currentText()
        self.dirty = True
        self.cursor_readout()

    def visibility_changed(self, checked):
        self.workspace.channel_checks[self.vertical_channel.currentIndex()].setChecked(checked)
        self.dirty = True

    def auto_scale(self):
        capture = self.engine.capture
        if capture is None:
            return
        for i in range(8):
            values = capture.values[:, i]
            finite = values[np.isfinite(values)]
            if len(finite):
                self.scales[i] = max(float(np.ptp(finite)) / 6, abs(float(finite.mean())) / 3, 1e-6)
                self.offsets[i] = 0
        self.load_vertical(self.vertical_channel.currentIndex())
        self.reset_range()
        self.dirty = True

    def reset_range(self):
        capture = self.engine.capture
        if capture is not None:
            x = (capture.indices - capture.trigger_index) / self.workspace.settings.sample_rate
            self.plot.setXRange(float(x[0]), float(x[-1]), padding=0)
        self.plot.setYRange(-4, 4, padding=0)

    def cursors_changed(self, checked):
        for cursor in self.cursors:
            cursor.setVisible(checked)
        if checked:
            x_range = self.plot.viewRange()[0]
            self.cursors[0].setValue(x_range[0] + (x_range[1] - x_range[0]) * 0.35)
            self.cursors[1].setValue(x_range[0] + (x_range[1] - x_range[0]) * 0.65)
            self.cursors[2].setValue(-1)
            self.cursors[3].setValue(1)
        self.cursor_readout()

    def cursor_readout(self, *_):
        if not self.cursor_check.isChecked():
            self.readout.setText("Cursors off · AC coupling removes the captured mean; trigger levels always use raw DC input units.")
            return
        dt = abs(self.cursors[1].value() - self.cursors[0].value())
        index = self.vertical_channel.currentIndex()
        dv = abs(self.cursors[3].value() - self.cursors[2].value()) * self.scales[index]
        hz = f"{1 / dt:.6g} Hz" if dt > 0 else "—"
        self.readout.setText(f"Δt {dt:.6g} s · 1/Δt {hz} · ΔV {dv:.6g} {self.workspace.settings.unit} on {self.workspace.channel_name(index)} · Vertical cursors are in displayed divisions.")

    def render(self):
        capture = self.engine.capture
        if not self.dirty and self.last_capture == self.engine.count:
            return
        self.dirty = False
        timing_warning = self.workspace.timing.continuity_note(min(self.engine.size, self.workspace.buffer.count))
        if timing_warning:
            self.status.setText("Scope waiting for a continuous device-time/sequence window. " + timing_warning)
            return
        fresh = self.last_capture != self.engine.count
        self.last_capture = self.engine.count
        state = "Armed" if self.engine.running else "Stopped"
        rate = self.workspace.settings.sample_rate
        if capture is None:
            self.status.setText(f"{state} · Waiting for {self.engine.size:,} samples and a {self.engine.edge.lower()} edge at {self.engine.level:g} · {rate:g} samples/s configured")
            return
        x = (capture.indices - capture.trigger_index) / rate
        for i, curve in enumerate(self.curves):
            visible = self.workspace.channel_checks[i].isChecked()
            curve.setVisible(visible)
            if visible:
                values = capture.values[:, i].copy()
                finite = values[np.isfinite(values)]
                if self.couplings[i] == "AC" and len(finite):
                    values -= finite.mean()
                curve.setData(x, values / self.scales[i] + self.offsets[i], connect="finite")
        source = self.engine.channel
        self.trigger_level.setValue(self.engine.level / self.scales[source] + self.offsets[source])
        self.trigger_level.setVisible(self.couplings[source] == "DC")
        if fresh:
            self.plot.setXRange(float(x[0]), float(x[-1]), padding=0)
            self.plot.setYRange(-4, 4, padding=0)
        requested = float(self.timebase.currentText())
        effective = len(x) / rate / 10
        limited = f" · Effective {effective:g} s/div (sample count limited)" if not np.isclose(requested, effective) else ""
        values = capture.values[:, self.vertical_channel.currentIndex()]
        finite = values[np.isfinite(values)]
        measure = f" · Vpp {np.ptp(finite):.5g} · RMS {np.sqrt(np.mean(finite ** 2)):.5g} {self.workspace.settings.unit}" if len(finite) else ""
        self.status.setText(f"{state} · {'Triggered' if capture.triggered else 'Auto / untriggered'} · Capture {self.engine.count} · {len(x):,} samples · {rate:g} samples/s{limited}{measure}")
        self.cursor_readout()
