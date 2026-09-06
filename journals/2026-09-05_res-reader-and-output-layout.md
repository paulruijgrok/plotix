# 2026-09-05 — native `.res` reading, session output layout, folder input

Second sitting on plotix. Started with a working package that read UNICORN ASCII
exports; ended with one that reads the instrument's native files, files its
output by day and session, and plots a whole folder in one command. Three
commits, all pushed.

## What changed and why

### 1. Read ÄKTA `.res` files directly (`603970b`)

**Why.** plotix could only read a run after UNICORN had exported it to ASCII.
That is a manual step between finishing a run and seeing a figure, and one
that's easy to skip mid-experiment — which was the stated motivation.

The format is undocumented, so it was reverse-engineered from the three example
runs in `Data/FPLC/20260902_PfDh_Nb02P/` and cross-checked against the ASCII
export of the one run that has both forms. Reading `.res` turns out to be
better as well as more convenient: the export is decimated, so the native file
carries ~15x more UV samples (14548 vs 973 for the development run).

**Format, as worked out** (documented in full in `src/plotix/formats/fplc/res.py`):

- 256-byte blocks behind a header whose magic is `0x47114711`.
- A directory of 344-byte entries, one per curve, at an offset that **varies
  between files** — so it is located by content: curves are stored
  contiguously, so entry *n*'s `start + allocated` equals entry *n+1*'s
  `start`, and that chain is a near-unambiguous signature. Vectorised over all
  four byte alignments because the table is not word-aligned.
- Each curve begins with 78-byte axis descriptors giving name, unit, column
  width, column type (int32 / float64 / fixed-width text) and a float64 scale
  factor. Every axis *except the first* is a stored column, so a UV curve
  stores 8 bytes per point and a fraction curve stores 180.
- Records end at the first all-zero record.

**Three decisions forced by what the real files do:**

- **Channels are identified from axis descriptors, not names.** Two of the
  three example files leave the channel-name fields blank *and* store the full
  names shifted by one against the curves they label. Naming by them would have
  put the UV trace on the conductivity axis and turned the temperature curve
  into a set of injection marks. The unit in each curve's own descriptor cannot
  drift that way. Curves with no name at all are still read.
- **Injection vs logbook is decided by content.** The two channels are
  structurally identical, down to both naming their text column `Inject`. The
  logbook always holds at least one full sentence (the method-run line with its
  timestamp); an injection mark is only ever a short id. A *median* label
  length does not separate them — most logbook entries are terse block markers
  like "End Block", and the median came out at exactly 15 — so the **longest**
  label is the discriminator (threshold 24 chars).
- **Volume is zeroed at the injection and trimmed before it, by default.** The
  `.res` axis is accumulated volume from method start, so it includes the pump
  wash — which in this data carries a **14 mAU** artefact against a **9 mAU**
  main peak and would dominate an autoscaled figure. UNICORN's own export
  zeroes and trims identically, which is what makes the two forms agree.
  Configurable via `origin` (injection / start / a number) and `trim`. Logbook
  marks are shifted but never trimmed, since they precede the injection by
  design.

Also fixed in passing: peak detection now enforces a minimum separation of
0.5% of the x-range, or the full-rate `.res` data labels one noisy summit
twice. The spacing is computed from the *average* step, not the median — an
ÄKTA quantises volume to 0.01 ml while sampling several times per step, so the
median consecutive difference is zero.

### 2. Dated session output layout (`a797b43`)

**Why.** Output went to a single `figures/` directory that every run
overwrote, so replotting to try a setting destroyed the figure you were about
to use, and a day's work was scattered across whichever data folders it came
from.

Output now goes to `output/<YYYYMMDD>_<FORMAT>/<YYYYMMDD_HHMMSS>/`. The day
folder is dated when plotix *runs*, not when the data was acquired, so
replotting old runs collects them into today's session. The format suffix means
two instruments on one day get one folder each.

`OutputLayout` freezes its timestamp at construction, so one layout means one
folder: plotting forty files, or running a whole batch, keeps them together
even across midnight. `--daily` drops the per-run folder and overwrites the
day's; `-o` bypasses the layout entirely.

**Known interaction, deliberately accepted:** batch resume skips a file whose
outputs already exist *at its destination*, and in the default per-run mode
every invocation gets a fresh folder — so nothing is ever already there and an
interrupted batch replots from the start. That is the direct cost of "a re-run
never destroys the last one". `--daily` or `-o` restores resume. Documented in
`docs/output_layout.md` and in the batch module docstring rather than left to
be discovered.

### 3. Plot a whole folder, mirroring its structure (`0b713a0`)

**Why.** Plotting a folder of runs meant one command per file.

Every command that takes files now takes folders: `plotix fplc FOLDER` plots
everything plotable inside, and `plotix batch FOLDER` does the same with
logging and a summary. Output mirrors the source tree.

**Two silent-data-loss bugs were found by writing the tests for this**, both of
which reported success:

- `--flat` overwrote `expA/run1` with `expB/run1` — "3 plotted", 2 files on
  disk.
- On the plain-path API, the resume check marked the second same-named run as
  "already done", so the batch reported success with a run's figures missing
  entirely.

