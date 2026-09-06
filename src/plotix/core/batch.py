"""Unattended batch plotting.

Built for the case where a folder (or a whole drive) of runs needs figures made
overnight. The rules that matter:

* **Fail-isolated** — one unreadable file logs a traceback and the batch
  continues. A single corrupt export never costs you the other 200 figures.
* **Resumable** — a file whose outputs already exist at its destination is
  skipped unless ``force`` is set, so an interrupted batch can simply be
  re-run. Note that the default session layout gives every invocation its own
  timestamped folder, which means nothing is ever already present there; pin
  the destination (``outdir``, or ``OutputLayout(mode="daily")``) when resume
  is what you want.
* **Logged** — every run writes to a batch log file, and the batch ends with a
  summary of what succeeded, what was skipped, and what failed and why.
* **Non-interactive** — nothing ever prompts. Missing parameters fail that
  dataset and move on.
"""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .export import DEFAULT_FORMATS
from .output import OutputLayout

__all__ = [
    "BatchResult",
    "BatchReport",
    "InputFile",
    "discover_inputs",
    "discover_tree",
    "resolve_stems",
    "run_batch",
    "load_config",
]

logger = logging.getLogger("plotix.batch")


@dataclass
class BatchResult:
    """Outcome for a single input file."""

    path: Path
    status: str  # "ok" | "skipped" | "failed"
    outputs: list[Path] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0


@dataclass
class BatchReport:
    """Aggregate outcome of a batch run."""

    results: list[BatchResult] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    finished: float | None = None
    #: Directories written to, in the order first used.
    destinations: list[Path] = field(default_factory=list)

    def of(self, status: str) -> list[BatchResult]:
        return [r for r in self.results if r.status == status]

    @property
    def ok(self) -> list[BatchResult]:
        return self.of("ok")

    @property
    def skipped(self) -> list[BatchResult]:
        return self.of("skipped")

    @property
    def failed(self) -> list[BatchResult]:
        return self.of("failed")

    def summary(self) -> str:
        elapsed = (self.finished or time.time()) - self.started
        lines = [
            "",
            "=" * 62,
            "plotix batch summary",
            "=" * 62,
            f"  succeeded : {len(self.ok)}",
            f"  skipped   : {len(self.skipped)} (outputs already present)",
            f"  failed    : {len(self.failed)}",
            f"  elapsed   : {elapsed:.1f} s",
        ]
        if self.destinations:
            lines.append("")
            lines.append("Output:")
            lines.extend(f"  {d}" for d in self.destinations)
        if self.failed:
            lines.append("")
            lines.append("Failures:")
            for result in self.failed:
                lines.append(f"  - {result.path.name}: {result.error}")
        lines.append("=" * 62)
        return "\n".join(lines)


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML or JSON batch config into a plain dict."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        data = yaml.safe_load(text) or {}
    elif path.suffix.lower() == ".json":
        import json

        data = json.loads(text)
    else:
        raise ValueError(f"{path.name}: expected a .yaml, .yml or .json config")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: config must be a mapping at the top level")
    return data


@dataclass(frozen=True)
class InputFile:
    """A file to plot, and where it sat relative to the folder it was found in.

    ``subdir`` is what lets the output mirror the source tree: point plotix at
    a folder of experiment subfolders and each one's figures land in a matching
    subfolder, so two experiments holding a run of the same name do not
    overwrite each other.
    """

    path: Path
    subdir: Path = Path(".")

    @property
    def mirrored(self) -> bool:
        return self.subdir != Path(".")


