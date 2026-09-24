# 2026-09-24 — UNICORN 7 exports, lab-data hygiene, archive reorganisation

Third sitting. Mostly *using* plotix on real data — the whole "old Akta"
archive and a fresh set of runs from the new instrument — with one reader fix
that the new instrument's export format forced. Two commits, **not yet pushed**
(the sandbox has no GitHub credentials; push from a terminal).

## What changed and why

### 1. Lab data is never committed (`9170f91`)

`.gitignore` now ignores everything under `Data/` except the single example run
(`Data/FPLC/20260902_PfDh_Nb02P/`) that the README quick start and the
`.res`/`.asc` cross-validation test depend on. New `.res` files, the plasmid
database export and anything else dropped into `Data/` no longer appear as
untracked. Decision: lab data lives outside the repo; the repo carries code and
one worked example.

### 2. Read UNICORN 7 ASCII exports (`b99d104`)

**Why.** The new ÄKTA ("Squirtle") runs UNICORN 7, which saves the ASCII
export as `.csv` (UTF-16, tab-separated). The curves parsed fine when passed
with `format="fplc"`, but every fraction and injection mark was silently
dropped: UNICORN 7 writes the event units bare (`Fraction`, `Injection`,
`Logbook`) where older versions wrote `(Fractions)`, `(Injections)`,
`(Set Marks)`, and `EVENT_UNITS` in `asc.py` only knew the parenthesised forms.

**What.**

- `asc.py`: `EVENT_UNITS` accepts both spellings.
- `core/plotting.py`: `add_event_bands` thins labels by the widest label's
  character count, not a fixed `max_labels` — UNICORN 7 fractions are 96-well
  positions (`1.B.11`), three times wider than tube numbers, and collided.
- `formats/fplc/plot.py`: `_fraction_bands` strips *every* trailing terminal
  mark, and matches `Waste(Frac)` as well as `Waste`. UNICORN 7 logs a waste
  mark at each outlet switch, so a run ends with two; the survivor's 11
  characters were driving the label budget down to one label per ten fractions.
- `docs/fplc.md`: how to feed a UNICORN 7 `.csv` (name it explicitly, or
  rename to `.asc` for folder discovery — folders are not scanned for `.csv`
  because plotix writes `.csv` itself).
- Tests: `build_asc(unicorn7=True)` fixture variant; three new tests. 173 pass.

```bash
MPLBACKEND=Agg python3 -m pytest -q          # 173 passed
python3 -m ruff check src tests              # clean
# ruff format --check reports pre-existing drift in 17 files — untouched
```

## Data work (outside the repo)

**`.../Experimental/FPLC/old Akta/`** — 88 `.res` files, all plotted, then
reorganised:

- Filed by the **instrument run date** (`ds.meta["run_started"]`), not the
  filename prefix: 17 filenames were wrong (e.g. `260706…` runs were 2024-07-06;
  the `20251103 pMD10x` set ran 2025-11-04). `_reorganize_log.txt` at the top
  level records every move.
- Layout: `YYYY/{binder_data,target_data}/YYYYMMDD_<category>_<IDs>/`, day
  folders holding the `.res` plus the six plotix outputs. Companion `.asc`,
  `.cdf`, `.xls`, `.TIF` files moved with their run.
- Category rules (from P.): LDH without a binder token → target; `Mb`/`MB`/
  monobody → binder; `Nb`/`NB`/nanobody → binder; `pMD` names resolved
  against the plasmid database export (`Malaria DX plasmids_260918.xlsx`,
  sheet *pMD plasmids*): all eight are Nb 1983_15 / 1774_3 constructs → binder.
- One mixed day (20260902) duplicated into both categories.
- Leftovers: `2025/20251007_BirA` (no category) and the top-level
  `250515_pfLDH_after_TEV_cleavage_HisTrap_flowtrough.asc` (no matching run).

**`.../FPLC/Squirtle/260923_Nb01P_Spytag_and_1rsDIM_Shuffle_and_BL21/`** — four
UNICORN 7 `.csv` exports plotted into `plots/`:

```bash
cd ".../260923_Nb01P_Spytag_and_1rsDIM_Shuffle_and_BL21"
MPLBACKEND=Agg python3 -m plotix fplc *.csv -o plots
```

## Open items / next steps

- **Push.** `main` is 5 commits ahead of `origin/main`.
- UNICORN 7 exports carry no column / method / run-date metadata in the
  logbook (the subtitle is blank). Check whether the export can include them or
  whether the `.zip` result file is worth reading.
- Folder discovery skips `.csv` by design. If UNICORN 7 becomes the daily
  instrument, consider sniffing `.csv` content (the `Chrom.1` first row is
  distinctive) and excluding plotix's own `_source_data.csv` by name.
- `2025/20251007_BirA` and the TEV-cleavage `.asc` still need a home.
- Last fraction label on the band can clip at the right axis edge.
- `ruff format` drift in 17 files predates this session; reformat in its own
  commit when convenient.
