"""Shared fixtures.

Tests run against synthetic UNICORN exports built here rather than against real
instrument files, so the suite is self-contained and can exercise awkward cases
(ragged channels, alternative encodings, missing preamble) on demand. The real
example run under ``Data/`` is used as an extra integration check when present.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ASC = (
    REPO_ROOT / "Data" / "FPLC" / "20260902_PfDh_Nb02P" / "20260902_PfLDH_Nb02P.asc"
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
