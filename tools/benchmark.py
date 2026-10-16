"""Local synthetic microbenchmark; not a sustained serial/GUI throughput claim."""

from pathlib import Path
import platform
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serial_workspace.analysis import spectrum
from serial_workspace.stream import NumericParser, SampleBuffer


def main():
    parser = NumericParser()
    count = 50000
    start = time.perf_counter()
    for _ in range(count):
        parser.parse("0.125,1.25,-0.5")
    elapsed = time.perf_counter() - start
    print(f"Python {platform.python_version()} / NumPy {np.__version__} / {platform.system()}")
    print(f"Parse 3-channel CSV: {count / elapsed:,.0f} rows/s ({elapsed:.3f} s)")

    buffer = SampleBuffer()
    batch = np.random.default_rng(42).normal(size=(1024, 8)).tolist()
    start = time.perf_counter()
    for _ in range(100):
        buffer.append(batch)
    print(f"Append 102,400 eight-channel rows: {time.perf_counter() - start:.3f} s")

    signal = np.sin(2 * np.pi * 50 * np.arange(8192) / 1000)
    start = time.perf_counter()
    for _ in range(200):
        spectrum(signal, 1000, 8192)
    print(f"8,192-point windowed FFT: {(time.perf_counter() - start) * 1000 / 200:.3f} ms/transform")
    print("Synthetic core timings only; excludes serial I/O, GUI, logging and exports.")


if __name__ == "__main__":
    main()
