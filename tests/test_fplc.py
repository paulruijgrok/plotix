"""Tests for the FPLC reader and chromatogram plot."""

from __future__ import annotations

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from plotix.formats.fplc.channels import normalise_run_date  # noqa: E402
from plotix.formats.fplc.plot import MIN_DISPLAY_SPAN, plot_chromatogram  # noqa: E402
from plotix.formats.fplc.reader import read_asc, sniff_asc  # noqa: E402

# ----------------------------------------------------------------------- reader


def test_read_asc_parses_curves_and_events(simple_asc):
    ds = read_asc(simple_asc)

    assert ds.format == "fplc"
    assert set(ds.curves) >= {"UV", "Conductivity", "Concentration B"}
    uv = ds.require("UV")
    assert uv.y_unit == "mAU"
    assert uv.x_unit == "ml"
    assert uv.x_label == "Volume"
    assert uv.kind == "uv"
    assert len(uv) == 200

    assert len(ds.events_of("fraction")) == 8
    assert len(ds.events_of("injection")) == 1
    assert ds.events_of("injection")[0].x == pytest.approx(0.5)


def test_read_asc_handles_ragged_channel_lengths(simple_asc):
    ds = read_asc(simple_asc)
    # Conductivity is deliberately sampled at half the UV rate in the fixture.
    assert len(ds.require("Conductivity")) == 100
    assert len(ds.require("UV")) == 200


def test_read_asc_x_is_monotonic_and_finite(simple_asc):
    ds = read_asc(simple_asc)
    for curve in ds.curves.values():
        assert np.all(np.isfinite(curve.x)) and np.all(np.isfinite(curve.y))
        assert np.all(np.diff(curve.x) >= 0)


def test_read_asc_extracts_run_metadata(simple_asc):
    ds = read_asc(simple_asc)
    assert ds.meta["run_name"] == "test run 001"
    assert ds.meta["column"] == "Superdex 200 10/300 GL"
    assert ds.meta["column_volume"] == pytest.approx(23.56)
    assert ds.meta["method"] == "testmtd"
    assert ds.meta["run_started"] == "2026-09-02 17:41"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "cp1252"])
def test_read_asc_survives_encoding_variants(asc_factory, encoding):
    path = asc_factory(f"enc_{encoding}.asc", encoding=encoding)
    ds = read_asc(path)
    assert len(ds.require("UV")) == 200


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_read_asc_survives_line_ending_variants(asc_factory, newline):
    path = asc_factory("le.asc", newline=newline)
    assert len(read_asc(path).require("UV")) == 200


def test_read_asc_without_curve_count_row(asc_factory):
    """Header rows are located by content, not by a fixed preamble length."""
    path = asc_factory("nocount.asc", include_count_row=False)
    ds = read_asc(path)
    assert len(ds.require("UV")) == 200
    assert ds.meta["run_name"] == "test run 001"


def test_read_asc_without_logbook(asc_factory):
    path = asc_factory("nolog.asc", include_logbook=False)
    ds = read_asc(path)
    assert "column" not in ds.meta
    assert ds.events_of("logbook") == []


def test_read_asc_can_drop_logbook_events(simple_asc):
    assert read_asc(simple_asc, keep_logbook=False).events_of("logbook") == []
    assert read_asc(simple_asc, keep_logbook=True).events_of("logbook")


def test_read_asc_rejects_a_non_unicorn_file(tmp_path):
    path = tmp_path / "junk.asc"
    path.write_text("this is not a chromatogram\n")
    with pytest.raises(ValueError, match="no numeric data rows"):
        read_asc(path)


def test_sniff_asc():
    assert sniff_asc("run:10_UV\tml\t mAU\n0.0\t1.0")
    assert not sniff_asc("id,name,value\n1,a,2")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9/2/2026, 5:41:13 PM Pacific Daylight Time", "2026-09-02 17:41"),
        ("12/31/2025, 11:05:00 AM UTC", "2025-12-31 11:05"),
        ("not a date", "not a date"),
    ],
)
def test_normalise_run_date(raw, expected):
    assert normalise_run_date(raw) == expected


# ------------------------------------------------------------------------- plot


def test_plot_chromatogram_returns_source_data_matching_the_plot(simple_asc):
    bundle = plot_chromatogram(simple_asc)
    try:
        assert bundle.stem == "run"
        assert set(bundle.source_data["series"]) == {"UV"}
        # Every plotted sample is present in the source data.
        ds = read_asc(simple_asc)
        assert len(bundle.source_data) == len(ds.require("UV"))
        assert "marks" in bundle.tables
        assert set(bundle.tables["marks"]["kind"]) == {"fraction", "injection"}
    finally:
        bundle.close()


