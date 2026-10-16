"""Task-oriented processing controls and exportable extraction results."""

import time
import pyqtgraph as pg
from PySide6 import QtWidgets as W

from .computation import LatestComputation
from .signal_tools import process_signal


EXPLANATIONS = {
    "Histogram": "See which values occur most often. The horizontal axis is your value, not time.",
    "Autocorrelation": "Look for repetition: peaks at nonzero time lags suggest repeating patterns.",
    "Moving average": "Smooth short-term variation by averaging the most recent N samples. Larger N smooths more but blurs fast changes.",
    "Rolling statistics": "Track the local mean, RMS and standard deviation as a trailing window moves along the signal.",
    "Derivative": "Show how quickly the value changes. This amplifies noise; consider smoothing first.",
    "Integral": "Accumulate area under the signal within this window. The integral starts again at zero for each window.",
    "Low-pass filter": "Keep slower changes; suppress frequencies above the upper cutoff. Raw samples stay unchanged.",
    "High-pass filter": "Keep faster changes; suppress frequencies below the lower cutoff, including DC.",
    "Band-pass filter": "Keep a frequency band between the lower and upper cutoffs.",
    "Band-stop filter": "Remove a frequency band between the lower and upper cutoffs.",
    "FFT band reconstruction": "Extract selected Fourier bins, then reconstruct their time waveform with an inverse FFT. Sharp band boundaries can ring.",
    "Envelope": "Follow the strength of an oscillating signal with a Hilbert amplitude envelope.",
    "Peaks": "Extract local high points. Prominence rejects small bumps; separation prevents counting nearby peaks twice. Open Extracted rows for the table.",
    "Threshold events": "Extract periods above a threshold. Hysteresis adds a dead band to reduce noisy retriggering. Partial-window events are flagged.",
    "Acquisition metadata": "Compare configured rate, device-time estimates and host receive throughput. Device timestamps/sequence numbers must be selected explicitly in Settings.",
    "XY / phase": "Compare simultaneous channel values: B on the horizontal axis and A on the vertical axis.",
    "A + B": "Add two sample-aligned channels. Stored data is unchanged.",
    "A - B": "Subtract B from A to compare channels or remove a shared offset.",
    "A * B": "Multiply simultaneous channel values. Output units are squared input units.",
    "A / B": "Divide A by B. Zero denominators become gaps instead of infinities.",
}
ADVANCED_TOOLS = {"Rolling statistics", "Low-pass filter", "High-pass filter", "Band-pass filter",
                  "Band-stop filter", "FFT band reconstruction", "Envelope", "Peaks", "Threshold events"}


def number(value, minimum, maximum, decimals=3):
    widget = W.QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    return widget