def discover_tree(
    roots: Iterable[str | Path],
    patterns: Sequence[str] = ("*.res", "*.asc"),
    recursive: bool = True,
) -> list[InputFile]:
    """Every input under ``roots``, each tagged with its source subfolder.

    A root that is itself a file is taken as-is with no subfolder, so a folder
    and a handful of individual files can be mixed freely.
    """
    found: dict[Path, InputFile] = {}
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if root.is_file():
            resolved = root.resolve()
            found.setdefault(resolved, InputFile(resolved))
            continue
        if not root.is_dir():
            logger.warning("input root does not exist, skipping: %s", root)
            continue
        base = root.resolve()
        for pattern in patterns:
            matches = base.rglob(pattern) if recursive else base.glob(pattern)
            for match in matches:
                if match.name.startswith("."):
                    continue
                resolved = match.resolve()
                found.setdefault(
                    resolved, InputFile(resolved, resolved.parent.relative_to(base))
                )
    return [found[key] for key in sorted(found)]


def discover_inputs(
    roots: Iterable[str | Path],
    patterns: Sequence[str] = ("*.res", "*.asc"),
    recursive: bool = True,
) -> list[Path]:
    """Every input file under ``roots`` matching ``patterns``, sorted and unique.

    The paths only. Use :func:`discover_tree` when the output should mirror the
    source folder structure.
    """
    return [item.path for item in discover_tree(roots, patterns, recursive)]


def resolve_stems(items: Sequence[InputFile], mirror: bool) -> dict[Path, str]:
    """Output filename stem for each input, made unique within its directory.

    Two experiment folders routinely hold a run of the same name. Mirroring
    keeps them apart, but writing them into one directory would make the second
    overwrite the first — or, worse, be skipped as "already done" by the resume
    check, so the batch reports success while one run's figures are simply
    missing.

    Colliding stems are therefore prefixed with where they came from: the
    mirrored subfolder when there is one, otherwise the file's own parent
    directory. A numeric suffix settles anything still ambiguous after that, so
    the result is unique by construction rather than by hope.
    """
    from collections import Counter

    from .export import slugify

    stems = {item.path: slugify(item.path.stem) for item in items}

    # Two files only collide if they end up in the same directory. Mirroring
    # separates them by their source subfolder; without it, everything shares
    # one directory — which is also the case for plain paths, whose subfolder
    # is unknown, so the flag alone is not enough to decide.
    def directory_of(item: InputFile) -> Path:
        return item.subdir if mirror else Path(".")

    counts = Counter((directory_of(item), stems[item.path]) for item in items)
    for item in items:
        if counts[(directory_of(item), stems[item.path])] < 2:
            continue
        source = item.subdir.as_posix() if item.mirrored else item.path.parent.name
        if source not in {"", "."}:
            stems[item.path] = slugify(f"{source}_{item.path.stem}")

    # Last resort, so uniqueness holds by construction rather than by hope.
    seen: dict[tuple[Path, str], int] = {}
    for item in items:
        key = (directory_of(item), stems[item.path])
        if key in seen:
            seen[key] += 1
            stems[item.path] = f"{stems[item.path]}_{seen[key]}"
        else:
            seen[key] = 1
    return stems


def _configure_logging(log_path: Path | None, verbose: bool) -> logging.Handler | None:
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        logger.addHandler(stream)
    if log_path is None:
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return handler


def _expected_outputs(outdir: Path, stem: str, formats: Sequence[str]) -> list[Path]:
    return [outdir / f"{stem}.{fmt.lower().lstrip('.')}" for fmt in formats]


