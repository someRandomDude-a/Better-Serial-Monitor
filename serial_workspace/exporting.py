"""Background exports use detached snapshots; workers never touch widgets."""

import csv
import json
from pathlib import Path

import numpy as np
from PySide6 import QtCore


class ExportSignals(QtCore.QObject):
    finished = QtCore.Signal(str, str)


class ExportJob(QtCore.QRunnable):
    def __init__(self, path, operation):
        super().__init__()
        self.path = path
        self.operation = operation
        self.signals = ExportSignals()

    def run(self):
        try:
            self.operation(self.path)
        except Exception as exc:
            self.signals.finished.emit(self.path, str(exc))
        else:
            self.signals.finished.emit(self.path, "")


def write_samples(path, indices, values, rate, names, trigger=None):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if trigger is None:
            writer.writerow(["sample_index", "sample_time_s"] + names)
        else:
            writer.writerow(["time_from_trigger_s"] + names)
        for index, row in zip(indices, values):
            prefix = [int(index), f"{index / rate:.12g}"] if trigger is None else [f"{(index - trigger) / rate:.12g}"]
            writer.writerow(prefix + [f"{v:.12g}" if np.isfinite(v) else "" for v in row])


def write_log(path, text):
    Path(path).write_text(text, encoding="utf-8")


def write_table(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if value is None or isinstance(value, (float, np.floating)) and not np.isfinite(value) else value for value in row])


def write_spectral(path, result):
    """Stream potentially large spectrogram exports on the file worker, not the GUI."""
    view = result["view"]
    if view == "Harmonics & quality":
        columns = ["harmonic", "frequency_hz", "rms_amplitude", "relative_dbc", "phase_sine_deg"]
        rows = result["rows"]
    elif view == "Spectral peaks":
        columns = ["frequency_estimate_hz", "peak_bin_amplitude", "relative_db", "half_prominence_width_hz", "fft_bin"]
        rows = result["rows"]
    elif view == "Spectrogram":
        columns = ["sample_time_s", "frequency_hz", "power_density_unit2_per_hz"]
        rows = ((float(t), float(f), float(result["density"][i,j])) for j,t in enumerate(result["t"]) for i,f in enumerate(result["f"]))
    else:
        columns = ["frequency_hz", "amplitude_peak", "phase_cosine_deg"]
        arrays = [result["f"], result["amplitude"], result["phase"]]
        if "density" in result:
            columns.append("power_density_unit2_per_hz")
            arrays.append(result["density"])
        rows = zip(*arrays)
    write_table(path, columns, rows)


def write_report(path, report):
    def clean(value):
        if isinstance(value, dict):
            return {str(k): clean(v) for k,v in value.items()}
        if isinstance(value, (list, tuple, np.ndarray)):
            return [clean(v) for v in value]
        if isinstance(value, (float, np.floating)):
            return float(value) if np.isfinite(value) else None
        if isinstance(value, np.integer):
            return int(value)
        return value
    Path(path).write_text(json.dumps(clean(report), indent=2, allow_nan=False), encoding="utf-8")
