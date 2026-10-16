"""Bounded device-time/sequence diagnostics; host throughput is never a sampling clock."""

from collections import deque
from itertools import islice
import time
import numpy as np


class TimingTracker:
    def __init__(self, timestamp_enabled=False, sequence_enabled=False):
        self.timestamp_enabled = timestamp_enabled
        self.sequence_enabled = sequence_enabled
        self.times = deque(maxlen=65536)
        self.sequences = deque(maxlen=65536)
        self.arrivals = deque(maxlen=2048)
        self.accepted = 0
        self.missing_sequence = self.duplicates = self.resets = self.missing_metadata = 0
        self.last_sequence = self.last_time = None

    def observe(self, timestamp, sequence, arrival):
        self.accepted += 1
        if (self.timestamp_enabled and timestamp is None) or (self.sequence_enabled and sequence is None):
            self.missing_metadata += 1
        if timestamp is not None and self.last_time is not None and timestamp <= self.last_time:
            self.resets += 1
        if sequence is not None and self.last_sequence is not None:
            step = sequence - self.last_sequence
            if step > 1:
                self.missing_sequence += int(step - 1)
            elif step == 0:
                self.duplicates += 1
            elif step < 0:
                self.resets += 1
        self.last_time = timestamp
        self.last_sequence = sequence
        self.times.append(np.nan if timestamp is None else timestamp)
        self.sequences.append(np.nan if sequence is None else sequence)
        if self.arrivals and arrival == self.arrivals[-1][0]:
            self.arrivals[-1] = (arrival, self.accepted)
        else:
            self.arrivals.append((arrival, self.accepted))
        while len(self.arrivals) > 2 and self.arrivals[-1][0] - self.arrivals[0][0] > 10:
            self.arrivals.popleft()

    def recent(self, count=8192):
        if count <= 0:
            return np.array([]), np.array([])
        times = np.fromiter(islice(reversed(self.times), count), dtype=float)[::-1].copy()
        sequences = np.fromiter(islice(reversed(self.sequences), count), dtype=float)[::-1].copy()
        return times, sequences

    def summary(self, configured_rate, now=None):
        times, sequences = self.recent()
        result = {"Configured sample rate (Hz)": configured_rate,
                  "Host accepted rows/s (not sample clock)": None,
                  "Device nominal sample rate (Hz)": None, "Device interval jitter RMS (s)": None,
                  "Device interval min (s)": None, "Device interval max (s)": None,
                  "Missing sequence numbers (session)": self.missing_sequence,
                  "Duplicate sequences (session)": self.duplicates,
                  "Clock/sequence resets (session)": self.resets,
                  "Rows missing selected metadata (session)": self.missing_metadata,
                  "Accepted rows (session)": self.accepted}
        if len(self.arrivals) > 1:
            duration = self.arrivals[-1][0] - self.arrivals[0][0]
            if duration >= 0.5:
                result["Host accepted rows/s (not sample clock)"] = (self.arrivals[-1][1] - self.arrivals[0][1]) / duration
            if (time.monotonic() if now is None else now) - self.arrivals[-1][0] > 1:
                result["Host accepted rows/s (not sample clock)"] = 0.0
        if self.timestamp_enabled and len(times) > 2:
            intervals = np.diff(times)
            steps = np.diff(sequences) if self.sequence_enabled else np.ones_like(intervals)
            valid = np.isfinite(intervals) & (intervals > 0) & np.isfinite(steps) & (steps > 0)
            per_sample = intervals[valid] / steps[valid]
            if len(per_sample) > 1:
                nominal = float(np.median(per_sample))
                result["Device nominal sample rate (Hz)"] = 1 / nominal
                result["Device interval jitter RMS (s)"] = float(np.sqrt(np.mean((per_sample - nominal)**2)))
                result["Device interval min (s)"] = float(np.min(per_sample))
                result["Device interval max (s)"] = float(np.max(per_sample))
        return result

    def continuity_note(self, count):
        times, sequences = self.recent(count)
        if self.sequence_enabled and (not np.all(np.isfinite(sequences)) or np.any(np.diff(sequences) != 1)):
            return "Selected sequence field has missing, repeated, skipped, or reset values in this window."
        if self.timestamp_enabled:
            if len(times) < 2 or not np.all(np.isfinite(times)):
                return "Waiting for valid device timestamps on every sample in this window."
            intervals = np.diff(times)
            if not np.all(np.isfinite(intervals)):
                return "Device timestamp intervals exceed the supported numeric range."
            if np.any(intervals <= 0):
                return "Device timestamps are repeated or move backwards in this window."
            nominal = np.median(intervals)
            if np.max(np.abs(intervals - nominal)) > nominal * 0.05:
                return "Device intervals vary by more than 5%; uniform-sampling tools are paused (no resampling is performed)."
        return ""
