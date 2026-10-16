"""Software edge-triggered captures. Triggering uses sample indices, never arrival time."""

from dataclasses import dataclass
import time

import numpy as np


@dataclass
class Capture:
    indices: np.ndarray
    values: np.ndarray
    trigger_index: int
    triggered: bool


class ScopeEngine:
    def __init__(self):
        self.size = 1000
        self.pretrigger = 0.3
        self.channel = 0
        self.level = 0.0
        self.edge = "Rising"
        self.mode = "Auto"
        self.holdoff = 0
        self.running = True
        self.capture = None
        self.pending = None
        self.scanned = -1
        self.next_allowed = 0
        self.last_capture_time = time.monotonic()
        self.count = 0

    def arm(self):
        self.running = True
        self.pending = None
        self.scanned = -1
        self.next_allowed = 0
        self.last_capture_time = time.monotonic()

    def reset(self):
        self.capture = None
        self.count = 0
        self.arm()

    def process(self, buffer, now=None):
        if not self.running or buffer.count < self.size:
            return False
        now = time.monotonic() if now is None else now
        # Extra retained history allows finding triggers between GUI refreshes.
        indices, values = buffer.snapshot(min(buffer.capacity, max(self.size * 3, 4096)))
        first, end = int(indices[0]), int(indices[-1]) + 1
        pre = int(self.size * self.pretrigger)
        post = self.size - pre
        if self.pending is not None and self.pending - pre < first:
            self.pending = None  # Buffer overwrite invalidated the unfinished capture.
        if self.pending is None:
            signal = values[:, self.channel]
            if self.edge == "Rising":
                crossed = (signal[:-1] < self.level) & (signal[1:] >= self.level)
            else:
                crossed = (signal[:-1] > self.level) & (signal[1:] <= self.level)
            candidates = np.flatnonzero(crossed) + first + 1
            eligible = candidates[(candidates > self.scanned) & (candidates >= first + pre) & (candidates >= self.next_allowed)]
            if len(eligible):
                # Latest complete capture gives the freshest display; single uses the first edge.
                complete = eligible[eligible + post <= end]
                self.pending = int(eligible[0] if self.mode == "Single" or not len(complete) else complete[-1])
            self.scanned = end - 1
        triggered = self.pending is not None and self.pending + post <= end
        auto = self.mode == "Auto" and now - self.last_capture_time >= 0.3
        if not triggered and not auto:
            return False
        trigger = self.pending if triggered else end - post
        offset = trigger - pre - first
        self.capture = Capture(indices[offset:offset + self.size].copy(),
                               values[offset:offset + self.size].copy(), int(trigger), bool(triggered))
        self.pending = None
        self.next_allowed = trigger + self.holdoff + 1
        self.last_capture_time = now
        self.count += 1
        if self.mode == "Single":
            self.running = False
        return True
