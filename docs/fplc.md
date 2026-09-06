# FPLC chromatograms

Reads ÄKTA / UNICORN runs in either of two forms and plots them:

| Form | What it is | When to use it |
|---|---|---|
| `.res` | The instrument's own result file | Default. No export step, and ~15x more UV samples. |
| `.asc` | UNICORN's ASCII export | When a `.res` won't parse, or the export is all you have. |

Both produce the same `Dataset` — same channel names, same event kinds, same metadata, same volume origin — so the figure, the source data and everything downstream are identical whichever you point at. `plotix` decides which reader to use from the file's content, not its extension, so a misnamed file still reads correctly.

```bash
plotix fplc run.res          # native result file
plotix fplc run.asc          # ASCII export
plotix plot run.res          # format detected automatically
```

## Input: `.res` (native result file)

Just point plotix at the file UNICORN wrote. No export step.

The format is undocumented; this reader was reverse-engineered against UNICORN 3.10 files and cross-checked against the ASCII export of the same run (they agree to 0.014 mAU rms on a 8.9 mAU peak, with identical fraction marks and metadata — see `tests/test_fplc_res.py`).

### How it identifies channels

Each curve in a `.res` carries its own *axis descriptors*, which state the unit, the column widths and types, and the scale factor for the stored integers. plotix identifies channels from those rather than from the recorded channel names, because the names are not dependable: some files leave them blank, and some store them **shifted by one against the curves they label**, which would hand the temperature trace the name `Inject` and turn a real measurement into a set of marks. The unit in a curve's own descriptor never has that problem.

The same applies to the text channels. Fraction collection is identifiable from its `TubeNo` axis; the injection and logbook channels are structurally identical, so they are told apart by content — the logbook always contains at least one full sentence (the method-run line, with its timestamp), while an injection mark is only ever a short id.

### The volume origin

This is the one place where `.res` needs a decision that `.asc` does not.

The `.res` volume axis is accumulated volume from the moment the method started, so it includes the pump wash and equilibration before the sample went on. That region routinely holds a **larger UV excursion than the sample itself** — 14 mAU of pump-wash artefact against a 9 mAU main peak in the development data — which would dominate any autoscaled figure and make the real peaks look small.

UNICORN's own ASCII export solves this by zeroing volume at the injection and dropping everything before it, so plotix does the same by default. That is what makes the two file forms give the same figure and the same peak volumes.

```bash
plotix fplc run.res                                   # zeroed at the injection (default)
plotix fplc run.res --origin start --keep-pre-injection   # the instrument's raw axis
plotix fplc run.res --origin 2.38                     # explicit, in ml
```

```python
read_res("run.res")                       # default
read_res("run.res", origin="start")       # accumulated volume, nothing trimmed
read_res("run.res", origin=2.38)          # explicit origin
read_res("run.res", trim=False)           # zeroed, but keep the equilibration
```

The shift applied is recorded in `ds.meta["volume_origin"]`. Logbook marks are shifted but never trimmed — they describe the method set-up and legitimately sit before the injection, so they end up at negative volumes. If a run has no injection mark, the axis is left exactly as the instrument recorded it and `ds.meta["volume_origin_note"]` says so.

## Input: `.asc` (ASCII export)

In UNICORN: **File → Export → Export data to ASCII**, with the curves you care about selected. Anything the export contains is parsed; nothing needs to be pre-selected for plotix's benefit. The exported axis is already zeroed at the injection, so `origin` and `trim` do nothing here.

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

