import numpy as np

from serial_workspace.scope import ScopeEngine
from serial_workspace.stream import SampleBuffer


def make_engine(mode="Normal"):
    engine = ScopeEngine()
    engine.size = 20
    engine.pretrigger = 0.25
    engine.mode = mode
    return engine


def test_triggered_capture_waits_for_posttrigger_and_single_stops():
    buffer = SampleBuffer(100, 1)
    engine = make_engine("Single")
    buffer.append([(-1,)] * 25 + [(1,)] * 5)
    assert not engine.process(buffer)
    buffer.append([(1,)] * 10)
    assert engine.process(buffer)
    assert engine.capture.triggered
    assert not engine.running
    np.testing.assert_array_equal(engine.capture.indices, np.arange(20, 40))
    assert engine.capture.trigger_index == 25
    assert engine.capture.values[4, 0] == -1
    assert engine.capture.values[5, 0] == 1


def test_falling_trigger_and_level():
    buffer = SampleBuffer(100, 1)
    engine = make_engine()
    engine.edge = "Falling"
    engine.level = 2
    buffer.append([(3,)] * 25 + [(1,)] * 25)
    assert engine.process(buffer)
    assert engine.capture.trigger_index == 25


def test_auto_free_runs_and_normal_waits():
    buffer = SampleBuffer(100, 1)
    buffer.append([(1,)] * 50)
    engine = make_engine("Normal")
    assert not engine.process(buffer, now=engine.last_capture_time + 1)
    engine.mode = "Auto"
    assert engine.process(buffer, now=engine.last_capture_time + 1)
    assert not engine.capture.triggered
    assert len(engine.capture.values) == 20


def test_missing_values_do_not_cross_trigger():
    buffer = SampleBuffer(100, 1)
    buffer.append([(-1,)] * 25 + [(np.nan,)] + [(1,)] * 25)
    assert not make_engine().process(buffer)


def test_no_retrigger_from_old_edge_and_holdoff():
    buffer = SampleBuffer(200, 1)
    engine = make_engine()
    engine.holdoff = 100
    buffer.append([(-1,)] * 25 + [(1,)] * 25)
    assert engine.process(buffer)
    assert not engine.process(buffer)
    buffer.append([(-1,)] * 25 + [(1,)] * 25)
    assert not engine.process(buffer)


def test_pending_capture_invalidated_by_buffer_overwrite():
    buffer = SampleBuffer(40, 1)
    engine = make_engine()
    buffer.append([(-1,)] * 25 + [(1,)] * 5)
    assert not engine.process(buffer)
    buffer.append([(1,)] * 100)
    assert not engine.process(buffer)
    assert engine.pending is None
