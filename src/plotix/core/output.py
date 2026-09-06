"""Where output goes.

Figures are made in sessions: you come back from the instrument with a handful
of runs and plot them, then do it again tomorrow with different ones. The
layout follows that shape::

    output/
      20260905_FPLC/              <- one day, one kind of data
        20260905_143022/          <- one invocation of plotix
          <run>.png .pdf .svg
          <run>_source_data.csv
          <run>_peaks.csv
          <run>_marks.csv
        20260905_151140/          <- replotted with different settings
          ...
      20260905_PLATE/             <- a different instrument, same day
      20260906_FPLC/              <- tomorrow

Three properties this buys, in order of how much they matter:

* **A re-run never destroys the last one.** Each invocation gets its own
  timestamped folder, so trying different settings leaves both results side by
  side rather than overwriting the figure you were about to use.
* **A day's work is in one place**, regardless of where the raw data sits.
* **The folder name says what is in it** without opening anything.

The day folder is dated when plotix runs, not when the data was acquired, so
replotting last week's runs today collects them into today's session.

``daily`` mode drops the per-run folder and writes straight into the day
folder, overwriting what is there. That is the right mode once settings have
settled and the accumulating timestamped folders are just clutter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = [
    "OutputLayout",
    "DEFAULT_ROOT",
    "day_folder_name",
    "run_folder_name",
]

#: Default root, relative to wherever plotix is run from.
DEFAULT_ROOT = "output"

_DAY_FORMAT = "%Y%m%d"
_RUN_FORMAT = "%Y%m%d_%H%M%S"
_LABEL_STRIP = re.compile(r"[^\w.\-]+")


def day_folder_name(kind: str, when: datetime | None = None) -> str:
    """``20260905_FPLC`` — the date plotix ran, plus the kind of data."""
    stamp = (when or datetime.now()).strftime(_DAY_FORMAT)
    tag = _LABEL_STRIP.sub("_", kind.strip()).strip("_").upper()
    return f"{stamp}_{tag}" if tag else stamp


def run_folder_name(when: datetime | None = None, label: str | None = None) -> str:
    """``20260905_143022`` — one invocation, optionally tagged."""
    stamp = (when or datetime.now()).strftime(_RUN_FORMAT)
    if label:
        tag = _LABEL_STRIP.sub("_", label.strip()).strip("_")
        if tag:
            return f"{stamp}_{tag}"
    return stamp


@dataclass
class OutputLayout:
    """Resolves where a run's files are written.

    One layout is built per invocation and reused for every file in it, so a
    batch of forty runs lands in a single timestamped folder rather than forty
    of them. The timestamp is therefore taken once, at construction.

    Parameters
    ----------
    root:
        The ``output/`` directory. Relative paths resolve against the current
        working directory.
    mode:
        ``"run"`` (default) writes to ``<root>/<day>/<timestamp>/``, so each
        invocation is preserved. ``"daily"`` writes to ``<root>/<day>/``,
        overwriting whatever is already there.
    label:
        Appended to the run folder name to say what the run was about.
    when:
        Override the timestamp. Only useful for tests and for reproducing a
        previous session's layout.
    """

    root: str | Path = DEFAULT_ROOT
    mode: str = "run"
    label: str | None = None
    when: datetime | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"run", "daily"}:
            raise ValueError(
                f"mode must be 'run' or 'daily', got {self.mode!r}"
            )
        # Freeze the clock so every file in one invocation shares a folder,
        # even if the batch runs past midnight.
        self.when = self.when or datetime.now()
        self.root = Path(self.root)

    def directory(self, kind: str) -> Path:
        """The directory for output of the given kind, e.g. ``"fplc"``.

        Not created here — :meth:`~plotix.core.export.FigureBundle.save` makes
        the directory when it actually writes, so asking where output *would*
        go has no side effects.
        """
        day = self.root / day_folder_name(kind, self.when)
        if self.mode == "daily":
            return day
        return day / run_folder_name(self.when, self.label)

    def describe(self, kind: str) -> str:
        """One-line summary for logs and CLI output."""
        return str(self.directory(kind))
