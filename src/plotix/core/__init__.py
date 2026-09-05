"""Format-agnostic machinery shared by every plotix data format."""

from .dataset import Curve, Dataset, Event
from .export import DEFAULT_FORMATS, FigureBundle, curves_to_long_frame, slugify
from .io import parse_number, read_text
from .peaks import Peak, find_peaks, peaks_to_frame
from .registry import (
    FormatSpec,
    detect_format,
    get_format,
    list_formats,
    register_format,
)
from .theme import THEMES, Theme, active_theme, get_theme, register_theme, use

__all__ = [
    "Curve",
    "Dataset",
    "Event",
    "FigureBundle",
    "DEFAULT_FORMATS",
    "curves_to_long_frame",
    "slugify",
    "read_text",
    "parse_number",
    "Peak",
    "find_peaks",
    "peaks_to_frame",
    "FormatSpec",
    "register_format",
    "get_format",
    "list_formats",
    "detect_format",
    "Theme",
    "THEMES",
    "get_theme",
    "register_theme",
    "use",
    "active_theme",
]