class ProcessingControls(W.QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace
        self.engine = LatestComputation(self)
        self.engine.ready.connect(self.finished)
        self.result = None
        self.last_submit = 0
        self.last_key = None
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.help = W.QLabel()
        self.help.setWordWrap(True)
        self.help.setObjectName("muted")
        layout.addWidget(self.help)
        self.options = W.QWidget()
        grid = W.QGridLayout(self.options)
        grid.setContentsMargins(0, 0, 0, 0)
        s = workspace.settings
        self.low = number(s.filter_low, 0, 5000000, 6)
        self.high = number(s.filter_high, 0.000001, 5000000, 6)
        self.order = W.QSpinBox()
        self.order.setRange(1, 10)
        self.order.setValue(s.filter_order)
        self.prominence = number(s.peak_prominence, 0, 1e9)
        self.distance = W.QSpinBox()
        self.distance.setRange(1, 100000)
        self.distance.setValue(s.peak_distance)
        self.threshold = number(s.event_threshold, -1e9, 1e9, 4)
        self.hysteresis = number(s.event_hysteresis, 0, 1e9, 4)
        self.pairs = []
        for i, (caption, widget) in enumerate((("Lower cutoff (Hz)", self.low), ("Upper cutoff (Hz)", self.high),
                                              ("Filter order", self.order), ("Peak prominence", self.prominence),
                                              ("Separation (samples)", self.distance), ("Threshold", self.threshold),
                                              ("Hysteresis width", self.hysteresis))):
            caption_widget = W.QLabel(caption)
            grid.addWidget(caption_widget, i//3, (i%3)*2)
            grid.addWidget(widget, i//3, (i%3)*2+1)
            self.pairs.append((caption_widget, widget))
            widget.valueChanged.connect(self.invalidate)
        self.original = W.QCheckBox("Compare with original")
        self.original.setChecked(True)
        self.original.toggled.connect(self.show_original)
        grid.addWidget(self.original, 2, 2, 1, 3)
        layout.addWidget(self.options)
        self.raw_curve = workspace.analysis_plot.plot(pen=pg.mkPen("#8696aa", width=1), connect="finite")
        self.markers = workspace.analysis_plot.plot(pen=None, symbol="o", symbolSize=7, symbolBrush="#fb923c")
        self.rms_curve = workspace.analysis_plot.plot(pen=pg.mkPen("#34d399", width=1.5), connect="finite")
        self.std_curve = workspace.analysis_plot.plot(pen=pg.mkPen("#a78bfa", width=1.5), connect="finite")

    def tool_changed(self, *_):
        self.invalidate()
        self.workspace.analysis_curve.clear()
        tool = self.workspace.analysis_tool.currentText()
        reference = tool.startswith("A ") or tool == "XY / phase"
        smooth = tool in ("Moving average", "Rolling statistics")
        for widget in (self.workspace.reference_caption, self.workspace.analysis_reference):
            widget.setVisible(reference)
        for widget in (self.workspace.smoothing_caption, self.workspace.smoothing):
            widget.setVisible(smooth)
        self.help.setText(EXPLANATIONS[tool])
        self.help.setVisible(self.workspace.settings.show_tips)
        filters = tool.endswith(" filter") or tool == "FFT band reconstruction"
        shown = [filters and tool != "Low-pass filter", filters and tool != "High-pass filter",
                 tool.endswith(" filter"), tool == "Peaks", tool == "Peaks",
                 tool == "Threshold events", tool == "Threshold events"]
        for (caption, widget), visible in zip(self.pairs, shown):
            caption.setVisible(visible)
            widget.setVisible(visible)
        self.original.setVisible(tool in ADVANCED_TOOLS and tool not in ("Peaks", "Threshold events"))
        self.options.setVisible(any(shown) or tool in ADVANCED_TOOLS)
        self.workspace.analysis_tabs.setCurrentIndex(2 if tool == "Acquisition metadata" else 0)
        self.workspace.analysis_note.setText("Collect numeric samples to begin. Processing never changes the raw receive buffer.")

    def invalidate(self, *_):
        self.engine.invalidate()
        self.result = None
        self.last_submit = 0
        for curve in (self.raw_curve, self.markers, self.rms_curve, self.std_curve):
            curve.clear()
        self.workspace.analysis_rows.setRowCount(0)
        self.last_key = None
        self.workspace.invalidate_plot()

    def show_original(self):
        self.raw_curve.setVisible(self.original.isChecked())

    def render(self, tool, times, values):
        now = time.monotonic()
        key = (self.workspace.buffer.total, self.engine.generation)
        if self.last_key == key:
            return
        if self.engine.job is not None or now - self.last_submit < 1 / self.workspace.settings.analysis_hz:
            return
        warning = self.workspace.timing.continuity_note(len(values))
        if warning:
            self.last_key = key
            self.finished(None, warning)
            return
        self.last_submit = now
        self.last_key = key
        rate = self.workspace.settings.sample_rate
        options = dict(width=self.workspace.smoothing.value(), low=self.low.value(), high=self.high.value(),
                       order=self.order.value(), prominence=self.prominence.value(), distance=self.distance.value(),
                       threshold=self.threshold.value(), hysteresis=self.hysteresis.value())
        channel_name = self.workspace.channel_name(self.workspace.settings.selected_channel)

        def calculate():
            result = process_signal(tool, times, values, rate, **options)
            result.context = dict(tool=tool, channel=channel_name, configured_rate_hz=rate,
                                  first_sample_time_s=float(times[0]), last_sample_time_s=float(times[-1]), parameters=options)
            return result, times, values

        self.engine.submit(calculate)

    def finished(self, bundle, error):
        if self.workspace.frozen:
            return
        if error:
            self.result = None
            self.workspace.analysis_curve.clear()
            self.workspace.analysis_rows.setRowCount(0)
            for curve in (self.raw_curve, self.markers, self.rms_curve, self.std_curve):
                curve.clear()
            self.workspace.analysis_note.setText(error)
            return
        result, times, values = bundle
        self.result = result
        plot = self.workspace.analysis_plot
        self.workspace.analysis_curve.setData(result.x, result.y, connect="finite")
        plot.setLabel("bottom", result.x_label)
        plot.setLabel("left", self.workspace.settings.unit)
        self.raw_curve.setData(times, values, connect="finite")
        self.show_original()
        if result.markers is not None:
            self.markers.setData(*result.markers)
        else:
            self.markers.clear()
        for name, curve in (("RMS", self.rms_curve), ("Standard deviation", self.std_curve)):
            if name in result.extra:
                curve.setData(result.x, result.extra[name], connect="finite")
            else:
                curve.clear()
        table = self.workspace.analysis_rows
        table.setColumnCount(len(result.columns))
        table.setHorizontalHeaderLabels(result.columns)
        table.setRowCount(min(500, len(result.rows)))
        for r, row in enumerate(result.rows[:500]):
            for c, value in enumerate(row):
                table.setItem(r, c, W.QTableWidgetItem(str(value) if isinstance(value, bool) else f"{value:.8g}"))
        self.workspace.analysis_note.setText(result.note + f" Extracted rows: {len(result.rows):,} (first 500 shown; export includes all)." +
                                            (" Colors: blue/accent mean, green RMS, purple standard deviation." if result.extra else ""))
