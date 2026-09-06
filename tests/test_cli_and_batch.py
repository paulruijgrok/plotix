"""Tests for the CLI surface and the unattended batch runner."""

from __future__ import annotations

import json

import matplotlib
import pytest

matplotlib.use("Agg")

from plotix.api import plot_file, read, resolve_format  # noqa: E402
from plotix.cli import main  # noqa: E402
from plotix.core.batch import discover_inputs, load_config, run_batch  # noqa: E402

# -------------------------------------------------------------------------- api


def test_read_and_resolve_format(simple_asc):
    assert resolve_format(simple_asc).name == "fplc"
    assert resolve_format(simple_asc, "fplc").name == "fplc"
    assert read(simple_asc).format == "fplc"


def test_resolve_format_fails_clearly_on_unknown_extension(tmp_path):
    path = tmp_path / "mystery.dat"
    path.write_text("?")
    with pytest.raises(ValueError, match="could not determine the format"):
        resolve_format(path)


def test_plot_file_defaults_to_a_figures_folder_beside_the_input(simple_asc):
    written = plot_file(simple_asc, formats=("png",))
    assert all(p.parent.name == "figures" for p in written)
    assert any(p.name.endswith("_source_data.csv") for p in written)


# -------------------------------------------------------------------------- cli


def test_cli_formats_lists_fplc(capsys):
    assert main(["formats"]) == 0
    assert "fplc" in capsys.readouterr().out


def test_cli_plot_writes_outputs(simple_asc, tmp_path, capsys):
    out = tmp_path / "figs"
    code = main(["fplc", str(simple_asc), "-o", str(out), "-f", "png"])
    assert code == 0
    assert (out / "run.png").exists()
    assert (out / "run_source_data.csv").exists()
    assert "run.png" in capsys.readouterr().out


def test_cli_generic_plot_detects_the_format(simple_asc, tmp_path):
    assert main(["plot", str(simple_asc), "-o", str(tmp_path), "-f", "png"]) == 0
    assert (tmp_path / "run.png").exists()


def test_cli_reports_missing_files_without_crashing(tmp_path, capsys):
    code = main(["fplc", str(tmp_path / "absent.asc"), "-o", str(tmp_path)])
    assert code == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_no_source_data_flag(simple_asc, tmp_path):
    main(["fplc", str(simple_asc), "-o", str(tmp_path), "-f", "png", "--no-source-data"])
    assert (tmp_path / "run.png").exists()
    assert not (tmp_path / "run_source_data.csv").exists()


def test_cli_plot_switches(simple_asc, tmp_path):
    code = main(
        [
            "fplc",
            str(simple_asc),
            "-o",
            str(tmp_path),
            "-f",
            "png",
            "--auxiliary",
            "none",
            "--no-peaks",
            "--no-fractions",
            "--no-fill",
            "--xlim",
            "2",
            "18",
        ]
    )
    assert code == 0
    assert not (tmp_path / "run_peaks.csv").exists()


def test_cli_plots_a_res_file(simple_res, tmp_path):
    assert main(["fplc", str(simple_res), "-o", str(tmp_path), "-f", "png"]) == 0
    assert (tmp_path / "run.png").exists()
    assert (tmp_path / "run_source_data.csv").exists()


def test_cli_origin_options(simple_res, tmp_path):
    import pandas as pd

    assert main(["fplc", str(simple_res), "-o", str(tmp_path), "-f", "png"]) == 0
    zeroed = pd.read_csv(tmp_path / "run_peaks.csv")["Volume (ml)"].iloc[0]

    raw_dir = tmp_path / "raw"
    assert (
        main(
            [
                "fplc",
                str(simple_res),
                "-o",
                str(raw_dir),
                "-f",
                "png",
                "--origin",
                "start",
                "--keep-pre-injection",
            ]
        )
        == 0
    )
    raw = pd.read_csv(raw_dir / "run_peaks.csv")["Volume (ml)"].iloc[0]
    # The synthetic run injects at 2.0 ml, so the two origins differ by that.
    assert raw - zeroed == pytest.approx(2.0, abs=0.05)


def test_cli_numeric_origin(simple_res, tmp_path):
    import pandas as pd

    assert (
        main(["fplc", str(simple_res), "-o", str(tmp_path), "-f", "png", "--origin", "4"])
        == 0
    )
    assert pd.read_csv(tmp_path / "run_peaks.csv")["Volume (ml)"].iloc[0] == pytest.approx(
        4.0, abs=0.05
    )


