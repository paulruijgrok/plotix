"""Naming and metadata conventions shared by both FPLC readers.

The ASCII export and the native ``.res`` file describe the same run with the
same vocabulary — ``UV``, ``Cond``, ``Conc``, fraction marks, a logbook of set
marks. Keeping that vocabulary in one place is what lets a single chromatogram
plot serve both readers without caring which one produced the dataset.
"""

from __future__ import annotations

import re

__all__ = [
    "CHANNEL_ALIASES",
    "SIGNAL_KIND",
    "canonical_channel",
    "split_curve_name",
    "normalise_run_date",
    "parse_logbook",
]

#: Maps the channel name instruments write onto a stable plotix name. Lookup is
#: case-insensitive and ignores spaces and underscores.
CHANNEL_ALIASES: dict[str, str] = {
    "uv": "UV",
    "uv1": "UV",
    "uv1_280": "UV",
    "uv1_280nm": "UV",
    "uv2": "UV2",
    "uv2_260": "UV2",
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

#: Measurement unit -> canonical channel. UNICORN gives each detector a
#: distinctive unit, which makes this the most dependable way to identify a
#: channel — more dependable than the recorded channel name, which some ``.res``
#: files store misaligned with the curves it labels. Keys are lower-cased and
#: stripped.
UNIT_CHANNELS: dict[str, str] = {
    "mau": "UV",
    "au": "UV",
    "ms/cm": "Conductivity",
    "s/cm": "Conductivity",
    "%": "Conductivity%",
    "%b": "Concentration B",
    "mpa": "Pressure",
    "bar": "Pressure",
    "psi": "Pressure",
    "ml/min": "Flow",
    "l/h": "Flow",
    "°c": "Temperature",
    "c": "Temperature",
    "ph": "pH",
}

#: Canonical channel -> curve kind, used by the plot to pick colours and axes.
SIGNAL_KIND: dict[str, str] = {
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

# "20260902 my run 001:10_UV" -> run "20260902 my run 001", channel "UV".
# The channel part is allowed to be empty because the .res directory stores
# this string in a fixed-width field that a long run name truncates — the run
# name is still recoverable even when the channel has been cut off.
_CURVE_NAME = re.compile(r"^(?P<run>.*?):\s*\d+\s*_(?P<channel>.*)$")

_COLUMN_LOGBOOK = re.compile(
    r"Base\s+CV,\s*(?P<cv>[\d.,]+)\s*\{(?P<cv_unit>[^}]*)\},\s*(?P<column>\S+)",
    re.IGNORECASE,
)
_METHOD_LOGBOOK = re.compile(r"Method\s*:\s*(?P<method>.+?)\s*$", re.IGNORECASE)
_RUN_DATE_LOGBOOK = re.compile(r"Method Run\s+(?P<when>[^,]+,[^,]+)", re.IGNORECASE)
_RUN_DATE = re.compile(
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[AP]M)?",
    re.IGNORECASE,
)


def canonical_channel(raw: str, unit: str | None = None) -> str:
    """Normalise an instrument channel name; unknown names pass through.

    When ``unit`` is given it takes precedence over the name. Some ``.res``
    files store the curve names shifted by one against the curves they label,
    so a UV trace can arrive carrying the name of the conductivity channel; the
    unit recorded in the curve's own axis descriptor never has that problem.
    """
    if unit:
        by_unit = UNIT_CHANNELS.get(unit.strip().lower())
        if by_unit:
            return by_unit
    stripped = raw.strip()
    for key in (stripped.lower().replace(" ", "").replace("_", ""), stripped.lower()):
        if key in CHANNEL_ALIASES:
            return CHANNEL_ALIASES[key]
    return stripped


def split_curve_name(field: str) -> tuple[str | None, str]:
    """Split ``run:10_UV`` into (run name, channel).

    Both the ASCII header and the ``.res`` directory use this form, so both
    readers recover the run name the same way. Text that does not match is
    returned unchanged as the channel.
    """
    field = field.strip()
    if not field:
        return None, ""
    match = _CURVE_NAME.match(field)
    if match:
        return match.group("run").strip(), match.group("channel").strip()
    return None, field


def normalise_run_date(raw: str) -> str:
    """Compact UNICORN's verbose timestamp.

    ``"9/2/2026, 5:41:13 PM Pacific Daylight Time"`` -> ``"2026-09-02 17:41"``.
    Unparseable text is returned unchanged — a long subtitle beats losing the
    run date entirely.
    """
    from datetime import datetime

    text = raw.strip()
    match = _RUN_DATE.match(text)
    if not match:
        return text
    time_part = match.group("time")
    if time_part.count(":") == 1:
        time_part += ":00"
    ampm = (match.group("ampm") or "").upper()
    fmt = "%m/%d/%Y %I:%M:%S %p" if ampm else "%m/%d/%Y %H:%M:%S"
    stamp = f"{match.group('date')} {time_part}" + (f" {ampm}" if ampm else "")
    try:
        return datetime.strptime(stamp, fmt).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def parse_logbook(entries: list[str]) -> dict[str, object]:
    """Mine column, method and run date out of logbook text.

    UNICORN records the method's set marks as free text; the column name and
    volume, the method name and the start time are all in there and are what a
    reader of the figure most wants in the subtitle.
    """
    meta: dict[str, object] = {}
    for text in entries:
        if "column" not in meta:
            match = _COLUMN_LOGBOOK.search(text)
            if match:
                meta["column"] = match.group("column").replace("_", " ")
                try:
                    meta["column_volume"] = float(match.group("cv").replace(",", "."))
                    meta["column_volume_unit"] = match.group("cv_unit").strip()
                except ValueError:
                    pass
        if "run_started" not in meta:
            match = _RUN_DATE_LOGBOOK.search(text)
            if match:
                meta["run_started"] = normalise_run_date(match.group("when"))
        if "method" not in meta:
            match = _METHOD_LOGBOOK.search(text)
            if match:
                meta["method"] = match.group("method").strip()
    return meta
