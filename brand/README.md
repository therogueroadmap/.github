# Brand assets

Source and build for The Rogue Roadmap brand images: the plugin icons, the GitHub and YouTube avatars, the favicon and the YouTube and X banners. Everything in `out/` is generated from `src/` by `build.py`.

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
| `out/banner-youtube.png` | 2560 x 1440, navy, < 6 MB | YouTube channel banner |
| `out/banner-x.png` | 1500 x 500, navy, < 5 MB | X (Twitter) header |
| `out/preview.html` | | Local readability check on light and dark backgrounds, plus the banners with optional guides |

Plugins: `rogue-toolkit`, `rogue-workflow`, `multisession-dev-plugin`, `qa-flutter-plugin`.

## Banners

Text on the left, emblem (sun and figure only, no rounded square) on the right, on a full-bleed navy background. The brand name is Outfit 700 in cream with an orange rule below it; then one subtitle line per language in Outfit 400, the first at full opacity and the others at 72 %.

The copy lives in `src/banner-text.json`: a `title` and 1 to 3 `subtitles` (`lang` + `text`), drawn in list order. The brand identity notes are the source of truth for the copy; keep both in sync by hand. To change the text, edit the JSON and rebuild.

| Banner | Text column | Constraint |
|--------|-------------|------------|
| YouTube | starts at x 530, centred vertically in the safe zone | every line inside the 1546 x 423 safe zone (x 507-2053, y 508.5-931.5) |
| X | starts at x 400, title box at y 70 | every line between y 60 and 440 and clear of the profile picture (circle at (206, 500), r 166) |

Lines are never wrapped. The build measures each line with `resvg --query-all` using the bundled font. If a line would reach the emblem (minus 40 px on YouTube, 30 px on X), the build shrinks that group of lines proportionally and measures again. If it would have to go below the minimum (subtitles 28 px on YouTube and 18 px on X, title 90 and 56), the build fails with exit code 2 and says which line does not fit and how wide it is. That means the copy is too long and should be shortened. The same exit code is used for an invalid `banner-text.json` and for text that resvg did not draw (font not found).

## Font

`fonts/Outfit-Variable.ttf` is Outfit, variable weight axis, copied unchanged from [google/fonts](https://github.com/google/fonts) `ofl/outfit/Outfit[wght].ttf` at commit `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`. It is licensed under the SIL Open Font License 1.1; the licence is in `fonts/OFL.txt`, taken from the same commit. The banners are rendered with `--skip-system-fonts --use-font-file fonts/Outfit-Variable.ttf`, so the output does not depend on the fonts installed on the machine.

## Regenerate

`build.py` rasterizes with [resvg](https://github.com/linebender/resvg/releases), pinned to **0.50.0** (`RESVG_VERSION` in `build.py`). Install the official Windows binary into a folder outside the repo, e.g. `tools/resvg/`, and either put it on `PATH` or set the `RESVG` environment variable to the executable. The build refuses to run with any other version and says which one to install. It installs nothing.

```
python brand/build.py
python -m pytest brand/tests
```

The tests in `brand/tests/test_banners.py` check the banner composition, the data validation and, with resvg, that every line fits. The tests in `brand/tests/test_outputs.py` read the PNGs and need Pillow (`pip install pillow`); they are skipped when resvg or Pillow is missing. The CI of this repo runs only `python -m pytest tests -q`, so it does not need resvg. The build is deterministic: running it twice yields byte-identical PNGs (`test_build_is_reproducible`).
