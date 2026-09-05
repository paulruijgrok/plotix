"""Command-line interface.

    plotix plot RUN.asc                 # figure + source data next to the file
    plotix fplc RUN.asc -o figures      # same, format pinned explicitly
    plotix batch batch.yaml             # unattended run over many files
    plotix formats                      # what plotix can read

Every format registered in :mod:`plotix.core.registry` gets its own subcommand
automatically, so a new instrument needs no changes here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .core.batch import discover_inputs, load_config, run_batch
from .core.export import DEFAULT_FORMATS
from .core.registry import list_formats
from .core.theme import THEMES

__all__ = ["main", "build_parser"]


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--outdir",
        type=Path,
        default=None,
        help="output directory (default: a 'figures/' folder beside the input)",
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


def _fplc_plot_kwargs(args: argparse.Namespace) -> dict:
    auxiliary = args.auxiliary
    if isinstance(auxiliary, list) and len(auxiliary) == 1:
        auxiliary = auxiliary[0]
    return {
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
            "  plotix plot run.asc\n"
            "  plotix fplc run.asc -o figures --formats png pdf\n"
            "  plotix fplc run.asc --auxiliary none --max-peaks 3\n"
            "  plotix batch batch.yaml\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"plotix {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    generic = sub.add_parser("plot", help="plot one or more files, detecting the format")
    generic.add_argument("inputs", nargs="+", type=Path, help="data files to plot")
    generic.add_argument("--format", default=None, help="force a format instead of detecting it")
    _add_output_options(generic)
    _add_fplc_options(generic)

    for spec in list_formats():
        fmt_parser = sub.add_parser(spec.name, help=spec.description)
        fmt_parser.add_argument("inputs", nargs="+", type=Path, help="data files to plot")
        _add_output_options(fmt_parser)
        if spec.name == "fplc":
            _add_fplc_options(fmt_parser)

    batch = sub.add_parser("batch", help="plot many files unattended, with resume and logging")
    batch.add_argument("config", type=Path, nargs="?", default=None, help="YAML/JSON batch config")
    batch.add_argument(
        "--inputs", nargs="+", type=Path, default=None, help="input files or folders"
    )
    batch.add_argument("-o", "--outdir", type=Path, default=None, help="output directory")
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


def _cmd_plot(args: argparse.Namespace, format_name: str | None) -> int:
    from .api import plot as plot_source

    plot_kwargs = _fplc_plot_kwargs(args) if hasattr(args, "signal") else {"theme": args.theme}
    failures = 0

    for path in args.inputs:
        if not path.exists():
            print(f"error: no such file: {path}", file=sys.stderr)
            failures += 1
            continue
        outdir = args.outdir if args.outdir is not None else path.parent / "figures"
        try:
            bundle = plot_source(path, format=format_name, **plot_kwargs)
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
        print(f"{path.name} -> {outdir}")
        for out in written:
            print(f"  {out.name}")

    return 1 if failures else 0


def _cmd_batch(args: argparse.Namespace) -> int:
    config: dict = load_config(args.config) if args.config else {}

    roots = args.inputs or config.get("inputs")
    if not roots:
        print("error: batch needs inputs, from --inputs or the config", file=sys.stderr)
        return 2
    outdir = args.outdir or config.get("outdir")
    if not outdir:
        print("error: batch needs an output directory, from -o or the config", file=sys.stderr)
        return 2

    files = discover_inputs(
        roots,
        patterns=config.get("patterns", ["*.asc"]),
        recursive=config.get("recursive", True),
    )
    if not files:
        print("error: no input files matched", file=sys.stderr)
        return 1

    report = run_batch(
        files,
        outdir,
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
