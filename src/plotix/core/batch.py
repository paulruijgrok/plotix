"""Unattended batch plotting.

Built for the case where a folder (or a whole drive) of runs needs figures made
overnight. The rules that matter:

* **Fail-isolated** — one unreadable file logs a traceback and the batch
  continues. A single corrupt export never costs you the other 200 figures.
* **Resumable** — a file whose outputs already exist is skipped unless
  ``force`` is set, so an interrupted batch can simply be re-run.
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
    patterns: Sequence[str] = ("*.asc",),
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
    outdir: str | Path,
    *,
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
        Where figures and source data go.
    force:
        Re-plot inputs whose outputs already exist.
    per_file_subdir:
        Give each input its own subdirectory under ``outdir``.
    plot_kwargs:
        Passed through to the format's plot function.
    """
    # Imported here to keep module import cheap and avoid a cycle with api.
    from ..api import plot as plot_source
    from ..core.export import slugify

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    handler = _configure_logging(Path(log_path) if log_path else None, verbose)
    report = BatchReport()
    plot_kwargs = dict(plot_kwargs or {})

    logger.info("batch start: %d input(s) -> %s", len(inputs), outdir)

    try:
        for n, raw_path in enumerate(inputs, start=1):
            path = Path(raw_path)
            started = time.time()
            target = outdir / slugify(path.stem) if per_file_subdir else outdir
            stem = slugify(path.stem)

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
