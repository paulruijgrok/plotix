"""Shared fixtures.

Tests run against synthetic UNICORN exports built here rather than against real
instrument files, so the suite is self-contained and can exercise awkward cases
(ragged channels, alternative encodings, missing preamble) on demand. The real
example run under ``Data/`` is used as an extra integration check when present.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE_DIR = REPO_ROOT / "Data" / "FPLC" / "20260902_PfDh_Nb02P"
EXAMPLE_ASC = _EXAMPLE_DIR / "20260902_PfLDH_Nb02P.asc"
#: The .res of the same run as EXAMPLE_ASC — the pair is what lets the binary
#: reader be checked against a known-good export rather than against itself.
EXAMPLE_RES = (
    _EXAMPLE_DIR / "20260902 Nb02P 60 ul plus PfLDH 100 ul incub 20min001.res"
)


def gaussian(x: np.ndarray, centre: float, height: float, width: float) -> np.ndarray:
    return height * np.exp(-0.5 * ((x - centre) / width) ** 2)


def build_asc(
    path: Path,
    *,
    run_name: str = "test run 001",
    n: int = 200,
    x_max: float = 20.0,
    peaks: tuple[tuple[float, float, float], ...] = ((6.0, 100.0, 0.5), (12.0, 40.0, 0.7)),
    conductivity: str = "flat",
    fractions: int = 8,
    encoding: str = "utf-8",
    newline: str = "\r\n",
    include_count_row: bool = True,
    include_logbook: bool = True,
) -> Path:
    """Write a synthetic UNICORN ASCII export.

    Mirrors the real layout: paired x/y columns per curve, ragged lengths
    padded with blanks, quoted text values in the event channels.

    Parameters
    ----------
    conductivity:
        ``"flat"`` for an isocratic buffer (should be dropped by ``auto``
        auxiliary selection) or ``"gradient"`` for a rising salt gradient
        (should be kept).
    """
    x = np.linspace(0.0, x_max, n)
    uv = sum(gaussian(x, c, h, w) for c, h, w in peaks) + 0.01 * np.sin(x * 7)

    if conductivity == "gradient":
        cond = 2.0 + 48.0 * np.clip((x - 4.0) / (x_max - 6.0), 0.0, 1.0)
    else:
        cond = 18.1 + 0.02 * np.sin(x * 5)

    # Deliberately ragged: conductivity is sampled less often than UV.
    cond_x = x[::2]
    cond = cond[::2]

    conc = np.zeros_like(cond_x) if conductivity == "flat" else np.clip((cond_x - 4) * 5, 0, 100)

    frac_x = np.linspace(1.0, x_max - 1.0, fractions)
    frac_labels = [str(i + 1) for i in range(fractions)]

    columns: list[tuple[str, str, list[str], list[str]]] = [
        ("UV", " mAU", [f"{v:9.3f}" for v in x], [f"{v:12.6f}" for v in uv]),
        ("Cond", " mS/cm", [f"{v:9.3f}" for v in cond_x], [f"{v:12.6f}" for v in cond]),
        ("Conc", " %B", [f"{v:9.3f}" for v in cond_x], [f"{v:12.6f}" for v in conc]),
        (
            "Fractions",
            "(Fractions)",
            [f"{v:9.3f}" for v in frac_x],
            [f' "{lab}"' for lab in frac_labels],
        ),
        ("Inject", "(Injections)", ["    0.500"], ['   "1"']),
    ]
    if include_logbook:
        columns.append(
            (
                "Logbook",
                "(Set Marks)",
                ["   -1.000", "   -1.000", "   -1.000"],
                [
                    ' "Method Run 9/2/2026, 5:41:13 PM Pacific Daylight Time, '
                    'Method : testmtd"',
                    ' "Base CV, 23.56 {ml}, Superdex_200_10/300_GL"',
                    ' "End Block"',
                ],
            )
        )

    n_rows = max(len(xs) for _, _, xs, _ in columns)
    n_cols = 2 * len(columns)

    lines: list[str] = []
    if include_count_row:
        lines.append("\t".join([str(len(columns)), ""] * len(columns)))
    # UNICORN writes the curve name in the x column and leaves the y column
    # blank, so each name is followed by an empty field.
    lines.append("\t".join(f"{run_name}:10_{name}\t" for name, _, _, _ in columns))
    lines.append("\t".join(f"ml\t{unit}" for _, unit, _, _ in columns))

    blank_x, blank_y = " " * 9, " " * 12
    for row in range(n_rows):
        fields: list[str] = []
        for _, _, xs, ys in columns:
            if row < len(xs):
                fields.extend([xs[row], ys[row]])
            else:
                fields.extend([blank_x, blank_y])
        lines.append("\t".join(fields))

    assert all(len(line.split("\t")) <= n_cols + 1 for line in lines[1:])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((newline.join(lines) + newline).encode(encoding))
    return path


# --------------------------------------------------------------------------- .res
#
# A minimal but structurally faithful UNICORN .res file: 256-byte blocks, a
# 344-byte directory whose entries chain by block allocation, and curves whose
# 78-byte axis descriptors describe their own record layout. Building these
# here means the binary reader is tested against files whose exact contents are
# known, including the awkward cases real files exhibit (missing channel names,
# names shifted against the curves they label).

RES_BLOCK = 256
RES_DIR_ENTRY = 344
RES_AXIS = 78


def _axis(index, flag, name, unit, size, dtype, scale):
    return (
        struct.pack("<HBB", RES_AXIS, index, flag)
        + name.encode("latin-1").ljust(40, b"\x00")
        + unit.encode("latin-1").ljust(16, b"\x00")
        + struct.pack("<BB", size, dtype)
        + struct.pack("<d", scale)
        + b"\x00" * 8
    )


#: Axis descriptors for a numeric curve: implicit index, volume, value.
def _signal_axes(unit, scale):
    return (
        _axis(1, 0x80, "Acc. Time", "min", 4, 1, 1 / 300)
        + _axis(2, 0x80, "Acc. Volume", "ml", 4, 1, 0.01)
        + _axis(1, 0x40, "0", unit, 4, 1, scale)
    )


#: Axis descriptors for a text channel: index, time, volume, then the columns.
def _event_axes(text_axis_name):
    return (
        _axis(1, 0x80, "", "", 4, 1, 1.0)
        + _axis(1, 0x80, "Time", "min", 8, 3, 1.0)
        + _axis(2, 0x80, "Volume", "ml", 8, 3, 1.0)
        + _axis(0, 0x40, text_axis_name, "", 76, 4, 1.0)
        + _axis(0, 0x40, "Add. Text", "", 76, 4, 1.0)
        + _axis(0, 0x40, "Value", "", 8, 3, 1.0)
        + _axis(0, 0x40, "Flags", "", 4, 1, 1.0)
    )


def _curve_block(axes: bytes, records: bytes) -> bytes:
    """A curve: 32 bytes of padding, a 6-byte preamble, axes, then records."""
    body = b"\x00" * 32 + struct.pack("<HHH", 6, 2, 1) + axes + records
    # Pad to a whole number of blocks, leaving a zero record as the terminator.
    pad = (-len(body)) % RES_BLOCK
    return body + b"\x00" * (pad + RES_BLOCK)


def _signal_records(x_ml, y, scale):
    out = bytearray()
    for xv, yv in zip(x_ml, y):
        out += struct.pack("<ii", int(round(xv / 0.01)), int(round(yv / scale)))
    return bytes(out)


def _event_records(rows):
    """rows: (volume_ml, label) — time is derived at a nominal 0.75 ml/min."""
    out = bytearray()
    for volume, label in rows:
        out += struct.pack("<d", volume / 0.75)
        out += struct.pack("<d", volume)
        out += label.encode("latin-1").ljust(76, b"\x00")
        out += b"\x00" * 76
        out += struct.pack("<d", 0.0)
        out += struct.pack("<i", 1)
    return bytes(out)


def build_res(
    path: Path,
    *,
    run_name: str = "test run 001",
    n: int = 400,
    x_max: float = 20.0,
    injection: float = 2.0,
    peaks: tuple[tuple[float, float, float], ...] = ((8.0, 100.0, 0.5), (14.0, 40.0, 0.7)),
    fractions: int = 6,
    conductivity: str = "flat",
    name_curves: bool = True,
    shift_names: bool = False,
    directory_offset: int = 4099,
) -> Path:
    """Write a synthetic UNICORN ``.res`` file.

    Peak positions are given in *accumulated* volume, i.e. before the injection
    origin is subtracted, so a peak at 8.0 with ``injection=2.0`` is expected at
    6.0 ml in the parsed dataset.

    Parameters
    ----------
    name_curves:
        Write channel names into the directory. Real files sometimes leave them
        blank, so the reader must not depend on them.
    shift_names:
        Write each curve's name into the *previous* entry, reproducing the
        misalignment seen in real files.
    """
    x = np.linspace(0.0, x_max, n)
    uv = sum(gaussian(x, c, h, w) for c, h, w in peaks)
    cond = (
        18.1 + 0.02 * np.sin(x * 5)
        if conductivity == "flat"
        else 2.0 + 48.0 * np.clip((x - 4.0) / (x_max - 6.0), 0.0, 1.0)
    )
    conc = np.zeros_like(x) if conductivity == "flat" else np.clip((x - 4) * 5, 0, 100)

    frac_rows = [
        (injection + 1.0 + i * 1.0, str(i + 1)) for i in range(fractions)
    ]
    logbook_rows = [
        (0.0, "Method Run 9/2/2026, 5:41:13 PM Pacific Daylight Time, Method : testmtd"),
        (0.0, "Base CV, 23.56 {ml}, Superdex_200_10/300_GL"),
        (0.0, "End Block"),
    ]

    curves: list[tuple[str, bytes]] = [
        ("Logbook", _curve_block(_event_axes("Inject"), _event_records(logbook_rows))),
        ("UV", _curve_block(_signal_axes(" mAU", 0.001), _signal_records(x, uv, 0.001))),
        ("Cond", _curve_block(_signal_axes(" mS/cm", 0.001), _signal_records(x, cond, 0.001))),
        ("Conc", _curve_block(_signal_axes(" %B", 0.001), _signal_records(x, conc, 0.001))),
        ("Inject", _curve_block(_event_axes("Inject"), _event_records([(injection, "3")]))),
        ("Fractions", _curve_block(_event_axes("TubeNo"), _event_records(frac_rows))),
    ]

    header = bytearray(b"\x11G\x11G" + b"\x00" * 20)
    header += b"UNICORN 3.10".ljust(16, b"\x00")

    first_block = -(-(directory_offset + len(curves) * RES_DIR_ENTRY) // RES_BLOCK) + 1
    body = bytearray()
    entries = bytearray()
    block = first_block
    for i, (name, payload) in enumerate(curves):
        blocks = len(payload) // RES_BLOCK
        entry = bytearray(b"\x00" * RES_DIR_ENTRY)
        label_index = i - 1 if shift_names else i
        if name_curves and not shift_names:
            entry[: len(name)] = name.encode("latin-1")
        if 0 <= label_index < len(curves):
            full = f"{run_name}:10_{curves[label_index][0]}".encode("latin-1")
            entry[_RES_FULL : _RES_FULL + len(full)] = full[: RES_DIR_ENTRY - _RES_FULL]
        entry[240:244] = struct.pack("<I", blocks)
        entry[244:248] = struct.pack("<I", blocks)
        entry[248:252] = struct.pack("<I", block)
        entries += entry
        body += payload
        block += blocks

    out = bytearray(header)
    out += b"\x00" * (directory_offset - len(out))
    out += entries
    out += b"\x00" * (first_block * RES_BLOCK - len(out))
    out += body

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


_RES_FULL = 287


@pytest.fixture
def res_factory(tmp_path):
    """Callable that writes a synthetic .res into a temporary directory."""

    def make(name: str = "run.res", **kwargs) -> Path:
        return build_res(tmp_path / name, **kwargs)

    return make


@pytest.fixture
def simple_res(res_factory) -> Path:
    return res_factory()


@pytest.fixture
def example_res() -> Path:
    if not EXAMPLE_RES.exists():
        pytest.skip("example .res run not present in Data/")
    return EXAMPLE_RES


@pytest.fixture
def asc_factory(tmp_path):
    """Callable that writes a synthetic .asc into a temporary directory."""

    def make(name: str = "run.asc", **kwargs) -> Path:
        return build_asc(tmp_path / name, **kwargs)

    return make


@pytest.fixture
def simple_asc(asc_factory) -> Path:
    return asc_factory()


@pytest.fixture
def gradient_asc(asc_factory) -> Path:
    return asc_factory("gradient.asc", conductivity="gradient")


@pytest.fixture
def example_asc() -> Path:
    if not EXAMPLE_ASC.exists():
        pytest.skip("example FPLC run not present in Data/")
    return EXAMPLE_ASC
