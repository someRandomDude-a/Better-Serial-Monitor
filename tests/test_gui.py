import time

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from serial_workspace.app import SerialMonitor
from serial_workspace.settings import THEMES


@pytest.fixture(scope="module")
def application():
    app = W.QApplication.instance() or W.QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture
def window(application, tmp_path, monkeypatch):
    monkeypatch.setenv("SERIAL_MONITOR_SETTINGS", str(tmp_path / "settings.json"))
    widget = SerialMonitor()
    widget.show()
    application.processEvents()
    yield widget
    widget.close()
    application.processEvents()


def test_every_page_and_theme_render(window, application):
    assert window.pages.count() == 6
    signal = np.column_stack([np.sin(2 * np.pi * 50 * np.arange(4096) / 1000)] * 3)
    window.buffer.append(signal.tolist())
    window.parser.names = ["Voltage", "Current", "Temperature"]
    for theme in THEMES:
        window.settings.theme = theme
        window.apply_theme()
        for page in range(6):
            window.navigate(page)
            window.last_render = 0
            window.tick()
            application.processEvents()
    assert window.stats.item(0, 0) is not None
    assert window.scope.engine.capture is not None


def test_demo_navigation_and_freeze_keeps_acquiring(window, application):
    window.start_demo()
    try:
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert window.buffer.count > 100
        window.toggle_freeze()
        count = window.buffer.total
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert window.buffer.total > count
        window.toggle_freeze()
        window.navigate(1)
        window.last_render = 0
        window.tick()
        assert window.scope.engine.capture is not None
    finally:
        window.disconnect()
    assert window.session is None


def test_filter_hex_and_settings_apply(window, application):
    window.logs.extend([(0, "RX", b"1,2"), (0, "RX", b"hello")])
    window.invalidate_log()
    window.search.setText("hello")
    window.render_log()
    assert "hello" in window.console.toPlainText()
    assert "1,2" not in window.console.toPlainText()
    window.search.clear()
    window.hex_check.setChecked(True)
    window.render_log()
    assert "68 65 6c 6c 6f" in window.console.toPlainText()
    window.controls["theme"].setCurrentText("AMOLED")
    window.apply_settings()
    assert window.settings.theme == "AMOLED"


def test_scope_vertical_settings_and_cursors(window):
    scope = window.scope
    scope.scale.setValue(0.25)
    scope.offset.setValue(1.5)
    scope.coupling.setCurrentText("AC")
    scope.cursor_check.setChecked(True)
    scope.cursors[0].setValue(0.01)
    scope.cursors[1].setValue(0.03)
    scope.cursors[2].setValue(0)
    scope.cursors[3].setValue(2)
    assert "50 Hz" in scope.readout.text()
    assert "0.5 units" in scope.readout.text()
    window.sync_view_settings()
    assert window.settings.scope_scales[0] == 0.25
    assert window.settings.scope_couplings[0] == "AC"


def test_all_analysis_tools_and_background_exports(window, tmp_path, monkeypatch, application):
    from serial_workspace.settings import ANALYSIS_TOOLS

    signal = np.column_stack([np.sin(2 * np.pi * 20 * np.arange(4096) / 1000), np.ones(4096)])
    window.buffer.append(signal.tolist())
    window.parser.names = ["A", "B"]
    for tool in ANALYSIS_TOOLS:
        window.analysis_tool.setCurrentText(tool)
        window.render_analysis()
    path = tmp_path / "samples.csv"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    window.export_samples()
    deadline = time.monotonic() + 5
    while window.export_jobs and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert not window.export_jobs
    assert path.read_text().splitlines()[0] == "sample_index,sample_time_s,A,B"
    assert len(path.read_text().splitlines()) == 4097


def test_single_capture_arms_for_new_data(window):
    scope = window.scope
    scope.single_capture()
    window.buffer.append([(-1,)] * 100 + [(1,)] * 100)
    scope.process()
    assert scope.engine.capture is not None
    assert not scope.engine.running


def test_input_loss_resets_measurement_buffer(window):
    from serial_workspace.settings import Settings
    from serial_workspace.transport import Acquisition, Packet

    window.buffer.append([(1,), (2,)])
    window.session = Acquisition(Settings())
    window.session.incoming.put_nowait(Packet([b"3"], 0, epoch=1))
    window._drain()
    assert window.buffer.total == 1
    assert window.buffer.snapshot()[1][0, 0] == 3
    assert "Input loss" in window.statusBar().currentMessage()
    window.session = None


def test_scope_timebase_persists_whole_seconds(window):
    from serial_workspace.scope_ui import ScopePanel

    window.settings.scope_timebase = 1.0
    panel = ScopePanel(window)
    assert panel.timebase.currentText() == "1"
    panel.deleteLater()


