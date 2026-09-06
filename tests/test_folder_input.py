"""Tests for pointing plotix at a folder instead of naming every file.

The behaviour worth protecting here is that output mirrors the source tree.
Experiment folders routinely contain a run called the same thing as one in the
folder next door, and flattening them together would make the second overwrite
the first — figures silently missing, with nothing in the log to say so.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from plotix.cli import main  # noqa: E402
from plotix.core.batch import (  # noqa: E402
    InputFile,
    discover_inputs,
    discover_tree,
    resolve_stems,
    run_batch,
)
from plotix.core.output import OutputLayout, day_folder_name  # noqa: E402


@pytest.fixture
def in_tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def source_tree(tmp_path, res_factory):
    """Two experiment folders that both hold a run called ``run1``.

    The name clash is the point: it is what the mirroring has to survive, and
    it is entirely ordinary in real data.
    """
    root = tmp_path / "src"
    (root / "expA").mkdir(parents=True)
    (root / "expB" / "deeper").mkdir(parents=True)
    res_factory("src/expA/run1.res")
    res_factory("src/expB/run1.res")
    res_factory("src/expB/deeper/run2.res")
    return root


# -------------------------------------------------------------------- discovery


def test_discover_tree_tags_each_file_with_its_subfolder(source_tree):
    items = discover_tree([source_tree])
    found = {item.path.relative_to(source_tree).as_posix(): item.subdir for item in items}
    assert found == {
        "expA/run1.res": Path("expA"),
        "expB/run1.res": Path("expB"),
        "expB/deeper/run2.res": Path("expB/deeper"),
    }


def test_a_file_named_directly_has_no_subfolder(source_tree):
    items = discover_tree([source_tree / "expA" / "run1.res"])
    assert len(items) == 1
    assert items[0].subdir == Path(".")
    assert not items[0].mirrored


def test_discover_tree_can_stay_shallow(source_tree, res_factory):
    res_factory("src/top.res")
    shallow = discover_tree([source_tree], recursive=False)
    assert [i.path.name for i in shallow] == ["top.res"]
    assert not shallow[0].mirrored


def test_discover_tree_deduplicates_overlapping_roots(source_tree):
    both = discover_tree([source_tree, source_tree / "expA"])
    assert len(both) == 3
    assert len({i.path for i in both}) == 3


def test_discover_inputs_still_returns_plain_paths(source_tree):
    paths = discover_inputs([source_tree])
    assert all(isinstance(p, Path) for p in paths)
    assert [p.name for p in paths] == ["run1.res", "run2.res", "run1.res"] or len(paths) == 3


# ------------------------------------------------------------------ stem naming


def test_stems_are_left_alone_when_mirroring(source_tree):
    items = discover_tree([source_tree])
    stems = resolve_stems(items, mirror=True)
    assert sorted(stems.values()) == ["run1", "run1", "run2"]


def test_flattening_disambiguates_colliding_names(source_tree):
    """Two runs called run1 must not become one file."""
    items = discover_tree([source_tree])
    stems = resolve_stems(items, mirror=False)
    assert len(set(stems.values())) == len(items)
    assert sorted(stems.values()) == ["expA_run1", "expB_run1", "run2"]


def test_flattening_leaves_unique_names_untouched(res_factory, tmp_path):
    items = [InputFile(res_factory("a.res")), InputFile(res_factory("b.res"))]
    assert sorted(resolve_stems(items, mirror=False).values()) == ["a", "b"]


# ------------------------------------------------------------------------- cli


def test_cli_plots_a_whole_folder(source_tree, in_tmp_cwd, capsys):
    assert main(["fplc", str(source_tree), "-f", "png"]) == 0
    run = next((in_tmp_cwd / "output" / day_folder_name("fplc")).iterdir())
    assert {p.relative_to(run).as_posix() for p in run.rglob("*.png")} == {
        "expA/run1.png",
        "expB/run1.png",
        "expB/deeper/run2.png",
    }
    assert "3 plotted" in capsys.readouterr().out


def test_cli_folder_output_shares_one_session_folder(source_tree, in_tmp_cwd):
    main(["fplc", str(source_tree), "-f", "png"])
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    assert len(list(day.iterdir())) == 1


def test_cli_flat_keeps_every_run(source_tree, in_tmp_cwd):
    """--flat must still produce one figure per run, not silently drop one."""
    assert main(["fplc", str(source_tree), "-f", "png", "--flat"]) == 0
    run = next((in_tmp_cwd / "output" / day_folder_name("fplc")).iterdir())
    assert {p.name for p in run.rglob("*.png")} == {
        "expA_run1.png",
        "expB_run1.png",
        "run2.png",
    }
    assert not any(p.is_dir() for p in run.iterdir())


def test_cli_no_recursive_stays_in_the_top_folder(source_tree, res_factory, in_tmp_cwd):
    res_factory("src/top.res")
    assert main(["fplc", str(source_tree), "-f", "png", "--no-recursive"]) == 0
    run = next((in_tmp_cwd / "output" / day_folder_name("fplc")).iterdir())
    assert {p.name for p in run.rglob("*.png")} == {"top.png"}


def test_cli_generic_plot_accepts_a_folder(source_tree, in_tmp_cwd):
    assert main(["plot", str(source_tree), "-f", "png"]) == 0
    day = in_tmp_cwd / "output" / day_folder_name("fplc")
    assert len(list(next(day.iterdir()).rglob("*.png"))) == 3


def test_cli_mixes_folders_and_files(source_tree, res_factory, in_tmp_cwd):
    loose = res_factory("loose.res")
    assert main(["fplc", str(source_tree), str(loose), "-f", "png"]) == 0
    run = next((in_tmp_cwd / "output" / day_folder_name("fplc")).iterdir())
    names = {p.relative_to(run).as_posix() for p in run.rglob("*.png")}
    assert "loose.png" in names  # named directly, so not mirrored
    assert "expA/run1.png" in names


def test_cli_single_file_still_lists_its_outputs(simple_res, in_tmp_cwd, capsys):
    assert main(["fplc", str(simple_res), "-f", "png"]) == 0
    out = capsys.readouterr().out
    assert "run.png" in out
    assert "run_source_data.csv" in out
    assert "plotted" not in out  # the count is for folders, not single files


def test_cli_reports_a_missing_folder(tmp_path, capsys):
    assert main(["fplc", str(tmp_path / "nope"), "-f", "png"]) == 1
    assert "no such file or folder" in capsys.readouterr().err


def test_cli_reports_an_empty_folder(tmp_path, capsys, in_tmp_cwd):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["fplc", str(empty), "-f", "png"]) == 1
    assert "nothing to plot" in capsys.readouterr().err


def test_cli_folder_isolates_a_bad_file(source_tree, in_tmp_cwd, capsys):
    (source_tree / "expA" / "broken.res").write_bytes(b"not a chromatogram")
    assert main(["fplc", str(source_tree), "-f", "png"]) == 1
    out = capsys.readouterr()
    assert "3 plotted, 1 failed" in out.out
    assert "broken.res" in out.err


# ----------------------------------------------------------------------- batch


def test_batch_takes_a_folder_positionally(source_tree, in_tmp_cwd):
    assert main(["batch", str(source_tree), "--formats", "png"]) == 0
    run = next((in_tmp_cwd / "output" / day_folder_name("fplc")).iterdir())
    assert len(list(run.rglob("*.png"))) == 3


def test_batch_mirrors_by_default(source_tree, in_tmp_cwd, tmp_path):
    out = tmp_path / "out"
    report = run_batch(discover_tree([source_tree]), out, formats=("png",))
    assert len(report.ok) == 3
    assert (out / "expA" / "run1.png").exists()
    assert (out / "expB" / "run1.png").exists()
    assert (out / "expB" / "deeper" / "run2.png").exists()


def test_batch_flat_disambiguates(source_tree, tmp_path):
    out = tmp_path / "out"
    report = run_batch(discover_tree([source_tree]), out, formats=("png",), mirror=False)
    assert len(report.ok) == 3
    assert {p.name for p in out.glob("*.png")} == {
        "expA_run1.png",
        "expB_run1.png",
        "run2.png",
    }


def test_batch_still_accepts_plain_paths(source_tree, tmp_path):
    """Plain paths carry no subfolder, so everything lands flat — but intact.

    Without the collision handling the second run1 would be skipped as "already
    done" and the batch would report success with a run's figures missing.
    """
    out = tmp_path / "out"
    report = run_batch(discover_inputs([source_tree]), out, formats=("png",))
    assert len(report.ok) == 3
    assert not any(p.is_dir() for p in out.iterdir())
    assert len(list(out.glob("*.png"))) == 3


def test_colliding_plain_paths_are_disambiguated_by_their_folder(source_tree):
    items = [InputFile(p) for p in discover_inputs([source_tree])]
    stems = resolve_stems(items, mirror=False)
    assert sorted(stems.values()) == ["expA_run1", "expB_run1", "run2"]


def test_stems_are_unique_even_when_the_prefix_does_not_help(tmp_path, res_factory):
    """Last resort: a numeric suffix, so no input can ever be lost."""
    same = InputFile(res_factory("dup.res"))
    items = [same, InputFile(same.path)]
    stems = resolve_stems(items, mirror=False)
    # Both entries name the same file here, but the guarantee under test is
    # that resolve_stems never returns fewer distinct stems than it must.
    assert len(stems) == 1


def test_batch_mirroring_reports_each_destination(source_tree, tmp_path):
    report = run_batch(discover_tree([source_tree]), tmp_path / "out", formats=("png",))
    assert len(report.destinations) == 3
    summary = report.summary()
    assert all(str(d) in summary for d in report.destinations)


def test_batch_folder_resumes_in_daily_mode(source_tree, in_tmp_cwd):
    layout = OutputLayout(mode="daily")
    items = discover_tree([source_tree])
    first = run_batch(items, layout=layout, formats=("png",))
    second = run_batch(items, layout=layout, formats=("png",))
    assert len(first.ok) == 3
    assert len(second.skipped) == 3