def run_batch(
    inputs: Sequence[str | Path | InputFile],
    outdir: str | Path | None = None,
    *,
    layout: OutputLayout | None = None,
    format: str | None = None,
    formats: Sequence[str] = DEFAULT_FORMATS,
    dpi: int = 300,
    force: bool = False,
    mirror: bool = True,
    per_file_subdir: bool = False,
    log_path: str | Path | None = None,
    verbose: bool = False,
    plot_kwargs: dict[str, Any] | None = None,
) -> BatchReport:
    """Plot every input, isolating failures and skipping finished work.

    Parameters
    ----------
    inputs:
        Files to plot. Plain paths work; :class:`InputFile` values from
        :func:`discover_tree` additionally carry the source subfolder to
        mirror in the output.
    mirror:
        Recreate each input's source subfolder under the destination, so runs
        from different experiment folders stay apart. Only has an effect on
        inputs that came from :func:`discover_tree`.
    outdir:
        Write everything here. Leave unset to use the dated session layout,
        which puts each format's output in its own day folder — so a batch
        spanning two instruments sorts itself out.
    layout:
        The session layout to use when ``outdir`` is unset. One layout is built
        for the whole batch, so every file lands in the same run folder even if
        the batch runs past midnight.
    force:
        Re-plot inputs whose outputs already exist.
    per_file_subdir:
        Give each input its own subdirectory under the destination.
    plot_kwargs:
        Passed through to the format's plot function.

    Notes
    -----
    Resume works by checking whether a file's outputs already exist *at the
    destination it would be written to*. In the default per-run layout every
    invocation gets a fresh timestamped folder, so nothing is ever skipped and
    an interrupted batch replots from the start. To resume unattended work, pin
    the destination with ``outdir`` or with ``OutputLayout(mode="daily")``.
    """
    # Imported here to keep module import cheap and avoid a cycle with api.
    from ..api import plot as plot_source
    from ..api import resolve_format

    handler = _configure_logging(Path(log_path) if log_path else None, verbose)
    report = BatchReport()
    plot_kwargs = dict(plot_kwargs or {})
    fixed_outdir = Path(outdir) if outdir is not None else None
    layout = layout or OutputLayout()
    items = [
        raw if isinstance(raw, InputFile) else InputFile(Path(raw)) for raw in inputs
    ]
    stems = resolve_stems(items, mirror)

    logger.info(
        "batch start: %d input(s) -> %s",
        len(inputs),
        fixed_outdir if fixed_outdir is not None else f"{layout.root}/<day>/<run>",
    )

    try:
        for n, item in enumerate(items, start=1):
            path = item.path
            started = time.time()
            stem = stems[path]

            if fixed_outdir is not None:
                destination = fixed_outdir
            else:
                try:
                    destination = layout.directory(resolve_format(path, format).name)
                except (ValueError, KeyError) as exc:
                    logger.error("FAILED %s: %s", path.name, exc)
                    report.results.append(
                        BatchResult(
                            path=path,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                            seconds=time.time() - started,
                        )
                    )
                    continue

            if mirror and item.mirrored:
                destination = destination / item.subdir
            target = destination / stem if per_file_subdir else destination
            if destination not in report.destinations:
                report.destinations.append(destination)

            if not force and all(p.exists() for p in _expected_outputs(target, stem, formats)):
                logger.info("[%d/%d] skip (already done): %s", n, len(inputs), path.name)
                report.results.append(
                    BatchResult(path=path, status="skipped", seconds=time.time() - started)
                )
                continue

            logger.info("[%d/%d] plotting: %s", n, len(inputs), path.name)
            try:
                bundle = plot_source(path, format=format, **plot_kwargs)
                bundle.stem = stem
                written = bundle.save(target, formats=formats, dpi=dpi, close=True)
                report.results.append(
                    BatchResult(
                        path=path,
                        status="ok",
                        outputs=written,
                        seconds=time.time() - started,
                    )
                )
                logger.debug("wrote %d file(s) for %s", len(written), path.name)
            except Exception as exc:  # noqa: BLE001 - fail isolation is the point
                logger.error("FAILED %s: %s: %s", path.name, type(exc).__name__, exc)
                logger.debug("traceback for %s:\n%s", path.name, traceback.format_exc())
                report.results.append(
                    BatchResult(
                        path=path,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                        seconds=time.time() - started,
                    )
                )
    finally:
        report.finished = time.time()
        logger.info("%s", report.summary())
        if handler is not None:
            logger.removeHandler(handler)
            handler.close()

    return report