def test_gui_serial_loopback_transmit_and_disconnect(window, application):
    window.port.setEditText("loop://")
    window.toggle_connection()
    try:
        deadline = time.monotonic() + 2
        while not window.session.connected and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert window.session.connected
        window.input.setText("1,2,3")
        window.ending.setCurrentText("CRLF")
        window.send()
        deadline = time.monotonic() + 2
        while window.buffer.count == 0 and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert window.buffer.count == 1
        np.testing.assert_array_equal(window.buffer.snapshot()[1][0, :3], [1, 2, 3])
        assert window.session.tx_bytes == 7
    finally:
        window.disconnect()
    assert window.session is None


def test_scope_png_and_raw_capture_export(window, tmp_path, monkeypatch, application):
    signal = np.column_stack([np.sin(2 * np.pi * 20 * np.arange(4096) / 1000)] * 2)
    window.buffer.append(signal.tolist())
    window.scope.process()
    window.navigate(1)
    window.scope.render()
    image = tmp_path / "scope.png"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(image), ""))
    window.export_plot()
    assert image.read_bytes().startswith(b"\x89PNG")
    capture = tmp_path / "capture.csv"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(capture), ""))
    window.export_scope()
    deadline = time.monotonic() + 5
    while window.export_jobs and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    lines = capture.read_text().splitlines()
    assert lines[0].startswith("time_from_trigger_s,CH 1")
    assert len(lines) == window.scope.engine.size + 1


def test_settings_panels_follow_theme_background(window, application):
    from serial_workspace.themes import PALETTES

    window.navigate(5)
    content = window.controls["theme"].parentWidget()
    for theme in THEMES:
        window.settings.theme = theme
        window.apply_theme()
        application.processEvents()
        image = content.grab().toImage()
        assert image.pixelColor(image.width() - 20, image.height() - 20).name() == PALETTES[theme]["panel"]


