import queue
import time

from serial_workspace.settings import Settings
from serial_workspace.transport import Acquisition


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_loopback_transmit_receive_and_release():
    acquisition = Acquisition(Settings(port="loop://"))
    acquisition.start()
    try:
        assert wait_until(lambda: acquisition.connected)
        acquisition.send(b"1,2,3\r\n")
        assert wait_until(lambda: acquisition.rx_bytes >= 7)
        packets = []
        while True:
            try:
                packets.append(acquisition.incoming.get_nowait())
            except queue.Empty:
                break
        assert any(p.direction == "RX" and p.records == [b"1,2,3"] for p in packets)
        assert any(p.direction == "TX" for p in packets)
    finally:
        acquisition.stop()
    assert not acquisition.connected
    assert not acquisition.thread.is_alive()
    assert not acquisition.error


def test_queue_overflow_is_counted_without_blocking():
    acquisition = Acquisition(Settings())
    for _ in range(300):
        acquisition._publish([b"test"])
    assert acquisition.incoming.qsize() == 256
    assert acquisition.dropped_records == 44
    assert acquisition.stream_epoch == 44
    while not acquisition.incoming.empty():
        acquisition.incoming.get_nowait()
    acquisition._publish([b"after gap"])
    assert acquisition.incoming.get_nowait().epoch == 44


def test_demo_has_bounded_worker_and_numeric_records():
    acquisition = Acquisition(Settings(), demo=True)
    acquisition.start()
    try:
        assert wait_until(lambda: acquisition.incoming.qsize() > 0)
        packet = acquisition.incoming.get_nowait()
        assert len(packet.records[0].split(b",")) == 3
    finally:
        acquisition.stop()
    assert not acquisition.thread.is_alive()
