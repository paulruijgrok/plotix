"""Tests for the native UNICORN ``.res`` reader.

The format is undocumented, so these tests carry more weight than usual: they
are the only thing standing between a layout assumption and a silently wrong
figure. Two kinds of check are used together —

* against synthetic files built in ``conftest``, where the expected numbers are
  known exactly and awkward variants (blank channel names, names shifted
  against their curves, a gradient run) can be produced on demand;
* against the real example run, whose ASCII export is an independent record of
  the same data, so the binary reader can be checked point-for-point against
  something it had no part in producing.
"""

from __future__ import annotations

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from plotix.api import plot as plot_source  # noqa: E402
from plotix.core.registry import detect_format  # noqa: E402
from plotix.formats.fplc import plot_chromatogram, read_fplc  # noqa: E402
from plotix.formats.fplc.res import read_res, sniff_res  # noqa: E402

# --------------------------------------------------------------- basic parsing


def test_read_res_finds_all_channels(simple_res):
    ds = read_res(simple_res)
    assert set(ds.curves) == {"UV", "Conductivity", "Concentration B"}
    assert ds.require("UV").y_unit == "mAU"
    assert ds.require("UV").x_unit == "ml"
    assert ds.require("UV").kind == "uv"
    assert ds.meta["source_format"] == "res"
    assert ds.meta["software"].startswith("UNICORN")


def test_read_res_splits_events_by_kind(simple_res):
    ds = read_res(simple_res)
    assert len(ds.events_of("fraction")) == 6
    assert len(ds.events_of("injection")) == 1
    assert len(ds.events_of("logbook")) == 3
    assert [e.label for e in ds.events_of("fraction")] == ["1", "2", "3", "4", "5", "6"]


def test_read_res_extracts_metadata_from_the_logbook(simple_res):
    ds = read_res(simple_res)
    assert ds.meta["run_name"] == "test run 001"
    assert ds.meta["column"] == "Superdex 200 10/300 GL"
    assert ds.meta["column_volume"] == pytest.approx(23.56)
    assert ds.meta["method"] == "testmtd"
    assert ds.meta["run_started"] == "2026-09-02 17:41"


def test_read_res_rejects_other_files(tmp_path):
    path = tmp_path / "not.res"
    path.write_bytes(b"just some bytes, definitely not UNICORN")
    with pytest.raises(ValueError, match="not a UNICORN .res"):
        read_res(path)


def test_sniff_res():
    assert sniff_res(b"\x11G\x11G\x18\x00\x00\x00")
    assert not sniff_res(b"run:10_UV\tml")


def test_directory_is_found_wherever_it_sits(res_factory):
    """The directory offset is not fixed, so it must be located by content."""
    for offset in (2048, 4099, 9001):
        ds = read_res(res_factory(f"at{offset}.res", directory_offset=offset))
        assert set(ds.curves) == {"UV", "Conductivity", "Concentration B"}


# ------------------------------------------------- robustness to bad names
#
# Real files disagree about where — and whether — channel names are written, so
# the reader identifies curves from their axis descriptors instead.


def test_channels_are_identified_without_any_names(res_factory):
    ds = read_res(res_factory("noname.res", name_curves=False))
    assert set(ds.curves) == {"UV", "Conductivity", "Concentration B"}
    assert len(ds.events_of("fraction")) == 6


def test_channels_survive_names_shifted_against_their_curves(res_factory):
    """Some files label each curve with the *previous* curve's name."""
    ds = read_res(res_factory("shifted.res", shift_names=True))
    assert ds.require("UV").y_unit == "mAU"
    assert ds.require("Conductivity").y_unit == "mS/cm"
    assert ds.require("Concentration B").y_unit == "%B"
    # The unnamed entry is the logbook, and must not be dropped or mistaken for
    # the injection channel.
    assert len(ds.events_of("logbook")) == 3
    assert len(ds.events_of("injection")) == 1
    assert ds.meta["column"] == "Superdex 200 10/300 GL"


def test_logbook_and_injection_are_told_apart_by_content(simple_res):
    ds = read_res(simple_res)
    logbook = ds.events_of("logbook")
    injection = ds.events_of("injection")
    assert any("Method Run" in e.label for e in logbook)
    assert [e.label for e in injection] == ["3"]


# ------------------------------------------------------------- volume origin


def test_default_origin_is_the_injection(simple_res):
    ds = read_res(simple_res)
    assert ds.meta["volume_origin"] == pytest.approx(2.0)
    # Peaks were placed at 8.0 and 14.0 in accumulated volume.
    uv = ds.require("UV")
    assert uv.x.min() >= 0.0
    assert uv.x[uv.y.argmax()] == pytest.approx(6.0, abs=0.05)
    assert ds.events_of("injection")[0].x == pytest.approx(0.0, abs=1e-9)
    assert ds.events_of("fraction")[0].x == pytest.approx(1.0, abs=0.01)


def test_origin_start_keeps_the_instrument_axis(simple_res):
    ds = read_res(simple_res, origin="start")
    assert ds.meta["volume_origin"] == 0.0
    uv = ds.require("UV")
    assert uv.x[uv.y.argmax()] == pytest.approx(8.0, abs=0.05)
    assert ds.events_of("injection")[0].x == pytest.approx(2.0, abs=0.01)


def test_explicit_numeric_origin(simple_res):
    ds = read_res(simple_res, origin=4.0)
    assert ds.meta["volume_origin"] == 4.0
    uv = ds.require("UV")
    assert uv.x[uv.y.argmax()] == pytest.approx(4.0, abs=0.05)


