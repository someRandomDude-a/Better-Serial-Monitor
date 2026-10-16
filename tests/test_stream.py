import numpy as np
import pytest

from serial_workspace.stream import LineFramer, NumericParser, SampleBuffer


def test_framing_across_chunks_and_mixed_endings():
    framer = LineFramer()
    assert framer.feed(b"1,2\r") == [b"1,2"]
    assert framer.feed(b"\n3\n4\r5") == [b"3", b"4"]
    assert framer.feed(b"6\n") == [b"56"]


def test_oversized_line_discards_until_terminator():
    framer = LineFramer(limit=4)
    assert framer.feed(b"12345") == []
    assert framer.feed(b"67\n9\n") == [b"9"]
    assert framer.oversized == 1


@pytest.mark.parametrize("text,expected", [
    ("1,2,-3e-2", (1, 2, -0.03)), ("1 2 3", (1, 2, 3)), (".25", (0.25,)),
])
def test_numeric_parser(text, expected):
    assert NumericParser().parse(text).values == expected


@pytest.mark.parametrize("text", ["hello", "a,b,c", "1,nan", "inf", "1,", "x: nan", "{}", "[]"])
def test_non_numeric_records(text):
    assert NumericParser().parse(text) is None


def test_named_channels_are_stable_and_gaps_are_nan():
    parser = NumericParser()
    first = parser.parse("temperature:20, pressure=101").values
    second = parser.parse('{"pressure": 102, "enabled": true, "note": "x"}').values
    assert first[:2] == (20, 101)
    assert np.isnan(second[0])
    assert second[1] == 102
    assert parser.names == ["temperature", "pressure"]


def test_csv_custom_delimiter_and_channel_limit():
    parser = NumericParser(mode="CSV", delimiter=";")
    assert parser.parse("1;2;3;4;5;6;7;8;9").values == tuple(range(1, 9))
    assert len(parser.names) == 8


def test_ring_wrap_and_large_batch():
    buffer = SampleBuffer(capacity=4, channels=2)
    buffer.append([(1,), (2, 20), (3,)])
    buffer.append([(4,), (5,)])
    indices, values = buffer.snapshot()
    np.testing.assert_array_equal(indices, [1, 2, 3, 4])
    np.testing.assert_array_equal(values[:, 0], [2, 3, 4, 5])
    assert np.isnan(values[1, 1])
    buffer.append([(n,) for n in range(6, 16)])
    indices, values = buffer.snapshot(2)
    np.testing.assert_array_equal(indices, [13, 14])
    np.testing.assert_array_equal(values[:, 0], [14, 15])
    buffer.append([(16,)])
    np.testing.assert_array_equal(buffer.snapshot()[1][:, 0], [13, 14, 15, 16])
    buffer.clear()
    assert buffer.count == buffer.total == 0


def test_ring_matches_reference_over_many_batches():
    rng = np.random.default_rng(42)
    buffer = SampleBuffer(97, 3)
    reference = []
    for _ in range(100):
        batch = rng.normal(size=(int(rng.integers(1, 150)), 3)).tolist()
        buffer.append(batch)
        reference.extend(batch)
        np.testing.assert_allclose(buffer.snapshot()[1], reference[-97:])
