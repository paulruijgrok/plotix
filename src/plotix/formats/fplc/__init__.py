"""FPLC chromatograms from ÄKTA / UNICORN ASCII exports."""

from ...core.registry import FormatSpec, register_format
from .plot import plot_chromatogram
from .reader import read_asc, sniff_asc

__all__ = ["read_asc", "plot_chromatogram", "SPEC"]

SPEC = register_format(
    FormatSpec(
        name="fplc",
        description="ÄKTA / UNICORN FPLC chromatogram (ASCII export)",
        extensions=(".asc",),
        reader=read_asc,
        plot=plot_chromatogram,
        sniff=sniff_asc,
        aliases=("akta", "unicorn", "chromatogram"),
    )
)
