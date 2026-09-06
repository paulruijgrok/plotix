# Where output goes

Every figure plotix writes lands in a dated session folder:

```
output/
  20260905_FPLC/                  <- one day, one kind of data
    20260905_143022/              <- one invocation of plotix
      20260902 Nb02P ... .png .pdf .svg
      20260902 Nb02P ..._source_data.csv
      20260902 Nb02P ..._peaks.csv
      20260902 Nb02P ..._marks.csv
    20260905_151140_nopeaks/      <- replotted with different settings
      ...
  20260905_PLATE/                 <- a different instrument, same day
  20260906_FPLC/                  <- tomorrow
```

Three properties, in the order they matter:

1. **A re-run never destroys the last one.** Each invocation gets its own timestamped folder, so trying `--auxiliary Conductivity` to see how it looks leaves both versions side by side instead of overwriting the figure you were about to paste into a slide.
2. **A day's work is in one place**, regardless of which folders the raw data was scattered across.
3. **The folder name says what is in it** without opening anything.

## The rules

**Root.** `output/`, relative to wherever you run the command — so each project collects its own. `--output-root DIR` moves it.

**Day folder — `20260905_FPLC`.** Dated when *plotix runs*, not when the data was acquired. Replotting last week's runs today therefore collects them into today's session rather than scattering them by acquisition date. The suffix is the format name, uppercased, so two kinds of data on one day get one folder each; a batch spanning both sorts itself out automatically.

**Run folder — `20260905_143022`.** One per invocation. The date is repeated so the folder is still self-describing if you copy it somewhere else. `--label` appends a tag: `--label pfldh` gives `20260905_143022_pfldh`.

**One invocation, one folder.** The timestamp is taken once when the command starts, so plotting forty files — or running a whole batch — puts them all together. This holds even if the batch runs past midnight.

## Modes

```bash
plotix fplc run.res                       # output/20260905_FPLC/20260905_143022/
plotix fplc run.res --label pfldh         # ..._143022_pfldh/
plotix fplc run.res --daily               # output/20260905_FPLC/ — overwrites
plotix fplc run.res --output-root ~/plots # ~/plots/20260905_FPLC/...
plotix fplc run.res -o exact/place        # exactly there; no layout at all
```

`--daily` drops the per-run folder and writes straight into the day folder, overwriting what is already there. It is the right mode once settings have settled and the accumulating timestamped folders are just clutter — and it is also what makes batch resume work (see below).

`-o` bypasses the layout completely, for when something else owns the destination.

## Python

```python
import plotix
from plotix import OutputLayout

plotix.plot_file("run.res")                                  # default layout
plotix.plot_file("run.res", "exact/place")                   # exact directory
plotix.plot_file("run.res", layout=OutputLayout(mode="daily"))
```

Plotting several files into **one** session folder means building the layout once and passing it to each call — a fresh default layout per call would take a new timestamp each time:

```python
layout = OutputLayout(label="screen")
for path in paths:
    plotix.plot_file(path, layout=layout)
```

`OutputLayout.directory(kind)` returns where output *would* go without creating anything, which is useful for logging or for checking before a long run:

```python
>>> OutputLayout().directory("fplc")
PosixPath('output/20260905_FPLC/20260905_143022')
```

`when=` pins the timestamp, for tests or for writing into a previous session's folder.

## Interaction with batch resume

The batch runner skips a file whose outputs already exist *at the destination it would be written to*. In the default per-run layout every invocation gets a fresh folder, so nothing is ever already there and **an interrupted batch replots from the start**.

That is the intended trade: a new folder per invocation is what stops a re-run destroying earlier results. When resume is what you want — a long unattended run that might be interrupted — pin the destination:

```bash
plotix batch configs/batch_example.yaml --daily     # resumes into today's folder
plotix batch configs/batch_example.yaml -o nightly  # resumes into nightly/
```

Both make the destination stable across invocations, so the second run skips what the first finished. Plotting is fast (well under a second per run), so for small batches the default's re-plotting costs little.

The batch summary always prints the directories it wrote to:

```
Output:
  output/20260905_FPLC/20260905_180050
```

## Config file

Batch configs take the same settings:

```yaml
output_root: output   # root of the layout
daily: false          # true overwrites the day folder
label: overnight      # tag on the run folder
# outdir: some/place  # set this to bypass the layout entirely
```
