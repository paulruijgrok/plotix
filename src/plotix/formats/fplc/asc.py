"""Reader for ÄKTA / UNICORN ASCII chromatogram exports (``.asc``).

File layout
-----------
UNICORN writes one tab-separated block in which every curve occupies a *pair*
of columns — its own x values followed by its y values — because detectors are
sampled at different rates. Columns are padded with blanks once a curve runs
out of samples, so the block is ragged rather than rectangular::

    10      10      10      ...            <- optional curve-count row
    run:10_UV       run:10_Cond    ...     <- curve names (one per pair)
    ml      mAU     ml     mS/cm   ...     <- x unit, y unit per pair
    0.000   -0.002  0.000  18.118  ...     <- data
             ...

Channels whose y-unit is parenthesised — ``(Fractions)``, ``(Injections)``,
``(Set Marks)`` — hold quoted text labels rather than numbers, and become
:class:`~plotix.core.dataset.Event` objects instead of curves.

The parser locates the header rows by finding the first row whose first field
parses as a number, rather than assuming a fixed number of preamble lines, so
exports with or without the curve-count row both work.

The exported volume axis is already zeroed at the injection, so unlike the
``.res`` reader this one needs no origin handling.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ...core.dataset import Curve, Dataset, Event
from ...core.io import parse_number, read_text
from .channels import (
    SIGNAL_KIND,
    canonical_channel,
    parse_logbook,
    split_curve_name,
)

__all__ = ["read_asc", "sniff_asc", "EVENT_UNITS"]

#: y-unit -> event kind. Parenthesised units mark text channels.
EVENT_UNITS: dict[str, str] = {
    "(fractions)": "fraction",
    "(injections)": "injection",
    "(set marks)": "logbook",
    "(logbook)": "logbook",
    "(run log)": "logbook",
}


def sniff_asc(head: str) -> bool:
    """True if ``head`` looks like a UNICORN ASCII export."""
    import re

    lowered = head[:4000].lower()
    has_pairs = "\t" in head
    has_channel = bool(re.search(r":\s*\d+\s*_(uv|cond|conc|pressure|flow)", lowered))
    has_units = "mau" in lowered or "ms/cm" in lowered
    return has_pairs and (has_channel or has_units)


def _find_header_rows(rows: list[list[str]]) -> tuple[int, int, int]:
    """Return (names_row, units_row, first_data_row) indices.

    The first row whose leading field parses as a number starts the data; the
    two rows above it are the units and the curve names.
    """
    for i, row in enumerate(rows):
        if not row:
            continue
        if parse_number(row[0]) is not None and i >= 2:
            return i - 2, i - 1, i
    raise ValueError("no numeric data rows found — not a UNICORN ASCII export?")


def read_asc(
    path: str | Path,
    encoding: str | None = None,
    keep_logbook: bool = True,
) -> Dataset:
    """Parse a UNICORN ``.asc`` export into a :class:`Dataset`.

    Parameters
    ----------
    path:
        The ``.asc`` file.
    encoding:
        Force a text encoding. By default the encoding is detected, which
        covers the UTF-16 and Windows-codepage variants UNICORN emits.
    keep_logbook:
        Keep logbook/set-mark entries as events. They are not drawn by default
        but carry the run metadata (column, method, date).
    """
    path = Path(path)
    text = read_text(path, encoding=encoding)
    rows = [line.split("\t") for line in text.splitlines()]
    rows = [row for row in rows if any(field.strip() for field in row)]
    if not rows:
        raise ValueError(f"{path}: file is empty")

    names_idx, units_idx, data_start = _find_header_rows(rows)
    names_row, units_row = rows[names_idx], rows[units_idx]
    n_pairs = min(len(names_row), len(units_row)) // 2

    dataset = Dataset(name=path.stem, format="fplc", source_path=path)
    dataset.meta["source_format"] = "asc"
    run_names: list[str] = []
    logbook_text: list[str] = []

    for pair in range(n_pairs):
        xc, yc = 2 * pair, 2 * pair + 1
        run_name, raw_channel = split_curve_name(names_row[xc])
        if not raw_channel:
            continue
        if run_name:
            run_names.append(run_name)

        x_unit = units_row[xc].strip() if xc < len(units_row) else ""
        y_unit = units_row[yc].strip() if yc < len(units_row) else ""
        event_kind = EVENT_UNITS.get(y_unit.lower())

        xs: list[float] = []
        ys: list[float] = []
        labels: list[tuple[float, str]] = []

        for row in rows[data_start:]:
            if yc >= len(row):
                continue
            x_value = parse_number(row[xc])
            if x_value is None:
                continue
            raw_y = row[yc].strip()
            if event_kind is not None:
                label = raw_y.strip('"').strip()
                if label:
                    labels.append((x_value, label))
                continue
            y_value = parse_number(raw_y)
            if y_value is None:
                continue
            xs.append(x_value)
            ys.append(y_value)

        if event_kind is not None:
            for x, label in labels:
                if event_kind == "logbook":
                    logbook_text.append(label)
                    if not keep_logbook:
                        continue
                dataset.add_event(
                    Event(x=x, label=label, kind=event_kind, meta={"channel": raw_channel})
                )
            continue

        if not xs:
            continue

        channel = canonical_channel(raw_channel)
        dataset.add_curve(
            Curve(
                name=channel,
                x=np.asarray(xs),
                y=np.asarray(ys),
                x_label="Volume" if x_unit.lower() == "ml" else "Time",
                x_unit=x_unit,
                y_label=channel,
                y_unit=y_unit,
                kind=SIGNAL_KIND.get(channel, "signal"),
                meta={"raw_channel": raw_channel, "run": run_name},
            )
        )

    dataset.meta["run_name"] = run_names[0] if run_names else path.stem
    dataset.meta["n_curves"] = len(dataset.curves)
    dataset.meta.update(parse_logbook(logbook_text))
    if dataset.curves:
        first = next(iter(dataset.curves.values()))
        dataset.meta["x_label"] = first.x_label
        dataset.meta["x_unit"] = first.x_unit
    return dataset
