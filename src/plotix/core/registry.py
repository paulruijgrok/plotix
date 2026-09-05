"""Registry of supported data formats.

Adding an instrument to plotix means writing a reader and a plot function, then
registering them here. The CLI, the batch runner and :func:`plotix.plot_file`
all discover formats through this registry, so a new format becomes available
everywhere at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .dataset import Dataset
from .export import FigureBundle

__all__ = ["FormatSpec", "register_format", "get_format", "list_formats", "detect_format"]

ReaderFn = Callable[..., Dataset]
PlotFn = Callable[..., FigureBundle]


@dataclass(frozen=True)
class FormatSpec:
    """Everything plotix needs to know about one data format."""

    name: str
    description: str
    extensions: tuple[str, ...]
    reader: ReaderFn
    plot: PlotFn
    #: Optional sniffer: given the first chunk of a file's text, does it look
    #: like this format? Used to disambiguate shared extensions such as .txt.
    sniff: Callable[[str], bool] | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def matches_extension(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions


_REGISTRY: dict[str, FormatSpec] = {}


def register_format(spec: FormatSpec) -> FormatSpec:
    _REGISTRY[spec.name.lower()] = spec
    for alias in spec.aliases:
        _REGISTRY[alias.lower()] = spec
    return spec


def get_format(name: str) -> FormatSpec:
    try:
        return _REGISTRY[name.lower()]
    except KeyError:
        raise KeyError(
            f"unknown format {name!r}; available: {sorted(list_formats())}"
        ) from None


def list_formats() -> list[FormatSpec]:
    """Registered formats, deduplicated and sorted by canonical name."""
    unique = {id(spec): spec for spec in _REGISTRY.values()}
    return sorted(unique.values(), key=lambda s: s.name)


def detect_format(path: str | Path, peek_bytes: int = 4096) -> FormatSpec | None:
    """Guess a file's format from its extension, refined by content sniffing.

    Extension is the first filter. When several formats claim the extension,
    each one's ``sniff`` decides; a format with no sniffer is accepted only if
    it is the sole candidate.
    """
    path = Path(path)
    candidates = [spec for spec in list_formats() if spec.matches_extension(path)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    from .io import read_text

    try:
        head = read_text(path)[:peek_bytes]
    except OSError:
        return None
    for spec in candidates:
        if spec.sniff is not None and spec.sniff(head):
            return spec
    return None