def test_trim_false_keeps_pre_injection_data(simple_res):
    trimmed = read_res(simple_res)
    kept = read_res(simple_res, trim=False)
    assert kept.require("UV").x.min() < 0
    assert len(kept.require("UV")) > len(trimmed.require("UV"))
    # Both describe the same run, so the peak lands in the same place.
    for ds in (trimmed, kept):
        uv = ds.require("UV")
        assert uv.x[uv.y.argmax()] == pytest.approx(6.0, abs=0.05)


def test_logbook_marks_are_never_trimmed(simple_res):
    """Logbook entries describe the method set-up and precede the injection."""
    ds = read_res(simple_res)
    logbook = ds.events_of("logbook")
    assert logbook and all(e.x < 0 for e in logbook)


def test_bad_origin_is_rejected(simple_res):
    with pytest.raises(ValueError, match="origin must be"):
        read_res(simple_res, origin="middle")


def test_keep_logbook_false_drops_the_events_but_keeps_the_metadata(simple_res):
    ds = read_res(simple_res, keep_logbook=False)
    assert ds.events_of("logbook") == []
    assert ds.meta["column"] == "Superdex 200 10/300 GL"


# -------------------------------------------------------------- dispatch


def test_read_fplc_dispatches_on_content_not_extension(res_factory, tmp_path):
    """A .res misnamed as .asc must still be read as binary."""
    misnamed = res_factory("misnamed.asc")
    ds = read_fplc(misnamed)
    assert ds.meta["source_format"] == "res"


def test_read_fplc_reads_both_forms(simple_res, simple_asc):
    assert read_fplc(simple_res).meta["source_format"] == "res"
    assert read_fplc(simple_asc).meta["source_format"] == "asc"


def test_res_only_kwargs_are_harmless_for_asc(simple_asc):
    ds = read_fplc(simple_asc, origin="start", trim=False)
    assert ds.meta["source_format"] == "asc"


def test_read_fplc_still_rejects_typos(simple_res):
    with pytest.raises(TypeError, match="unexpected keyword"):
        read_fplc(simple_res, orgin="injection")


def test_detect_format_recognises_res(simple_res):
    assert detect_format(simple_res).name == "fplc"


# ------------------------------------------------------------------ plotting


def test_plot_from_res_produces_the_usual_bundle(simple_res, tmp_path):
    bundle = plot_chromatogram(simple_res)
    written = bundle.save(tmp_path, formats=("png",), close=True)
    names = {p.name for p in written}
    assert {
        "run.png",
        "run_source_data.csv",
        "run_marks.csv",
        "run_peaks.csv",
    } == names


def test_plot_origin_options_reach_the_reader(simple_res):
    default = plot_chromatogram(simple_res)
    raw = plot_chromatogram(simple_res, origin="start")
    try:
        assert default.source_data["x"].min() >= 0
        assert default.tables["peaks"].iloc[0]["Volume (ml)"] == pytest.approx(6.0, abs=0.05)
        assert raw.tables["peaks"].iloc[0]["Volume (ml)"] == pytest.approx(8.0, abs=0.05)
    finally:
        default.close()
        raw.close()


def test_api_plot_accepts_res(simple_res):
    bundle = plot_source(simple_res)
    try:
        assert bundle.meta["format"] == "fplc"
    finally:
        bundle.close()


# ------------------------------------- cross-validation against the real export


def test_res_and_asc_of_the_same_run_agree(example_res, example_asc):
    """The strongest check available: two independent records of one run."""
    res = read_fplc(example_res)
    asc = read_fplc(example_asc)

    for key in ("run_name", "column", "method", "run_started"):
        assert res.meta[key] == asc.meta[key], key

    # Fraction marks are exact values in both forms, so they must match exactly.
    assert [(round(e.x, 3), e.label) for e in res.events_of("fraction")] == [
        (round(e.x, 3), e.label) for e in asc.events_of("fraction")
    ]

    res_uv, asc_uv = res.require("UV"), asc.require("UV")
    # The export is decimated; the .res holds the full-rate data.
    assert len(res_uv) > 10 * len(asc_uv)
    assert res_uv.x.min() == pytest.approx(asc_uv.x.min(), abs=0.02)
    assert res_uv.x.max() == pytest.approx(asc_uv.x.max(), abs=0.02)

    # Compare on the export's own grid: agreement to well under the trace's
    # noise floor means the volume axis, scale factor and origin are all right.
    interpolated = np.interp(asc_uv.x, res_uv.x, res_uv.y)
    rms = float(np.sqrt(((interpolated - asc_uv.y) ** 2).mean()))
    assert rms < 0.05  # mAU, against a 8.9 mAU main peak


def test_res_and_asc_find_the_same_peaks(example_res, example_asc):
    from plotix.core.peaks import find_peaks

    res_peaks = find_peaks(read_fplc(example_res).require("UV"))
    asc_peaks = find_peaks(read_fplc(example_asc).require("UV"))

    assert len(res_peaks) == len(asc_peaks)
    for a, b in zip(res_peaks, asc_peaks):
        assert a.x == pytest.approx(b.x, abs=0.05)
        assert a.height == pytest.approx(b.height, rel=0.02)


def test_every_example_res_parses(example_res):
    """All runs in the example folder, not just the one with an export."""
    for path in sorted(example_res.parent.glob("*.res")):
        ds = read_fplc(path)
        assert ds.require("UV").y_unit == "mAU"
        assert ds.meta["column"] == "Superdex 200 10/300 GL"
        assert ds.meta["volume_origin"] > 0
        assert len(ds.events_of("fraction")) > 5
        assert len(ds.events_of("injection")) == 1
