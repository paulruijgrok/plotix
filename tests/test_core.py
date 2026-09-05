"""Tests for the format-agnostic core: containers, io, peaks, export, registry."""

from __future__ import annotations

import numpy as np
import pytest

from plotix.core.dataset import Curve, Dataset, Event
from plotix.core.export import FigureBundle, curves_to_long_frame, slugify
from plotix.core.io import detect_encoding, parse_number, read_text
from plotix.core.peaks import find_peaks, peaks_to_frame
from plotix.core.registry import detect_format, get_format, list_formats
from plotix.core.theme import THEMES, Theme, active_theme, get_theme, use

# --------------------------------------------------------------------------- io


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("1.5", 1.5),
        ("  -0.002000 ", -0.002),
        ('"3"', 3.0),
        ("1,5", 1.5),  # European decimal comma
        ("", None),
        ("   ", None),
        ('"Waste"', None),
        ("abc", None),
    ],
)
def test_parse_number(token, expected):
    assert parse_number(token) == expected


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "cp1252", "latin-1"])
def test_read_text_round_trips_encodings(tmp_path, encoding):
    text = "Temp\t°C\nvalue\t34.0\n"
    path = tmp_path / f"sample_{encoding}.txt"
    path.write_bytes(text.encode(encoding))
    assert read_text(path) == text


def test_detect_encoding_uses_bom():
    assert detect_encoding("x".encode("utf-16")) in {"utf-16-le", "utf-16-be"}
    assert detect_encoding(b"plain ascii") is None


# ---------------------------------------------------------------------- dataset


def test_curve_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same shape"):
        Curve(name="bad", x=np.arange(3), y=np.arange(4))


def test_curve_span_and_clip():
    curve = Curve(name="c", x=np.linspace(0, 10, 11), y=np.arange(11.0))
    assert curve.span == 10.0
    clipped = curve.clip(2.0, 5.0)
    assert clipped.x.min() == 2.0 and clipped.x.max() == 5.0
    assert len(clipped) == 4
    assert curve.y_axis_label == "y"


def test_curve_axis_labels_include_units():
    curve = Curve(
        name="UV", x=np.arange(3.0), y=np.arange(3.0), x_label="Volume", x_unit="ml",
        y_label="UV", y_unit="mAU",
    )
    assert curve.x_axis_label == "Volume (ml)"
    assert curve.y_axis_label == "UV (mAU)"


def test_dataset_lookup_is_case_insensitive_and_require_raises():
    ds = Dataset(name="d", format="test")
    ds.add_curve(Curve(name="UV", x=np.arange(3.0), y=np.arange(3.0)))
    ds.add_event(Event(x=1.0, label="1", kind="fraction"))

    assert ds.get("uv") is not None
    assert ds.get("missing") is None
    assert ds.require("UV").name == "UV"
    with pytest.raises(KeyError):
        ds.require("nope")
    assert len(ds.events_of("fraction")) == 1
    assert ds.events_of("injection") == []


def test_dataset_x_range_unions_curves():
    ds = Dataset(name="d", format="test")
    ds.add_curve(Curve(name="a", x=np.array([0.0, 5.0]), y=np.zeros(2)))
    ds.add_curve(Curve(name="b", x=np.array([2.0, 9.0]), y=np.zeros(2)))
    assert ds.x_range() == (0.0, 9.0)


# ------------------------------------------------------------------------ peaks


def test_find_peaks_recovers_known_gaussians():
    x = np.linspace(0, 20, 2000)
    y = (
        100 * np.exp(-0.5 * ((x - 5) / 0.4) ** 2)
        + 40 * np.exp(-0.5 * ((x - 12) / 0.6) ** 2)
    )
    curve = Curve(name="UV", x=x, y=y, x_label="Volume", x_unit="ml", y_unit="mAU")

    peaks = find_peaks(curve)
    assert len(peaks) == 2
    assert peaks[0].x == pytest.approx(5.0, abs=0.05)
    assert peaks[1].x == pytest.approx(12.0, abs=0.05)
    assert peaks[0].height == pytest.approx(100.0, rel=0.02)
    # Analytic area of a Gaussian: height * sigma * sqrt(2*pi), measured here
    # only across the half-height window, so just check it is positive and
    # that the larger peak has the larger area.
    assert peaks[0].area > peaks[1].area > 0


