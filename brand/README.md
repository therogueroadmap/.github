# Brand assets

Source and build for The Rogue Roadmap icons: the plugin icons, the GitHub and YouTube avatars and the favicon. Everything in `out/` is generated from `src/` by `build.py`.

## Palette

Flat colors only: no gradients and no outline strokes on the emblem.

| Name   | Hex       |
|--------|-----------|
| Navy   | `#0A1B35` |
| Orange | `#F7792C` |
| Cream  | `#FCF3E1` |

## Emblem

`src/emblem.svg` is the master: `viewBox="0 0 1024 1024"` with three elements, `bg` (rounded square filling the canvas), `sun` (orange) and `figure` (cream hood, shoulder and road; holes use `fill-rule="evenodd"` so the navy shows through).

`src/emblem-small.svg` is the same master emblem with `bg` full-bleed (no `rx`): the favicon uses the master emblem full-bleed, not a simplified version.

## Badge (plugin icons only)

Each plugin icon adds a round badge at the bottom right:

- Outer diameter 30 % of the canvas (border included), 2 % gap to the right and bottom edges.
- Navy border about 1.5 % of the canvas. The stroke is centred on the circle, so the radius is `(D - border) / 2` to keep the outer edge at exactly 30 %.
- Orange fill. The glyph sits inside with a 17 % inner margin of the diameter.

## Glyphs

`src/glyphs/<plugin>.svg`, one per plugin:

- 24 x 24 grid (`viewBox="0 0 24 24"`), no fill.
- `stroke-width` 2.6, `stroke-linecap` and `stroke-linejoin` `round`. The build paints the stroke navy.
- A new glyph per plugin, never reused.

## Outputs and destinations

| File | Size | Destination |
|------|------|-------------|
| `out/plugin-<plugin>.png` | 1024 x 1024, transparent corners, < 2 MB | Plugin directory icon, one per plugin repo (PNG only, no SVG or WebP) |
| `out/avatar-github.png` | 1024 x 1024, navy full-bleed, no badge | GitHub organization avatar (same motif scale as the plugin icons) |
| `out/avatar-youtube.png` | 800 x 800, navy full-bleed, no badge | YouTube channel avatar. The motif is scaled so its bounding box fits the inscribed circle with at least 6 % margin |
| `out/favicon/favicon.svg` | vector | Website favicon |
| `out/favicon/favicon-32.png`, `apple-touch-icon.png` (180), `favicon-512.png` | 32, 180, 512 | Website favicon fallbacks |
| `out/preview.html` | | Local readability check on light and dark backgrounds |

Plugins: `rogue-toolkit`, `rogue-workflow`, `multisession-dev-plugin`, `qa-flutter-plugin`.

## Regenerate

`build.py` rasterizes with [resvg](https://github.com/linebender/resvg/releases), pinned to **0.50.0** (`RESVG_VERSION` in `build.py`). Install the official Windows binary into a folder outside the repo, e.g. `tools/resvg/`, and either put it on `PATH` or set the `RESVG` environment variable to the executable. The build refuses to run with any other version and says which one to install. It installs nothing.

```
python brand/build.py
python -m pytest brand/tests
```

The tests in `brand/tests/test_outputs.py` read the PNGs and need Pillow (`pip install pillow`); they are skipped when resvg or Pillow is missing. The CI of this repo runs only `python -m pytest tests -q`, so it does not need resvg. The build is deterministic: running it twice yields byte-identical PNGs (`test_build_is_reproducible`).
