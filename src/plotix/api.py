"""High-level, format-agnostic entry points.

These are the two functions most day-to-day use goes through::

    ds = plotix.read("run.asc")             # -> Dataset
    plotix.plot_file("run.asc", "figures")  # -> figure + source-data CSVs

Both dispatch on the format registry, so they gain support for new instruments
automatically as formats are added.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .core.dataset import Dataset
from .core.export import DEFAULT_FORMATS, FigureBundle
from .core.registry import FormatSpec, detect_format, get_format

__all__ = ["resolve_format", "read", "plot", "plot_file"]


def resolve_format(
    path: str | Path, format: str | None = None
) -> FormatSpec:
    """The :class:`FormatSpec` for ``path``, detected unless ``format`` is given."""
    if format is not None:
        return get_format(format)
    spec = detect_format(path)
    if spec is None:
        raise ValueError(
            f"could not determine the format of {Path(path).name!r}. "
            f"Pass format=... explicitly."
        )
    return spec


def read(
    path: str | Path, format: str | None = None, **kwargs: Any
) -> Dataset:
    """Parse a data file into a :class:`~plotix.core.dataset.Dataset`."""
    return resolve_format(path, format).reader(path, **kwargs)


def plot(
    source: str | Path | Dataset,
    format: str | None = None,
    **kwargs: Any,
) -> FigureBundle:
    """Build the standard figure for a file or an already-parsed dataset."""
    if isinstance(source, Dataset):
        spec = get_format(format or source.format)
    else:
        spec = resolve_format(source, format)
    return spec.plot(source, **kwargs)


def plot_file(
    path: str | Path,
    outdir: str | Path | None = None,
    *,
    format: str | None = None,
    formats: Sequence[str] = DEFAULT_FORMATS,
    dpi: int = 300,
    write_source_data: bool = True,
    close: bool = True,
    **plot_kwargs: Any,
) -> list[Path]:
    """Read a file, plot it, and write the figure plus its source data.

    ``outdir`` defaults to a ``figures/`` directory beside the input file, so
    the common case is a single argument.
    """
    path = Path(path)
    outdir = Path(outdir) if outdir is not None else path.parent / "figures"
    bundle = plot(path, format=format, **plot_kwargs)
    return bundle.save(
        outdir,
        formats=formats,
        dpi=dpi,
        write_source_data=write_source_data,
        close=close,
    )
