# Adding a data format

A new instrument needs two functions and one registration. The CLI subcommand, format detection, source-data export, theming and batch support all follow from that — none of them need editing.

## The contract

```
file  ──reader──▶  Dataset  ──plot──▶  FigureBundle  ──.save()──▶  figures + CSVs
```

- **`reader(path, **kwargs) -> Dataset`** — parse the file. Do no analysis and make no plotting decisions here; a reader's only job is to represent faithfully what the file contains.
- **`plot(source, **kwargs) -> FigureBundle`** — accept a path *or* a `Dataset`, build the figure, and return it together with the numbers behind it.

## Containers

```python
Curve(name, x, y, x_label, x_unit, y_label, y_unit, kind, meta)
Event(x, label, kind, meta)
Dataset(name, format, source_path, curves, events, meta)
```

Each `Curve` carries its own `x`, so channels sampled at different rates need no resampling — and must not be resampled, since that would change the numbers a reader might reuse from the source-data CSV. `Event` covers anything discrete and labelled: fraction marks, injections, log entries, well positions, annotations.

## Skeleton

```
src/plotix/formats/myformat/
    __init__.py     # registers the FormatSpec
    reader.py
    plot.py
```

An instrument that writes more than one file form (a native binary plus a text
export, say) gets one module per form and a `reader.py` that dispatches between
them on content — see `formats/fplc/`, which pairs `res.py` and `asc.py` behind
`read_fplc`, with the vocabulary they share in `channels.py`. Both return the
same `Dataset`, so the plot and everything downstream never learn which form
was read. Register the union of the extensions in one `FormatSpec` rather than
declaring two formats.

**`reader.py`**

```python
from ...core.dataset import Curve, Dataset
from ...core.io import parse_number, read_text


def read_myformat(path, encoding=None) -> Dataset:
    text = read_text(path, encoding=encoding)   # handles UTF-16/BOM/codepages
    ds = Dataset(name=Path(path).stem, format="myformat", source_path=Path(path))
    ds.add_curve(Curve(name="Signal", x=..., y=...,
                       x_label="Time", x_unit="s",
                       y_label="Signal", y_unit="AU", kind="signal"))
    ds.meta["instrument"] = ...
    return ds


def sniff_myformat(head: str) -> bool:
    """Does the first few KB look like this format? Only needed if the
    extension is shared with another format."""
    return "MYINSTRUMENT" in head
```

`read_text` already absorbs encoding variation and `parse_number` tolerates comma decimal separators — use both rather than reimplementing them.

**`plot.py`**

```python
from ...core import theme as theme_mod
from ...core.export import FigureBundle, curves_to_long_frame, slugify
from ...core.plotting import finish_figure, plot_curve, style_axes
from .reader import read_myformat


def plot_myformat(source, *, theme="publication", **kwargs) -> FigureBundle:
    ds = source if isinstance(source, Dataset) else read_myformat(source)
    curve = ds.require("Signal")

    with theme_mod.use(theme) as th:
        fig, ax = plt.subplots()
        style_axes(ax, th, xlabel=curve.x_axis_label, ylabel=curve.y_axis_label)
        plot_curve(ax, curve, th.primary, theme=th, fill=True)
        finish_figure(fig, ax, th, title=ds.name)
        fig.tight_layout()

    return FigureBundle(
        figure=fig,
        stem=slugify(ds.name),
        source_data=curves_to_long_frame([curve]),
        tables={},              # any derived tables, e.g. detected peaks
        meta={"format": "myformat"},
    )
```

**`__init__.py`**

```python
from ...core.registry import FormatSpec, register_format
from .plot import plot_myformat
from .reader import read_myformat, sniff_myformat

SPEC = register_format(FormatSpec(
    name="myformat",
    description="What this instrument produces",
    extensions=(".dat",),
    reader=read_myformat,
    plot=plot_myformat,
    sniff=sniff_myformat,     # only needed for shared extensions
    aliases=("myinstrument",),
))
```

Finally, import the subpackage in `src/plotix/formats/__init__.py` so registration happens on import.

## House rules

**Never hard-code a colour or a font size.** Ask the active theme: `th.primary`, `th.secondary`, `th.lw_primary`. This is what keeps figures from different instruments looking like they belong together, and makes restyling the package a one-file change.

**Reuse the plotting primitives.** `style_axes`, `add_offset_axis`, `enforce_min_span`, `raise_axes`, `add_event_bands`, `add_event_lines`, `annotate_peaks` and `finish_figure` in `core.plotting` exist so every format's spines, secondary axes, event marks and title block behave identically. If you need something they don't do, add it there rather than locally — the next format will want it too.

**Ship the numbers.** `source_data` must contain exactly what was drawn, and nothing that wasn't. Put derived quantities (peaks, integrals, fits) in `tables`, keyed by a name that becomes the CSV suffix.

**Trust the data over its labels.** Where a format records the same fact twice —
a channel's name and its unit, say — prefer whichever one the file derives from
the measurement itself. Real `.res` files store channel names shifted by one
against the curves they label, so a reader that trusted names would put the UV
trace on the conductivity axis; the unit in each curve's own descriptor cannot
drift that way. Cross-check when you can, and write a test with the awkward
variant baked in.

**Prefer dropping to shouting.** If a channel carries no information for a given run, leave it out of the default figure rather than giving it an axis. If it is drawn anyway, hold its axis open with `enforce_min_span` so autoscaling can't magnify noise into an apparent signal. See the two design decisions in [docs/fplc.md](fplc.md) for the worked example.

**Add the format to `--help` for free.** Any format-specific CLI options go in a `_add_<name>_options` helper in `cli.py`, mirroring `_add_fplc_options`. Formats with no special options need no CLI changes at all.

## Tests

Add `tests/test_myformat.py` and build synthetic files in `tests/conftest.py` rather than depending on real data, so the suite stays self-contained. Cover, at minimum:

- a well-formed file parses to the expected curves, units and events
- ragged / short channels, alternative encodings, alternative line endings
- a malformed file raises a clear error rather than producing a wrong figure
- the plot's `source_data` matches the curves actually drawn
- `save()` writes every expected artefact

Then run the full suite — not a subset — before committing.
