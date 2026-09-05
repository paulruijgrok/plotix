# Batch processing

Plot a folder of runs unattended. Designed for the case where the batch is left running and nobody is watching it: it never prompts, never lets one bad file stop the rest, and leaves a record of what happened.

## Guarantees

- **Fail-isolated.** Each dataset runs inside its own error boundary. A corrupt export logs its exception and the batch moves on — one bad file never costs you the other 200 figures.
- **Resumable.** A dataset whose figures already exist is skipped, so an interrupted overnight run picks up where it stopped when you re-run the same command. `--force` re-plots everything.
- **Logged.** Every dataset is logged, with a batch-level summary at the end (succeeded / skipped / failed, elapsed time, and the reason for each failure). `--log PATH` also writes it to a file.
- **Non-interactive.** Nothing ever asks a question. A missing parameter fails that dataset and is logged, rather than blocking the run.

## Command line

```bash
# From a config file
plotix batch configs/batch_example.yaml

# Or entirely from flags
plotix batch --inputs Data/FPLC -o figures --formats png pdf --log figures/batch.log
```

| Option | Effect |
|---|---|
| `--inputs PATH...` | files or folders to plot (folders are searched recursively) |
| `-o, --outdir DIR` | where figures and CSVs go |
| `--format NAME` | force a format instead of detecting per file |
| `--formats EXT...` | figure formats to write |
| `--dpi N` | raster resolution |
| `--force` | re-plot datasets that already have outputs |
| `--per-file-subdir` | give each input its own output subfolder |
| `--log PATH` | write the batch log to a file |
| `-v, --verbose` | include per-file debug detail and tracebacks in the log |

Flags override the config file, so a saved config can be reused with a one-off change.

Exit code is `0` when nothing failed and `1` when at least one dataset failed — usable directly in a shell script or cron job.

## Config file

YAML or JSON. Every key is optional except `inputs` and `outdir`.

```yaml
# configs/batch_example.yaml
inputs:
  - Data/FPLC
outdir: figures

patterns: ["*.asc"]      # which files to pick up under each input folder
recursive: true          # descend into subfolders
formats: [png, pdf, svg]
dpi: 300
force: false             # true re-plots datasets that are already done
per_file_subdir: false   # true gives each input its own output folder
log: figures/batch.log

# Passed straight to the format's plot function, so anything the Python API
# accepts can be set here.
plot:
  auxiliary: auto
  max_peaks: 6
  annotate_peaks_: true
```

### Per-dataset settings

Dataset-specific parameters belong in their own config rather than hard-coded into a script. Keep one config per group of runs that share settings:

```yaml
# configs/iex_runs.yaml — salt gradients, so force the conductivity axis in
inputs: [Data/FPLC/iex]
outdir: figures/iex
plot:
  auxiliary: [Conductivity, "Concentration B"]
  peak_window: [5.0, 40.0]
```

```bash
plotix batch configs/iex_runs.yaml
plotix batch configs/sec_runs.yaml
```

## Python API

```python
from plotix.core.batch import discover_inputs, run_batch

files = discover_inputs(["Data/FPLC"], patterns=["*.asc"])
report = run_batch(
    files,
    "figures",
    formats=("png", "pdf"),
    log_path="figures/batch.log",
    plot_kwargs={"auxiliary": "auto", "max_peaks": 4},
)

print(report.summary())
for failure in report.failed:
    print(failure.path.name, failure.error)
```

`run_batch` returns a `BatchReport`. Each entry is a `BatchResult` with `.path`, `.status` (`"ok"`, `"skipped"`, `"failed"`), `.outputs`, `.error` and `.seconds`, so a wrapper script can act on individual outcomes — re-queue failures, tabulate timings, or fail a CI job.

## Example summary

```
==============================================================
plotix batch summary
==============================================================
  succeeded : 47
  skipped   : 12 (outputs already present)
  failed    : 2
  elapsed   : 61.4 s

Failures:
  - 20260814_trial3.asc: ValueError: no numeric data rows found — not a UNICORN ASCII export?
  - 20260820_blank.asc: KeyError: '20260820_blank: none of ('UV',) present; available curves: ['Pressure']'
==============================================================
```
