# plotix

Quick, beautiful plots of experimental data files. Point it at a raw instrument file and it gives you a publication-ready figure in PNG, PDF and SVG — plus the tidy CSV of exactly the numbers that were drawn, the way journals ask for figure source data. Each instrument format gets its own reader and its own purpose-built plot; everything they share (theming, export, peak finding, batch running) lives in one core.

For ÄKTA FPLC runs it reads the instrument's **native `.res` file directly**, so there is no export step between finishing a run and having a figure.

## Quick start

```bash
git clone https://github.com/paulruijgrok/plotix.git
cd plotix
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

plotix fplc Data/FPLC          # a whole folder: everything plotable in it
```

Or one file: `plotix fplc "Data/FPLC/20260902_PfDh_Nb02P/20260902 Nb02P 60 ul plus PfLDH 100 ul incub 20min001.res"`

Expected output — a dated session folder holding a `.png`, `.pdf` and `.svg` of the chromatogram (UV trace, labelled peak volumes, fraction band), alongside `..._source_data.csv` (every plotted point), `..._peaks.csv` (peak volumes, heights, widths, areas) and `..._marks.csv` (fraction and injection positions):

```
output/
  20260905_FPLC/
    20260905_143022/
      20260902 Nb02P ... .png .pdf .svg
      20260902 Nb02P ..._source_data.csv
      20260902 Nb02P ..._peaks.csv
      20260902 Nb02P ..._marks.csv
```

From Python:

```python
import plotix

plotix.plot_file("run.res")                      # figure + source data, one call

bundle = plotix.plot("run.res", auxiliary="Conductivity")
bundle.source_data.head()                        # the numbers behind the figure
bundle.figure.axes[0].set_xlim(5, 25)            # tweak, then save
bundle.save("somewhere", formats=("pdf",))
```

## Installation

### Requirements

- Python ≥ 3.9
- numpy ≥ 1.21, pandas ≥ 1.3, matplotlib ≥ 3.5, scipy ≥ 1.7, PyYAML ≥ 6.0

All dependencies are pure pip installs; there are no compiled or external tools.

### Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # drop [dev] if you don't need pytest/ruff
pytest                      # 170 tests, ~11 s
```

### Known gotchas

- **`plotix: command not found` after install.** pip put the console script in a directory that isn't on `PATH` (it warns when it does). Either add that directory to `PATH` or use `python -m plotix` instead.
- **Headless machines.** Set `MPLBACKEND=Agg` if matplotlib tries to open a display.
- **Instrument encodings.** UNICORN ASCII exports appear as UTF-8, UTF-16 (with or without BOM) and Windows codepages depending on version and locale. plotix detects this; pass `encoding=` to the reader only if a file still comes out garbled.
- **`.res` support is reverse-engineered.** The format is undocumented, and this reader was worked out against UNICORN 3.10 files. It identifies channels from each curve's own axis descriptors rather than from recorded names, which is what makes it survive the naming quirks real files have — but a file from a very different UNICORN version may still need work. If one fails, the ASCII export is the fallback, and the file is worth reporting.

## Pipelines

### FPLC chromatograms

Reads ÄKTA / UNICORN runs — either the instrument's native `.res` result file or the `.asc` ASCII export — and produces a chromatogram: UV absorbance against elution volume as the visual subject, auxiliary channels (conductivity, %B, pressure, pH) on colour-matched offset axes, collected fractions as a band along the bottom, and peak volumes labelled on the trace. Auxiliary channels that never move are dropped automatically, so an isocratic SEC run gives a clean UV-only figure without being asked. [Full details](docs/fplc.md)

```bash
plotix fplc ~/data/todays_runs     # a folder — no need to name each file
plotix fplc run.res
plotix fplc run.res --auxiliary Conductivity "Concentration B" --max-peaks 3
```

Both file forms produce the same dataset and the same figure, so nothing downstream needs to know which one you used. Reading `.res` directly skips the export step, and gives roughly 15x more UV samples, since the ASCII export is decimated. The `.res` reader is checked against the ASCII export of the same run as part of the test suite; they agree to 0.014 mAU rms on a 8.9 mAU peak, with identical fraction marks and metadata.

## Where output goes

Figures land in a dated session folder, so a re-run with different settings never overwrites the figure you were about to use:

```
output/<YYYYMMDD>_<FORMAT>/<YYYYMMDD_HHMMSS>/
```

The day folder is dated when plotix runs (not when the data was acquired), and named after the kind of data — so two instruments on the same day get `20260905_FPLC` and `20260905_PLATE` side by side. Every file in one invocation shares one run folder, including a whole batch.

Point plotix at a folder and the output mirrors its structure, so runs from different experiment folders stay apart:

```
~/data/todays_runs/          output/20260905_FPLC/20260905_143022/
  expA/run1.res       ->       expA/run1.png ...
  expB/run1.res       ->       expB/run1.png ...
```

`--flat` puts everything in one folder instead; names that would then collide get their source folder prefixed, so no run is ever silently overwritten.

```bash
plotix fplc run.res                       # output/20260905_FPLC/20260905_143022/
plotix fplc run.res --label pfldh         # ..._pfldh, to say what the run was
plotix fplc run.res --daily               # output/20260905_FPLC/, overwriting it
plotix fplc run.res --output-root ~/plots # somewhere else entirely
plotix fplc run.res -o exact/place        # bypass the layout completely
```

`--daily` is the mode for once settings have settled and the accumulating timestamped folders are just clutter. [Full details](docs/output_layout.md)

## Batch processing

Any format can be run unattended across a folder of datasets. The batch runner isolates failures (one corrupt export never costs you the rest of the run), skips work that is already done so an interrupted batch resumes on re-run, logs every dataset, and prints a summary of what succeeded and what failed. [Full details](docs/batch_processing.md)

```bash
plotix batch ~/data/todays_runs                # just a folder
plotix batch configs/batch_example.yaml        # or a saved config
plotix batch ~/data/todays_runs --daily        # stable destination, resumable
```

## Adding a format

New instruments plug into the same machinery. In short: write `reader.py` that returns a `Dataset` of `Curve`s and `Event`s, write `plot.py` that returns a `FigureBundle`, and register the pair with a `FormatSpec`. The CLI subcommand, format detection, source-data export and batch support all follow automatically. [Full details](docs/adding_a_format.md)

## Repo map

- `src/plotix/core/` — shared machinery: containers (`dataset`), theming (`theme`), plot primitives (`plotting`), figure and CSV export (`export`), output layout (`output`), peak detection (`peaks`), file decoding (`io`), format registry (`registry`), batch runner (`batch`)
- `src/plotix/formats/` — one subpackage per instrument format (`fplc/` so far: `res.py` and `asc.py` readers, shared `channels.py`, `plot.py`)
- `src/plotix/cli.py` — command-line interface
- `tests/` — pytest suite; run the whole thing before every commit
- `configs/` — example batch configs
- `docs/` — per-format and per-framework documentation
- `Data/` — example raw data (`.res` result files and one `.asc` export of the same run)

## Status

**Stable:** the FPLC readers (`.res` and `.asc`) and chromatogram plot, the source-data export contract, the output layout, the batch runner, and the CLI.

**Experimental:** the theme system currently ships one theme (`publication`); the `Theme` dataclass and `register_theme` are in place for adding more, but the palette may still shift.

**Planned:** additional formats (plate readers, spectra, gels), overlay plots comparing several runs on one axis, and per-format defaults loadable from a config file. The `.res` reader covers the channels these runs use; multi-wavelength UV (UV1/UV2/UV3 in one run) is handled in principle but has not been tested against a real file.
