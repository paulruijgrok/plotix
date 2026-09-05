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
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ...core.dataset import Curve, Dataset, Event
from ...core.io import parse_number, read_text

__all__ = ["read_asc", "sniff_asc", "CHANNEL_ALIASES"]

#: Maps the channel suffix UNICORN writes onto a stable plotix name. Keys are
#: lower-cased and stripped of spaces/underscores before lookup.
CHANNEL_ALIASES: dict[str, str] = {
    "uv": "UV",
    "uv1": "UV",
    "uv1_280": "UV",
    "uv1_280nm": "UV",
    "uv2": "UV2",
    "uv3": "UV3",
    "cond": "Conductivity",
    "conductivity": "Conductivity",
    "cond%": "Conductivity%",
    "concb": "Concentration B",
    "conc": "Concentration B",
    "concentration": "Concentration B",
    "pressure": "Pressure",
    "systempressure": "Pressure",
    "prec": "Pre-column pressure",
    "flow": "Flow",
    "temp": "Temperature",
    "temperature": "Temperature",
    "ph": "pH",
    "uvcellpath": "UV cell path length",
}

#: y-unit -> event kind. Parenthesised units mark text channels.
EVENT_UNITS: dict[str, str] = {
    "(fractions)": "fraction",
    "(injections)": "injection",
    "(set marks)": "logbook",
    "(logbook)": "logbook",
    "(run log)": "logbook",
}

_SIGNAL_KIND = {
    "UV": "uv",
    "UV2": "uv",
    "UV3": "uv",
    "Conductivity": "conductivity",
    "Conductivity%": "conductivity",
    "Concentration B": "gradient",
    "Pressure": "pressure",
    "Flow": "flow",
    "Temperature": "temperature",
    "pH": "ph",
}

# "20260902 my run 001:10_UV" -> run name "20260902 my run 001", channel "UV"
_HEADER_SPLIT = re.compile(r"^(?P<run>.*?):\s*\d+\s*_(?P<channel>.+)$")
_COLUMN_LOGBOOK = re.compile(
    r"Base\s+CV,\s*(?P<cv>[\d.,]+)\s*\{(?P<cv_unit>[^}]*)\},\s*(?P<column>\S+)",
    re.IGNORECASE,
)
_METHOD_LOGBOOK = re.compile(r"Method\s*:\s*(?P<method>.+?)\s*$", re.IGNORECASE)
_RUN_DATE_LOGBOOK = re.compile(r"Method Run\s+(?P<when>[^,]+,[^,]+)", re.IGNORECASE)


def _normalise_run_date(raw: str) -> str:
    """Turn UNICORN's verbose timestamp into a compact ISO-style one.

    ``"9/2/2026, 5:41:13 PM Pacific Daylight Time"`` -> ``"2026-09-02 17:41"``.
    The raw string is returned unchanged if it does not parse, since a slightly
    long subtitle is better than losing the run date entirely.
    """
    from datetime import datetime

    text = raw.strip()
    match = re.match(
        r"(?P<date>\d{1,2}/\d{1,2}/\d{4}),?\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[AP]M)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    time_part = match.group("time")
    if time_part.count(":") == 1:
        time_part += ":00"
    ampm = (match.group("ampm") or "").upper()
    fmt = "%m/%d/%Y %H:%M:%S" if not ampm else "%m/%d/%Y %I:%M:%S %p"
    stamp = f"{match.group('date')} {time_part}" + (f" {ampm}" if ampm else "")
    try:
        return datetime.strptime(stamp, fmt).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def sniff_asc(head: str) -> bool:
    """True if ``head`` looks like a UNICORN ASCII export."""
    lowered = head[:4000].lower()
    has_pairs = "\t" in head
    has_channel = bool(re.search(r":\s*\d+\s*_(uv|cond|conc|pressure|flow)", lowered))
    has_units = "mau" in lowered or "ms/cm" in lowered
    return has_pairs and (has_channel or has_units)


def _canonical_channel(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "").replace("_", "")
    # Keep the '%' that distinguishes Cond from Cond%, which the strip above
    # would otherwise leave attached to an unrecognised key.
    if key in CHANNEL_ALIASES:
        return CHANNEL_ALIASES[key]
    if raw.strip().lower() in CHANNEL_ALIASES:
        return CHANNEL_ALIASES[raw.strip().lower()]
    return raw.strip()


def _split_header(field: str) -> tuple[str | None, str]:
    """Split ``run:10_UV`` into (run name, channel); fall back to the raw text."""
    field = field.strip()
    if not field:
        return None, ""
    match = _HEADER_SPLIT.match(field)
    if match:
        return match.group("run").strip(), match.group("channel").strip()
    return None, field


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


def _parse_logbook(events: list[Event]) -> dict[str, str]:
    """Pull column, method and run date out of the logbook text channel."""
    meta: dict[str, str] = {}
    for event in events:
        text = event.label
        if "column" not in meta:
            match = _COLUMN_LOGBOOK.search(text)
            if match:
                meta["column"] = match.group("column").replace("_", " ")
                cv = parse_number(match.group("cv"))
                if cv is not None:
                    meta["column_volume"] = cv
                    meta["column_volume_unit"] = match.group("cv_unit").strip()
        if "run_started" not in meta:
            match = _RUN_DATE_LOGBOOK.search(text)
            if match:
                meta["run_started"] = _normalise_run_date(match.group("when"))
        if "method" not in meta:
            match = _METHOD_LOGBOOK.search(text)
            if match:
                meta["method"] = match.group("method").strip()
    return meta


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
        but carry the run metadata (column, method, date) and are useful when
        checking what the instrument actually did.
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
    run_names: list[str] = []
    logbook_events: list[Event] = []

    for pair in range(n_pairs):
        xc, yc = 2 * pair, 2 * pair + 1
        run_name, raw_channel = _split_header(names_row[xc])
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
            events = [
                Event(x=x, label=label, kind=event_kind, meta={"channel": raw_channel})
                for x, label in labels
            ]
            if event_kind == "logbook":
                logbook_events = events
                if keep_logbook:
                    dataset.events.extend(events)
            else:
                dataset.events.extend(events)
            continue

        if not xs:
            continue

        channel = _canonical_channel(raw_channel)
        dataset.add_curve(
            Curve(
                name=channel,
                x=np.asarray(xs),
                y=np.asarray(ys),
                x_label="Volume" if x_unit.lower() == "ml" else "Time",
                x_unit=x_unit,
                y_label=channel,
                y_unit=y_unit,
                kind=_SIGNAL_KIND.get(channel, "signal"),
                meta={"raw_channel": raw_channel, "run": run_name},
            )
        )

    dataset.meta["run_name"] = run_names[0] if run_names else path.stem
    dataset.meta["n_curves"] = len(dataset.curves)
    dataset.meta.update(_parse_logbook(logbook_events))
    if dataset.curves:
        first = next(iter(dataset.curves.values()))
        dataset.meta["x_label"] = first.x_label
        dataset.meta["x_unit"] = first.x_unit
    return dataset
