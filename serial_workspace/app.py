"""Qt workspace. Acquisition runs in a worker; all rendering stays on the GUI thread."""

from collections import deque
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import time

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6 import QtCore, QtGui, QtWidgets as W
from serial.tools import list_ports

from .analysis import autocorrelation, moving_average, statistics
from .exporting import ExportJob, write_log, write_report, write_samples, write_spectral, write_table
from .metadata import TimingTracker
from .processing_ui import ADVANCED_TOOLS, ProcessingControls
from .settings import ANALYSIS_TOOLS, Settings, THEMES, settings_path
from .scope_ui import ScopePanel
from .spectrum_ui import SpectrumPanel
from .stream import NumericParser, SampleBuffer
from .themes import PALETTES, stylesheet
from .transport import Acquisition


BAUD_RATES = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200,
              230400, 250000, 460800, 500000, 921600, 1000000, 2000000]
PAGES = [
    ("Monitor", "Receive, filter, and transmit serial records."),
    ("Scope", "Triggered captures · timebase, vertical scales, and measurement cursors."),
    ("Plotter", "Time-domain values · drag to pan, scroll to zoom."),
    ("Spectrum", "Single-sided FFT · frequency and amplitude in input units."),
    ("Analysis", "Windowed measurements and signal transformations."),
    ("Settings", "Appearance, acquisition, channels, and performance."),
]


def label(text, name=None):
    widget = W.QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = W.QPushButton(text.replace("&", "&&"))
    widget.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(lambda checked=False: callback())
    if primary:
        widget.setObjectName("primary")
    return widget


def combo(values, current=None):
    widget = W.QComboBox()
    widget.addItems([str(value) for value in values])
    if current is not None:
        widget.setCurrentText(str(current))
    return widget


def card():
    frame = W.QFrame()
    frame.setObjectName("card")
    layout = W.QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    return frame, layout


