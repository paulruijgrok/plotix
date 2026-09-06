"""Command-line interface.

    plotix fplc FOLDER                  # plot everything in a folder
    plotix plot RUN.res                 # figure + source data in today's session folder
    plotix fplc RUN.res --daily         # same, but overwrite today's folder
    plotix fplc RUN.res -o somewhere    # write exactly there instead
    plotix batch batch.yaml             # unattended run over many files
    plotix formats                      # what plotix can read

Output goes to output/<YYYYMMDD>_<FORMAT>/<YYYYMMDD_HHMMSS>/ unless -o says
otherwise; see :mod:`plotix.core.output`.

Every format registered in :mod:`plotix.core.registry` gets its own subcommand
automatically, so a new instrument needs no changes here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .core.batch import (
    InputFile,
    discover_tree,
    load_config,
    resolve_stems,
    run_batch,
)
from .core.export import DEFAULT_FORMATS
from .core.output import DEFAULT_ROOT, OutputLayout
from .core.registry import get_format, list_formats
from .core.theme import THEMES

__all__ = ["main", "build_parser"]


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="data files, or folders to plot everything in",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="when given a folder, do not descend into its subfolders",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help=(
            "put every figure in one folder instead of mirroring the source "
            "subfolders"
        ),
    )


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--outdir",
        type=Path,
        default=None,
        help=(
            "write exactly here, bypassing the dated session layout "
            "(default: output/<YYYYMMDD>_<FORMAT>/<YYYYMMDD_HHMMSS>/)"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_ROOT,
        metavar="DIR",
        help=f"root of the session layout (default: {DEFAULT_ROOT}/)",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help=(
            "write straight into the day folder, overwriting it, instead of "
            "a new timestamped folder per run"
        ),
    )
    parser.add_argument(
        "--label",
        default=None,
        help="tag appended to the run folder name, e.g. --label pfldh",
    )
    parser.add_argument(
        "-f",
        "--formats",
        nargs="+",
        default=list(DEFAULT_FORMATS),
        metavar="EXT",
        help=f"figure formats to write (default: {' '.join(DEFAULT_FORMATS)})",
    )
    parser.add_argument("--dpi", type=int, default=300, help="raster resolution (default: 300)")
    parser.add_argument(
        "--no-source-data",
        action="store_true",
        help="do not write the source-data CSVs alongside the figure",
    )
    parser.add_argument(
        "--theme",
        default="publication",
        choices=sorted(THEMES),
        help="visual theme (default: publication)",
    )


def _add_fplc_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--auxiliary",
        default="auto",
        help=(
            "auxiliary channels on the right-hand axes: 'auto' (only channels "
            "that vary), 'none', or names e.g. 'Conductivity' "
            "'Concentration B' (default: auto)"
        ),
        nargs="+",
    )
    parser.add_argument("--signal", default="UV", help="main channel to plot (default: UV)")
    parser.add_argument("--no-fractions", action="store_true", help="hide the fraction band")
    parser.add_argument("--no-injection", action="store_true", help="hide injection marks")
    parser.add_argument("--no-peaks", action="store_true", help="do not detect or label peaks")
    parser.add_argument("--no-fill", action="store_true", help="do not fill under the trace")
    parser.add_argument(
        "--max-peaks", type=int, default=6, help="most peaks to label (default: 6)"
    )
    parser.add_argument(
        "--peak-prominence",
        type=float,
        default=0.05,
        help="peak prominence threshold, as a fraction of the signal range (default: 0.05)",
    )
    parser.add_argument(
        "--xlim",
        nargs=2,
        type=float,
        metavar=("MIN", "MAX"),
        default=None,
        help="restrict the x-axis range",
    )
    parser.add_argument("--title", default=None, help="override the figure title")
    parser.add_argument(
        "--origin",
        default="injection",
        metavar="WHERE",
        help=(
            "where volume zero sits, for .res input: 'injection' (default, "
            "matches UNICORN's ASCII export), 'start' for the instrument's own "
            "accumulated volume, or a number in ml"
        ),
    )
    parser.add_argument(
        "--keep-pre-injection",
        action="store_true",
        help="keep the equilibration data before the origin instead of trimming it",
    )


def _parse_origin(value: str) -> str | float:
    """``--origin`` takes either a keyword or a volume in millilitres."""
    try:
        return float(value)
    except ValueError:
        return value


def _fplc_plot_kwargs(args: argparse.Namespace) -> dict:
    auxiliary = args.auxiliary
    if isinstance(auxiliary, list) and len(auxiliary) == 1:
        auxiliary = auxiliary[0]
    return {
        "origin": _parse_origin(args.origin),
        "trim": not args.keep_pre_injection,
        "theme": args.theme,
        "auxiliary": auxiliary,
        "signal": args.signal,
        "show_fractions": not args.no_fractions,
        "show_injection": not args.no_injection,
        "annotate_peaks_": not args.no_peaks,
        "max_peaks": args.max_peaks,
        "min_peak_prominence": args.peak_prominence,
        "fill": not args.no_fill,
        "xlim": tuple(args.xlim) if args.xlim else None,
        "title": args.title,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plotix",
        description="Quick, beautiful plots of experimental data files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  plotix fplc ~/data/20260905_runs      # a whole folder\n"
            "  plotix plot run.res\n"
            "  plotix fplc run.res --daily\n"
            "  plotix fplc run.asc -o exact/place --formats png pdf\n"
            "  plotix fplc run.res --auxiliary none --max-peaks 3\n"
            "  plotix fplc run.res --origin start --keep-pre-injection\n"
            "  plotix batch batch.yaml\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"plotix {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    generic = sub.add_parser(
        "plot", help="plot files or whole folders, detecting the format"
    )
    _add_input_options(generic)
    generic.add_argument("--format", default=None, help="force a format instead of detecting it")
    _add_output_options(generic)
    _add_fplc_options(generic)

    for spec in list_formats():
        fmt_parser = sub.add_parser(spec.name, help=spec.description)
        _add_input_options(fmt_parser)
        _add_output_options(fmt_parser)
        if spec.name == "fplc":
            _add_fplc_options(fmt_parser)

    batch = sub.add_parser("batch", help="plot many files unattended, with resume and logging")
    batch.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=None,
        help="a folder to plot everything in, or a YAML/JSON batch config",
    )
    batch.add_argument(
        "--inputs", nargs="+", type=Path, default=None, help="input files or folders"
    )
    batch.add_argument(
        "--no-recursive", action="store_true", help="do not descend into subfolders"
    )
    batch.add_argument(
        "--flat", action="store_true", help="do not mirror the source subfolders"
    )
    batch.add_argument(
        "-o", "--outdir", type=Path, default=None,
        help="write exactly here, bypassing the dated session layout",
    )
    batch.add_argument(
        "--output-root", type=Path, default=DEFAULT_ROOT, metavar="DIR",
        help=f"root of the session layout (default: {DEFAULT_ROOT}/)",
    )
    batch.add_argument(
        "--daily", action="store_true",
        help="write straight into the day folder, overwriting it",
    )
    batch.add_argument("--label", default=None, help="tag appended to the run folder name")
    batch.add_argument("--format", default=None, help="force a format for every input")
    batch.add_argument("--formats", nargs="+", default=None, metavar="EXT")
    batch.add_argument("--dpi", type=int, default=None)
    batch.add_argument("--force", action="store_true", help="re-plot inputs already done")
    batch.add_argument(
        "--per-file-subdir", action="store_true", help="one output subfolder per input"
    )
    batch.add_argument("--log", type=Path, default=None, help="write a batch log here")
    batch.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("formats", help="list the data formats plotix can read")

    return parser


def _layout_from(args: argparse.Namespace) -> OutputLayout:
    """One layout per invocation, so every file plotted shares a folder."""
    return OutputLayout(
        root=args.output_root,
        mode="daily" if args.daily else "run",
        label=args.label,
    )


def _patterns_for(format_name: str | None) -> list[str]:
    """Filename patterns to look for when an argument is a folder."""
    specs = [get_format(format_name)] if format_name else list_formats()
    return sorted({f"*{ext}" for spec in specs for ext in spec.extensions})


def _expand(
    inputs: Sequence[Path], format_name: str | None, recursive: bool = True
) -> tuple[list[InputFile], list[Path]]:
    """Turn the command's arguments into files to plot.

    A folder argument expands to everything plotable inside it, tagged with the
    subfolder it came from so the output can mirror the source tree. Files
    named directly are taken as given. Returns the files and any arguments that
    do not exist, so the caller can report them.
    """
    missing = [p for p in inputs if not p.exists()]
    present = [p for p in inputs if p.exists()]
    if not present:
        return [], missing
    return discover_tree(present, _patterns_for(format_name), recursive), missing


def _cmd_plot(args: argparse.Namespace, format_name: str | None) -> int:
    from .api import plot as plot_source
    from .api import resolve_format

    plot_kwargs = _fplc_plot_kwargs(args) if hasattr(args, "signal") else {"theme": args.theme}
    layout = _layout_from(args)

    items, missing = _expand(args.inputs, format_name, recursive=not args.no_recursive)
    failures = len(missing)
    for path in missing:
        print(f"error: no such file or folder: {path}", file=sys.stderr)
    if not items:
        if not missing:
            print("error: nothing to plot in the given input", file=sys.stderr)
        return 1

    # A single named file gets the full listing; a folder of runs gets one line
    # each and a count, which is what stays readable at forty files.
    detailed = len(items) == 1
    mirror = not args.flat
    stems = resolve_stems(items, mirror)
    plotted = 0

    for item in items:
        path = item.path
        try:
            spec = resolve_format(path, format_name)
        except ValueError as exc:
            print(f"error: {path.name}: {exc}", file=sys.stderr)
            failures += 1
            continue
        outdir = args.outdir if args.outdir is not None else layout.directory(spec.name)
        if mirror and item.mirrored:
            outdir = outdir / item.subdir
        try:
            bundle = plot_source(path, format=spec.name, **plot_kwargs)
            bundle.stem = stems[path]
            written = bundle.save(
                outdir,
                formats=args.formats,
                dpi=args.dpi,
                write_source_data=not args.no_source_data,
                close=True,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue to next file
            print(f"error: {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
            continue
        plotted += 1
        print(f"{path.name} -> {outdir}")
        if detailed:
            for out in written:
                print(f"  {out.name}")

    if not detailed:
        summary = f"\n{plotted} plotted"
        if failures:
            summary += f", {failures} failed"
        print(summary)

    return 1 if failures else 0


def _cmd_batch(args: argparse.Namespace) -> int:
    # The positional is whichever is more convenient: a folder to plot, or a
    # config describing a whole run.
    config: dict = {}
    extra_roots: list[Path] = []
    if args.source is not None:
        if args.source.is_dir():
            extra_roots.append(args.source)
        else:
            config = load_config(args.source)

    roots = list(args.inputs or []) + extra_roots or config.get("inputs")
    if not roots:
        print(
            "error: batch needs inputs — give it a folder, --inputs, or a config",
            file=sys.stderr,
        )
        return 2
    outdir = args.outdir or config.get("outdir")

    items = discover_tree(
        roots,
        patterns=config.get("patterns", ["*.res", "*.asc"]),
        recursive=config.get("recursive", not args.no_recursive),
    )
    if not items:
        print("error: no input files matched", file=sys.stderr)
        return 1

    report = run_batch(
        items,
        outdir,
        mirror=not (args.flat or config.get("flat", False)),
        layout=OutputLayout(
            root=args.output_root if args.output_root != DEFAULT_ROOT else config.get(
                "output_root", DEFAULT_ROOT
            ),
            mode="daily" if (args.daily or config.get("daily", False)) else "run",
            label=args.label or config.get("label"),
        ),
        format=args.format or config.get("format"),
        formats=args.formats or config.get("formats", list(DEFAULT_FORMATS)),
        dpi=args.dpi or config.get("dpi", 300),
        force=args.force or config.get("force", False),
        per_file_subdir=args.per_file_subdir or config.get("per_file_subdir", False),
        log_path=args.log or config.get("log"),
        verbose=args.verbose,
        plot_kwargs=config.get("plot", {}),
    )
    return 1 if report.failed else 0


def _cmd_formats() -> int:
    print("Formats plotix can read:\n")
    for spec in list_formats():
        exts = " ".join(spec.extensions)
        aliases = f"  (aliases: {', '.join(spec.aliases)})" if spec.aliases else ""
        print(f"  {spec.name:<12} {exts:<10} {spec.description}{aliases}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "formats":
        return _cmd_formats()
    if args.command == "batch":
        return _cmd_batch(args)
    if args.command == "plot":
        return _cmd_plot(args, getattr(args, "format", None))
    return _cmd_plot(args, args.command)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
