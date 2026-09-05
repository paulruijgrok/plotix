"""Format-agnostic containers for experimental data.

Every reader in :mod:`plotix.formats` returns a :class:`Dataset`. Everything
downstream — plotting, source-data export, the CLI — works only against these
containers, so adding a new instrument format never requires touching the
plotting or export code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["Curve", "Event", "Dataset"]


@dataclass
class Curve:
    """A single continuous signal sampled on its own x-axis.

    Instruments frequently sample different detectors at different rates, so
    each curve carries its own ``x`` rather than sharing a global axis.
    """

    name: str
    x: np.ndarray
    y: np.ndarray
    x_label: str = "x"
    x_unit: str = ""
    y_label: str = "y"
    y_unit: str = ""
    kind: str = "signal"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        if self.x.shape != self.y.shape:
            raise ValueError(
                f"curve {self.name!r}: x and y must have the same shape "
                f"({self.x.shape} vs {self.y.shape})"
            )

    def __len__(self) -> int:
        return int(self.x.size)

    @property
    def y_axis_label(self) -> str:
        return f"{self.y_label} ({self.y_unit})" if self.y_unit else self.y_label

    @property
    def x_axis_label(self) -> str:
        return f"{self.x_label} ({self.x_unit})" if self.x_unit else self.x_label

    @property
    def span(self) -> float:
        """Peak-to-peak range of ``y``; 0.0 for an empty curve."""
        if self.y.size == 0:
            return 0.0
        finite = self.y[np.isfinite(self.y)]
        return float(np.ptp(finite)) if finite.size else 0.0

    def clip(self, xmin: float | None = None, xmax: float | None = None) -> Curve:
        """Return a copy restricted to an x-range (inclusive)."""
        mask = np.ones(self.x.shape, dtype=bool)
        if xmin is not None:
            mask &= self.x >= xmin
        if xmax is not None:
            mask &= self.x <= xmax
        return Curve(
            name=self.name,
            x=self.x[mask],
            y=self.y[mask],
            x_label=self.x_label,
            x_unit=self.x_unit,
            y_label=self.y_label,
            y_unit=self.y_unit,
            kind=self.kind,
            meta=dict(self.meta),
        )


@dataclass
class Event:
    """A labelled point on the x-axis (fraction mark, injection, log entry)."""

    x: float
    label: str
    kind: str = "event"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dataset:
    """A parsed data file: named curves, discrete events, and metadata."""

    name: str
    format: str
    source_path: Path | None = None
    curves: dict[str, Curve] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add_curve(self, curve: Curve) -> None:
        self.curves[curve.name] = curve

    def add_event(self, event: Event) -> None:
        self.events.append(event)

    def get(self, *names: str) -> Curve | None:
        """First curve matching any of ``names`` (case-insensitive), else None."""
        lowered = {k.lower(): v for k, v in self.curves.items()}
        for name in names:
            hit = lowered.get(name.lower())
            if hit is not None:
                return hit
        return None

    def require(self, *names: str) -> Curve:
        curve = self.get(*names)
        if curve is None:
            raise KeyError(
                f"{self.name}: none of {names} present; available curves: "
                f"{sorted(self.curves)}"
            )
        return curve

    def events_of(self, *kinds: str) -> list[Event]:
        wanted = {k.lower() for k in kinds}
        return [e for e in self.events if e.kind.lower() in wanted]

    def x_range(self, curves: Sequence[str] | None = None) -> tuple[float, float]:
        """Union of the x-ranges of the named curves (all curves by default)."""
        selected = [self.curves[n] for n in curves] if curves else list(self.curves.values())
        selected = [c for c in selected if len(c)]
        if not selected:
            return (0.0, 1.0)
        return (
            float(min(c.x.min() for c in selected)),
            float(max(c.x.max() for c in selected)),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Dataset(name={self.name!r}, format={self.format!r}, "
            f"curves={sorted(self.curves)}, n_events={len(self.events)})"
        )
