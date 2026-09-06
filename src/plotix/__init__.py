"""plotix — quick, beautiful plots of experimental data files.

Two ideas hold the package together:

1. **A shared core, specialised edges.** Anything that is true of all data —
   containers, theming, figure export, peak finding, batch running — lives in
   :mod:`plotix.core`. Anything specific to one instrument lives in a
   :mod:`plotix.formats` subpackage with a reader and a plot function.
2. **Every figure ships its numbers.** Saving a plot also writes the tidy CSV
   of exactly what was drawn, the way journals ask for figure source data.
3. **Output is filed by session.** Figures go to a dated folder per day and per
   invocation, so a re-run never overwrites the last one — see
   :mod:`plotix.core.output`.

Typical use::

    import plotix
    plotix.plot_file("run.res")

or from the shell::

    plotix plot run.res
"""

from __future__ import annotations

from . import core, formats
from .api import plot, plot_file, read, resolve_format
from .core.dataset import Curve, Dataset, Event
from .core.export import DEFAULT_FORMATS, FigureBundle
from .core.output import OutputLayout
from .core.registry import list_formats
from .core.theme import THEMES, Theme, register_theme, use

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "core",
    "formats",
    "read",
    "plot",
    "plot_file",
    "resolve_format",
    "list_formats",
    "Dataset",
    "Curve",
    "Event",
    "FigureBundle",
    "DEFAULT_FORMATS",
    "OutputLayout",
    "Theme",
    "THEMES",
    "use",
    "register_theme",
]