Fixed by `resolve_stems`, which guarantees output filenames are unique *within
each destination directory*: colliding names take their source folder as a
prefix (`expA_run1`, `expB_run1`), and a numeric suffix settles anything still
ambiguous. The key insight was that the `mirror` flag alone is the wrong test —
what matters is whether two files land in the same directory, which plain paths
also do.

## Exact commands

```bash
# install (per environment — this bit was missed once)
cd ~/Documents/Claude/Projects/Plotix
pip install -e ".[dev]"

# everything in a folder, mirrored, into today's session folder
plotix fplc Data/FPLC

# one file
plotix fplc "Data/FPLC/20260902_PfDh_Nb02P/20260902 Nb02P 60 ul plus PfLDH 100 ul incub 20min001.res"

# variants exercised this session
plotix fplc FOLDER --flat --no-recursive
plotix fplc run.res --daily --label pfldh --output-root ~/plots
plotix fplc run.res --origin start --keep-pre-injection
plotix batch FOLDER --formats png --daily        # resumable
plotix batch configs/batch_example.yaml

# pre-commit checks (all clean)
pytest                              # 170 passed, ~11 s
ruff check src tests
vulture src --min-confidence 80
```

## Files / commits touched

| Commit | Summary | Scope |
|---|---|---|
| `f13f4f2` | Initial commit (previous sitting, 2026-09-04) | 31 files, 87 tests |
| `603970b` | Read ÄKTA `.res` files directly | 21 files; new `formats/fplc/{res,asc,channels}.py`, `reader.py` became a dispatcher; 117 tests |
| `a797b43` | Dated session output folders | 14 files; new `core/output.py`, `api`/`cli`/`batch` wired; 144 tests |
| `0b713a0` | Folder input with source mirroring | 8 files; `InputFile`/`discover_tree`/`resolve_stems` in `core/batch.py`; 170 tests |

New this session: `src/plotix/core/output.py`, `src/plotix/formats/fplc/{res,asc,channels}.py`,
`tests/test_{fplc_res,output_layout,folder_input}.py`, `docs/output_layout.md`.
Repo now 42 tracked files, ~3.7k lines of source, ~2.0k lines of tests.

All three commits pushed to `github.com/paulruijgrok/plotix` (`main`).

Notion mirror: *Docs / plotix / 2026/09/05 Native .res reading, session output
folders, and folder input*. The `plotix` hub page was created this session —
there was none before — following the same pattern as the other project hubs in
the Docs database.

## Verification highlights

- `.res` vs `.asc` of the same run: identical run name, column, method and
  start time; fraction marks identical to 3 dp (37 of them, including the
  trailing `Waste`); UV traces agreeing to **0.014 mAU rms** against an 8.9 mAU
  main peak; the same five peaks within 0.05 ml and 2% height. This is now a
  test (`test_res_and_asc_of_the_same_run_agree`).
- Synthetic `.res` files are built in `tests/conftest.py` so the suite is
  self-contained and can exercise awkward variants on demand — blank channel
  names, names shifted against their curves, directories at three offsets. The
  fixture earned its keep immediately: it caught the reader silently dropping
  curves whose directory entry had no name, which none of the real files
  exercised in that exact way.
- Figures visually inspected at every stage against the `.asc` figure of the
  same run.

## Open items / next steps

**Environment**

- Resolved during the session: `pip install -e .` into conda base. Verified
  end-to-end on the real data —
  `plotix batch .../Data/FPLC/20260902_PfDh_Nb02P` gave 4 succeeded, 0 failed,
  3.5 s, into `output/20260905_FPLC/20260905_185341`. Worth remembering that
  the install is per-environment; the first attempt failed with
  `command not found` because only the dev sandbox had it.

**Known limitations, deliberately deferred**

- `.res` support is reverse-engineered against **UNICORN 3.10 only**. Later
  UNICORN versions write a zipped result format this reader will not recognise;
  it fails cleanly on the magic-number check and the ASCII export is the
  fallback.
- Multi-wavelength UV (UV1/UV2/UV3 in one run) is handled in principle — same
  unit resolves to UV, UV2, UV3 — but **no example file exercises it**.
- The logbook-vs-injection test is a content heuristic. Right on every file
  available, but a run whose logbook held only terse marks would be misread. A
  structural discriminator would be better if one exists.
- Batch resume does not work in the default per-run layout (see above). If
  unattended runs get long enough for the re-plotting to hurt, the fix is to
  let resume look across sibling run folders of the same day.
- Peak areas are integrated across the half-height window only — a reasonable
  comparative measure, not a baseline-resolved integral. Baseline fitting and
  valley-to-valley integration deferred.
- Flat-mode disambiguation uses only the immediate source folder, so two runs
  of the same name under differently-nested folders with the same leaf name
  fall through to the numeric suffix. Correct, but less informative than it
  could be.

**Planned work**

- **Second data format** — the obvious next step. `docs/adding_a_format.md`
  records the contract; a new instrument needs a reader, a plot function and a
  `FormatSpec`.
- `plotix clean --older-than 30d` to prune old session folders. Nothing prunes
  them today.
- Only one theme (`publication`) is registered. `Theme` and `register_theme`
  are in place for a `presentation` variant.
- Overlay plots comparing several runs on one axis — the containers support it,
  there is no entry point.
- No CI workflow; tests are run locally before each commit.
- If FPLC ever needs splitting further in the output layout (SEC vs IEX, say),
  that suffix should come from the dataset's metadata rather than the format
  registry.
