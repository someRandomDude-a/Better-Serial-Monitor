"""Line framing, numeric parsing and bounded sample storage (no UI dependencies)."""

from dataclasses import dataclass
import json
import re

import numpy as np


NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
LABEL = re.compile(rf"^\s*([^:=,;\t]+?)\s*[:=]\s*({NUMBER})\s*$")


class LineFramer:
    """Accept LF, CR or CRLF; discard oversized records until their terminator."""

    def __init__(self, limit=65536):
        self.limit = limit
        self.pending = bytearray()
        self.discarding = False
        self.after_cr = False
        self.oversized = 0

    def feed(self, chunk):
        records = []
        for byte in chunk:
            if byte == 10 and self.after_cr:
                self.after_cr = False
                continue
            self.after_cr = byte == 13
            if byte in (10, 13):
                if not self.discarding:
                    records.append(bytes(self.pending))
                self.pending.clear()
                self.discarding = False
            elif not self.discarding:
                if len(self.pending) >= self.limit:
                    self.pending.clear()
                    self.discarding = True
                    self.oversized += 1
                else:
                    self.pending.append(byte)
        return records


@dataclass
class ParsedSample:
    values: tuple
    device_time: float | None = None
    sequence: float | None = None


class NumericParser:
    def __init__(self, mode="Auto", delimiter=",", channels=8,
                 timestamp_field="", sequence_field="", timestamp_unit="Milliseconds"):
        self.mode = mode
        self.delimiter = delimiter
        self.channels = channels
        self.names = []
        self.timestamp_field = timestamp_field
        self.sequence_field = sequence_field
        self.time_scale = {"Seconds": 1.0, "Milliseconds": 0.001, "Microseconds": 0.000001}[timestamp_unit]

    @classmethod
    def from_settings(cls, settings):
        return cls(settings.parser, settings.delimiter, timestamp_field=settings.timestamp_field,
                   sequence_field=settings.sequence_field, timestamp_unit=settings.timestamp_unit)

    def _metadata(self, data):
        timestamp = data.get(self.timestamp_field) if self.timestamp_field else None
        sequence = data.get(self.sequence_field) if self.sequence_field else None
        timestamp = float(timestamp) * self.time_scale if type(timestamp) in (int, float) else None
        sequence = float(sequence) if type(sequence) in (int, float) else None
        if timestamp is not None and not np.isfinite(timestamp):
            timestamp = None
        if sequence is not None and (not np.isfinite(sequence) or sequence < 0 or sequence > 2**53 - 1 or not sequence.is_integer()):
            sequence = None
        return timestamp, sequence

    def parse(self, text):
        text = text.strip()
        if not text:
            return None
        try:
            if self.mode == "JSON" or (self.mode == "Auto" and text.startswith("{")):
                data = json.loads(text)
                if not isinstance(data, dict):
                    return None
                pairs = [(str(k), float(v)) for k, v in data.items()
                         if type(v) in (int, float) and np.isfinite(v)]
                return self._named(pairs)
            if self.mode == "Labels" or (self.mode == "Auto" and (":" in text or "=" in text)):
                parts = re.split(r"[,;\t]", text)
                matches = [LABEL.fullmatch(part) for part in parts]
                if not matches or not all(matches):
                    return None
                return self._named([(match[1].strip(), float(match[2])) for match in matches])
            parts = text.split(self.delimiter) if self.delimiter in text else text.split()
            values = [float(part.strip()) for part in parts]
            if not values or not all(np.isfinite(values)):
                return None
            metadata = {str(i + 1): value for i, value in enumerate(values)}
            timestamp, sequence = self._metadata(metadata)
            values = [v for i, v in enumerate(values, 1) if str(i) not in (self.timestamp_field, self.sequence_field)]
            if not values:
                return None
            for i in range(min(len(values), self.channels)):
                if len(self.names) <= i:
                    self.names.append(f"CH {i + 1}")
            return ParsedSample(tuple(values[:self.channels]), timestamp, sequence)
        except (ValueError, TypeError, OverflowError, RecursionError):
            return None

    def _named(self, pairs):
        if not pairs or not all(np.isfinite(value) for _, value in pairs):
            return None
        timestamp, sequence = self._metadata(dict(pairs))
        values = [np.nan] * self.channels
        for name, value in pairs:
            if name in (self.timestamp_field, self.sequence_field):
                continue
            if name not in self.names and len(self.names) < self.channels:
                self.names.append(name)
            if name in self.names:
                values[self.names.index(name)] = value
        if not np.any(np.isfinite(values)):
            return None
        return ParsedSample(tuple(values), timestamp, sequence)


class SampleBuffer:
    """Preallocated ring buffer. All access belongs to the GUI thread."""

    def __init__(self, capacity=32768, channels=8):
        self.capacity = capacity
        self.channels = channels
        self.data = np.full((capacity, channels), np.nan, dtype=np.float64)
        self.count = 0
        self.total = 0
        self.position = 0

    def append(self, rows):
        if not rows:
            return
        array = np.full((len(rows), self.channels), np.nan)
        for i, row in enumerate(rows):
            width = min(len(row), self.channels)
            array[i, :width] = row[:width]
        original_size = len(array)
        if original_size >= self.capacity:
            self.data[:] = array[-self.capacity:]
            self.position = 0
            self.count = self.capacity
        else:
            first = min(original_size, self.capacity - self.position)
            self.data[self.position:self.position + first] = array[:first]
            remainder = original_size - first
            if remainder:
                self.data[:remainder] = array[first:]
            self.position = (self.position + original_size) % self.capacity
            self.count = min(self.capacity, self.count + original_size)
        self.total += original_size

    def snapshot(self, limit=None):
        count = self.count if limit is None else min(self.count, max(0, int(limit)))
        start = (self.position - count) % self.capacity
        if start + count <= self.capacity:
            values = self.data[start:start + count].copy()
        else:
            values = np.concatenate((self.data[start:], self.data[:count - (self.capacity - start)]))
        indices = np.arange(self.total - count, self.total, dtype=np.float64)
        return indices, values

    def clear(self):
        self.count = self.total = self.position = 0