Channel names are normalised, so `UV1_280`, `UV 1_280nm` and `UV` all arrive as `UV`. (The `.res` reader derives the same names from each curve's unit instead — see above — so both forms agree.)

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
- **Peaks.** Detected by prominence and labelled with elution volume. Labels stagger vertically where peaks crowd, rather than being dropped. Detections closer than 0.5% of the run's volume are treated as one peak, so the full-rate `.res` data does not label a single noisy summit twice.

### Two design decisions worth knowing

**Flat channels are dropped.** With `auxiliary="auto"` (the default), a channel is only drawn if its peak-to-peak range clears a threshold — 1 mS/cm for conductivity, 1 %B for the gradient. An isocratic SEC run therefore gives a clean UV-only figure: its %B never leaves zero and its conductivity only drifts, so an axis for either would add furniture and tell the reader nothing.

**Drawn channels are not magnified.** When a channel *is* drawn — including one you asked for explicitly — its axis is held open to a minimum span (5 mS/cm for conductivity, 10 %B for the gradient). Without this, an axis auto-fitted to a nearly-flat channel stretches detector ripple into a dramatic squiggle that visually outranks the real signal. With it, a flat trace looks flat, which is the honest reading.

Both sets of thresholds are module-level dicts (`MIN_SPAN`, `MIN_DISPLAY_SPAN` in `plotix.formats.fplc.plot`) and can be edited or monkey-patched if your runs need different ones.

## Output files

For an input `run.res`, `plotix fplc run.res` writes the following into the session folder (identically for `run.asc`) — see [output_layout.md](output_layout.md):

| File | Contents |
|---|---|
| `run.png`, `run.pdf`, `run.svg` | the figure (PDF/SVG keep text as real, editable text) |
| `run_source_data.csv` | every plotted point, tidy long form: `series, x, x_label, x_unit, y, y_label, y_unit` |
| `run_peaks.csv` | one row per labelled peak: volume, height, prominence, width at half height, start, end, area |
| `run_marks.csv` | fraction and injection positions with their labels |

Source data is long rather than wide on purpose: channels are sampled on different x-grids, and interpolating them onto a shared axis to make a wide table would silently alter the numbers a reader might reuse.

## Command line

```bash
plotix fplc run.res                       # today's session folder
plotix fplc run.res --daily               # today's day folder, overwriting it
plotix fplc run.res -o exact/place        # exactly there
plotix fplc a.res b.res c.asc             # several files, mixed forms, one folder
```

| Option | Effect |
|---|---|
| `--origin WHERE` | `.res` only: where volume zero sits — `injection` (default), `start`, or a number in ml |
| `--keep-pre-injection` | `.res` only: keep the equilibration data instead of trimming it |
| `-o, --outdir DIR` | write exactly here, bypassing the session layout |
| `--output-root DIR`, `--daily`, `--label` | control the session layout ([details](output_layout.md)) |
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
from plotix.formats.fplc import read_fplc, plot_chromatogram

ds = read_fplc("run.res")             # or "run.asc" — same result
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
bundle.save("exact/place", formats=("pdf", "png"))
```

`plot_chromatogram` accepts a path or an already-parsed `Dataset`, so you can inspect or filter the data before plotting. The returned `FigureBundle` exposes `.figure` (a normal matplotlib figure, adjust it freely before saving), `.source_data`, `.tables` and `.meta`.

### Common recipes

**Skip the void volume when finding peaks**

```python
plot_chromatogram("run.res", peak_window=(8.0, 25.0))
```

**See the equilibration that the default trims away**

```python
plot_chromatogram("run.res", origin="start", trim=False)
```

**Force conductivity in for a run where it barely moves**

```python
plot_chromatogram("run.res", auxiliary="Conductivity")
```

**Plot a volume window only**

```python
plot_chromatogram("run.res", xlim=(5, 25))
```

**Compare the peak table across a set of runs**

```python
import pandas as pd, plotix
from pathlib import Path

rows = []
for path in Path("Data/FPLC").rglob("*.res"):
    bundle = plotix.plot(path)
    table = bundle.tables.get("peaks")
    if table is not None:
        rows.append(table.assign(run=path.stem))
    bundle.close()

pd.concat(rows).to_csv("all_peaks.csv", index=False)
```
