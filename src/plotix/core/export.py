"""Figure and source-data export.

Every plotix figure is written together with the numbers behind it, in the
spirit of journal "source data" files: whatever a reader sees in the figure,
they can reopen as a CSV. :class:`FigureBundle` is what plot functions return,
and :meth:`FigureBundle.save` is the single place that decides filenames.

Source data is written in tidy long form (``series, x, y, ...``) rather than a
wide table, because instrument channels are sampled on different x-grids and
interpolating them onto a common axis would silently alter the numbers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

from .dataset import Curve, Event

__all__ = ["FigureBundle", "DEFAULT_FORMATS", "slugify", "curves_to_long_frame"]

DEFAULT_FORMATS: tuple[str, ...] = ("png", "pdf", "svg")

_SLUG_STRIP = re.compile(r"[^\w.\-]+")
_SLUG_COLLAPSE = re.compile(r"[-_]{2,}")


def slugify(text: str, max_length: int = 80) -> str:
    """Filesystem-safe stem derived from a run or dataset name."""
    cleaned = _SLUG_STRIP.sub("_", text.strip())
    cleaned = _SLUG_COLLAPSE.sub("_", cleaned).strip("._-")
    return (cleaned or "figure")[:max_length]


def curves_to_long_frame(curves: Iterable[Curve]) -> pd.DataFrame:
    """Tidy long-form frame of the plotted curves, one row per sample."""
    frames = []
    for curve in curves:
        if len(curve) == 0:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "series": curve.name,
                    "x": curve.x,
                    "x_label": curve.x_label,
                    "x_unit": curve.x_unit,
                    "y": curve.y,
                    "y_label": curve.y_label,
                    "y_unit": curve.y_unit,
                }
            )
        )
    if not frames:
        return pd.DataFrame(
            columns=["series", "x", "x_label", "x_unit", "y", "y_label", "y_unit"]
        )
    return pd.concat(frames, ignore_index=True)


def events_to_frame(events: Iterable[Event]) -> pd.DataFrame:
    rows = [{"kind": e.kind, "x": e.x, "label": e.label} for e in events]
    if not rows:
        return pd.DataFrame(columns=["kind", "x", "label"])
    return pd.DataFrame(rows)


@dataclass
class FigureBundle:
    """A finished figure plus everything needed to reproduce its numbers.

    Attributes
    ----------
    figure:
        The matplotlib figure.
    stem:
        Filename stem shared by every artefact of this plot.
    source_data:
        Tidy frame of the plotted curves. Written as ``<stem>_source_data.csv``.
    tables:
        Extra named frames written as ``<stem>_<key>.csv`` — used for fraction
        and injection marks, detected peaks, and similar derived tables.
    meta:
        Free-form provenance carried alongside the figure.
    """

    figure: Figure
    stem: str
    source_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def save(
        self,
        outdir: str | Path,
        formats: Sequence[str] = DEFAULT_FORMATS,
        dpi: int = 300,
        write_source_data: bool = True,
        close: bool = False,
    ) -> list[Path]:
        """Write the figure in every requested format, plus the CSVs.

        Returns the paths written, figures first.
        """
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        for fmt in formats:
            fmt = fmt.lower().lstrip(".")
            path = outdir / f"{self.stem}.{fmt}"
            self.figure.savefig(path, format=fmt, dpi=dpi)
            written.append(path)

        if write_source_data:
            if not self.source_data.empty:
                path = outdir / f"{self.stem}_source_data.csv"
                self.source_data.to_csv(path, index=False, float_format="%.6g")
                written.append(path)
            for key, frame in self.tables.items():
                if frame is None or frame.empty:
                    continue
                path = outdir / f"{self.stem}_{key}.csv"
                frame.to_csv(path, index=False, float_format="%.6g")
                written.append(path)

        if close:
            self.close()
        return written

    def close(self) -> None:
        import matplotlib.pyplot as plt

        plt.close(self.figure)

    def _repr_html_(self) -> str | None:  # pragma: no cover - notebook nicety
        return None