def test_find_peaks_respects_window_and_max():
    x = np.linspace(0, 20, 2000)
    y = sum(100 * np.exp(-0.5 * ((x - c) / 0.3) ** 2) for c in (3, 8, 13, 18))
    curve = Curve(name="UV", x=x, y=y)

    assert len(find_peaks(curve, max_peaks=2)) == 2
    windowed = find_peaks(curve, xmin=6.0, xmax=15.0)
    assert [round(p.x) for p in windowed] == [8, 13]


def test_find_peaks_on_flat_curve_returns_nothing():
    curve = Curve(name="flat", x=np.linspace(0, 10, 100), y=np.zeros(100))
    assert find_peaks(curve) == []


def test_peaks_to_frame_labels_columns_with_units():
    x = np.linspace(0, 10, 500)
    curve = Curve(
        name="UV", x=x, y=100 * np.exp(-0.5 * ((x - 5) / 0.4) ** 2),
        x_label="Volume", x_unit="ml", y_unit="mAU",
    )
    frame = peaks_to_frame(find_peaks(curve), curve)
    assert "Volume (ml)" in frame.columns
    assert "height (mAU)" in frame.columns
    assert len(frame) == 1
    assert peaks_to_frame([], curve).empty


# ----------------------------------------------------------------------- export


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("run 001", "run_001"),
        ("a/b\\c", "a_b_c"),
        ("  spaced  ", "spaced"),
        ("!!!", "figure"),
        ("keep.dots-and_dashes", "keep.dots-and_dashes"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_curves_to_long_frame_keeps_every_sample():
    a = Curve(name="a", x=np.arange(4.0), y=np.arange(4.0), y_unit="mAU")
    b = Curve(name="b", x=np.arange(2.0), y=np.arange(2.0), y_unit="mS/cm")
    frame = curves_to_long_frame([a, b])

    assert len(frame) == 6
    assert set(frame["series"]) == {"a", "b"}
    assert frame.loc[frame["series"] == "b", "y_unit"].unique().tolist() == ["mS/cm"]
    assert curves_to_long_frame([]).empty


def test_figure_bundle_saves_figures_and_csvs(tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    bundle = FigureBundle(
        figure=fig,
        stem="demo",
        source_data=pd.DataFrame({"series": ["a"], "x": [0.0], "y": [1.0]}),
        tables={"peaks": pd.DataFrame({"peak": [1]}), "empty": pd.DataFrame()},
    )
    written = bundle.save(tmp_path, formats=("png", "svg"), close=True)
    names = {p.name for p in written}

    assert {"demo.png", "demo.svg", "demo_source_data.csv", "demo_peaks.csv"} <= names
    assert "demo_empty.csv" not in names
    assert all(p.exists() for p in written)


def test_figure_bundle_can_skip_source_data(tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    fig, _ = plt.subplots()
    bundle = FigureBundle(
        figure=fig, stem="nodata", source_data=pd.DataFrame({"x": [1.0]})
    )
    written = bundle.save(tmp_path, formats=("png",), write_source_data=False, close=True)
    assert [p.name for p in written] == ["nodata.png"]


# ------------------------------------------------------------------ theme/registry


def test_theme_context_restores_previous_theme():
    before = active_theme()
    with use("publication") as th:
        assert th.name == "publication"
        assert active_theme() is th
    assert active_theme() is before


def test_get_theme_accepts_instance_and_rejects_unknown():
    custom = Theme(name="custom")
    assert get_theme(custom) is custom
    assert get_theme("publication") is THEMES["publication"]
    with pytest.raises(KeyError, match="unknown theme"):
        get_theme("nope")


def test_theme_rc_params_are_complete():
    rc = THEMES["publication"].rc_params()
    assert rc["pdf.fonttype"] == 42  # editable text in vector output
    assert rc["svg.fonttype"] == "none"
    assert rc["axes.spines.top"] is False


def test_registry_knows_fplc(simple_asc):
    names = [spec.name for spec in list_formats()]
    assert "fplc" in names
    assert get_format("akta").name == "fplc"  # alias
    assert detect_format(simple_asc).name == "fplc"
    with pytest.raises(KeyError, match="unknown format"):
        get_format("does-not-exist")


def test_detect_format_returns_none_for_unknown_extension(tmp_path):
    path = tmp_path / "thing.xyz"
    path.write_text("nothing to see")
    assert detect_format(path) is None
