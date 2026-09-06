"""Peak detection shared by any format with peak-shaped signals.

Deliberately conservative: peaks are ranked by prominence relative to the
signal's own range, so the same default threshold behaves sensibly whether a
trace tops out at 5 mAU or 5000 mAU.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .dataset import Curve

__all__ = ["Peak", "find_peaks", "peaks_to_frame"]

# numpy renamed trapz -> trapezoid in 2.0 and deprecated the old spelling.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


@dataclass
class Peak:
    """One detected peak, described in the curve's own units."""

    x: float
    height: float
    prominence: float
    width: float
    left_x: float
    right_x: float
    area: float

    def as_row(self) -> dict[str, float]:
        return {
            "x": self.x,
            "height": self.height,
            "prominence": self.prominence,
            "width": self.width,
            "left_x": self.left_x,
            "right_x": self.right_x,
            "area": self.area,
        }


#: Default minimum spacing between peaks, as a fraction of the curve's x-range.
#: Without a floor, a high-rate trace splits a single noisy summit into two
#: detections a few samples apart and the figure labels the same peak twice.
#: Expressing it as a fraction keeps one default working whether the trace has
#: a thousand points or a hundred thousand.
MIN_SEPARATION_FRAC = 0.005


def find_peaks(
    curve: Curve,
    min_prominence_frac: float = 0.05,
    max_peaks: int | None = 6,
    min_separation: float | None = None,
    min_separation_frac: float = MIN_SEPARATION_FRAC,
    xmin: float | None = None,
    xmax: float | None = None,
) -> list[Peak]:
    """Detect peaks in ``curve``, strongest first.

    Parameters
    ----------
    min_prominence_frac:
        Minimum prominence as a fraction of the curve's peak-to-peak range.
        The default of 0.05 keeps baseline ripple out while still catching
        clear shoulders.
    max_peaks:
        Keep only this many, ranked by prominence. ``None`` keeps all.
    min_separation:
        Minimum spacing between peaks, in x units. Overrides
        ``min_separation_frac`` when given.
    min_separation_frac:
        Minimum spacing as a fraction of the curve's x-range, used when
        ``min_separation`` is not set. Set either to 0 to detect every local
        maximum that clears the prominence threshold.
    xmin, xmax:
        Restrict detection to a window (e.g. skip the void volume).
    """
    from scipy.signal import find_peaks as _scipy_find_peaks
    from scipy.signal import peak_widths

    working = curve.clip(xmin, xmax)
    x, y = working.x, working.y
    if x.size < 5:
        return []

    span = working.span
    if span <= 0:
        return []

    separation = (
        min_separation
        if min_separation is not None
        else min_separation_frac * float(np.ptp(x))
    )
    distance = None
    if separation > 0 and x.size > 1:
        # Average rather than median step: instruments quantise x (an ÄKTA
        # records volume to 0.01 ml while sampling several times per step), so
        # consecutive differences are often zero and a median would be too.
        mean_step = float(np.ptp(x)) / (x.size - 1)
        if mean_step > 0:
            distance = max(1, int(round(separation / mean_step)))

    indices, props = _scipy_find_peaks(
        y,
        prominence=min_prominence_frac * span,
        distance=distance,
    )
    if indices.size == 0:
        return []

    widths, _, left_ips, right_ips = peak_widths(y, indices, rel_height=0.5)

    peaks: list[Peak] = []
    for i, idx in enumerate(indices):
        left_x = float(np.interp(left_ips[i], np.arange(x.size), x))
        right_x = float(np.interp(right_ips[i], np.arange(x.size), x))
        window = (x >= left_x) & (x <= right_x)
        area = float(_trapezoid(y[window], x[window])) if window.sum() > 1 else 0.0
        peaks.append(
            Peak(
                x=float(x[idx]),
                height=float(y[idx]),
                prominence=float(props["prominences"][i]),
                width=abs(right_x - left_x),
                left_x=left_x,
                right_x=right_x,
                area=area,
            )
        )

    peaks.sort(key=lambda p: p.prominence, reverse=True)
    if max_peaks is not None:
        peaks = peaks[:max_peaks]
    peaks.sort(key=lambda p: p.x)
    return peaks


def peaks_to_frame(peaks: list[Peak], curve: Curve) -> pd.DataFrame:
    """Tabulate peaks with column names carrying the curve's units."""
    if not peaks:
        return pd.DataFrame()
    xu = f" ({curve.x_unit})" if curve.x_unit else ""
    yu = f" ({curve.y_unit})" if curve.y_unit else ""
    rows = []
    for n, peak in enumerate(peaks, start=1):
        rows.append(
            {
                "peak": n,
                f"{curve.x_label}{xu}": peak.x,
                f"height{yu}": peak.height,
                f"prominence{yu}": peak.prominence,
                f"width_at_half_height{xu}": peak.width,
                f"start{xu}": peak.left_x,
                f"end{xu}": peak.right_x,
                "area": peak.area,
            }
        )
    return pd.DataFrame(rows)
