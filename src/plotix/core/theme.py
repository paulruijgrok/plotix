"""Visual identity for every plotix figure.

A :class:`Theme` bundles the two things that make figures look consistent and
deliberate: a small, carefully chosen colour palette and a set of matplotlib
rcParams. Plot functions never hard-code a colour or a font size — they ask the
active theme, so restyling the whole package is a one-file change.

The default theme, ``publication``, is a clean white-background style: no top or
right spines, light horizontal guides only, muted-but-saturated colours, and
generous whitespace.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt

__all__ = ["Theme", "THEMES", "get_theme", "register_theme", "use", "active_theme"]


@dataclass(frozen=True)
class Theme:
    """A named look: semantic colours plus matplotlib rcParams."""

    name: str

    # Semantic roles. Plot code refers to these, never to hex literals.
    primary: str = "#1D3557"  # main signal (e.g. UV absorbance)
    secondary: str = "#E07A5F"  # first auxiliary trace (e.g. conductivity)
    tertiary: str = "#3D8361"  # second auxiliary trace (e.g. gradient %B)
    quaternary: str = "#6A7FDB"  # further traces (pressure, pH, ...)
    accent: str = "#9A8C98"  # markers, fraction ticks
    ink: str = "#22252A"  # primary text
    muted: str = "#6E7377"  # secondary text, minor labels
    hairline: str = "#DCDEE1"  # spines, grid, separators
    band: str = "#F2F1EE"  # alternating fraction bands
    canvas: str = "#FFFFFF"  # figure and axes background

    # Line weights, in points, so plots scale coherently between themes.
    lw_primary: float = 1.9
    lw_secondary: float = 1.2
    lw_hairline: float = 0.8

    # Soft fill under the primary trace. 0 disables it.
    fill_alpha: float = 0.09

    rc: dict[str, Any] = field(default_factory=dict)

    @property
    def cycle(self) -> list[str]:
        """Ordered colours for arbitrary extra series."""
        return [
            self.primary,
            self.secondary,
            self.tertiary,
            self.quaternary,
            self.accent,
        ]

    def rc_params(self) -> dict[str, Any]:
        """Full rcParams dict: shared base, overridden by this theme's ``rc``."""
        base = {
            "figure.facecolor": self.canvas,
            "figure.dpi": 110,
            "savefig.facecolor": self.canvas,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.06,
            "axes.facecolor": self.canvas,
            "axes.edgecolor": self.ink,
            "axes.labelcolor": self.ink,
            "axes.titlecolor": self.ink,
            "axes.linewidth": 0.9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.axisbelow": True,
            "axes.titlelocation": "left",
            "axes.titleweight": "semibold",
            "axes.titlepad": 12.0,
            "axes.labelpad": 6.0,
            "axes.prop_cycle": mpl.cycler(color=self.cycle),
            "grid.color": self.hairline,
            "grid.linewidth": 0.7,
            "grid.alpha": 0.9,
            "xtick.color": self.muted,
            "ytick.color": self.muted,
            "xtick.labelcolor": self.ink,
            "ytick.labelcolor": self.ink,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.major.size": 4.0,
            "ytick.major.size": 4.0,
            "xtick.major.width": 0.9,
            "ytick.major.width": 0.9,
            "xtick.minor.size": 2.0,
            "ytick.minor.size": 2.0,
            "legend.frameon": False,
            "legend.handlelength": 1.6,
            "legend.handletextpad": 0.6,
            "legend.columnspacing": 1.4,
            "legend.borderaxespad": 0.0,
            "lines.solid_capstyle": "round",
            "lines.antialiased": True,
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Helvetica Neue",
                "Helvetica",
                "Arial",
                "DejaVu Sans",
                "sans-serif",
            ],
            "mathtext.fontset": "dejavusans",
            "pdf.fonttype": 42,  # embed real text, not outlines, so figures stay editable
            "ps.fonttype": 42,
            "svg.fonttype": "none",
        }
        base.update(self.rc)
        return base


PUBLICATION = Theme(
    name="publication",
    rc={
        "font.size": 9.5,
        "axes.titlesize": 11.0,
        "axes.labelsize": 9.5,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
        "figure.figsize": (6.4, 3.8),
    },
)

THEMES: dict[str, Theme] = {PUBLICATION.name: PUBLICATION}

_ACTIVE: Theme = PUBLICATION


def register_theme(theme: Theme) -> None:
    """Make ``theme`` selectable by name from the API and the CLI."""
    THEMES[theme.name] = theme


def get_theme(theme: str | Theme | None = None) -> Theme:
    """Resolve a theme name (or pass a :class:`Theme` through unchanged)."""
    if theme is None:
        return _ACTIVE
    if isinstance(theme, Theme):
        return theme
    try:
        return THEMES[theme]
    except KeyError:
        raise KeyError(
            f"unknown theme {theme!r}; available: {sorted(THEMES)}"
        ) from None


def active_theme() -> Theme:
    """The theme currently in effect."""
    return _ACTIVE


@contextlib.contextmanager
def use(theme: str | Theme | None = None) -> Iterator[Theme]:
    """Apply a theme's rcParams for the duration of the block.

    ``with theme.use("publication") as t:`` both styles matplotlib and hands
    back the resolved :class:`Theme` so plot code can read semantic colours.
    """
    global _ACTIVE
    resolved = get_theme(theme)
    previous = _ACTIVE
    _ACTIVE = resolved
    try:
        with plt.rc_context(resolved.rc_params()):
            yield resolved
    finally:
        _ACTIVE = previous