class SerialMonitor(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings, warning = Settings.load()
        self.session = None
        self.buffer = SampleBuffer(self.settings.sample_capacity)
        self.parser = NumericParser.from_settings(self.settings)
        self.timing = TimingTracker(bool(self.settings.timestamp_field), bool(self.settings.sequence_field))
        self.last_analysis = 0
        self.scope_started = False
        self.logs = deque(maxlen=self.settings.max_lines)
        self.log_bytes = 0
        self.pending_logs = []
        self.log_dirty = True
        self.frozen = False
        self.last_data_version = -1
        self.last_render = 0.0
        self.last_status = 0.0
        self.last_rx = 0
        self.last_rx_time = time.monotonic()
        self.rx_rate = 0.0
        self.rx_bytes = self.tx_bytes = self.dropped = self.oversized = 0
        self.non_numeric = 0
        self.rx_epoch = 0
        self.peak = None
        self.peak_key = None
        self.reported_error = False
        self.controls = {}
        self.color_buttons = []
        self.export_jobs = set()
        self.export_pool = QtCore.QThreadPool(self)
        self.export_pool.setMaxThreadCount(1)
        self.setWindowTitle("Serial Monitor")
        self.resize(1320, 880)
        self.setMinimumSize(1000, 700)
        self._build()
        self._shortcuts()
        self.apply_theme()
        self.refresh_ports()
        if self.settings.geometry:
            self.restoreGeometry(QtCore.QByteArray.fromBase64(self.settings.geometry.encode("ascii", errors="ignore")))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(15)
        self.statusBar().showMessage(warning or "Ready · Select a port or start the demo. No connection is opened automatically.")

    def _build(self):
        root = W.QWidget()
        root.setObjectName("workspace")
        self.setCentralWidget(root)
        outer = W.QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = W.QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(184)
        nav = W.QVBoxLayout(self.sidebar)
        nav.setContentsMargins(14, 26, 14, 18)
        nav.addWidget(label("SERIAL / WORKSPACE", "eyebrow"))
        nav.addSpacing(24)
        self.nav_buttons = []
        for i, (title, _) in enumerate(PAGES):
            item = button(f"0{i + 1}    {title}", lambda checked=False, page=i: self.navigate(page))
            item.setObjectName("nav")
            item.setCheckable(True)
            nav.addWidget(item)
            self.nav_buttons.append(item)
        nav.addStretch()
        nav.addWidget(label("LOCAL ACQUISITION", "eyebrow"))
        note = label("Data stays on this device.\nNo telemetry or account.", "muted")
        note.setWordWrap(True)
        nav.addWidget(note)
        nav.addSpacing(14)
        nav.addWidget(button("User guide    F1", self.show_guide))
        outer.addWidget(self.sidebar)

        body = W.QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(16)
        outer.addLayout(body, 1)
        top = W.QFrame()
        top.setObjectName("topbar")
        bar = W.QHBoxLayout(top)
        bar.setContentsMargins(12, 10, 12, 10)
        self.menu_button = button("☰", self.toggle_sidebar)
        self.menu_button.setToolTip("Show or hide navigation (Ctrl+B)")
        bar.addWidget(self.menu_button)
        bar.addWidget(label("PORT", "eyebrow"))
        self.port = W.QComboBox()
        self.port.setEditable(True)
        self.port.setMinimumWidth(120)
        self.port.setToolTip("Serial device name or URL (for example loop://)")
        bar.addWidget(self.port, 1)
        self.refresh_button = button("Refresh", self.refresh_ports)
        bar.addWidget(self.refresh_button)
        bar.addWidget(label("BAUD", "eyebrow"))
        self.baud = combo(sorted(set(BAUD_RATES + self.settings.custom_baud_rates + [self.settings.baud_rate])), self.settings.baud_rate)
        self.baud.setEditable(True)
        self.baud.setFixedWidth(120)
        bar.addWidget(self.baud)
        self.connect_button = button("Connect", self.toggle_connection, True)
        bar.addWidget(self.connect_button)
        self.demo_button = button("Demo signal", self.start_demo)
        bar.addWidget(self.demo_button)
        body.addWidget(top)

        heading = W.QHBoxLayout()
        titles = W.QVBoxLayout()
        titles.setSpacing(4)
        self.title = label("Monitor", "title")
        self.subtitle = label(PAGES[0][1], "muted")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        heading.addLayout(titles, 1)
        self.freeze_button = button("Freeze view", self.toggle_freeze)
        self.freeze_button.setToolTip("Freeze visual updates; acquisition and buffer retention continue (Space outside text fields).")
        heading.addWidget(self.freeze_button)
        self.experience = combo(["Monitor", "Explore", "Advanced"], self.settings.experience)
        self.experience.setToolTip("Monitor keeps everyday serial controls in focus. Explore reveals analysis views; Advanced opens fine-tuning controls. No data or device settings are changed.")
        self.experience.currentTextChanged.connect(self.set_experience)
        heading.addWidget(self.experience)
        export = button("Export ▾", self.export_menu)
        heading.addWidget(export)
        body.addLayout(heading)

        metrics = W.QHBoxLayout()
        self.metrics_frame = W.QWidget()
        self.metrics_frame.setLayout(metrics)
        metrics.setSpacing(12)
        self.metric_labels = []
        for title, initial in [("CONNECTION", "Offline"), ("RECEIVE RATE", "0 B/s"),
                               ("SAMPLES IN BUFFER", "0"), ("DROPPED RECORDS", "0")]:
            frame, layout = card()
            layout.addWidget(label(title, "eyebrow"))
            value = label(initial, "metric")
            layout.addWidget(value)
            self.metric_labels.append(value)
            metrics.addWidget(frame, 1)
        body.addWidget(self.metrics_frame)
        self.pages = W.QStackedWidget()
        body.addWidget(self.pages, 1)
        self._monitor_page()
        self._plotter_page()
        self._spectrum_page()
        self._analysis_page()
        self.scope = ScopePanel(self)
        self.pages.insertWidget(1, self.scope)
        self._settings_page()
        self.navigate(0)
        self.set_experience(self.settings.experience)

    def _monitor_page(self):
        page, layout = card()
        self.discovery = W.QFrame()
        self.discovery.setObjectName("card")
        discover = W.QVBoxLayout(self.discovery)
        self.discovery_text = label("Start here: choose a port and Connect to read messages, or try Demo signal. You do not need to configure signal analysis to use the monitor.", "muted")
        self.discovery_text.setWordWrap(True)
        discover.addWidget(self.discovery_text)
        next_steps = W.QHBoxLayout()
        next_steps.addWidget(button("Plot numeric values →", lambda: self.discover(2)))
        next_steps.addWidget(button("Find repeating frequencies →", lambda: self.discover(3)))
        next_steps.addWidget(button("What can I do?", self.show_learning_path))
        dismiss = button("Hide tips", self.hide_tips)
        next_steps.addWidget(dismiss)
        discover.addLayout(next_steps)
        layout.addWidget(self.discovery)
        toolbar = W.QHBoxLayout()
        self.search = W.QLineEdit()
        self.search.setPlaceholderText("Filter records…  Ctrl+K")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.invalidate_log)
        toolbar.addWidget(self.search, 1)
        self.timestamp_check = W.QCheckBox("Timestamps")
        self.timestamp_check.setChecked(self.settings.timestamps)
        self.timestamp_check.toggled.connect(self.invalidate_log)
        toolbar.addWidget(self.timestamp_check)
        self.hex_check = W.QCheckBox("Hex")
        self.hex_check.setChecked(self.settings.hex_display)
        self.hex_check.toggled.connect(self.invalidate_log)
        toolbar.addWidget(self.hex_check)
        self.scroll_check = W.QCheckBox("Follow")
        self.scroll_check.setChecked(self.settings.autoscroll)
        toolbar.addWidget(self.scroll_check)
        toolbar.addWidget(button("Copy", self.copy_log))
        toolbar.addWidget(button("Clear", self.clear_log))
        layout.addLayout(toolbar)
        self.console = W.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(W.QPlainTextEdit.LineWrapMode.NoWrap)
        self.console.setPlaceholderText("Received records appear here.\n\nNumeric records are also available in Plotter, Spectrum, and Analysis.\nStart Demo signal to explore the tools without a device.")
        self.console.document().setMaximumBlockCount(self.settings.max_lines)
        layout.addWidget(self.console, 1)
        send = W.QHBoxLayout()
        self.input = W.QLineEdit()
        self.input.setPlaceholderText("Transmit UTF-8 text or hex bytes…")
        self.input.returnPressed.connect(self.send)
        send.addWidget(self.input, 1)
        self.send_mode = combo(["Text", "Hex bytes"])
        send.addWidget(self.send_mode)
        self.ending = combo(["None", "LF", "CR", "CRLF"], self.settings.line_ending)
        self.ending.setToolTip("Appended to text transmissions only. CRLF sends carriage return, then newline.")
        send.addWidget(self.ending)
        self.send_button = button("Send ↵", self.send, True)
        send.addWidget(self.send_button)
        layout.addLayout(send)
        layout.addWidget(label("RX / TX records · Filters affect the view only. Acquisition continues when the view is frozen.", "muted"))
        self.pages.addWidget(page)

    def _new_plot(self, x_label, y_label):
        plot = pg.PlotWidget()
        plot.setMinimumHeight(200)
        plot.setLabel("bottom", x_label)
        plot.setLabel("left", y_label)
        plot.showGrid(x=True, y=True, alpha=0.16)
        plot.getPlotItem().setClipToView(True)
        plot.getPlotItem().setDownsampling(auto=True, mode="peak")
        plot.getPlotItem().getViewBox().setDefaultPadding(0.03)
        return plot

    def _plotter_page(self):
        page, layout = card()
        toolbar = W.QHBoxLayout()
        toolbar.addWidget(label("TIME DOMAIN", "eyebrow"))
        toolbar.addStretch()
        toolbar.addWidget(label("Visible window (s)", "muted"))
        self.time_window = W.QDoubleSpinBox()
        self.time_window.setRange(0.01, 3600)
        self.time_window.setDecimals(2)
        self.time_window.setValue(self.settings.plot_window)
        self.time_window.valueChanged.connect(self.invalidate_plot)
        toolbar.addWidget(self.time_window)
        self.follow_plot = W.QCheckBox("Live range")
        self.follow_plot.setChecked(True)
        self.follow_plot.setToolTip("Turn off to retain your pan/zoom range while new values arrive.")
        self.follow_plot.toggled.connect(self.invalidate_plot)
        toolbar.addWidget(self.follow_plot)
        toolbar.addWidget(button("Fit Y", lambda: self.time_plot.enableAutoRange(axis="y")))
        toolbar.addWidget(button("Clear samples", self.clear_samples))
        layout.addLayout(toolbar)
        self.time_plot = self._new_plot("Sample time (s)", self.settings.unit)
        self.time_curves = [self.time_plot.plot(connect="finite") for _ in range(8)]
        layout.addWidget(self.time_plot, 1)
        channels = W.QGridLayout()
        self.channel_checks = []
        for i in range(8):
            check = W.QCheckBox(f"CH {i + 1}")
            check.setChecked(self.settings.channel_visible[i])
            check.toggled.connect(self.invalidate_plot)
            channels.addWidget(check, i // 4, i % 4)
            self.channel_checks.append(check)
        layout.addLayout(channels)
        self.plot_note = label("Waiting for numeric records · Up to 8 channels. Sample time uses the configured sample rate.", "muted")
        self.plot_note.setWordWrap(True)
        layout.addWidget(self.plot_note)
        self.pages.addWidget(page)

    def _channel_selector(self):
        widget = combo([f"CH {i + 1}" for i in range(8)])
        widget.setCurrentIndex(self.settings.selected_channel)
        widget.currentIndexChanged.connect(self.channel_changed)
        return widget

    def _spectrum_page(self):
        page, layout = card()
        self.spectral = SpectrumPanel(self)
        self.spectrum_channel = self.spectral.channel
        self.fft_size = self.spectral.size
        self.window = self.spectral.window
        self.db_scale = self.spectral.scale
        self.dc_check = self.spectral.dc
        self.hold_check = self.spectral.hold
        self.spectrum_plot = self.spectral.plot
        self.spectrum_curve = self.spectral.curve
        self.hold_curve = self.spectral.hold_curve
        self.spectrum_note = self.spectral.note
        layout.addWidget(self.spectral)
        self.pages.addWidget(page)

    def _analysis_page(self):
        page, layout = card()
        toolbar = W.QHBoxLayout()
        self.analysis_channel = self._channel_selector()
        self.analysis_channel.setMinimumWidth(120)
        toolbar.addWidget(label("Channel A", "muted"))
        toolbar.addWidget(self.analysis_channel)
        self.analysis_tool = combo(ANALYSIS_TOOLS)
        self.analysis_tool.setCurrentText(self.settings.analysis_tool)
        self.analysis_tool.currentTextChanged.connect(self.invalidate_processing)
        toolbar.addWidget(self.analysis_tool)
        self.reference_caption = label("Channel B", "muted")
        toolbar.addWidget(self.reference_caption)
        self.analysis_reference = combo([f"CH {i + 1}" for i in range(8)])
        self.analysis_reference.setCurrentIndex(self.settings.analysis_reference)
        self.analysis_reference.currentIndexChanged.connect(self.invalidate_plot)
        toolbar.addWidget(self.analysis_reference)
        self.smoothing_caption = label("Smoothing samples", "muted")
        toolbar.addWidget(self.smoothing_caption)
        self.smoothing = W.QSpinBox()
        self.smoothing.setRange(2, 512)
        self.smoothing.setValue(self.settings.smoothing)
        self.smoothing.valueChanged.connect(self.invalidate_processing)
        toolbar.addWidget(self.smoothing)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        split = W.QSplitter()
        self.stats = W.QTableWidget(13, 2)
        self.stats.setHorizontalHeaderLabels(["Raw channel A", "Value"])
        self.stats.setToolTip("Measurements of the original selected channel, before filtering or other display processing.")
        self.stats.verticalHeader().hide()
        self.stats.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.stats.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats.setMinimumWidth(290)
        split.addWidget(self.stats)
        self.analysis_plot = self._new_plot("Value", "Count")
        self.analysis_curve = self.analysis_plot.plot(connect="finite")
        self.analysis_tabs = W.QTabWidget()
        self.analysis_tabs.addTab(self.analysis_plot, "Result plot")
        self.analysis_rows = W.QTableWidget(0, 0)
        self.analysis_rows.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.analysis_rows.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.ResizeToContents)
        self.analysis_tabs.addTab(self.analysis_rows, "Extracted rows")
        quality_page = W.QWidget()
        quality_layout = W.QVBoxLayout(quality_page)
        quality_note = label("Device rate needs explicit timestamp fields. Host rows/s measures throughput, not the sampling clock. Configure metadata fields in Settings → Acquisition.", "muted")
        quality_note.setWordWrap(True)
        quality_layout.addWidget(quality_note)
        self.metadata_table = W.QTableWidget(0, 2)
        self.metadata_table.setHorizontalHeaderLabels(["Metadata", "Value"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.metadata_table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        quality_layout.addWidget(self.metadata_table)
        quality_layout.addWidget(button("Use measured device sample rate…", self.adopt_sample_rate))
        quality_layout.addWidget(button("Set timestamp / sequence fields…", lambda: self.open_settings_tab(1)))
        self.analysis_tabs.addTab(quality_page, "Data quality")
        split.addWidget(self.analysis_tabs)
        split.setSizes([330, 650])
        layout.addWidget(split, 1)
        self.processing = ProcessingControls(self)
        layout.insertWidget(1, self.processing)
        self.analysis_note = label("Measurements use the most recent FFT-size window. No samples yet.", "muted")
        self.analysis_note.setWordWrap(True)
        layout.addWidget(self.analysis_note)
        self.pages.addWidget(page)
        self.processing.tool_changed()
        self.fft_size.currentTextChanged.connect(self.invalidate_processing)

    def _settings_page(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tabs = W.QTabWidget()
        self.settings_tabs = tabs
        layout.addWidget(tabs, 1)
        self._settings_form(tabs, "Appearance", [
            ("experience", "Workspace detail", ["Monitor", "Explore", "Advanced"]),
            ("show_tips", "Plain-language guidance", bool), ("show_metrics", "Summary cards", bool),
            ("theme", "Theme", THEMES), ("accent", "Accent color", "color"),
            ("font_size", "Interface font size", (8, 18)), ("compact", "Compact spacing", bool),
            ("sidebar", "Show navigation sidebar", bool), ("grid", "Plot grid", bool),
            ("line_width", "Plot line width", (0.5, 5.0)),
        ], "Liquid Glass uses soft, opaque layered surfaces. It does not enable native blur or window transparency.")
        self._settings_form(tabs, "Acquisition", [
            ("data_bits", "Data bits", [5, 6, 7, 8]), ("parity", "Parity", ["None", "Even", "Odd", "Mark", "Space"]),
            ("stop_bits", "Stop bits", [1.0, 1.5, 2.0]), ("flow_control", "Flow control", ["None", "RTS/CTS", "XON/XOFF"]),
            ("encoding", "Text encoding", ["utf-8", "ascii", "latin-1"]),
            ("parser", "Numeric parser", ["Auto", "CSV", "Labels", "JSON"]),
            ("delimiter", "CSV delimiter (one character)", str),
            ("timestamp_field", "Device time: key or CSV column", str),
            ("timestamp_unit", "Device timestamp unit", ["Seconds", "Milliseconds", "Microseconds"]),
            ("sequence_field", "Sequence: key or CSV column", str),
        ], "Disconnect before changing these fields. Optional metadata: use a JSON/label key (e.g. time_us) or a 1-based CSV column (e.g. 1). Selected fields are removed from plotted channels. Leave blank for ordinary serial text/numeric data. Timestamp and sequence fields must be different.")
        self._settings_form(tabs, "Signal & performance", [
            ("sample_rate", "Sample rate (samples/s)", (0.01, 10000000.0)),
            ("unit", "Amplitude unit label", str),
            ("refresh_hz", "Maximum visual refresh (Hz)", (5, 60)),
            ("analysis_hz", "Maximum analysis updates (Hz)", (1, 20)),
            ("sample_capacity", "Sample buffer (rows)", (1024, 1000000)),
            ("max_lines", "Console record limit", (100, 100000)),
        ], "Frequency axes use this configured sample rate. Device timestamp estimates appear in Analysis → Data quality and can be adopted explicitly; USB receive timing is never used as a sample clock. Changing parsing/rate/capacity clears samples. Analysis runs in bounded background jobs; lower its update rate for less CPU use.")
        channel_page = W.QWidget()
        channel_page.setObjectName("settingsContent")
        channel_layout = W.QVBoxLayout(channel_page)
        channel_layout.setContentsMargins(20, 20, 20, 20)
        channel_layout.addWidget(label("Channel names override incoming labels. Empty names use the parsed label or CH number.", "muted"))
        grid = W.QGridLayout()
        self.name_controls = []
        for i in range(8):
            grid.addWidget(label(f"Channel {i + 1}"), i, 0)
            name = W.QLineEdit(self.settings.channel_names[i])
            name.setMaxLength(40)
            name.setPlaceholderText("Use incoming name")
            self.name_controls.append(name)
            grid.addWidget(name, i, 1)
            color = button(self.settings.channel_colors[i], lambda checked=False, index=i: self.choose_channel_color(index))
            color.setProperty("color", self.settings.channel_colors[i])
            self.color_buttons.append(color)
            grid.addWidget(color, i, 2)
        channel_layout.addLayout(grid)
        channel_layout.addStretch()
        tabs.addTab(channel_page, "Channels")
        bottom = W.QHBoxLayout()
        bottom.addWidget(button("Import…", self.import_settings))
        bottom.addWidget(button("Export settings…", self.export_settings))
        bottom.addWidget(button("Restore defaults", self.restore_defaults))
        bottom.addStretch()
        bottom.addWidget(button("Apply & save", self.apply_settings, True))
        layout.addLayout(bottom)
        path_note = label(f"Preferences: {settings_path()}\nForm changes take effect only when applied. Connection and view controls are saved on exit.", "muted")
        path_note.setWordWrap(True)
        path_note.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_note)
        self.pages.addWidget(page)

    def _settings_form(self, tabs, title, fields, note):
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        content = W.QWidget()
        content.setObjectName("settingsContent")
        box = W.QVBoxLayout(content)
        box.setContentsMargins(22, 20, 22, 20)
        info = label(note, "muted")
        info.setWordWrap(True)
        box.addWidget(info)
        box.addSpacing(14)
        form = W.QFormLayout()
        form.setSpacing(14)
        form.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        for key, caption, kind in fields:
            value = getattr(self.settings, key)
            if kind is bool:
                control = W.QCheckBox("Enabled")
                control.setChecked(value)
            elif kind is str:
                control = W.QLineEdit(value)
                control.setMaxLength(200)
            elif kind == "color":
                control = button(value, self.choose_accent)
                control.setProperty("color", value)
            elif isinstance(kind, tuple) and len(kind) == 2 and isinstance(kind[0], (int, float)):
                control = W.QDoubleSpinBox() if isinstance(value, float) else W.QSpinBox()
                if isinstance(control, W.QDoubleSpinBox):
                    control.setDecimals(2)
                control.setRange(*kind)
                control.setValue(value)
            else:
                control = combo(kind, value)
            self.controls[key] = control
            form.addRow(caption, control)
        box.addLayout(form)
        box.addStretch()
        scroll.setWidget(content)
        tabs.addTab(scroll, title.replace("&", "&&"))

    def _shortcuts(self):
        for i in range(len(PAGES)):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{i + 1}"), self)
            shortcut.activated.connect(lambda page=i: self.navigate(page))
        for sequence, callback in [("Ctrl+,", lambda: self.navigate(5)), ("Ctrl+B", self.toggle_sidebar),
                                   ("Ctrl+K", self.focus_search), ("Ctrl+L", self.clear_log),
                                   ("Ctrl+E", self.export_samples), ("F1", self.show_guide)]:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space and not isinstance(self.focusWidget(), (W.QLineEdit, W.QAbstractSpinBox, W.QPlainTextEdit, W.QComboBox)):
            self.toggle_freeze()
            event.accept()
        else:
            super().keyPressEvent(event)

    def navigate(self, page):
        if page in (1, 3, 4) and hasattr(self, "experience") and self.experience.currentText() == "Monitor":
            self.set_experience("Explore")
        self.pages.setCurrentIndex(page)
        if page == 1:
            self.scope_started = True
        self.last_analysis = 0
        self.title.setText(PAGES[page][0])
        self.subtitle.setText(PAGES[page][1])
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == page)
        self.freeze_button.setEnabled(page != 5)
        self.invalidate_plot()
        if page == 0:
            self.log_dirty = True

    def set_experience(self, mode):
        self.settings.experience = mode
        self.experience.blockSignals(True)
        self.experience.setCurrentText(mode)
        self.experience.blockSignals(False)
        for i, item in enumerate(self.nav_buttons):
            item.setVisible(mode != "Monitor" or i in (0, 2, 5))
        self.spectral.tune.setChecked(mode == "Advanced")
        self.metrics_frame.setVisible(self.settings.show_metrics)
        self.discovery.setVisible(self.settings.show_tips)
        self.spectral.update_help()
        self.processing.help.setVisible(self.settings.show_tips)
        if "experience" in self.controls:
            self.controls["experience"].setCurrentText(mode)
        if mode == "Monitor" and self.pages.currentIndex() in (1, 3, 4):
            self.navigate(0)

    def discover(self, page):
        self.set_experience("Explore")
        self.navigate(page)

    def hide_tips(self):
        self.settings.show_tips = False
        self.controls["show_tips"].setChecked(False)
        self.set_experience(self.settings.experience)

    def open_settings_tab(self, index):
        self.navigate(5)
        self.settings_tabs.setCurrentIndex(index)

    def show_learning_path(self):
        existing = getattr(self, "learning_dialog", None)
        if existing and existing.isVisible():
            existing.raise_()
            return
        dialog = W.QDialog(self)
        self.learning_dialog = dialog
        dialog.setWindowTitle("Start simple, explore when ready")
        dialog.resize(630, 550)
        layout = W.QVBoxLayout(dialog)
        intro = label("You can use this as a regular serial monitor. Nothing below is required to send and read messages. Try each step on Demo signal before using your device.", "muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for title, text, page in [
            ("1. Read and send", "Monitor shows your device's text. Use the filter to find messages; choose line endings when sending.", 0),
            ("2. Watch numbers change", "Plotter turns numeric records into lines. CSV, key:value and JSON numbers work automatically.", 2),
            ("3. Hold an interesting moment", "Scope waits for a level crossing and captures what happened before and after it.", 1),
            ("4. Find repetition", "Spectrum shows repeating frequencies; Spectrogram shows how those frequencies change over time.", 3),
            ("5. Measure or extract", "Analysis smooths signals, isolates bands, finds peaks/events and checks device timing. Outputs never replace raw data.", 4),
        ]:
            frame, box = card()
            text_label = label(text, "muted")
            text_label.setWordWrap(True)
            box.addWidget(button(title + " →", lambda checked=False, target=page: (dialog.close(), self.discover(target))))
            box.addWidget(text_label)
            layout.addWidget(frame)
        layout.addWidget(label("Set the device sample rate before interpreting seconds or hertz. Use F1 for formulas and limits.", "muted"))
        dialog.show()

    def adopt_sample_rate(self):
        rate = self.timing.summary(self.settings.sample_rate)["Device nominal sample rate (Hz)"]
        if rate is None or not 0.01 <= rate <= 10000000:
            self.notice("No usable device rate yet. Select a timestamp field and collect at least three increasing timestamps.")
            return
        if self.timing.continuity_note(min(8192, self.buffer.count)):
            self.notice("Resolve timestamp/sequence discontinuities before adopting this estimate.")
            return
        if W.QMessageBox.question(self, "Use device rate estimate", f"Use {rate:.6g} samples/s for future time/frequency axes? Numeric buffers and captures will be cleared. Raw serial acquisition continues.") != W.QMessageBox.StandardButton.Yes:
            return
        self.settings.sample_rate = float(rate)
        self.controls["sample_rate"].setValue(rate)
        self.clear_samples(confirm=False)
        self.notice(f"Sample rate set to {rate:.6g} samples/s from device timestamps. This is an estimate, not calibration.")

    def render_metadata(self):
        metrics = self.timing.summary(self.settings.sample_rate)
        self.metadata_table.setRowCount(len(metrics))
        for row, (name, value) in enumerate(metrics.items()):
            self.metadata_table.setItem(row, 0, W.QTableWidgetItem(name))
            self.metadata_table.setItem(row, 1, W.QTableWidgetItem("Not available" if value is None else f"{value:.8g}"))

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())
        self.settings.sidebar = not self.sidebar.isHidden()
        self.controls["sidebar"].setChecked(self.settings.sidebar)

    def focus_search(self):
        self.navigate(0)
        self.search.setFocus()

    def refresh_ports(self):
        selected = self.port.currentText() or self.settings.port
        self.port.clear()
        try:
            ports = list_ports.comports()
            for port in ports:
                self.port.addItem(port.device)
                self.port.setItemData(self.port.count() - 1, port.description, QtCore.Qt.ItemDataRole.ToolTipRole)
            self.port.setEditText(selected)
        except OSError as exc:
            self.notice(f"Could not enumerate ports: {exc}")

    def _connection_settings(self):
        try:
            baud = int(self.baud.currentText())
        except ValueError as exc:
            raise ValueError("Baud rate must be an integer.") from exc
        if not 50 <= baud <= 12000000:
            raise ValueError("Baud rate must be between 50 and 12,000,000.")
        port = self.port.currentText().strip()
        if not port:
            raise ValueError("Select or enter a serial port first.")
        self.settings.port = port
        self.settings.baud_rate = baud
        if baud not in BAUD_RATES and baud not in self.settings.custom_baud_rates:
            self.settings.custom_baud_rates.append(baud)
        return replace(self.settings)

    def toggle_connection(self):
        if self.session:
            self.disconnect()
            return
        try:
            self._start(self._connection_settings())
        except ValueError as exc:
            self.notice(str(exc))

    def start_demo(self):
        if self.session:
            self.disconnect()
            if self.session:
                return
        # The built-in source always emits CSV at a known, fixed rate.
        if self.settings.sample_rate != 1000 or self.settings.parser not in ("Auto", "CSV") or self.settings.delimiter != "," or self.settings.timestamp_field or self.settings.sequence_field:
            answer = W.QMessageBox.question(self, "Demo source", "Demo uses CSV at 1,000 samples/s. Apply these settings and clear existing samples?")
            if answer != W.QMessageBox.StandardButton.Yes:
                return
            self.settings.sample_rate = 1000.0
            self.settings.parser = "Auto"
            self.settings.delimiter = ","
            self.settings.timestamp_field = ""
            self.settings.sequence_field = ""
            self.populate_settings(self.settings)
        self._start(replace(self.settings), demo=True)

    def _start(self, settings, demo=False):
        self.clear_samples(confirm=False)
        self.rx_bytes = self.tx_bytes = self.dropped = self.oversized = self.non_numeric = 0
        self.last_rx = 0
        self.rx_rate = 0
        self.last_rx_time = time.monotonic()
        self.reported_error = False
        self.rx_epoch = 0
        self.session = Acquisition(settings, demo)
        self.session.start()
        self.connect_button.setText("Disconnect")
        self.demo_button.setEnabled(False)
        self.port.setEnabled(False)
        self.baud.setEnabled(False)
        self.notice("Starting demo…" if demo else f"Opening {settings.port}…")

    def disconnect(self):
        if self.session:
            self.session.stop()
            if self.session.thread and self.session.thread.is_alive():
                self.notice("Waiting for the serial driver to close. A new connection cannot open yet.")
                return
            self._drain(all_packets=True)
            self._session_counters()
            self.session = None
        self.connect_button.setText("Connect")
        self.demo_button.setEnabled(True)
        self.port.setEnabled(True)
        self.baud.setEnabled(True)
        self.rx_rate = 0
        self.notice("Disconnected · Port released. Buffered data is still available.")

    def send(self):
        try:
            if not self.session:
                raise ValueError("Connect to a serial port before sending data.")
            text = self.input.text()
            if not text:
                return
            if self.send_mode.currentText() == "Hex bytes":
                data = bytes.fromhex(text)
            else:
                endings = {"None": "", "LF": "\n", "CR": "\r", "CRLF": "\r\n"}
                data = (text + endings[self.ending.currentText()]).encode(self.settings.encoding)
            if len(data) > 65536:
                raise ValueError("Transmit payload must be no larger than 65,536 bytes.")
            self.session.send(data)
            self.input.clear()
        except (ValueError, UnicodeError) as exc:
            self.notice(f"Not sent: {exc}")

    def _drain(self, all_packets=False):
        if not self.session:
            return
        deadline = time.monotonic() + (1 if all_packets else 0.010)
        rows = []
        while time.monotonic() < deadline:
            try:
                packet = self.session.incoming.get_nowait()
            except queue.Empty:
                break
            if packet.direction == "RX" and packet.epoch != self.rx_epoch:
                rows.clear()
                self.buffer.clear()
                self.scope.reset()
                self.timing = TimingTracker(bool(self.settings.timestamp_field), bool(self.settings.sequence_field))
                self.processing.invalidate()
                self.invalidate_spectrum()
                self.rx_epoch = packet.epoch
                self.notice("Input loss detected · Measurement buffer reset to avoid analysing across a sample gap. Reduce source bandwidth.")
            for raw in packet.records:
                record = (packet.timestamp, packet.direction, raw)
                if len(self.logs) == self.logs.maxlen:
                    self.log_bytes -= len(self.logs[0][2])
                self.logs.append(record)
                self.log_bytes += len(raw)
                while self.log_bytes > 16 * 1024 * 1024 and self.logs:
                    self.log_bytes -= len(self.logs.popleft()[2])
                    self.log_dirty = True
                if not self.log_dirty:
                    self.pending_logs.append(record)
                if packet.direction == "RX":
                    parsed = self.parser.parse(raw.decode(self.settings.encoding, errors="replace"))
                    if parsed:
                        rows.append(parsed.values)
                        self.timing.observe(parsed.device_time, parsed.sequence, packet.monotonic or time.monotonic())
                    elif raw.strip():
                        self.non_numeric += 1
        self.buffer.append(rows)
        # Do not accumulate an unbounded display queue while the monitor is hidden/frozen.
        if len(self.pending_logs) > self.settings.max_lines or self.pages.currentIndex() != 0 or self.frozen:
            self.pending_logs.clear()
            self.log_dirty = True

    def _session_counters(self):
        if self.session:
            self.rx_bytes = self.session.rx_bytes
            self.tx_bytes = self.session.tx_bytes
            self.dropped = self.session.dropped_records
            self.oversized = self.session.oversized_records

    def tick(self):
        self._drain()
        self._session_counters()
        now = time.monotonic()
        if self.session and self.session.thread and not self.session.thread.is_alive() and not self.reported_error:
            error = self.session.error
            self.reported_error = True
            self.disconnect()
            self.notice(f"Connection ended: {error}" if error else "Connection ended.")
        if now - self.last_status >= 0.5:
            self._update_status(now)
            self.last_status = now
        if now - self.last_render < 1 / self.settings.refresh_hz:
            return
        self.last_render = now
        if self.scope_started:
            self.scope.process()
        if self.frozen:
            return
        page = self.pages.currentIndex()
        if page == 0:
            self.render_log()
        elif page == 1:
            self._update_channel_names()
            self.scope.render()
        elif page == 3:
            self._update_channel_names()
            self.render_spectrum()
        elif page == 2 and self.last_data_version != self.buffer.total:
            self.last_data_version = self.buffer.total
            self._update_channel_names()
            self.render_time()
        elif page == 4 and now - self.last_analysis >= 1 / self.settings.analysis_hz and (self.last_data_version != self.buffer.total or self.analysis_tool.currentText() in ADVANCED_TOOLS):
            self.last_analysis = now
            self.last_data_version = self.buffer.total
            self._update_channel_names()
            self.render_analysis()

    def _update_status(self, now):
        elapsed = now - self.last_rx_time
        self.rx_rate = max(0, (self.rx_bytes - self.last_rx) / elapsed) if self.session and elapsed else 0
        self.last_rx, self.last_rx_time = self.rx_bytes, now
        state = "Demo · live" if self.session and self.session.demo else "Connected" if self.session and self.session.connected else "Opening…" if self.session else "Offline"
        self.metric_labels[0].setText(state)
        self.metric_labels[1].setText(f"{self.rx_rate / 1024:.1f} KiB/s" if self.rx_rate >= 1024 else f"{self.rx_rate:.0f} B/s")
        self.metric_labels[2].setText(f"{self.buffer.count:,}")
        self.metric_labels[3].setText(f"{self.dropped + self.oversized:,}")
        self.metric_labels[3].setToolTip(f"Discarded records (queue/framing): {self.dropped:,} · Oversized input records: {self.oversized:,}\nNon-numeric records: {self.non_numeric:,} (kept in Monitor, not sampled).\nRX: {self.rx_bytes:,} bytes · TX: {self.tx_bytes:,} bytes")
        self.send_button.setEnabled(bool(self.session and self.session.connected and not self.session.demo))
        self.discovery_text.setText(
            f"{self.buffer.count:,} numeric rows available across {len(self.parser.names)} channels. Ready for a graph? Plot values first, then try frequencies or guided tools. Raw messages and sends remain here."
            if self.buffer.count else "Start here: choose a port and Connect, or try Demo signal. Plain-text messages work without any signal settings. Numeric records can be plotted whenever you are ready.")
        if self.pages.currentIndex() == 4:
            self.render_metadata()

    def format_record(self, record, truncate=False):
        timestamp, direction, raw = record
        value = raw.hex(" ") if self.hex_check.isChecked() else raw.decode(self.settings.encoding, errors="replace").rstrip("\r\n")
        # Keep a record on one console line even when TX contains embedded line endings.
        value = value.replace("\r", "\\r").replace("\n", "\\n").replace("\x00", "\\0")
        if truncate and len(value) > 4096:
            value = value[:4096] + " … [display truncated; export retains full record]"
        prefix = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3] + "  " if self.timestamp_check.isChecked() else ""
        return f"{prefix}{direction}  {value}"

    def invalidate_log(self, *_):
        self.log_dirty = True
        self.pending_logs.clear()

    def render_log(self):
        if not self.log_dirty and not self.pending_logs:
            return
        scroll = self.console.verticalScrollBar()
        old_position = scroll.value()
        query = self.search.text().casefold()
        records = self.logs if self.log_dirty else self.pending_logs
        lines = [self.format_record(record, truncate=True) for record in records
                 if not query or query in self.format_record(record).casefold()]
        if self.log_dirty:
            self.console.setPlainText("\n".join(lines))
        elif lines:
            self.console.appendPlainText("\n".join(lines))
        if self.scroll_check.isChecked():
            scroll.setValue(scroll.maximum())
        else:
            scroll.setValue(old_position)
        self.pending_logs.clear()
        self.log_dirty = False

    def clear_log(self):
        self.logs.clear()
        self.log_bytes = 0
        self.pending_logs.clear()
        self.console.clear()
        self.log_dirty = False

    def copy_log(self):
        QtGui.QGuiApplication.clipboard().setText(self.console.toPlainText())
        self.notice("Visible monitor text copied.")

    def toggle_freeze(self):
        self.frozen = not self.frozen
        self.freeze_button.setText("Resume view" if self.frozen else "Freeze view")
        self.invalidate_log()
        self.invalidate_plot()
        self.spectral.engine.invalidate()
        self.spectral.last_key = None
        self.processing.engine.invalidate()
        self.processing.last_key = None
        self.notice("View frozen · Acquisition continues; old samples can still leave the ring buffer." if self.frozen else "Live view resumed.")

    def clear_samples(self, confirm=True):
        if confirm and self.buffer.count:
            if W.QMessageBox.question(self, "Clear samples", "Clear buffered numeric samples? Console records are kept.") != W.QMessageBox.StandardButton.Yes:
                return
        self.buffer.clear()
        self.parser = NumericParser.from_settings(self.settings)
        self.timing = TimingTracker(bool(self.settings.timestamp_field), bool(self.settings.sequence_field))
        self.scope.reset()
        self.processing.invalidate()
        self.invalidate_spectrum()
        self._update_channel_names()

    def invalidate_plot(self, *_):
        self.last_data_version = -1
        if hasattr(self, "scope"):
            self.scope.dirty = True

    def invalidate_spectrum(self, *_):
        self.peak = None
        self.peak_key = None
        self.invalidate_plot()
        if hasattr(self, "spectral"):
            self.spectral.invalidate()

    def invalidate_processing(self, *_):
        self.invalidate_plot()
        if hasattr(self, "processing"):
            self.processing.tool_changed()

    def channel_changed(self, index):
        self.settings.selected_channel = index
        for widget in (getattr(self, "spectrum_channel", None), getattr(self, "analysis_channel", None)):
            if widget is not None and widget.currentIndex() != index:
                widget.blockSignals(True)
                widget.setCurrentIndex(index)
                widget.blockSignals(False)
        self.invalidate_spectrum()
        if hasattr(self, "processing"):
            self.processing.invalidate()

    def channel_name(self, index):
        return self.settings.channel_names[index] or (self.parser.names[index] if index < len(self.parser.names) else f"CH {index + 1}")

    def _update_channel_names(self):
        for i, check in enumerate(self.channel_checks):
            check.setText(self.channel_name(i))
            for widget in (self.spectrum_channel, self.analysis_channel, self.analysis_reference):
                if widget.itemText(i) != self.channel_name(i):
                    widget.blockSignals(True)
                    widget.setItemText(i, self.channel_name(i))
                    widget.blockSignals(False)
            if hasattr(self, "scope"):
                for widget in (self.scope.source, self.scope.vertical_channel):
                    if widget.itemText(i) != self.channel_name(i):
                        widget.blockSignals(True)
                        widget.setItemText(i, self.channel_name(i))
                        widget.blockSignals(False)

    def render_time(self):
        # Keep a bounded history available for panning; peak downsampling is handled by pyqtgraph.
        limit = max(2, round(self.time_window.value() * self.settings.sample_rate) + 1) if self.follow_plot.isChecked() else None
        indices, values = self.buffer.snapshot(limit)
        times = indices / self.settings.sample_rate
        for i, curve in enumerate(self.time_curves):
            visible = self.channel_checks[i].isChecked()
            curve.setVisible(visible)
            if visible:
                curve.setData(times, values[:, i], connect="finite")
        if len(times) and self.follow_plot.isChecked():
            end = max(times[-1], self.time_window.value())
            self.time_plot.setXRange(max(0, end - self.time_window.value()), end, padding=0)
        self.plot_note.setText(f"{self.buffer.count:,} retained / {self.buffer.total:,} received samples · {self.settings.sample_rate:g} samples/s configured · {self.settings.unit}")

    def current_signal(self):
        indices, values = self.buffer.snapshot(int(self.fft_size.currentText()))
        return indices / self.settings.sample_rate, values[:, self.settings.selected_channel]

    def render_spectrum(self):
        self.spectral.render()

    def render_analysis(self):
        times, values = self.current_signal()
        metrics = statistics(values, self.settings.sample_rate)
        continuity = self.timing.continuity_note(len(values))
        if continuity:
            for key in ("Frequency (Hz)", "Period (s)", "Rise 10–90% (s)", "Fall 90–10% (s)"):
                if key in metrics:
                    metrics[key] = None
        self.stats.setRowCount(len(metrics) if metrics else 1)
        if not metrics:
            self.stats.setItem(0, 0, W.QTableWidgetItem("No finite samples"))
            self.stats.setItem(0, 1, W.QTableWidgetItem("—"))
        for row, (key, value) in enumerate(metrics.items()):
            self.stats.setItem(row, 0, W.QTableWidgetItem(key))
            self.stats.setItem(row, 1, W.QTableWidgetItem("—" if value is None else f"{value:.6g}"))
        finite = values[np.isfinite(values)]
        tool = self.analysis_tool.currentText()
        self.smoothing.setEnabled(tool in ("Moving average", "Rolling statistics"))
        self.analysis_reference.setEnabled(tool.startswith("A ") or tool == "XY / phase")
        if tool == "Acquisition metadata":
            self.render_metadata()
            self.analysis_note.setText("Rates are labelled by their source. Device metadata is optional; serial monitoring always works without it.")
            return
        if tool in ADVANCED_TOOLS:
            self.processing.render(tool, times, values)
            return
        if continuity and tool in ("Autocorrelation", "Moving average", "Derivative", "Integral", "XY / phase"):
            self.analysis_curve.clear()
            self.analysis_note.setText(continuity)
            return
        x, y = np.array([]), np.array([])
        x_label, y_label = "Sample time (s)", self.settings.unit
        complete = len(finite) == len(values)
        if tool == "Histogram" and len(finite):
            counts, edges = np.histogram(finite, bins=min(64, max(4, int(np.sqrt(len(finite))))))
            x, y = (edges[:-1] + edges[1:]) / 2, counts
            x_label, y_label = f"Value ({self.settings.unit})", "Count"
        elif tool == "Autocorrelation":
            y = autocorrelation(values)
            x = np.arange(len(y)) / self.settings.sample_rate
            x_label, y_label = "Lag (s)", "Normalized correlation"
        elif tool == "Moving average":
            width = self.smoothing.value()
            y = moving_average(values, width)
            x = times[width - 1:] if len(y) else np.array([])
        elif tool == "Derivative" and len(values) > 1:
            y = np.diff(values) * self.settings.sample_rate
            x = times[1:]
            y_label = f"{self.settings.unit}/s"
        elif tool == "Integral" and complete and len(values):
            y = np.r_[0, np.cumsum((values[1:] + values[:-1]) * 0.5 / self.settings.sample_rate)]
            x = times
            y_label = f"{self.settings.unit}·s"
        elif tool in ("A + B", "A - B", "A * B", "A / B", "XY / phase"):
            _, matrix = self.buffer.snapshot(int(self.fft_size.currentText()))
            reference = matrix[:, self.analysis_reference.currentIndex()]
            x = times
            if tool == "A + B":
                y = values + reference
            elif tool == "A - B":
                y = values - reference
            elif tool == "A * B":
                y = values * reference
                y_label = f"{self.settings.unit}²"
            elif tool == "A / B":
                y = np.divide(values, reference, out=np.full_like(values, np.nan), where=reference != 0)
                y_label = "Ratio A/B"
            else:
                x, y = reference, values
                x_label = f"B: {self.channel_name(self.analysis_reference.currentIndex())} ({self.settings.unit})"
                y_label = f"A: {self.channel_name(self.settings.selected_channel)} ({self.settings.unit})"
        self.analysis_curve.setData(x, y, connect="finite")
        self.analysis_plot.setLabel("bottom", x_label)
        self.analysis_plot.setLabel("left", y_label)
        self.analysis_note.setText(f"Latest {len(values):,} rows · {len(finite):,} finite values · Frequency: mean-centered rising crossings, not a precision counter. Integral resets at each analysis window." + (" Missing values: correlation/integral unavailable." if not complete else ""))

    def apply_theme(self):
        W.QApplication.instance().setStyleSheet(stylesheet(self.settings))
        palette = PALETTES[self.settings.theme]
        qt_palette = QtGui.QPalette()
        for role, color in [(QtGui.QPalette.ColorRole.Window, palette["bg"]),
                            (QtGui.QPalette.ColorRole.WindowText, palette["text"]),
                            (QtGui.QPalette.ColorRole.Base, palette["plot"]),
                            (QtGui.QPalette.ColorRole.Text, palette["text"]),
                            (QtGui.QPalette.ColorRole.Button, palette["raised"]),
                            (QtGui.QPalette.ColorRole.ButtonText, palette["text"]),
                            (QtGui.QPalette.ColorRole.Highlight, self.settings.accent)]:
            qt_palette.setColor(role, QtGui.QColor(color))
        W.QApplication.instance().setPalette(qt_palette)
        self.console.setFont(QtGui.QFont("Consolas", self.settings.font_size))
        for plot in (self.time_plot, self.spectrum_plot, self.analysis_plot, self.scope.plot):
            plot.setBackground(palette["plot"])
            plot.showGrid(x=self.settings.grid, y=self.settings.grid, alpha=0.16)
            for axis in ("left", "bottom"):
                plot.getAxis(axis).setPen(palette["border"])
                plot.getAxis(axis).setTextPen(palette["muted"])
        self.time_plot.setLabel("left", self.settings.unit)
        for i, curve in enumerate(self.time_curves):
            curve.setPen(pg.mkPen(self.settings.channel_colors[i], width=self.settings.line_width))
            self.scope.curves[i].setPen(pg.mkPen(self.settings.channel_colors[i], width=self.settings.line_width))
            self.channel_checks[i].setStyleSheet(f"QCheckBox {{ color: {self.settings.channel_colors[i]}; }}")
        self.spectrum_curve.setPen(pg.mkPen(self.settings.accent, width=self.settings.line_width))
        self.hold_curve.setPen(pg.mkPen("#e3a442", width=1, style=QtCore.Qt.PenStyle.DashLine))
        self.analysis_curve.setPen(pg.mkPen(self.settings.accent, width=self.settings.line_width))
        self.sidebar.setVisible(self.settings.sidebar)
        self.set_experience(self.settings.experience)
        self.invalidate_plot()

    def choose_accent(self):
        self._choose_color(self.controls["accent"])

    def choose_channel_color(self, index):
        self._choose_color(self.color_buttons[index])

    def _choose_color(self, control):
        chosen = W.QColorDialog.getColor(QtGui.QColor(control.property("color")), self)
        if chosen.isValid():
            control.setProperty("color", chosen.name())
            control.setText(chosen.name())

    def populate_settings(self, settings):
        for key, control in self.controls.items():
            value = getattr(settings, key)
            if isinstance(control, W.QCheckBox):
                control.setChecked(value)
            elif isinstance(control, (W.QSpinBox, W.QDoubleSpinBox)):
                control.setValue(value)
            elif isinstance(control, W.QComboBox):
                control.setCurrentText(str(value))
            elif isinstance(control, W.QLineEdit):
                control.setText(value)
            else:
                control.setProperty("color", value)
                control.setText(value)
        for i, name in enumerate(self.name_controls):
            name.setText(settings.channel_names[i])
            self.color_buttons[i].setText(settings.channel_colors[i])
            self.color_buttons[i].setProperty("color", settings.channel_colors[i])

    def sync_view_settings(self):
        s = self.settings
        s.timestamps = self.timestamp_check.isChecked()
        s.autoscroll = self.scroll_check.isChecked()
        s.hex_display = self.hex_check.isChecked()
        s.line_ending = self.ending.currentText()
        s.plot_window = self.time_window.value()
        s.fft_size = int(self.fft_size.currentText())
        s.window = self.window.currentText()
        s.remove_dc = self.dc_check.isChecked()
        s.spectrum_scale = self.db_scale.currentText()
        s.peak_hold = self.hold_check.isChecked()
        s.channel_visible = [check.isChecked() for check in self.channel_checks]
        s.scope_timebase = float(self.scope.timebase.currentText())
        s.scope_mode = self.scope.mode.currentText()
        s.scope_edge = self.scope.edge.currentText()
        s.scope_level = self.scope.level.value()
        s.scope_source = self.scope.source.currentIndex()
        s.scope_pretrigger = self.scope.pretrigger.value()
        s.scope_holdoff = self.scope.holdoff.value()
        s.scope_scales = self.scope.scales.copy()
        s.scope_offsets = self.scope.offsets.copy()
        s.scope_couplings = self.scope.couplings.copy()
        s.analysis_tool = self.analysis_tool.currentText()
        s.analysis_reference = self.analysis_reference.currentIndex()
        s.smoothing = self.smoothing.value()
        s.spectrum_view = self.spectral.view.currentText()
        s.spectrum_overlap = self.spectral.overlap.value()
        s.spectral_prominence = self.spectral.prominence.value()
        s.spectrogram_colormap = self.spectral.colormap.currentText()
        s.spectrogram_range = self.spectral.dynamic_range.value()
        s.spectrogram_auto_levels = self.spectral.auto_levels.isChecked()
        s.spectrogram_min, s.spectrogram_max = map(float, self.spectral.colorbar.levels())
        s.fundamental = self.spectral.fundamental.value()
        s.harmonic_count = self.spectral.harmonics.value()
        s.filter_low = self.processing.low.value()
        s.filter_high = self.processing.high.value()
        s.filter_order = self.processing.order.value()
        s.peak_prominence = self.processing.prominence.value()
        s.peak_distance = self.processing.distance.value()
        s.event_threshold = self.processing.threshold.value()
        s.event_hysteresis = self.processing.hysteresis.value()
        s.sidebar = not self.sidebar.isHidden()
        s.geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        s.port = self.port.currentText().strip()
        try:
            value = int(self.baud.currentText())
            if 50 <= value <= 12000000:
                s.baud_rate = value
        except ValueError:
            pass

    def apply_settings(self):
        self.sync_view_settings()
        raw = asdict(self.settings)
        for key, control in self.controls.items():
            if isinstance(control, W.QCheckBox):
                raw[key] = control.isChecked()
            elif isinstance(control, (W.QSpinBox, W.QDoubleSpinBox)):
                raw[key] = control.value()
            elif isinstance(control, W.QComboBox):
                raw[key] = control.currentText()
                if key == "data_bits":
                    raw[key] = int(raw[key])
                elif key == "stop_bits":
                    raw[key] = float(raw[key])
            elif isinstance(control, W.QLineEdit):
                raw[key] = control.text()
            else:
                raw[key] = control.property("color")
        if len(raw["delimiter"]) != 1:
            self.notice("CSV delimiter must be exactly one character. Use a literal tab for tab-separated input.")
            return
        if raw["timestamp_field"].strip() and raw["timestamp_field"].strip() == raw["sequence_field"].strip():
            self.notice("Timestamp and sequence fields must be different. Leave either blank if not supplied.")
            return
        raw["channel_names"] = [name.text().strip() for name in self.name_controls]
        raw["channel_colors"] = [item.property("color") for item in self.color_buttons]
        new = Settings.from_dict(raw)
        metadata_fields = ("timestamp_field", "sequence_field", "timestamp_unit")
        connection_fields = ("data_bits", "parity", "stop_bits", "flow_control", "encoding", "parser", "delimiter", "sample_rate") + metadata_fields
        if self.session and any(getattr(new, key) != getattr(self.settings, key) for key in connection_fields):
            self.notice("Disconnect before changing acquisition, parser, or sample rate settings.")
            return
        clear = any(getattr(new, key) != getattr(self.settings, key) for key in ("sample_capacity", "sample_rate", "parser", "delimiter", "encoding") + metadata_fields)
        if clear and self.buffer.count and W.QMessageBox.question(self, "Reset sample buffer", "These changes clear buffered samples. Continue?") != W.QMessageBox.StandardButton.Yes:
            return
        try:
            new.save()
        except OSError as exc:
            self.notice(f"Settings were not applied: {exc}")
            return
        self.settings = new
        self.logs = deque(self.logs, maxlen=new.max_lines)
        self.log_bytes = sum(len(record[2]) for record in self.logs)
        self.console.document().setMaximumBlockCount(new.max_lines)
        if clear:
            self.buffer = SampleBuffer(new.sample_capacity)
            self.parser = NumericParser.from_settings(new)
            self.timing = TimingTracker(bool(new.timestamp_field), bool(new.sequence_field))
            self.scope.reset()
            self.processing.invalidate()
        self.invalidate_log()
        self.invalidate_spectrum()
        self.processing.invalidate()
        self._update_channel_names()
        self.apply_theme()
        self.populate_settings(new)
        self.notice("Settings applied and saved." + (" Sample buffer cleared." if clear else ""))

    def restore_defaults(self):
        if W.QMessageBox.question(self, "Restore defaults", "Replace the settings form with defaults? Nothing changes until Apply & save.") == W.QMessageBox.StandardButton.Yes:
            self.populate_settings(Settings())

    def import_settings(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Settings must be a JSON object.")
            self.populate_settings(Settings.from_dict(raw))
            self.notice("Settings form imported. Review and apply to activate. Connection/view controls are not imported.")
        except (OSError, ValueError, RecursionError) as exc:
            self.notice(f"Import failed: {exc}")

    def export_settings(self):
        self.sync_view_settings()
        path, _ = W.QFileDialog.getSaveFileName(self, "Export active settings", "serial-settings.json", "JSON (*.json)")
        if path:
            try:
                self.settings.save(path)
                self.notice("Active settings exported. Unapplied form changes are not included.")
            except OSError as exc:
                self.notice(f"Export failed: {exc}")

    def export_menu(self):
        menu = W.QMenu(self)
        menu.addAction("Buffered samples · CSV", self.export_samples)
        menu.addAction("Held scope capture · CSV", self.export_scope)
        menu.addAction("All retained monitor records · TXT", self.export_log)
        menu.addAction("Current plot · PNG", self.export_plot)
        menu.addAction("Analysis / spectral result · CSV", self.export_result)
        menu.addAction("Device timestamps / sequences · CSV", self.export_timing)
        menu.addAction("Measurement report · JSON", self.export_report)
        menu.addSeparator()
        menu.addAction("Active settings · JSON", self.export_settings)
        menu.exec(QtGui.QCursor.pos())

    def export_result(self):
        if self.pages.currentIndex() == 3:
            result = self.spectral.result
            if result is None:
                self.notice("Wait for a valid spectral result before exporting it.")
                return
            path, _ = W.QFileDialog.getSaveFileName(self, "Export displayed spectral result", "spectral-result.csv", "CSV (*.csv)")
            if path:
                self._export_job(path, lambda target: write_spectral(target, result))
            return
        elif self.pages.currentIndex() == 4:
            result = self.processing.result
            if self.analysis_tool.currentText() == "Acquisition metadata":
                data = (["metadata", "value"], list(self.timing.summary(self.settings.sample_rate).items()))
            elif result is not None:
                data = result.columns.copy(), [row.copy() for row in result.rows]
            else:
                x, y = self.analysis_curve.getData()
                data = (["x", "result"], np.column_stack((x, y)).tolist()) if x is not None and len(x) else None
        else:
            data = None
        if data is None:
            self.notice("Open Spectrum or Analysis and wait for a valid result before exporting it.")
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "Export displayed result", "analysis-result.csv", "CSV (*.csv)")
        if path:
            columns, rows = data
            self._export_job(path, lambda target: write_table(target, columns, rows))

    def export_timing(self):
        times, sequences = self.timing.recent(65536)
        if not len(times):
            self.notice("No numeric timing rows to export.")
            return
        indices = np.arange(self.timing.accepted - len(times), self.timing.accepted)
        path, _ = W.QFileDialog.getSaveFileName(self, "Export retained device metadata", "device-timing.csv", "CSV (*.csv)")
        if path:
            rows = np.column_stack((indices, times, sequences)).tolist()
            self._export_job(path, lambda target: write_table(target, ["epoch_sample_index", "device_time_s", "sequence"], rows))

    def export_report(self):
        self.sync_view_settings()
        times, values = self.current_signal()
        report = {"created_at": datetime.now().astimezone().isoformat(),
                  "channel": self.channel_name(self.settings.selected_channel), "unit": self.settings.unit,
                  "sample_rate_source": "User configured / explicitly adopted; not host arrival time",
                  "configured_rate_hz": self.settings.sample_rate, "statistics": statistics(values, self.settings.sample_rate),
                  "data_quality": self.timing.summary(self.settings.sample_rate),
                  "continuity_warning": self.timing.continuity_note(len(values)),
                  "analysis_tool": self.analysis_tool.currentText(), "settings": asdict(self.settings),
                  "scope": {"captures": self.scope.engine.count},
                  "notes": ["Uncalibrated software estimates. Settings may include local device names.",
                            "Spectral/processed sections describe the most recently completed result, which may precede the current live statistics."]}
        if report["continuity_warning"]:
            for key in ("Frequency (Hz)", "Period (s)", "Rise 10–90% (s)", "Fall 90–10% (s)"):
                if key in report["statistics"]:
                    report["statistics"][key] = None
        if self.spectral.result:
            spectral = self.spectral.result
            report["spectral"] = {key: spectral[key] for key in ("view", "rate", "count", "metrics", "rows", "context") if key in spectral}
        if self.processing.result:
            report["extraction"] = {"columns": self.processing.result.columns, "rows": self.processing.result.rows,
                                    "note": self.processing.result.note, "context": self.processing.result.context}
        path, _ = W.QFileDialog.getSaveFileName(self, "Export measurement report", "measurement-report.json", "JSON (*.json)")
        if path:
            self._export_job(path, lambda target: write_report(target, report))

    def export_samples(self):
        if not self.buffer.count:
            self.notice("No numeric samples to export.")
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "Export buffered samples", "samples.csv", "CSV (*.csv)")
        if not path:
            return
        indices, values = self.buffer.snapshot()
        active = max(1, len(self.parser.names))
        names = [self.channel_name(i) for i in range(active)]
        rate = self.settings.sample_rate
        self._export_job(path, lambda target: write_samples(target, indices, values[:, :active], rate, names))

    def export_log(self):
        path, _ = W.QFileDialog.getSaveFileName(self, "Export retained records", "monitor.txt", "Text (*.txt)")
        if path:
            text = "\n".join(self.format_record(record) for record in self.logs)
            self._export_job(path, lambda target: write_log(target, text))

    def export_scope(self):
        capture = self.scope.engine.capture
        if capture is None:
            self.notice("No scope capture to export yet.")
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "Export scope capture", "scope-capture.csv", "CSV (*.csv)")
        if path:
            rate = self.settings.sample_rate
            names = [self.channel_name(i) for i in range(8)]
            self._export_job(path, lambda target: write_samples(target, capture.indices, capture.values, rate, names, capture.trigger_index))

    def _export_job(self, path, operation):
        if self.export_jobs:
            self.notice("An export is already running. Wait for it to finish before starting another.")
            return
        job = ExportJob(path, operation)
        self.export_jobs.add(job)
        job.signals.finished.connect(self._export_finished)
        self.export_pool.start(job)
        self.notice("Exporting snapshot in background · Acquisition continues.")

    @QtCore.Slot(str, str)
    def _export_finished(self, path, error):
        self.export_jobs.clear()
        self.notice(f"Export failed: {error}" if error else f"Export saved: {path}")

    def export_plot(self):
        if self.pages.currentIndex() == 3 and self.spectral.view.currentText() in ("Harmonics & quality", "Spectral peaks"):
            self.notice("This result is a table. Export Analysis / spectral result · CSV or Measurement report · JSON instead.")
            return
        plot = {1: self.scope.plot, 2: self.time_plot, 3: self.spectrum_plot, 4: self.analysis_plot}.get(self.pages.currentIndex())
        if plot is None:
            self.notice("Open Plotter, Spectrum, or Analysis to export a plot.")
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "Export current plot", "plot.png", "PNG (*.png)")
        if path:
            try:
                pg.exporters.ImageExporter(plot.plotItem).export(path)
                self.notice("Plot image exported at the current view range.")
            except Exception as exc:
                self.notice(f"Image export failed: {exc}")

    def show_guide(self):
        dialog = W.QDialog(self)
        dialog.setWindowTitle("User guide")
        dialog.resize(900, 700)
        layout = W.QVBoxLayout(dialog)
        browser = W.QTextBrowser()
        browser.setOpenExternalLinks(True)
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        path = base / "docs" / "USER_GUIDE.md"
        browser.setSearchPaths([str(path.parent)])
        browser.document().setBaseUrl(QtCore.QUrl.fromLocalFile(str(path.parent) + "/"))
        try:
            browser.setMarkdown(path.read_text(encoding="utf-8"))
        except OSError:
            browser.setPlainText("See docs/USER_GUIDE.md in the source distribution.\n\nSelect a port and Connect, or use Demo signal.\nSet the device sample rate in Settings before using frequency measurements.\nCtrl+1…6 switches views; Ctrl+B toggles navigation.\nDisconnect releases the serial port. Freeze view does not stop acquisition.")
        layout.addWidget(browser)
        actions = W.QHBoxLayout()

        def open_reference(filename):
            try:
                browser.setMarkdown((path.parent / filename).read_text(encoding="utf-8"))
            except OSError as exc:
                browser.setPlainText(f"Documentation could not be read: {exc}")

        actions.addWidget(button("User guide", lambda: open_reference("USER_GUIDE.md")))
        actions.addWidget(button("Signal analysis reference", lambda: open_reference("SIGNAL_ANALYSIS.md")))
        actions.addStretch()
        actions.addWidget(button("Close", dialog.accept))
        layout.addLayout(actions)
        dialog.exec()

    def notice(self, text):
        self.statusBar().showMessage(text)

    def closeEvent(self, event):
        if self.export_jobs:
            self.notice("Wait for the current export to finish before closing.")
            event.ignore()
            return
        self.timer.stop()
        self.spectral.engine.stop()
        self.processing.engine.stop()
        self.disconnect()
        self.sync_view_settings()
        try:
            self.settings.save()
        except OSError as exc:
            W.QMessageBox.warning(self, "Preferences not saved", str(exc))
        event.accept()


def main():
    pg.setConfigOptions(antialias=False, useOpenGL=False)
    app = W.QApplication(sys.argv)
    app.setApplicationName("Serial Monitor")
    app.setStyle("Fusion")
    window = SerialMonitor()
    window.show()
    sys.exit(app.exec())
