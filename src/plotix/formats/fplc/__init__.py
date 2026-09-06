"""FPLC chromatograms from ÄKTA / UNICORN runs.

Two file forms are supported and produce identical datasets: the instrument's
native ``.res`` result file, and the ``.asc`` ASCII export made from it.
"""

from ...core.registry import FormatSpec, register_format
from .asc import read_asc, sniff_asc
from .plot import plot_chromatogram
from .reader import read_fplc, sniff_fplc
from .res import read_res, sniff_res

__all__ = [
    "read_fplc",
    "read_asc",
    "read_res",
    "sniff_fplc",
    "sniff_asc",
    "sniff_res",
    "plot_chromatogram",
    "SPEC",
]

SPEC = register_format(
    FormatSpec(
        name="fplc",
        description="ÄKTA / UNICORN FPLC chromatogram (.res result file or .asc export)",
        extensions=(".res", ".asc"),
        reader=read_fplc,
        plot=plot_chromatogram,
        sniff=lambda head: sniff_asc(head),
        aliases=("akta", "unicorn", "chromatogram"),
    )
)