def pump_until(application, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "Background result did not arrive in time"


def test_beginner_mode_discovery_and_customization(window, application):
    assert window.experience.currentText() == "Monitor"
    assert window.nav_buttons[3].isHidden()
    assert window.metrics_frame.isHidden()
    assert not window.scope_started
    window.discover(3)
    assert window.experience.currentText() == "Explore"
    assert not window.nav_buttons[3].isHidden()
    assert window.spectral.options.isHidden()
    window.set_experience("Advanced")
    assert not window.spectral.options.isHidden()
    window.hide_tips()
    assert window.discovery.isHidden()
    window.controls["show_tips"].setChecked(True)
    window.controls["show_metrics"].setChecked(True)
    window.apply_settings()
    assert not window.discovery.isHidden()
    assert not window.metrics_frame.isHidden()


def test_each_spectral_view_completes_and_exports(window, application):
    import json
    from serial_workspace.spectrum_ui import DESCRIPTIONS

    t = np.arange(8192)/1000
    window.buffer.append(np.column_stack([np.sin(2*np.pi*50*t)+0.1*np.sin(2*np.pi*100*t)]*2).tolist())
    window.navigate(3)
    for view in DESCRIPTIONS:
        window.spectral.view.setCurrentText(view)
        window.spectral.invalidate()
        window.render_spectrum()
        pump_until(application, lambda: window.spectral.result is not None)
        assert window.spectral.result["view"] == view
        columns, rows = window.spectral.export_data()
        assert len(columns) > 0
        assert len(rows) > 0
    for colormap in ("viridis", "plasma", "inferno", "CET-L1"):
        window.spectral.colormap.setCurrentText(colormap)
    window.spectral.auto_levels.setChecked(False)
    window.spectral.colorbar.setLevels((-90, -10))
    window.sync_view_settings()
    assert window.settings.spectrogram_min == -90
    assert window.settings.spectrogram_max == -10


def test_each_processing_tool_completes_without_changing_raw_data(window, application):
    from serial_workspace.processing_ui import ADVANCED_TOOLS

    t = np.arange(4096)/1000
    original = np.sin(2*np.pi*50*t)
    window.buffer.append(np.column_stack([original]*2).tolist())
    window.navigate(4)
    for tool in ADVANCED_TOOLS:
        window.analysis_tool.setCurrentText(tool)
        window.processing.invalidate()
        window.render_analysis()
        pump_until(application, lambda: window.processing.result is not None)
        assert window.processing.result.columns
        np.testing.assert_array_equal(window.buffer.snapshot()[1][:, 0], original)


def test_device_metadata_pipeline_and_rate_adoption(window, application, monkeypatch):
    from serial_workspace.metadata import TimingTracker
    from serial_workspace.stream import NumericParser
    from serial_workspace.transport import Acquisition, Packet

    window.settings.timestamp_field = "1"
    window.settings.timestamp_unit = "Microseconds"
    window.settings.sequence_field = "2"
    window.parser = NumericParser.from_settings(window.settings)
    window.timing = TimingTracker(True, True)
    window.session = Acquisition(window.settings)
    window.session.incoming.put_nowait(Packet([f"{i*2000},{i},{i/10}".encode() for i in range(256)], 0, monotonic=1))
    window._drain(all_packets=True)
    assert window.buffer.count == 256
    assert window.parser.names == ["CH 1"]
    assert window.timing.summary(1000)["Device nominal sample rate (Hz)"] == pytest.approx(500)
    window.session = None
    monkeypatch.setattr(W.QMessageBox, "question", lambda *args, **kwargs: W.QMessageBox.StandardButton.Yes)
    window.adopt_sample_rate()
    assert window.settings.sample_rate == pytest.approx(500)
    assert window.buffer.count == 0


def test_stale_background_computations_are_ignored(application):
    import threading
    from serial_workspace.computation import LatestComputation

    engine = LatestComputation()
    gate = threading.Event()
    received = []
    engine.ready.connect(lambda *args: received.append(args))
    try:
        assert engine.submit(lambda: gate.wait(2))
        assert not engine.submit(lambda: "unbounded queue")
        engine.invalidate()
        gate.set()
        pump_until(application, lambda: engine.job is None)
        assert not received
    finally:
        gate.set()
        engine.stop()


def test_fft_length_invalidates_cached_processing_result(window, application):
    window.buffer.append(np.sin(np.arange(8192)/10).reshape(-1,1).tolist())
    window.analysis_tool.setCurrentText("Rolling statistics")
    window.navigate(4)
    window.render_analysis()
    pump_until(application, lambda: window.processing.result is not None)
    assert len(window.processing.result.y) == 2048 - 15
    window.fft_size.setCurrentText("4096")
    assert window.processing.result is None
    window.render_analysis()
    pump_until(application, lambda: window.processing.result is not None)
    assert len(window.processing.result.y) == 4096 - 15


def test_learning_path_is_optional_and_non_modal(window):
    window.buffer.append([(1,), (2,)])
    window.show_learning_path()
    assert window.learning_dialog.isVisible()
    assert not window.learning_dialog.isModal()
    assert window.timer.isActive()
    window.learning_dialog.close()
    assert window.buffer.count == 2


def test_in_app_signal_reference_is_readable(window):
    from PySide6 import QtCore

    texts = []
    def inspect_dialog():
        dialog = W.QApplication.activeModalWidget()
        try:
            browser = dialog.findChild(W.QTextBrowser)
            texts.append(browser.toPlainText())
            reference = next(b for b in dialog.findChildren(W.QPushButton) if b.text() == "Signal analysis reference")
            reference.click()
            texts.append(browser.toPlainText())
        finally:
            dialog.accept()
    QtCore.QTimer.singleShot(50, inspect_dialog)
    window.show_guide()
    assert "User guide" in texts[0]
    assert "Signal analysis reference" in texts[1]


def test_selected_metadata_gaps_pause_spectrum(window, application):
    from serial_workspace.metadata import TimingTracker

    window.settings.sequence_field = "seq"
    window.timing = TimingTracker(False, True)
    window.buffer.append(np.sin(np.arange(4096)/10).reshape(-1,1).tolist())
    for i in range(4096):
        window.timing.observe(None, i if i < 4000 else i+2, i/1000)
    window.navigate(3)
    window.spectral.render()
    assert window.spectral.result is None
    assert "sequence" in window.spectral.note.text()


def test_constant_spectrum_does_not_claim_a_tone(window, application):
    window.buffer.append([(1,)] * 4096)
    window.navigate(3)
    window.render_spectrum()
    pump_until(application, lambda: window.spectral.result is not None)
    assert "No significant varying component" in window.spectral.note.text()


def test_measurement_report_qualifies_discontinuous_frequency(window, application, tmp_path, monkeypatch):
    import json
    from serial_workspace.metadata import TimingTracker

    t = np.arange(4096)/1000
    window.buffer.append(np.sin(2*np.pi*50*t).reshape(-1,1).tolist())
    window.settings.sequence_field = "seq"
    window.timing = TimingTracker(False, True)
    for i in range(4096):
        window.timing.observe(None, i if i < 4000 else i+2, i/1000)
    path = tmp_path / "qualified-report.json"
    monkeypatch.setattr(W.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    window.export_report()
    pump_until(application, lambda: not window.export_jobs)
    report = json.loads(path.read_text())
    assert report["statistics"]["Frequency (Hz)"] is None
    assert "sequence" in report["continuity_warning"]
