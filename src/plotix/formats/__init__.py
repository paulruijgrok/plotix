"""Instrument-specific readers and plots.

Importing this package registers every bundled format with
:mod:`plotix.core.registry`. Each format lives in its own subpackage with a
``reader`` module (file -> :class:`~plotix.core.dataset.Dataset`) and a ``plot``
module (Dataset -> :class:`~plotix.core.export.FigureBundle`).
"""

from . import fplc  # noqa: F401  (import registers the format)

__all__ = ["fplc"]
