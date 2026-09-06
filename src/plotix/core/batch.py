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

__all__ = ["BatchResult", "BatchReport", "discover_inputs", "run_batch", "load_config"]

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


def discover_inputs(
    roots: Iterable[str | Path],
    patterns: Sequence[str] = ("*.res", "*.asc"),
    recursive: bool = True,
) -> list[Path]:
    """Every input file under ``roots`` matching ``patterns``, sorted and unique.

    A root that is itself a file is taken as-is, so a config can mix folders
    and individual files.
    """
    found: list[Path] = []
    for root in roots:
        root = Path(root).expanduser()
        if root.is_file():
            found.append(root)
            continue
        if not root.is_dir():
            logger.warning("input root does not exist, skipping: %s", root)
            continue
        for pattern in patterns:
            found.extend(root.rglob(pattern) if recursive else root.glob(pattern))
    unique = sorted({p.resolve() for p in found if not p.name.startswith(".")})
    return unique


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
    inputs: Sequence[str | Path],
    outdir: str | Path | None = None,
    *,
    layout: OutputLayout | None = None,
    format: str | None = None,
    formats: Sequence[str] = DEFAULT_FORMATS,
    dpi: int = 300,
    force: bool = False,
    per_file_subdir: bool = False,
    log_path: str | Path | None = None,
    verbose: bool = False,
    plot_kwargs: dict[str, Any] | None = None,
) -> BatchReport:
    """Plot every input, isolating failures and skipping finished work.

    Parameters
    ----------
    inputs:
        Files to plot (use :func:`discover_inputs` to expand folders).
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
    from ..core.export import slugify

    handler = _configure_logging(Path(log_path) if log_path else None, verbose)
    report = BatchReport()
    plot_kwargs = dict(plot_kwargs or {})
    fixed_outdir = Path(outdir) if outdir is not None else None
    layout = layout or OutputLayout()

    logger.info(
        "batch start: %d input(s) -> %s",
        len(inputs),
        fixed_outdir if fixed_outdir is not None else f"{layout.root}/<day>/<run>",
    )

    try:
        for n, raw_path in enumerate(inputs, start=1):
            path = Path(raw_path)
            started = time.time()
            stem = slugify(path.stem)

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
