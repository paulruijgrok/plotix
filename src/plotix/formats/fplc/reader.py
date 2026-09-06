"""Entry point for reading FPLC runs, in either of the two file forms.

An ÄKTA run can reach plotix two ways: as the instrument's native ``.res``
result file, or as the ASCII export UNICORN produces from it. Both describe the
same run, so both readers return the same :class:`Dataset` shape — the same
canonical channel names, the same event kinds, the same metadata keys, and a
volume axis zeroed at the injection. Everything downstream is therefore
identical whichever file you point at.

:func:`read_fplc` dispatches on content (the ``.res`` magic number) rather than
on the file extension, so a misnamed file still reads correctly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.dataset import Dataset
from ...core.io import read_text
from .asc import EVENT_UNITS, read_asc, sniff_asc
from .channels import (
    CHANNEL_ALIASES,
    SIGNAL_KIND,
    canonical_channel,
    normalise_run_date,
    parse_logbook,
    split_curve_name,
)
from .res import RES_MAGIC, read_res, sniff_res

__all__ = [
    "read_fplc",
    "read_asc",
    "read_res",
    "sniff_asc",
    "sniff_res",
    "sniff_fplc",
    "CHANNEL_ALIASES",
    "EVENT_UNITS",
    "SIGNAL_KIND",
    "canonical_channel",
    "normalise_run_date",
    "parse_logbook",
    "split_curve_name",
    "RES_MAGIC",
]

# Keyword arguments each reader understands, so read_fplc can accept the union
# and hand each one only what it knows — callers (and the batch runner's config)
# should not have to care which file form they are pointing at.
_ASC_KWARGS = {"encoding", "keep_logbook"}
_RES_KWARGS = {"origin", "trim", "keep_logbook"}


def sniff_fplc(path: str | Path) -> bool:
    """True if ``path`` is an FPLC run in either supported form."""
    path = Path(path)
    try:
        head = path.read_bytes()[:4096]
    except OSError:
        return False
    if sniff_res(head):
        return True
    try:
        return sniff_asc(read_text(path)[:4096])
    except (OSError, UnicodeError):
        return False


def read_fplc(path: str | Path, **kwargs: Any) -> Dataset:
    """Read an FPLC run from a ``.res`` or ``.asc`` file.

    The file's own content decides which reader is used. Keyword arguments are
    passed to whichever reader applies and ignored by the other, so
    ``origin=``/``trim=`` are safe to set even for an ASCII export (which is
    already zeroed at the injection).

    Unknown keyword arguments raise, so a typo is still caught.
    """
    path = Path(path)
    with open(path, "rb") as handle:
        magic = handle.read(4)

    unknown = set(kwargs) - (_ASC_KWARGS | _RES_KWARGS)
    if unknown:
        raise TypeError(
            f"read_fplc() got unexpected keyword argument(s): {sorted(unknown)}"
        )

    if magic == RES_MAGIC:
        return read_res(path, **{k: v for k, v in kwargs.items() if k in _RES_KWARGS})
    return read_asc(path, **{k: v for k, v in kwargs.items() if k in _ASC_KWARGS})
