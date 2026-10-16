import csv
import json

import numpy as np

from serial_workspace.exporting import write_report, write_spectral, write_table


def test_table_blanks_non_finite_values_and_quotes_text(tmp_path):
    path = tmp_path / "table.csv"
    write_table(path, ["value", "note"], [[np.nan, "a,b"], [np.inf, None], [2.5, True]])
    with path.open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1] == ["", "a,b"]
    assert rows[2] == ["", ""]
    assert rows[3] == ["2.5", "True"]


def test_report_produces_strict_json_and_nulls(tmp_path):
    path = tmp_path / "report.json"
    write_report(path, {"values": np.array([1, np.nan, np.inf]), "count": np.int64(3)})
    assert json.loads(path.read_text()) == {"values": [1, None, None], "count": 3}


def test_spectrogram_export_streams_long_form_rows(tmp_path):
    result = dict(view="Spectrogram", f=np.array([0, 10, 20]), t=np.array([0.5, 1.5]),
                  density=np.arange(6).reshape(3,2))
    path = tmp_path / "stft.csv"
    write_spectral(path, result)
    with path.open(newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 7
    assert rows[1] == ["0.5", "0.0", "0.0"]
    assert rows[-1] == ["1.5", "20.0", "5.0"]
