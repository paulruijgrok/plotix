"""Reusable plotting primitives.

The pieces here are what give every plotix figure a common look regardless of
which instrument produced the data: consistent spine treatment, offset
secondary axes that stay legible, event bands along the x-axis, and peak
labels that do not collide with the trace.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable, Sequence

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator, MaxNLocator

from .dataset import Curve, Event
from .peaks import Peak
from .theme import Theme

__all__ = [
    "style_axes",
    "add_offset_axis",
    "enforce_min_span",
    "raise_axes",
    "plot_curve",
    "add_event_bands",
    "add_event_lines",
    "annotate_peaks",
    "finish_figure",
]


def style_axes(ax: Axes, theme: Theme, *, xlabel: str = "", ylabel: str = "") -> None:
    """Apply the theme's spine, tick and grid treatment to a primary axis."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.ink)
        ax.spines[side].set_linewidth(0.9)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6, prune=None))
    ax.grid(True, axis="y", color=theme.hairline, linewidth=0.7, alpha=0.9)
    ax.grid(False, axis="x")
    ax.set_axisbelow(True)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)


def add_offset_axis(
    ax: Axes,
    theme: Theme,
    color: str,
    label: str,
    offset: float = 0.0,
) -> Axes:
    """A right-hand twin axis, colour-matched to its trace.

    ``offset`` is in axes-fraction units and shifts the spine outwards so a
    second and third y-axis can coexist without overlapping tick labels.
    """
    twin = ax.twinx()
    twin.spines["top"].set_visible(False)
    twin.spines["left"].set_visible(False)
    twin.spines["bottom"].set_visible(False)
    twin.spines["right"].set_visible(True)
    twin.spines["right"].set_position(("axes", 1.0 + offset))
    twin.spines["right"].set_color(color)
    twin.spines["right"].set_linewidth(0.9)
    twin.tick_params(axis="y", colors=color, which="both", labelsize=None)
    twin.set_ylabel(label, color=color)
    twin.yaxis.set_major_locator(MaxNLocator(nbins=5))
    twin.grid(False)
    return twin


def enforce_min_span(ax: Axes, min_span: float) -> None:
    """Stop an auto-scaled axis from magnifying a flat trace into noise.

    An axis fitted to a channel that barely moves turns instrument ripple into
    a dramatic-looking squiggle that visually outranks the real signal. Holding
    the axis open to at least ``min_span``, centred on the data, keeps a flat
    trace looking flat — which is the honest reading.
    """
    lo, hi = ax.get_ylim()
    span = hi - lo
    if span >= min_span or min_span <= 0:
        return
    mid = (lo + hi) / 2.0
    ax.set_ylim(mid - min_span / 2.0, mid + min_span / 2.0)


def raise_axes(ax: Axes, twins: Sequence[Axes]) -> None:
    """Draw ``ax`` above its twins without its opaque background hiding them.

    ``twinx`` axes are created behind the original, so a primary axis with a
    filled background would paint over every auxiliary trace. Lifting the
    z-order and dropping the patch puts the main signal on top while leaving
    the auxiliary lines visible underneath it.
    """
    if not twins:
        return
    ax.set_zorder(max(t.get_zorder() for t in twins) + 1)
    ax.patch.set_visible(False)


def plot_curve(
    ax: Axes,
    curve: Curve,
    color: str,
    *,
    theme: Theme,
    label: str | None = None,
    linewidth: float | None = None,
    linestyle: str = "-",
    alpha: float = 1.0,
    fill: bool = False,
    fill_alpha: float | None = None,
    zorder: float = 3.0,
):
    """Draw one curve, optionally with a soft fill down to its baseline."""
    lw = linewidth if linewidth is not None else theme.lw_primary
    (line,) = ax.plot(
        curve.x,
        curve.y,
        color=color,
        linewidth=lw,
        linestyle=linestyle,
        alpha=alpha,
        label=label if label is not None else curve.name,
        zorder=zorder,
        solid_joinstyle="round",
    )
    if fill and len(curve):
        baseline = float(np.nanmin(curve.y))
        ax.fill_between(
            curve.x,
            curve.y,
            baseline,
            color=color,
            alpha=theme.fill_alpha if fill_alpha is None else fill_alpha,
            linewidth=0,
            zorder=zorder - 1,
        )
    return line


