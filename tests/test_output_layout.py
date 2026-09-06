"""Tests for the dated session output layout.

The layout's whole point is that a re-run never destroys the previous one, so
most of what is checked here is that two invocations land in different places
in run mode and the same place in daily mode.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from plotix.api import plot_file  # noqa: E402
from plotix.cli import main  # noqa: E402
from plotix.core.batch import discover_inputs, run_batch  # noqa: E402
from plotix.core.output import (  # noqa: E402
    DEFAULT_ROOT,
    OutputLayout,
    day_folder_name,
    run_folder_name,
)

WHEN = datetime(2026, 9, 5, 14, 30, 22)


@pytest.fixture
def in_tmp_cwd(tmp_path, monkeypatch):
    """Run with the working directory somewhere disposable.

    The default layout is relative to the working directory, so tests that
    exercise it must not be run from the repo.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ------------------------------------------------------------------ path names


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("fplc", "20260905_FPLC"),
        ("FPLC", "20260905_FPLC"),
        ("plate reader", "20260905_PLATE_READER"),
        ("", "20260905"),
    ],
)
def test_day_folder_name(kind, expected):
    assert day_folder_name(kind, WHEN) == expected


def test_run_folder_name():
    assert run_folder_name(WHEN) == "20260905_143022"
    assert run_folder_name(WHEN, "pfldh") == "20260905_143022_pfldh"
    assert run_folder_name(WHEN, "a b/c") == "20260905_143022_a_b_c"
    assert run_folder_name(WHEN, "  ") == "20260905_143022"


def test_layout_builds_the_expected_paths():
    assert OutputLayout(when=WHEN).directory("fplc") == Path(
        "output/20260905_FPLC/20260905_143022"
    )
    assert OutputLayout(mode="daily", when=WHEN).directory("fplc") == Path(
        "output/20260905_FPLC"
    )
    assert OutputLayout(root="/tmp/x", when=WHEN).directory("fplc") == Path(
        "/tmp/x/20260905_FPLC/20260905_143022"
    )
    assert DEFAULT_ROOT == "output"


def test_layout_separates_kinds_within_a_day():
    layout = OutputLayout(when=WHEN)
    assert layout.directory("fplc") != layout.directory("plate")
    assert layout.directory("fplc").parent.name == "20260905_FPLC"
    assert layout.directory("plate").parent.name == "20260905_PLATE"


def test_layout_freezes_its_timestamp():
    """One layout, one folder — every file in an invocation shares it."""
    layout = OutputLayout()
    assert layout.directory("fplc") == layout.directory("fplc")
    assert layout.when is not None


def test_layout_rejects_an_unknown_mode():
    with pytest.raises(ValueError, match="mode must be"):
        OutputLayout(mode="hourly")


def test_directory_has_no_side_effects(in_tmp_cwd):
    """Asking where output would go must not create anything."""
    OutputLayout().directory("fplc")
    assert not (in_tmp_cwd / "output").exists()


# ------------------------------------------------------------------- plot_file


def test_plot_file_writes_into_the_session_folder(simple_res, in_tmp_cwd):
    written = plot_file(simple_res, formats=("png",))
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    assert day.is_dir()
    run_folders = list(day.iterdir())
    assert len(run_folders) == 1
    # The layout root is relative to the working directory, so returned paths
    # are relative too; resolve before comparing.
    assert all(p.resolve().parent == run_folders[0].resolve() for p in written)
    assert any(p.name.endswith("_source_data.csv") for p in written)


def test_plot_file_outdir_bypasses_the_layout(simple_res, in_tmp_cwd, tmp_path):
    exact = tmp_path / "exact"
    written = plot_file(simple_res, exact, formats=("png",))
    assert all(p.parent == exact for p in written)
    assert not (in_tmp_cwd / "output").exists()


def test_plot_file_shares_one_folder_when_given_a_layout(
    simple_res, res_factory, in_tmp_cwd
):
    other = res_factory("other.res")
    layout = OutputLayout()
    first = plot_file(simple_res, layout=layout, formats=("png",))
    second = plot_file(other, layout=layout, formats=("png",))
    assert first[0].resolve().parent == second[0].resolve().parent


def test_daily_mode_overwrites_rather_than_accumulating(simple_res, in_tmp_cwd):
    for _ in range(2):
        plot_file(simple_res, layout=OutputLayout(mode="daily"), formats=("png",))
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    assert day.is_dir()
    # Files sit directly in the day folder; no run subfolders were made.
    assert not any(p.is_dir() for p in day.iterdir())
    assert (day / "run.png").exists()


def test_run_mode_keeps_both_attempts(simple_res, in_tmp_cwd):
    first = plot_file(
        simple_res, layout=OutputLayout(when=datetime(2026, 9, 5, 10, 0, 0)),
        formats=("png",),
    )
    second = plot_file(
        simple_res, layout=OutputLayout(when=datetime(2026, 9, 5, 11, 0, 0)),
        formats=("png",),
    )
    assert first[0].resolve().parent != second[0].resolve().parent
    assert first[0].exists() and second[0].exists()


# ------------------------------------------------------------------------- cli


