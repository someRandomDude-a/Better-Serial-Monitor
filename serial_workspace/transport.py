"""Bounded worker queues. No widget or Qt operations are allowed in this module."""

from dataclasses import dataclass
import math
import queue
import threading
import time

import serial

from .stream import LineFramer


@dataclass
class Packet:
    records: list
    timestamp: float
    direction: str = "RX"
    epoch: int = 0
    monotonic: float = 0.0


class Acquisition:
    def __init__(self, settings, demo=False):
        self.settings = settings
        self.demo = demo
        self.incoming = queue.Queue(maxsize=256)
        self.outgoing = queue.Queue(maxsize=128)
        self.stop_event = threading.Event()
        self.thread = None
        self.error = ""
        self.connected = False
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.dropped_records = 0
        self.oversized_records = 0
        self.stream_epoch = 0

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="serial-acquisition")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.75)

    def send(self, data):
        if self.demo or not self.connected:
            raise ValueError("Connect to a serial port before sending data.")
        try:
            self.outgoing.put_nowait(data)
        except queue.Full as exc:
            raise ValueError("Transmit queue is full; wait before sending again.") from exc

    def _publish(self, records, direction="RX"):
        if not records:
            return
        try:
            self.incoming.put_nowait(Packet(records, time.time(), direction, self.stream_epoch, time.monotonic()))
        except queue.Full:
            self.dropped_records += len(records)
            if direction == "RX":
                self.stream_epoch += 1

    def _run(self):
        try:
            if self.demo:
                self._demo()
                return
            s = self.settings
            with serial.serial_for_url(s.port, baudrate=s.baud_rate, bytesize=s.data_bits,
                               parity={"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}[s.parity],
                               stopbits=s.stop_bits, timeout=0.05, write_timeout=0.2,
                               rtscts=s.flow_control == "RTS/CTS", xonxoff=s.flow_control == "XON/XOFF") as connection:
                self.connected = True
                framer = LineFramer()
                while not self.stop_event.is_set():
                    # Bound both read and write work to avoid starving either direction.
                    for _ in range(8):
                        if self.stop_event.is_set():
                            break
                        try:
                            data = self.outgoing.get_nowait()
                        except queue.Empty:
                            break
                        written = connection.write(data)
                        self.tx_bytes += written
                        if written != len(data):
                            raise OSError("Incomplete serial write.")
                        self._publish([data], "TX")
                    chunk = connection.read(min(max(connection.in_waiting, 1), 4096))
                    if chunk:
                        self.rx_bytes += len(chunk)
                        records = framer.feed(chunk)
                        if framer.oversized != self.oversized_records:
                            self.stream_epoch += 1
                            # Do not join good records from opposite sides of an oversized record.
                            self.dropped_records += len(records)
                            records = []
                        self.oversized_records = framer.oversized
                        self._publish(records)
        except (serial.SerialException, OSError, ValueError) as exc:
            self.error = str(exc)
        finally:
            self.connected = False

    def _demo(self):
        self.connected = True
        # Demo is intentionally capped to keep it useful on slower machines.
        rate = min(self.settings.sample_rate, 10000)
        index = 0
        start = time.monotonic()
        while not self.stop_event.wait(0.02):
            target = int((time.monotonic() - start) * rate)
            count = min(target - index, 1024)
            records = []
            for i in range(index, index + count):
                t = i / rate
                a = math.sin(2 * math.pi * 50 * t) + 0.25 * math.sin(2 * math.pi * 120 * t)
                b = 0.6 * math.sin(2 * math.pi * 25 * t + 0.5)
                c = 0.3 + 0.1 * math.sin(2 * math.pi * 2 * t)
                records.append(f"{a:.6f},{b:.6f},{c:.6f}".encode("ascii"))
            index += count
            self.rx_bytes += sum(len(record) + 1 for record in records)
            self._publish(records)
