"""Shared file-reading helpers.

Instrument exports are written by Windows software with inconsistent encodings
and number formats. These helpers absorb that variation so format readers can
concentrate on the structure of their own file type.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["read_text", "detect_encoding", "parse_number", "TEXT_ENCODINGS"]

# Ordered by how likely they are for instrument exports. UTF-16 variants are
# listed first because their BOMs are unambiguous; latin-1 is last because it
# decodes any byte sequence and would mask the others if tried early.
TEXT_ENCODINGS: tuple[str, ...] = (
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-8",
    "cp1252",
    "latin-1",
)

_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def detect_encoding(data: bytes) -> str | None:
    """Encoding implied by a byte-order mark, or ``None`` if there is none."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return encoding
    return None


def read_text(path: str | Path, encoding: str | None = None) -> str:
    """Decode a text file, trying the encodings instruments actually emit.

    A caller-supplied ``encoding`` is used as-is. Otherwise a BOM decides, and
    failing that each candidate in :data:`TEXT_ENCODINGS` is tried in turn.
    """
    path = Path(path)
    data = path.read_bytes()

    if encoding is not None:
        return _strip_bom(data.decode(encoding))

    bom_encoding = detect_encoding(data)
    if bom_encoding is not None:
        return _strip_bom(data.decode(bom_encoding))

    for candidate in TEXT_ENCODINGS:
        try:
            text = data.decode(candidate)
        except (UnicodeDecodeError, UnicodeError):
            continue
        # UTF-16 without a BOM decodes ASCII text into CJK-looking garbage;
        # an interleaved NUL byte is the reliable tell for 16-bit encodings.
        if candidate.startswith("utf-16") and b"\x00" not in data[:512]:
            continue
        return _strip_bom(text)

    return _strip_bom(data.decode("latin-1", errors="replace"))


def _strip_bom(text: str) -> str:
    """Drop a decoded byte-order mark.

    Decoding with an explicit endianness (``utf-16-le``) leaves the BOM in the
    string, where it would corrupt the first header field.
    """
    return text.lstrip("﻿")


def parse_number(token: str) -> float | None:
    """Parse one numeric field, tolerating comma decimal separators.

    Returns ``None`` for blank or non-numeric fields, which instrument exports
    use as padding when channels have different lengths.
    """
    token = token.strip().strip('"')
    if not token:
        return None
    try:
        return float(token)
    except ValueError:
        pass
    # European locale export: "1.234,56" or "1,23".
    normalised = token.replace(".", "").replace(",", ".") if token.count(",") == 1 else token
    try:
        return float(normalised)
    except ValueError:
        return None