def test_cli_version_and_help_exit_cleanly(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "plotix" in capsys.readouterr().out


# ------------------------------------------------------------------------ batch


def test_discover_inputs_finds_files_and_accepts_explicit_paths(
    asc_factory, res_factory, tmp_path
):
    asc_factory("a.asc")
    nested = tmp_path / "sub"
    nested.mkdir()
    asc_factory("sub/b.asc")
    res_factory("c.res")

    found = discover_inputs([tmp_path])
    assert {p.name for p in found} == {"a.asc", "b.asc", "c.res"}

    assert discover_inputs([tmp_path / "a.asc"]) == [(tmp_path / "a.asc").resolve()]
    assert {p.name for p in discover_inputs([tmp_path], recursive=False)} == {
        "a.asc",
        "c.res",
    }
    assert discover_inputs([tmp_path / "missing"]) == []


def test_run_batch_isolates_failures(asc_factory, tmp_path):
    good = asc_factory("good.asc")
    bad = tmp_path / "bad.asc"
    bad.write_text("not a chromatogram")
    other = asc_factory("other.asc")

    report = run_batch([good, bad, other], tmp_path / "out", formats=("png",))

    assert len(report.ok) == 2
    assert len(report.failed) == 1
    assert report.failed[0].path.name == "bad.asc"
    assert "ValueError" in report.failed[0].error
    assert (tmp_path / "out" / "good.png").exists()
    assert "failed    : 1" in report.summary()


def test_run_batch_resumes_and_force_overrides(asc_factory, tmp_path):
    path = asc_factory("run.asc")
    out = tmp_path / "out"

    first = run_batch([path], out, formats=("png",))
    assert len(first.ok) == 1

    second = run_batch([path], out, formats=("png",))
    assert len(second.skipped) == 1 and not second.ok

    third = run_batch([path], out, formats=("png",), force=True)
    assert len(third.ok) == 1


def test_run_batch_writes_a_log_and_per_file_subdirs(asc_factory, tmp_path):
    path = asc_factory("run.asc")
    log = tmp_path / "logs" / "batch.log"
    report = run_batch(
        [path],
        tmp_path / "out",
        formats=("png",),
        per_file_subdir=True,
        log_path=log,
        verbose=True,
    )
    assert (tmp_path / "out" / "run" / "run.png").exists()
    assert log.exists()
    assert "batch start" in log.read_text()
    assert report.finished is not None


def test_run_batch_passes_plot_kwargs(gradient_asc, tmp_path):
    report = run_batch(
        [gradient_asc],
        tmp_path / "out",
        formats=("png",),
        plot_kwargs={"auxiliary": "none", "annotate_peaks_": False},
    )
    assert len(report.ok) == 1
    assert not (tmp_path / "out" / "gradient_peaks.csv").exists()


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_load_config_reads_yaml_and_json(tmp_path, suffix):
    payload = {"inputs": ["a"], "outdir": "out", "dpi": 200}
    path = tmp_path / f"cfg{suffix}"
    if suffix == ".json":
        path.write_text(json.dumps(payload))
    else:
        path.write_text("inputs:\n  - a\noutdir: out\ndpi: 200\n")
    assert load_config(path) == payload


def test_load_config_rejects_unsupported_and_malformed(tmp_path):
    bad_suffix = tmp_path / "cfg.txt"
    bad_suffix.write_text("x")
    with pytest.raises(ValueError, match="expected a .yaml"):
        load_config(bad_suffix)

    not_a_mapping = tmp_path / "cfg.json"
    not_a_mapping.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="mapping"):
        load_config(not_a_mapping)


def test_cli_batch_end_to_end(asc_factory, tmp_path):
    asc_factory("one.asc")
    asc_factory("two.asc")
    config = tmp_path / "batch.yaml"
    config.write_text(
        f"inputs:\n  - {tmp_path}\noutdir: {tmp_path / 'out'}\n"
        "formats:\n  - png\nplot:\n  auxiliary: none\n"
    )
    assert main(["batch", str(config)]) == 0
    assert (tmp_path / "out" / "one.png").exists()
    assert (tmp_path / "out" / "two.png").exists()


def test_cli_batch_requires_inputs_and_outdir(tmp_path, capsys):
    assert main(["batch"]) == 2
    assert "needs inputs" in capsys.readouterr().err
    assert main(["batch", "--inputs", str(tmp_path)]) == 2
    assert "output directory" in capsys.readouterr().err


def test_cli_batch_reports_when_nothing_matches(tmp_path, capsys):
    code = main(["batch", "--inputs", str(tmp_path), "-o", str(tmp_path / "out")])
    assert code == 1
    assert "no input files matched" in capsys.readouterr().err