def add_event_bands(
    ax: Axes,
    events: Sequence[Event],
    theme: Theme,
    *,
    height: float = 0.055,
    label_every: int | None = None,
    max_labels: int = 24,
    xmax: float | None = None,
) -> None:
    """Alternating bands with labels along the bottom of the axes.

    Used for collected fractions. Each event marks the *start* of a band that
    runs to the next event (or to ``xmax`` for the last one). Labels thin out
    automatically so they never overlap.
    """
    if not events:
        return

    ordered = sorted(events, key=lambda e: e.x)
    limit = xmax if xmax is not None else ax.get_xlim()[1]
    edges = [e.x for e in ordered] + [limit]

    if label_every is None:
        label_every = max(1, int(np.ceil(len(ordered) / max_labels)))

    trans = ax.get_xaxis_transform()  # x in data coords, y in axes coords

    for i, event in enumerate(ordered):
        left, right = edges[i], edges[i + 1]
        if right <= left:
            continue
        if i % 2 == 0:
            ax.axvspan(
                left,
                right,
                ymin=0.0,
                ymax=height,
                facecolor=theme.band,
                edgecolor="none",
                zorder=0.5,
            )
        ax.plot(
            [left, left],
            [0.0, height],
            transform=trans,
            color=theme.accent,
            linewidth=0.6,
            alpha=0.9,
            zorder=1.0,
            clip_on=False,
        )
        if i % label_every == 0:
            ax.text(
                (left + right) / 2.0,
                height / 2.0,
                event.label,
                transform=trans,
                ha="center",
                va="center",
                fontsize=6.0,
                color=theme.muted,
                zorder=2.0,
                clip_on=True,
            )

    ax.plot(
        [edges[0], edges[-1]],
        [height, height],
        transform=trans,
        color=theme.accent,
        linewidth=0.6,
        alpha=0.6,
        zorder=1.0,
        clip_on=False,
    )


def add_event_lines(
    ax: Axes,
    events: Iterable[Event],
    theme: Theme,
    *,
    color: str | None = None,
    linestyle: tuple = (0, (4, 3)),
    label: bool = True,
    y: float = 1.0,
    edge_margin: float = 0.01,
) -> None:
    """Vertical annotation lines, e.g. sample injection.

    Events sitting within ``edge_margin`` (a fraction of the x-range) of the
    left edge are drawn without a label: the line coincides with the y-axis
    there, so a label would float over the plot pointing at nothing.
    """
    colour = color or theme.muted
    xlo, xhi = ax.get_xlim()
    margin = edge_margin * (xhi - xlo)
    for event in events:
        at_edge = abs(event.x - xlo) <= margin
        ax.axvline(
            event.x,
            color=colour,
            linewidth=0.9,
            linestyle=linestyle,
            alpha=0.75,
            zorder=1.5,
        )
        if label and event.label and not at_edge:
            ax.annotate(
                event.label,
                xy=(event.x, y),
                xycoords=ax.get_xaxis_transform(),
                xytext=(3, -3),
                textcoords="offset points",
                ha="left",
                va="top",
                fontsize=7.0,
                color=colour,
            )


def annotate_peaks(
    ax: Axes,
    peaks: Sequence[Peak],
    theme: Theme,
    *,
    fmt: str = "{x:.2f}",
    color: str | None = None,
    marker: bool = True,
) -> None:
    """Label peaks above the trace, nudging text apart where peaks crowd."""
    if not peaks:
        return
    colour = color or theme.ink

    if marker:
        ax.plot(
            [p.x for p in peaks],
            [p.height for p in peaks],
            linestyle="none",
            marker="v",
            markersize=3.4,
            markerfacecolor=colour,
            markeredgecolor="none",
            alpha=0.75,
            zorder=5,
        )

    xspan = np.ptp(ax.get_xlim()) or 1.0
    last_x = -np.inf
    stagger = 0
    for peak in sorted(peaks, key=lambda p: p.x):
        # Alternate the vertical offset when two labels would sit on top of
        # each other, rather than dropping one of them.
        if (peak.x - last_x) / xspan < 0.07:
            stagger = 1 - stagger
        else:
            stagger = 0
        ax.annotate(
            fmt.format(x=peak.x, height=peak.height, area=peak.area),
            xy=(peak.x, peak.height),
            xytext=(0, 9 + 11 * stagger),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.0,
            color=colour,
            zorder=6,
        )
        last_x = peak.x


def finish_figure(
    fig: Figure,
    ax: Axes,
    theme: Theme,
    *,
    title: str | None = None,
    subtitle: str | None = None,
    caption: str | None = None,
    legend_handles: list | None = None,
    legend_ncol: int = 4,
    title_wrap: int = 58,
    subtitle_width: int = 76,
) -> None:
    """Title block, legend and caption, laid out consistently.

    Run names from instrument software are often long and descriptive, so the
    title wraps rather than running off the canvas, and the subtitle is
    elided at a width that stays inside the axes.
    """
    if title:
        wrapped = "\n".join(textwrap.wrap(title, width=title_wrap)) or title
        n_lines = wrapped.count("\n") + 1
        ax.set_title(wrapped, loc="left", pad=(18 if subtitle else 12) + 4 * (n_lines - 1))
    if subtitle:
        ax.annotate(
            textwrap.shorten(subtitle, width=subtitle_width, placeholder=" …"),
            xy=(0.0, 1.0),
            xycoords="axes fraction",
            xytext=(0, 7),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=8.0,
            color=theme.muted,
        )
    if legend_handles:
        ax.legend(
            handles=legend_handles,
            loc="upper right",
            ncol=min(legend_ncol, len(legend_handles)),
            frameon=False,
            fontsize=8.0,
            borderaxespad=0.2,
        )
    if caption:
        fig.text(
            0.0,
            -0.02,
            caption,
            ha="left",
            va="top",
            fontsize=6.8,
            color=theme.muted,
        )
