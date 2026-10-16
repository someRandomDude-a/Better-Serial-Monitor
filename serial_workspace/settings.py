"""Validated, portable preferences with atomic writes and legacy migration."""

from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import re
import tempfile


THEMES = ("Light", "Dark", "AMOLED", "Liquid Glass")
ANALYSIS_TOOLS = ("Histogram", "Autocorrelation", "Moving average", "Derivative", "Integral",
                  "A + B", "A - B", "A * B", "A / B", "XY / phase", "Rolling statistics",
                  "Low-pass filter", "High-pass filter", "Band-pass filter", "Band-stop filter",
                  "FFT band reconstruction", "Envelope", "Peaks", "Threshold events", "Acquisition metadata")
COLORS = ["#38bdf8", "#a78bfa", "#34d399", "#fb923c",
          "#f472b6", "#facc15", "#22d3ee", "#f87171"]


def settings_path():
    override = os.environ.get("SERIAL_MONITOR_SETTINGS")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    return base / "SerialMonitor" / "settings.json"


def valid_color(value):
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


@dataclass
class Settings:
    experience: str = "Monitor"
    show_tips: bool = True
    show_metrics: bool = False
    analysis_hz: int = 5
    theme: str = "Dark"
    accent: str = "#38bdf8"
    font_size: int = 10
    compact: bool = False
    sidebar: bool = True
    geometry: str = ""
    port: str = ""
    baud_rate: int = 115200
    custom_baud_rates: list = field(default_factory=list)
    data_bits: int = 8
    parity: str = "None"
    stop_bits: float = 1.0
    flow_control: str = "None"
    encoding: str = "utf-8"
    line_ending: str = "LF"
    timestamps: bool = True
    autoscroll: bool = True
    hex_display: bool = False
    max_lines: int = 5000
    sample_capacity: int = 32768
    refresh_hz: int = 20
    sample_rate: float = 1000.0
    timestamp_field: str = ""
    timestamp_unit: str = "Milliseconds"
    sequence_field: str = ""
    parser: str = "Auto"
    delimiter: str = ","
    fft_size: int = 2048
    window: str = "Hann"
    remove_dc: bool = True
    spectrum_scale: str = "dB"
    peak_hold: bool = False
    plot_window: float = 10.0
    grid: bool = True
    line_width: float = 1.5
    selected_channel: int = 0
    scope_timebase: float = 0.01
    scope_mode: str = "Auto"
    scope_edge: str = "Rising"
    scope_level: float = 0.0
    scope_source: int = 0
    scope_pretrigger: int = 30
    scope_holdoff: float = 0.0
    scope_scales: list = field(default_factory=lambda: [1.0] * 8)
    scope_offsets: list = field(default_factory=lambda: [0.0] * 8)
    scope_couplings: list = field(default_factory=lambda: ["DC"] * 8)
    analysis_tool: str = "Histogram"
    analysis_reference: int = 1
    smoothing: int = 16
    spectrum_view: str = "Amplitude FFT"
    spectrum_overlap: int = 50
    spectral_prominence: float = 10.0
    spectrogram_colormap: str = "viridis"
    spectrogram_range: float = 80.0
    spectrogram_auto_levels: bool = True
    spectrogram_min: float = -100.0
    spectrogram_max: float = 0.0
    fundamental: float = 0.0
    harmonic_count: int = 5
    filter_low: float = 10.0
    filter_high: float = 100.0
    filter_order: int = 4
    peak_prominence: float = 0.1
    peak_distance: int = 10
    event_threshold: float = 0.0
    event_hysteresis: float = 0.0
    channel_colors: list = field(default_factory=lambda: COLORS.copy())
    channel_names: list = field(default_factory=lambda: [""] * 8)
    channel_visible: list = field(default_factory=lambda: [True] * 8)
    unit: str = "units"

    @classmethod
    def from_dict(cls, raw):
        """Ignore unknown/invalid fields rather than trusting imported JSON."""
        result = cls()
        if not isinstance(raw, dict):
            return result
        raw = dict(raw)
        theme = raw.get("theme", "Dark")
        aliases = {name.lower(): name for name in THEMES}
        raw["theme"] = aliases.get(str(theme).lower(), "Dark")
        if "custom_accent_color" in raw and "accent" not in raw:
            raw["accent"] = raw["custom_accent_color"]
        choices = {
            "experience": ("Monitor", "Explore", "Advanced"),
            "timestamp_unit": ("Seconds", "Milliseconds", "Microseconds"),
            "spectrum_view": ("Amplitude FFT", "Phase", "Power density (Welch)", "Spectrogram", "Spectral peaks", "Harmonics & quality"),
            "spectrogram_colormap": ("viridis", "plasma", "inferno", "CET-L1"),
            "theme": THEMES, "data_bits": (5, 6, 7, 8),
            "parity": ("None", "Even", "Odd", "Mark", "Space"),
            "stop_bits": (1.0, 1.5, 2.0), "flow_control": ("None", "RTS/CTS", "XON/XOFF"),
            "encoding": ("utf-8", "ascii", "latin-1"),
            "line_ending": ("None", "LF", "CR", "CRLF"),
            "parser": ("Auto", "CSV", "Labels", "JSON"),
            "fft_size": (256, 512, 1024, 2048, 4096, 8192, 16384),
            "window": ("Hann", "Hamming", "Blackman", "Rectangular"),
            "spectrum_scale": ("dB", "Linear"),
            "scope_mode": ("Auto", "Normal", "Single"), "scope_edge": ("Rising", "Falling"),
            "scope_timebase": (0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02,
                               0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10),
            "analysis_tool": ANALYSIS_TOOLS,
        }
        bounds = {
            "font_size": (8, 18), "baud_rate": (50, 12000000),
            "max_lines": (100, 100000), "sample_capacity": (1024, 1000000),
            "refresh_hz": (5, 60), "sample_rate": (0.01, 10000000),
            "plot_window": (0.01, 3600), "line_width": (0.5, 5),
            "selected_channel": (0, 7),
            "scope_level": (-1e9, 1e9), "scope_source": (0, 7), "scope_pretrigger": (0, 90),
            "scope_holdoff": (0, 100000), "smoothing": (2, 512),
            "analysis_reference": (0, 7),
            "analysis_hz": (1, 20), "spectrum_overlap": (0, 90), "fundamental": (0, 5000000),
            "harmonic_count": (2, 20), "filter_low": (0, 5000000),
            "filter_high": (0.000001, 5000000), "filter_order": (1, 10),
            "peak_prominence": (0, 1e9), "peak_distance": (1, 100000),
            "event_threshold": (-1e9, 1e9), "event_hysteresis": (0, 1e9),
            "spectral_prominence": (0, 120), "spectrogram_range": (20, 160),
            "spectrogram_min": (-300, 300), "spectrogram_max": (-300, 300),
        }
        for key, default in asdict(result).items():
            value = raw.get(key, default)
            if key in choices:
                if not isinstance(value, bool) and value in choices[key]:
                    setattr(result, key, type(default)(value))
            elif key in bounds:
                low, high = bounds[key]
                if type(value) in (int, float) and low <= value <= high and math.isfinite(value):
                    setattr(result, key, type(default)(value))
            elif isinstance(default, bool):
                if isinstance(value, bool):
                    setattr(result, key, value)
            elif key == "accent":
                if valid_color(value):
                    result.accent = value
            elif key == "channel_colors":
                if isinstance(value, list) and len(value) == 8 and all(valid_color(c) for c in value):
                    result.channel_colors = value.copy()
            elif key == "channel_names":
                if isinstance(value, list) and len(value) == 8 and all(isinstance(n, str) for n in value):
                    result.channel_names = [n[:40] for n in value]
            elif key == "channel_visible":
                if isinstance(value, list) and len(value) == 8 and all(type(v) is bool for v in value):
                    result.channel_visible = value.copy()
            elif key in ("scope_scales", "scope_offsets"):
                low, high = (0.000001, 1e9) if key == "scope_scales" else (-1000, 1000)
                if isinstance(value, list) and len(value) == 8 and all(type(v) in (int, float) and low <= v <= high and math.isfinite(v) for v in value):
                    setattr(result, key, list(map(float, value)))
            elif key == "scope_couplings":
                if isinstance(value, list) and len(value) == 8 and all(v in ("AC", "DC") for v in value):
                    result.scope_couplings = value.copy()
            elif key == "custom_baud_rates":
                if isinstance(value, list):
                    result.custom_baud_rates = sorted({v for v in value if type(v) is int and 50 <= v <= 12000000})[:100]
            elif isinstance(default, str) and isinstance(value, str):
                setattr(result, key, value[:4096] if key == "geometry" else value[:200])
        if not result.delimiter or len(result.delimiter) != 1:
            result.delimiter = ","
        result.timestamp_field = result.timestamp_field.strip()[:40]
        result.sequence_field = result.sequence_field.strip()[:40]
        if result.sequence_field and result.sequence_field == result.timestamp_field:
            result.sequence_field = ""
        if result.spectrogram_min >= result.spectrogram_max:
            result.spectrogram_min, result.spectrogram_max = -100.0, 0.0
        return result

    @classmethod
    def load(cls, path=None):
        target = Path(path) if path else settings_path()
        legacy = Path.cwd() / "settings.json"
        if path is None and not os.environ.get("SERIAL_MONITOR_SETTINGS") and not target.exists() and legacy.exists():
            target = legacy
        if not target.exists():
            return cls(), ""
        try:
            return cls.from_dict(json.loads(target.read_text(encoding="utf-8"))), ""
        except (OSError, ValueError, RecursionError) as exc:
            return cls(), f"Could not load settings; defaults are in use. {exc}"

    def save(self, path=None):
        target = Path(path) if path else settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                             suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(asdict(self), handle, indent=2, allow_nan=False)
            os.replace(temporary, target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