def test_cli_uses_the_session_layout(simple_res, in_tmp_cwd):
    assert main(["fplc", str(simple_res), "-f", "png"]) == 0
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    run_folders = list(day.iterdir())
    assert len(run_folders) == 1
    assert (run_folders[0] / "run.png").exists()


def test_cli_daily_flag(simple_res, in_tmp_cwd):
    assert main(["fplc", str(simple_res), "-f", "png", "--daily"]) == 0
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    assert (day / "run.png").exists()


def test_cli_label_flag(simple_res, in_tmp_cwd):
    assert main(["fplc", str(simple_res), "-f", "png", "--label", "pfldh"]) == 0
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    assert list(day.iterdir())[0].name.endswith("_pfldh")


def test_cli_output_root_flag(simple_res, in_tmp_cwd):
    assert main(["fplc", str(simple_res), "-f", "png", "--output-root", "elsewhere"]) == 0
    assert (in_tmp_cwd / "elsewhere" / day_folder_name("fplc")).is_dir()
    assert not (in_tmp_cwd / "output").exists()


def test_cli_several_files_share_one_run_folder(res_factory, in_tmp_cwd):
    a, b = res_factory("a.res"), res_factory("b.res")
    assert main(["fplc", str(a), str(b), "-f", "png"]) == 0
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    run_folders = list(day.iterdir())
    assert len(run_folders) == 1
    assert {p.name for p in run_folders[0].glob("*.png")} == {"a.png", "b.png"}


# ----------------------------------------------------------------------- batch


def test_batch_uses_the_session_layout_and_reports_it(res_factory, in_tmp_cwd):
    res_factory("a.res")
    res_factory("b.res")
    report = run_batch(discover_inputs([in_tmp_cwd]), formats=("png",))

    assert len(report.ok) == 2
    assert len(report.destinations) == 1
    destination = report.destinations[0]
    assert destination.parent.name == day_folder_name("fplc")
    assert str(destination) in report.summary()
    assert (destination / "a.png").exists()


def test_batch_daily_mode_resumes(res_factory, in_tmp_cwd):
    """Resume needs a pinned destination; daily mode is how you pin it."""
    res_factory("a.res")
    files = discover_inputs([in_tmp_cwd])
    layout = OutputLayout(mode="daily")

    first = run_batch(files, layout=layout, formats=("png",))
    second = run_batch(files, layout=layout, formats=("png",))
    assert len(first.ok) == 1
    assert len(second.skipped) == 1

    forced = run_batch(files, layout=layout, formats=("png",), force=True)
    assert len(forced.ok) == 1


def test_batch_run_mode_never_skips(res_factory, in_tmp_cwd):
    """Documented consequence of a fresh folder per invocation."""
    res_factory("a.res")
    files = discover_inputs([in_tmp_cwd])
    run_batch(files, layout=OutputLayout(when=datetime(2026, 9, 5, 10, 0, 0)), formats=("png",))
    again = run_batch(
        files, layout=OutputLayout(when=datetime(2026, 9, 5, 11, 0, 0)), formats=("png",)
    )
    assert len(again.ok) == 1 and not again.skipped


def test_batch_outdir_still_wins(res_factory, in_tmp_cwd, tmp_path):
    res_factory("a.res")
    exact = tmp_path / "exact"
    report = run_batch(discover_inputs([in_tmp_cwd]), exact, formats=("png",))
    assert report.destinations == [exact]
    assert (exact / "a.png").exists()
    assert not (in_tmp_cwd / "output").exists()


def test_batch_separates_formats_into_their_own_day_folders(
    res_factory, asc_factory, in_tmp_cwd, monkeypatch
):
    """Two kinds of data on one day get one day folder each."""
    from plotix.core import registry

    res_factory("a.res")
    asc_factory("b.asc")

    # Pretend the .asc is a different instrument, to exercise the split without
    # inventing a whole second format.
    real_resolve = registry.detect_format

    def fake_detect(path, *args, **kwargs):
        spec = real_resolve(path, *args, **kwargs)
        if spec is not None and Path(path).suffix == ".asc":
            return registry.FormatSpec(
                name="plate",
                description="stand-in",
                extensions=(".asc",),
                reader=spec.reader,
                plot=spec.plot,
            )
        return spec

    monkeypatch.setattr("plotix.api.detect_format", fake_detect)

    report = run_batch(discover_inputs([in_tmp_cwd]), formats=("png",))
    assert len(report.ok) == 2
    days = {d.parent.name for d in report.destinations}
    assert days == {day_folder_name("fplc"), day_folder_name("plate")}


def test_cli_batch_without_outdir_uses_the_layout(res_factory, in_tmp_cwd):
    res_factory("a.res")
    assert main(["batch", "--inputs", str(in_tmp_cwd), "--formats", "png"]) == 0
    assert (in_tmp_cwd / "output" / day_folder_name("fplc")).is_dir()


def test_cli_batch_daily_flag(res_factory, in_tmp_cwd):
    res_factory("a.res")
    assert main(["batch", "--inputs", str(in_tmp_cwd), "--formats", "png", "--daily"]) == 0
    assert (in_tmp_cwd / "output" / day_folder_name("fplc") / "a.png").exists()