def test_auto_auxiliary_drops_flat_channels_and_keeps_gradients(simple_asc, gradient_asc):
    flat = plot_chromatogram(simple_asc)
    try:
        assert flat.meta["channels_plotted"] == ["UV"]
    finally:
        flat.close()

    gradient = plot_chromatogram(gradient_asc)
    try:
        assert "Conductivity" in gradient.meta["channels_plotted"]
        assert set(gradient.source_data["series"]) == set(
            gradient.meta["channels_plotted"]
        )
    finally:
        gradient.close()


def test_explicit_auxiliary_overrides_auto_selection(simple_asc):
    bundle = plot_chromatogram(simple_asc, auxiliary="Conductivity")
    try:
        assert bundle.meta["channels_plotted"] == ["UV", "Conductivity"]
    finally:
        bundle.close()

    with pytest.raises(KeyError, match="not in dataset"):
        plot_chromatogram(simple_asc, auxiliary="Nonexistent")


def test_auxiliary_none_plots_only_the_signal(gradient_asc):
    bundle = plot_chromatogram(gradient_asc, auxiliary="none")
    try:
        assert bundle.meta["channels_plotted"] == ["UV"]
        assert len(bundle.figure.axes) == 1
    finally:
        bundle.close()


def test_flat_auxiliary_axis_is_not_magnified(simple_asc):
    """A forced flat channel must not have its ripple stretched across the axis."""
    bundle = plot_chromatogram(simple_asc, auxiliary="Conductivity")
    try:
        twin = bundle.figure.axes[1]
        lo, hi = twin.get_ylim()
        assert (hi - lo) >= MIN_DISPLAY_SPAN["Conductivity"]
    finally:
        bundle.close()


def test_peaks_are_detected_and_tabulated(simple_asc):
    bundle = plot_chromatogram(simple_asc)
    try:
        peaks = bundle.tables["peaks"]
        assert len(peaks) == 2
        assert peaks["Volume (ml)"].tolist() == pytest.approx([6.0, 12.0], abs=0.15)
        assert bundle.meta["n_peaks"] == 2
    finally:
        bundle.close()


def test_peaks_can_be_disabled(simple_asc):
    bundle = plot_chromatogram(simple_asc, annotate_peaks_=False)
    try:
        assert "peaks" not in bundle.tables
        assert bundle.meta["n_peaks"] == 0
    finally:
        bundle.close()


def test_xlim_restricts_the_axis(simple_asc):
    bundle = plot_chromatogram(simple_asc, xlim=(5.0, 15.0))
    try:
        assert bundle.figure.axes[0].get_xlim() == (5.0, 15.0)
    finally:
        bundle.close()


def test_title_and_subtitle_can_be_overridden(simple_asc):
    bundle = plot_chromatogram(simple_asc, title="Custom", subtitle="", caption="")
    try:
        assert bundle.figure.axes[0].get_title(loc="left").startswith("Custom")
    finally:
        bundle.close()


def test_missing_signal_channel_raises(simple_asc):
    with pytest.raises(KeyError):
        plot_chromatogram(simple_asc, signal="UV7")


def test_plot_accepts_an_already_parsed_dataset(simple_asc):
    ds = read_asc(simple_asc)
    bundle = plot_chromatogram(ds)
    try:
        assert bundle.meta["run_name"] == "test run 001"
    finally:
        bundle.close()


def test_saving_writes_every_requested_artefact(simple_asc, tmp_path):
    bundle = plot_chromatogram(simple_asc)
    written = bundle.save(tmp_path, formats=("png", "pdf", "svg"), close=True)
    names = {p.name for p in written}
    assert {
        "run.png",
        "run.pdf",
        "run.svg",
        "run_source_data.csv",
        "run_marks.csv",
        "run_peaks.csv",
    } == names


# ------------------------------------------------------------------ integration


def test_example_run_parses_as_expected(example_asc):
    ds = read_asc(example_asc)
    assert ds.meta["column"] == "Superdex 200 10/300 GL"
    assert ds.require("UV").x_unit == "ml"
    assert len(ds.events_of("fraction")) > 10
    # An isocratic SEC run: the gradient channel never moves.
    assert ds.require("Concentration B").span == 0.0


def test_example_run_plots_and_finds_peaks(example_asc, tmp_path):
    bundle = plot_chromatogram(example_asc)
    try:
        assert bundle.meta["channels_plotted"] == ["UV"]
        assert bundle.meta["n_peaks"] >= 3
    finally:
        written = bundle.save(tmp_path, formats=("png",), close=True)
    assert (tmp_path / "20260902_PfLDH_Nb02P_source_data.csv") in written
