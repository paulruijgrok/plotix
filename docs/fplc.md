# FPLC chromatograms

Reads ÄKTA / UNICORN ASCII exports (`.asc`) and plots them.

## Input

In UNICORN: **File → Export → Export data to ASCII**, with the curves you care about selected. Anything the export contains is parsed; nothing needs to be pre-selected for plotix's benefit.

### File layout

Every curve occupies a *pair* of columns — its own x values then its y values — because detectors are sampled at different rates. Once a curve runs out of samples its columns are padded with blanks, so the block is ragged rather than rectangular:

```
10      10      10                        <- curve-count row (optional)
run:10_UV       run:10_Cond    ...        <- curve names, one per pair
ml      mAU     ml     mS/cm   ...        <- x unit, y unit per pair
0.000   -0.002  0.000  18.118  ...        <- data
0.037   -0.005  0.037  18.133  ...
...
36.349  -0.211                            <- shorter curves pad with blanks
```

plotix finds the header rows by locating the first row whose leading field is numeric, rather than assuming a fixed preamble, so exports with and without the curve-count row both work. UTF-8, UTF-16 (with or without BOM) and Windows codepages are all detected, as are comma decimal separators from European locales.

### Channels

Channel names are normalised, so `UV1_280`, `UV 1_280nm` and `UV` all arrive as `UV`:

| In the file | In plotix | Kind |
|---|---|---|
| `UV`, `UV1`, `UV1_280` | `UV` | signal |
| `UV2`, `UV3` | `UV2`, `UV3` | signal |
| `Cond` | `Conductivity` | signal |
| `Cond%` | `Conductivity%` | signal |
| `Conc` | `Concentration B` | signal |
| `Pressure`, `Flow`, `Temp`, `pH` | `Pressure`, `Flow`, `Temperature`, `pH` | signal |
| `Fractions` | — | events (`fraction`) |
| `Inject` | — | events (`injection`) |
| `Logbook` | — | events (`logbook`) |

Channels whose y-unit is parenthesised — `(Fractions)`, `(Injections)`, `(Set Marks)` — hold quoted text rather than numbers and become `Event`s. The logbook is also mined for run metadata: column name and volume, method name, and run start time, which appear in the figure subtitle.

## The figure

The plot is built around one question: *what came off the column, and where?* So the UV trace is the visual subject — heavy line, soft fill, peak volumes labelled — and everything else is quieter.

- **UV trace.** The main signal, in the theme's primary colour, with a light fill to its baseline.
- **Auxiliary channels.** Conductivity, %B, pressure and pH, on right-hand axes offset from each other, each colour-matched to its trace. At most two are drawn: a third offset axis stops being readable.
- **Fraction band.** Alternating shaded bands along the bottom 5% of the axes, with fraction numbers. Labels thin out automatically when fractions are dense, and a trailing non-numeric mark (`Waste`) closes the last band rather than opening a new one.
- **Injection marks.** A dashed vertical line. An injection at the very start of the run is drawn but not labelled, since the line coincides with the y-axis there.
- **Peaks.** Detected by prominence and labelled with elution volume. Labels stagger vertically where peaks crowd, rather than being dropped.

### Two design decisions worth knowing

**Flat channels are dropped.** With `auxiliary="auto"` (the default), a channel is only drawn if its peak-to-peak range clears a threshold — 1 mS/cm for conductivity, 1 %B for the gradient. An isocratic SEC run therefore gives a clean UV-only figure: its %B never leaves zero and its conductivity only drifts, so an axis for either would add furniture and tell the reader nothing.

**Drawn channels are not magnified.** When a channel *is* drawn — including one you asked for explicitly — its axis is held open to a minimum span (5 mS/cm for conductivity, 10 %B for the gradient). Without this, an axis auto-fitted to a nearly-flat channel stretches detector ripple into a dramatic squiggle that visually outranks the real signal. With it, a flat trace looks flat, which is the honest reading.

Both sets of thresholds are module-level dicts (`MIN_SPAN`, `MIN_DISPLAY_SPAN` in `plotix.formats.fplc.plot`) and can be edited or monkey-patched if your runs need different ones.

## Output files

For an input `run.asc`, `plotix fplc run.asc -o figures` writes:

| File | Contents |
|---|---|
| `run.png`, `run.pdf`, `run.svg` | the figure (PDF/SVG keep text as real, editable text) |
| `run_source_data.csv` | every plotted point, tidy long form: `series, x, x_label, x_unit, y, y_label, y_unit` |
| `run_peaks.csv` | one row per labelled peak: volume, height, prominence, width at half height, start, end, area |
| `run_marks.csv` | fraction and injection positions with their labels |

Source data is long rather than wide on purpose: channels are sampled on different x-grids, and interpolating them onto a shared axis to make a wide table would silently alter the numbers a reader might reuse.

## Command line

```bash
plotix fplc run.asc                       # figures/ beside the input
plotix fplc run.asc -o figures            # explicit output directory
plotix fplc a.asc b.asc c.asc -o figures  # several files at once
```

| Option | Effect |
|---|---|
| `-o, --outdir DIR` | where to write (default: `figures/` beside the input) |
| `-f, --formats png pdf svg` | figure formats (default: all three) |
| `--dpi N` | raster resolution (default: 300) |
| `--no-source-data` | skip the CSVs |
| `--theme NAME` | visual theme (default: `publication`) |
| `--auxiliary auto \| none \| NAME...` | which secondary channels to draw |
| `--signal NAME` | main channel (default: `UV`; use `UV2` for a second detector) |
| `--no-fractions`, `--no-injection` | hide the fraction band / injection marks |
| `--no-peaks` | skip peak detection and the peak table |
| `--no-fill` | draw the UV trace as a bare line |
| `--max-peaks N` | most peaks to label (default: 6) |
| `--peak-prominence F` | threshold as a fraction of the signal range (default: 0.05) |
| `--xlim MIN MAX` | restrict the volume axis |
| `--title TEXT` | override the title |

## Python API

```python
from plotix.formats.fplc import read_asc, plot_chromatogram

ds = read_asc("run.asc")
ds.curves.keys()                      # what the export contained
ds.meta["column"]                     # 'Superdex 200 10/300 GL'
ds.require("UV").y.max()              # tallest point, in mAU
[e.x for e in ds.events_of("fraction")]

bundle = plot_chromatogram(
    ds,
    auxiliary=["Conductivity", "Concentration B"],
    peak_window=(8.0, 25.0),          # ignore the void volume
    max_peaks=4,
)
bundle.save("figures", formats=("pdf", "png"))
```

`plot_chromatogram` accepts a path or an already-parsed `Dataset`, so you can inspect or filter the data before plotting. The returned `FigureBundle` exposes `.figure` (a normal matplotlib figure, adjust it freely before saving), `.source_data`, `.tables` and `.meta`.

### Common recipes

**Skip the void volume when finding peaks**

```python
plot_chromatogram("run.asc", peak_window=(8.0, 25.0))
```

**Force conductivity in for a run where it barely moves**

```python
plot_chromatogram("run.asc", auxiliary="Conductivity")
```

**Plot a volume window only**

```python
plot_chromatogram("run.asc", xlim=(5, 25))
```

**Compare the peak table across a set of runs**

```python
import pandas as pd, plotix
from pathlib import Path

rows = []
for path in Path("Data/FPLC").rglob("*.asc"):
    bundle = plotix.plot(path)
    table = bundle.tables.get("peaks")
    if table is not None:
        rows.append(table.assign(run=path.stem))
    bundle.close()

pd.concat(rows).to_csv("all_peaks.csv", index=False)
```
