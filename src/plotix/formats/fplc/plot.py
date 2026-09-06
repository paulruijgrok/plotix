"""Chromatogram figure for ÄKTA / UNICORN FPLC runs.

The figure is built around one question: *what came off the column, and where?*
So the UV trace is the visual subject — heavy line, soft fill, peak volumes
labelled — and everything else is deliberately quieter: auxiliary traces sit on
colour-matched offset axes, and collected fractions run as a thin band along the
bottom rather than as full-height lines competing with the signal.

Auxiliary channels are selected automatically. A channel that never moves (the
%B trace of an isocratic SEC run, say) adds an axis and a legend entry while
telling the reader nothing, so it is dropped unless explicitly requested.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

from ...core import peaks as peaks_mod
from ...core import theme as theme_mod
from ...core.dataset import Dataset, Event
from ...core.export import FigureBundle, curves_to_long_frame, slugify
from ...core.plotting import (
    add_event_bands,
    add_event_lines,
    add_offset_axis,
    annotate_peaks,
    enforce_min_span,
    finish_figure,
    plot_curve,
    raise_axes,
    style_axes,
)
from .reader import read_fplc

__all__ = ["plot_chromatogram", "AUXILIARY_CHANNELS", "MIN_SPAN", "MIN_DISPLAY_SPAN"]

#: Auxiliary channels considered for the right-hand axes, in drawing order.
AUXILIARY_CHANNELS: tuple[str, ...] = ("Conductivity", "Concentration B", "Pressure", "pH")

#: Below this peak-to-peak range a channel carries no information worth an axis
#: and is dropped in ``auxiliary="auto"`` mode. Units are the channel's own.
#: The conductivity threshold sits above the drift of a running isocratic SEC
#: buffer but well below any real ion-exchange gradient.
MIN_SPAN: dict[str, float] = {
    "Conductivity": 1.0,  # mS/cm
    "Concentration B": 1.0,  # %B
    "Pressure": 0.5,  # MPa
    "pH": 0.1,
}

#: Minimum height of an auxiliary axis, in the channel's own units. Applied
#: whenever a channel *is* drawn — including when the user asks for one that
#: barely moves — so its axis cannot magnify detector ripple into a squiggle
#: that outshouts the UV trace.
MIN_DISPLAY_SPAN: dict[str, float] = {
    "Conductivity": 5.0,  # mS/cm
    "Concentration B": 10.0,  # %B
    "Pressure": 1.0,  # MPa
    "pH": 1.0,
}

_AUX_ROLE = {
    "Conductivity": "secondary",
    "Concentration B": "tertiary",
    "Pressure": "quaternary",
    "pH": "accent",
}

# Fraction marks whose label is not a number close the last band rather than
# opening a new one.
_TERMINAL_FRACTION_LABELS = {"waste", "end", "stop"}


def _select_auxiliary(
    dataset: Dataset,
    requested: str | Sequence[str] | None,
) -> list:
    """Resolve the ``auxiliary`` argument into a list of curves to draw."""
    if requested is None or (isinstance(requested, str) and requested.lower() == "none"):
        return []

    if isinstance(requested, str) and requested.lower() == "auto":
        selected = []
        for name in AUXILIARY_CHANNELS:
            curve = dataset.get(name)
            if curve is None or len(curve) == 0:
                continue
            if curve.span < MIN_SPAN.get(name, 0.0):
                continue
            selected.append(curve)
        return selected[:2]  # two offset axes stay readable; a third does not

    names = [requested] if isinstance(requested, str) else list(requested)
    curves = []
    for name in names:
        curve = dataset.get(name)
        if curve is None:
            raise KeyError(
                f"auxiliary channel {name!r} not in dataset; available: "
                f"{sorted(dataset.curves)}"
            )
        curves.append(curve)
    return curves


def _fraction_bands(events: list[Event]) -> tuple[list[Event], float | None]:
    """Split fraction marks into band starts and a closing x position."""
    ordered = sorted(events, key=lambda e: e.x)
    if not ordered:
        return [], None
    last = ordered[-1]
    if last.label.strip().lower() in _TERMINAL_FRACTION_LABELS:
        return ordered[:-1], last.x
    return ordered, None


def _subtitle(dataset: Dataset) -> str:
    bits = []
    column = dataset.meta.get("column")
    if column:
        cv = dataset.meta.get("column_volume")
        unit = dataset.meta.get("column_volume_unit", "")
        bits.append(f"{column} ({cv:g} {unit} CV)" if cv else str(column))
    method = dataset.meta.get("method")
    if method:
        bits.append(f"method {method}")
    started = dataset.meta.get("run_started")
    if started:
        bits.append(str(started))
    return "  ·  ".join(bits)


def plot_chromatogram(
    source: str | Path | Dataset,
    *,
    theme: str | theme_mod.Theme | None = "publication",
    auxiliary: str | Sequence[str] | None = "auto",
    signal: str = "UV",
    show_fractions: bool = True,
    show_injection: bool = True,
    annotate_peaks_: bool = True,
    max_peaks: int = 6,
    min_peak_prominence: float = 0.05,
    peak_window: tuple[float, float] | None = None,
    fill: bool = True,
    xlim: tuple[float | None, float | None] | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    caption: str | None = None,
    figsize: tuple[float, float] | None = None,
    stem: str | None = None,
    origin: str | float = "injection",
    trim: bool = True,
) -> FigureBundle:
    """Plot an FPLC chromatogram and collect its source data.

    Parameters
    ----------
    source:
        Path to a ``.asc`` export, or an already-parsed :class:`Dataset`.
    auxiliary:
        ``"auto"`` (default) draws whichever of conductivity, %B, pressure and
        pH actually vary; ``"none"`` draws only the UV trace; a name or list of
        names forces specific channels.
    signal:
        Which channel is the subject of the plot. ``"UV"`` unless a run has
        several UV channels and you want ``"UV2"``.
    annotate_peaks_:
        Label peak positions on the trace and write a peak table CSV. Trailing
        underscore avoids shadowing the plotting helper of the same name.
    min_peak_prominence:
        Peak prominence threshold as a fraction of the signal's range.
    peak_window:
        ``(xmin, xmax)`` to restrict peak detection, e.g. to skip the void
        volume.
    origin, trim:
        Where volume zero sits, and whether to drop what comes before it. Only
        meaningful for ``.res`` input — an ASCII export is already zeroed at
        the injection — and ignored when ``source`` is an existing dataset.
        See :func:`~plotix.formats.fplc.res.read_res`.

    Returns
    -------
    FigureBundle
        Figure, tidy source data, and a peak/marks table — call ``.save()``.
    """
    dataset = (
        source
        if isinstance(source, Dataset)
        else read_fplc(source, origin=origin, trim=trim)
    )
    if not isinstance(dataset, Dataset):  # pragma: no cover - defensive
        raise TypeError("source must be a path or a Dataset")

    main = dataset.require(signal)
    aux_curves = _select_auxiliary(dataset, auxiliary)
    plotted = [main, *aux_curves]

    with theme_mod.use(theme) as th:
        fig, ax = plt.subplots(figsize=figsize or plt.rcParams["figure.figsize"])
        style_axes(ax, th, xlabel=main.x_axis_label, ylabel=main.y_axis_label)
        ax.yaxis.label.set_color(th.primary)
        ax.tick_params(axis="y", colors=th.primary)
        ax.spines["left"].set_color(th.primary)

        handles: list[Line2D] = []
        line = plot_curve(
            ax, main, th.primary, theme=th, label=main.name, fill=fill, zorder=4
        )
        handles.append(line)

        twins = []
        for i, curve in enumerate(aux_curves):
            colour = getattr(th, _AUX_ROLE.get(curve.name, "quaternary"))
            twin = add_offset_axis(
                ax, th, colour, curve.y_axis_label, offset=0.0 if i == 0 else 0.13
            )
            twins.append(twin)
            aux_line = plot_curve(
                twin,
                curve,
                colour,
                theme=th,
                label=curve.name,
                linewidth=th.lw_secondary,
                alpha=0.9,
                zorder=2,
            )
            handles.append(aux_line)
            enforce_min_span(twin, MIN_DISPLAY_SPAN.get(curve.name, 0.0))
        raise_axes(ax, twins)

        # Fraction band and injection marks sit on the primary axes so they
        # share its x scale.
        fraction_events, band_end = ([], None)
        if show_fractions:
            fraction_events, band_end = _fraction_bands(dataset.events_of("fraction"))

        injection_events = dataset.events_of("injection") if show_injection else []

        # x limits before the bands are drawn, so the last band closes correctly.
        data_xmin, data_xmax = dataset.x_range([c.name for c in plotted])
        lo = xlim[0] if xlim and xlim[0] is not None else data_xmin
        hi = xlim[1] if xlim and xlim[1] is not None else data_xmax
        ax.set_xlim(lo, hi)

        # Headroom: peak labels need space above, the fraction band below.
        ymin, ymax = float(main.y.min()), float(main.y.max())
        height = (ymax - ymin) or 1.0
        ax.set_ylim(ymin - 0.10 * height, ymax + 0.18 * height)

        if fraction_events:
            add_event_bands(
                ax,
                fraction_events,
                th,
                xmax=band_end if band_end is not None else hi,
            )
        if injection_events:
            add_event_lines(
                ax,
                [Event(e.x, "injection", e.kind) for e in injection_events],
                th,
            )

        detected: list[peaks_mod.Peak] = []
        if annotate_peaks_:
            detected = peaks_mod.find_peaks(
                main,
                min_prominence_frac=min_peak_prominence,
                max_peaks=max_peaks,
                xmin=peak_window[0] if peak_window else None,
                xmax=peak_window[1] if peak_window else None,
            )
            annotate_peaks(ax, detected, th, fmt="{x:.2f}")

        run_name = str(dataset.meta.get("run_name", dataset.name))
        finish_figure(
            fig,
            ax,
            th,
            title=title if title is not None else run_name,
            subtitle=subtitle if subtitle is not None else _subtitle(dataset),
            caption=caption
            if caption is not None
            else (f"Source: {dataset.source_path.name}" if dataset.source_path else None),
            legend_handles=handles if len(handles) > 1 else None,
        )
        fig.tight_layout()

    tables: dict[str, pd.DataFrame] = {}
    marks = [*dataset.events_of("fraction"), *dataset.events_of("injection")]
    if marks:
        tables["marks"] = pd.DataFrame(
            [{"kind": e.kind, main.x_label.lower(): e.x, "label": e.label} for e in marks]
        )
    if detected:
        tables["peaks"] = peaks_mod.peaks_to_frame(detected, main)

    return FigureBundle(
        figure=fig,
        stem=stem or slugify(dataset.name),
        source_data=curves_to_long_frame(plotted),
        tables=tables,
        meta={
            "format": "fplc",
            "run_name": run_name,
            "source_path": str(dataset.source_path) if dataset.source_path else None,
            "channels_plotted": [c.name for c in plotted],
            "n_peaks": len(detected),
            **{k: v for k, v in dataset.meta.items() if k != "run_name"},
        },
    )
