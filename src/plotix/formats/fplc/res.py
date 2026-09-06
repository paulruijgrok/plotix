"""Reader for native ÄKTA / UNICORN result files (``.res``).

Reading the instrument's own file removes the manual "export to ASCII" step,
and gives more than the export does: the ``.res`` holds the full-rate detector
data, where the ASCII export is decimated (roughly 15x fewer UV samples for the
runs this was developed against).

File layout
-----------
The format is undocumented; this reader was reverse-engineered against
UNICORN 3.10 files and cross-checked point-for-point against the ASCII export
of the same run.

The file is a flat array of 256-byte blocks behind a small header whose magic
is ``0x47114711``. Somewhere in the first part of the file sits a *directory*
of 344-byte entries, one per curve::

    +0    channel name, NUL-terminated ("UV", "Cond", "Fractions", ...)
    +240  uint24  blocks of data actually written
    +244  uint24  blocks allocated to this curve
    +248  uint24  first block of this curve
    +287  full curve name, "<run name>:10_<channel>"

Curves are stored back to back, so entry *n*'s ``start + allocated`` equals
entry *n+1*'s ``start``. That chain is a strong enough signature to locate the
directory by content, which matters because its offset is *not* fixed — it
differs between files written by the same software version.

Each curve begins with a header block. At ``+38`` is a list of 78-byte axis
descriptors, which make the data self-describing::

    +0   uint16  78, the record size — the list ends when this stops matching
    +2   uint8   axis index
    +3   uint8   0x80 for an x-axis, 0x40 for a stored value column
    +4   char[40] name        ("Acc. Volume", "TubeNo", ...)
    +44  char[16] unit        ("ml", " mAU", "min")
    +60  uint8   column width in bytes
    +61  uint8   column type  (1 = int32, 3 = float64, 4 = fixed-width text)
    +62  float64 scale factor applied to stored integers

Data records follow the last descriptor. **Every axis except the first is a
stored column**; the first is an implicit index. So a UV curve (Acc. Time,
Acc. Volume, value) stores 8 bytes per point — volume and value — while a
fraction curve stores time, volume, tube number, text, value and flags in 180.
Records end at the first all-zero record.

Volume origin
-------------
The ``.res`` x-axis is accumulated volume from the moment the method started,
so it includes the pump wash and equilibration before the sample went on. That
pre-injection region routinely contains a larger UV excursion than the sample
itself — 14 mAU of pump-wash artefact against a 9 mAU main peak in the
development data — which would dominate any autoscaled figure.

UNICORN's own ASCII export solves this by zeroing volume at the injection and
dropping everything before it, so this reader does the same by default. That
makes ``.res`` and ``.asc`` of the same run produce the same figure and the
same peak volumes. Both halves are configurable via ``origin`` and ``trim``.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np

from ...core.dataset import Curve, Dataset, Event
from .channels import (
    SIGNAL_KIND,
    canonical_channel,
    parse_logbook,
    split_curve_name,
)

__all__ = ["read_res", "sniff_res", "RES_MAGIC"]

RES_MAGIC = b"\x11G\x11G"

BLOCK = 256
DIR_ENTRY = 344
AXIS_RECORD = 78

# Column type codes from the axis descriptor.
_TYPE_INT32 = 1
_TYPE_FLOAT64 = 3
_TYPE_TEXT = 4
_TYPE_FMT = {_TYPE_INT32: "<i", _TYPE_FLOAT64: "<d"}

#: The logbook always records at least one full sentence — the method run line,
#: with its timestamp and method name. An injection mark is only ever a short
#: id. So the *longest* label separates the two channels, where a median does
#: not: most logbook entries are terse block markers like "End Block".
_LOGBOOK_LABEL_LENGTH = 24

_X_AXIS_FLAG = 0x80
_VALUE_AXIS_FLAG = 0x40
_PTR_MASK = 0xFFFFFF

# Offsets within a directory entry.
_OFF_USED, _OFF_ALLOC, _OFF_START = 240, 244, 248
_OFF_FULL_NAME = 287


def sniff_res(data: bytes) -> bool:
    """True if these bytes start a UNICORN ``.res`` file."""
    return data[:4] == RES_MAGIC


def _text(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("latin-1").strip()


def _entry_pointers(entry: bytes) -> tuple[int, int, int]:
    """(blocks used, blocks allocated, first block) from a directory entry.

    The top byte of each field carries flags, so it is masked off.
    """
    return tuple(  # type: ignore[return-value]
        struct.unpack("<I", entry[o : o + 4])[0] & _PTR_MASK
        for o in (_OFF_USED, _OFF_ALLOC, _OFF_START)
    )


def _looks_like_entry(data: bytes, offset: int) -> bool:
    """Cheap structural validation of a candidate directory entry."""
    entry = data[offset : offset + DIR_ENTRY]
    if len(entry) < DIR_ENTRY:
        return False
    used, alloc, start = _entry_pointers(entry)
    if not (0 < used <= alloc) or start <= 0:
        return False
    if (start + alloc) * BLOCK > len(data):
        return False
    # The curve it points at must begin with an axis descriptor.
    marker = start * BLOCK + 38
    if marker + 2 > len(data):
        return False
    return struct.unpack("<H", data[marker : marker + 2])[0] == AXIS_RECORD


def _find_directory(data: bytes) -> int:
    """Byte offset of the first directory entry.

    The offset varies between files, so it is found by content: curves are
    stored contiguously, so a genuine entry's ``start + allocated`` equals the
    next entry's ``start``. Searching for that chain (vectorised over all four
    byte alignments, since the table is not itself word-aligned) picks the
    directory out of a megabyte of binary essentially unambiguously.
    """
    words_per_entry = DIR_ENTRY // 4  # 86
    span = words_per_entry + _OFF_START // 4 + 1

    best: int | None = None
    for phase in range(4):
        usable = ((len(data) - phase) // 4) * 4
        if usable < span * 4:
            continue
        u = np.frombuffer(data[phase : phase + usable], dtype="<u4")
        if u.size <= span:
            continue
        w = np.arange(u.size - span)
        alloc = u[w + _OFF_ALLOC // 4] & _PTR_MASK
        start = u[w + _OFF_START // 4] & _PTR_MASK
        nxt = u[w + words_per_entry + _OFF_START // 4] & _PTR_MASK
        chained = (
            (start > 0)
            & (alloc > 0)
            & (alloc < len(data) // BLOCK)
            & (start + alloc == nxt)
        )
        for i in np.flatnonzero(chained):
            offset = phase + int(i) * 4
            if _looks_like_entry(data, offset) and _looks_like_entry(
                data, offset + DIR_ENTRY
            ):
                if best is None or offset < best:
                    best = offset
                break

    if best is None:
        raise ValueError("no curve directory found — not a UNICORN .res file?")

    # The chain may have been picked up mid-table; walk back to its first entry.
    while best - DIR_ENTRY >= 0 and _looks_like_entry(data, best - DIR_ENTRY):
        best -= DIR_ENTRY
    return best


def _read_axes(data: bytes, start_block: int) -> tuple[list[dict[str, Any]], int]:
    """Axis descriptors for a curve, and the offset where its data begins."""
    base = start_block * BLOCK
    pos = base + 38
    axes: list[dict[str, Any]] = []
    while (
        pos + AXIS_RECORD <= len(data)
        and struct.unpack("<H", data[pos : pos + 2])[0] == AXIS_RECORD
    ):
        record = data[pos : pos + AXIS_RECORD]
        axes.append(
            {
                "index": record[2],
                "flag": record[3],
                "name": _text(record[4:44]),
                "unit": _text(record[44:60]),
                "size": record[60],
                "type": record[61],
                "scale": struct.unpack("<d", record[62:70])[0],
            }
        )
        pos += AXIS_RECORD
    if not axes:
        raise ValueError(f"curve at block {start_block} has no axis descriptors")
    return axes, pos - base


def _read_records(
    data: bytes, start_block: int, used_blocks: int
) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    """Decode a curve's data records using its own axis descriptors.

    The first axis is an implicit index and is not stored; every later axis is
    a column. Reading stops at the first all-zero record, which is how the
    format pads a curve out to its block allocation.
    """
    axes, data_offset = _read_axes(data, start_block)
    columns = axes[1:]
    if not columns:
        return columns, []
    record_size = sum(c["size"] for c in columns)
    if record_size <= 0:
        return columns, []

    base = start_block * BLOCK
    # `used` counts data blocks and rounds up, so it bounds the record count.
    limit = min(base + used_blocks * BLOCK + data_offset, len(data))
    max_records = max(0, (limit - (base + data_offset)) // record_size)

    rows: list[list[Any]] = []
    offset = base + data_offset
    previous_x: float | None = None
    for _ in range(max_records):
        values: list[Any] = []
        cursor = offset
        for column in columns:
            raw = data[cursor : cursor + column["size"]]
            if len(raw) < column["size"]:
                return columns, rows
            if column["type"] == _TYPE_TEXT:
                values.append(_text(raw))
            elif column["type"] in _TYPE_FMT:
                values.append(
                    struct.unpack(_TYPE_FMT[column["type"]], raw)[0] * column["scale"]
                )
            else:  # unknown column type — keep the bytes rather than guessing
                values.append(raw)
            cursor += column["size"]

        x = values[0]
        if not isinstance(x, (int, float)):
            break
        # Padding past the end of the data is all zeros, which shows up as the
        # x coordinate jumping backwards.
        if previous_x is not None and x < previous_x:
            break
        previous_x = float(x)
        rows.append(values)
        offset += record_size

    return columns, rows


#: Units that identify a volume axis, which is the x-axis a chromatogram wants.
_VOLUME_UNITS = {"ml", "l", "cv", "µl", "ul"}


def _choose_x_column(columns: list[dict[str, Any]]) -> int:
    """Index of the column to use as x.

    Curves carry one x column (accumulated volume) but event channels carry
    both time and volume. Volume is preferred so that every curve and every
    mark in the dataset ends up on the same axis — picking time for the
    fraction marks and volume for the UV trace would silently misplace every
    fraction on the figure.
    """
    x_columns = [i for i, c in enumerate(columns) if c["flag"] == _X_AXIS_FLAG]
    if not x_columns:
        return 0
    for i in x_columns:
        if columns[i]["unit"].strip().lower() in _VOLUME_UNITS:
            return i
    return x_columns[0]


def _text_column(columns: list[dict[str, Any]]) -> int | None:
    return next(
        (
            i
            for i, c in enumerate(columns)
            if c["flag"] == _VALUE_AXIS_FLAG and c["type"] == _TYPE_TEXT
        ),
        None,
    )


def _event_kind(columns: list[dict[str, Any]], labels: list[str]) -> str | None:
    """Classify a curve as an event channel, or ``None`` if it holds numbers.

    Classification is structural rather than by name. The recorded channel
    names cannot be trusted: some ``.res`` files store them shifted by one
    against the curves they label, which would hand the temperature trace the
    name ``Inject`` and turn a real measurement into a set of marks. What the
    curve *contains* is never shifted, because it is described by the curve's
    own axis descriptors.

    A channel holding text is an event channel; one holding only numbers is a
    signal. Fraction collection is identifiable from its ``TubeNo`` text axis.
    The injection and logbook channels are structurally identical — both label
    their text column ``Inject`` — so they are told apart by what they contain:
    the logbook holds the method's set marks, at least one of which is a full
    sentence, while the injection channel holds only a short mark id.
    """
    text_column = _text_column(columns)
    if text_column is None:
        return None
    axis_name = columns[text_column]["name"].lower()
    if "tube" in axis_name or "frac" in axis_name:
        return "fraction"
    longest = max((len(label) for label in labels if label), default=0)
    if longest > _LOGBOOK_LABEL_LENGTH:
        return "logbook"
    return "injection"


def _injection_volume(events: list[Event]) -> float | None:
    injections = [e.x for e in events if e.kind == "injection"]
    return min(injections) if injections else None


def read_res(
    path: str | Path,
    origin: str | float = "injection",
    trim: bool = True,
    keep_logbook: bool = True,
) -> Dataset:
    """Parse a UNICORN ``.res`` file into a :class:`Dataset`.

    Parameters
    ----------
    path:
        The ``.res`` file.
    origin:
        Where volume zero sits. ``"injection"`` (default) matches UNICORN's
        ASCII export and puts zero at the sample injection, so peak volumes are
        elution volumes. ``"start"`` keeps the instrument's own accumulated
        volume, which includes equilibration. A number sets the origin
        explicitly, in millilitres of accumulated volume.
    trim:
        Drop everything before the origin. On by default, because the
        equilibration and pump-wash region often carries a larger UV excursion
        than the sample and would otherwise dominate the figure. Ignored when
        ``origin="start"``.
    keep_logbook:
        Keep logbook set marks as events. They are not drawn by default but
        carry the run metadata (column, method, date).
    """
    path = Path(path)
    data = path.read_bytes()
    if not sniff_res(data):
        raise ValueError(f"{path.name}: not a UNICORN .res file (bad magic)")

    directory = _find_directory(data)
    dataset = Dataset(name=path.stem, format="fplc", source_path=path)
    dataset.meta["source_format"] = "res"
    version = _text(data[24:40])
    if version:
        dataset.meta["software"] = version

    run_names: list[str] = []
    logbook_text: list[str] = []
    index = 0

    while True:
        offset = directory + index * DIR_ENTRY
        entry = data[offset : offset + DIR_ENTRY]
        if len(entry) < DIR_ENTRY or not _looks_like_entry(data, offset):
            break
        index += 1

        # Two sources for the name, and each file uses only one of them: some
        # write the short channel name at the head of the entry, others leave
        # that blank and carry it in the full "<run>:10_<channel>" string. The
        # full string is also the only source for the run name, but is stored
        # in a fixed-width field that a long run name truncates.
        #
        # An entry with no name at all is still read: the curve's own axis
        # descriptors say what it holds, so the name is a convenience rather
        # than a requirement, and skipping unnamed entries would silently drop
        # whole channels from files that leave those fields blank.
        run_name, tail_channel = split_curve_name(_text(entry[_OFF_FULL_NAME:]))
        channel = _text(entry[:40]) or tail_channel
        if run_name:
            run_names.append(run_name)

        used, _alloc, start = _entry_pointers(entry)
        columns, rows = _read_records(data, start, used)
        if not rows:
            continue

        x_column = _choose_x_column(columns)
        x_unit = columns[x_column]["unit"] or "ml"
        label_column = _text_column(columns)
        labels = (
            [str(row[label_column]) for row in rows] if label_column is not None else []
        )
        event_kind = _event_kind(columns, labels)

        if event_kind is not None:
            for row, label in zip(rows, labels):
                if not label:
                    continue
                event = Event(
                    x=float(row[x_column]),
                    label=label,
                    kind=event_kind,
                    meta={"channel": channel},
                )
                if event_kind == "logbook":
                    logbook_text.append(label)
                    if not keep_logbook:
                        continue
                dataset.add_event(event)
            continue

        value_column = next(
            (i for i, c in enumerate(columns) if c["flag"] == _VALUE_AXIS_FLAG), None
        )
        if value_column is None:
            continue
        name = canonical_channel(channel, columns[value_column]["unit"]) or (
            f"Channel {len(dataset.curves) + 1}"
        )
        # A run with several detectors of the same kind (UV1/UV2/UV3) resolves
        # them all to one name; keep each rather than overwriting.
        if name in dataset.curves:
            suffix = 2
            while f"{name}{suffix}" in dataset.curves:
                suffix += 1
            name = f"{name}{suffix}"
        dataset.add_curve(
            Curve(
                name=name,
                x=np.array([r[x_column] for r in rows], dtype=float),
                y=np.array([r[value_column] for r in rows], dtype=float),
                x_label="Volume" if x_unit.lower() == "ml" else "Time",
                x_unit=x_unit,
                y_label=name,
                y_unit=columns[value_column]["unit"],
                kind=SIGNAL_KIND.get(name, "signal"),
                meta={"raw_channel": channel, "run": run_name},
            )
        )

    if not dataset.curves and not dataset.events:
        raise ValueError(f"{path.name}: no curves found")

    dataset.meta["run_name"] = run_names[0] if run_names else path.stem
    dataset.meta["n_curves"] = len(dataset.curves)
    dataset.meta.update(parse_logbook(logbook_text))

    _apply_origin(dataset, origin, trim)

    if dataset.curves:
        first = next(iter(dataset.curves.values()))
        dataset.meta["x_label"] = first.x_label
        dataset.meta["x_unit"] = first.x_unit
    return dataset


def _apply_origin(dataset: Dataset, origin: str | float, trim: bool) -> None:
    """Shift (and optionally trim) the volume axis to the chosen origin."""
    if isinstance(origin, str):
        key = origin.lower()
        if key in {"start", "none", "raw"}:
            dataset.meta["volume_origin"] = 0.0
            return
        if key != "injection":
            raise ValueError(
                f"origin must be 'injection', 'start' or a number, got {origin!r}"
            )
        shift = _injection_volume(dataset.events)
        if shift is None:
            # No injection mark recorded — leave the axis as the instrument
            # wrote it rather than inventing an origin.
            dataset.meta["volume_origin"] = 0.0
            dataset.meta["volume_origin_note"] = "no injection mark; axis left as recorded"
            return
    else:
        shift = float(origin)

    dataset.meta["volume_origin"] = shift
    if not shift and not trim:
        return

    for name, curve in list(dataset.curves.items()):
        x = curve.x - shift
        y = curve.y
        if trim:
            keep = x >= 0
            x, y = x[keep], y[keep]
        dataset.curves[name] = Curve(
            name=curve.name,
            x=x,
            y=y,
            x_label=curve.x_label,
            x_unit=curve.x_unit,
            y_label=curve.y_label,
            y_unit=curve.y_unit,
            kind=curve.kind,
            meta=dict(curve.meta),
        )

    # Logbook marks legitimately sit before the injection (they describe the
    # method's set-up), so they are shifted but never trimmed.
    kept: list[Event] = []
    for event in dataset.events:
        moved = Event(
            x=event.x - shift, label=event.label, kind=event.kind, meta=dict(event.meta)
        )
        if trim and moved.x < 0 and moved.kind != "logbook":
            continue
        kept.append(moved)
    dataset.events = kept
