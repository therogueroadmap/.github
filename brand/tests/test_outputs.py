"""Checks on the generated files in brand/out (run `python brand/build.py` first)."""
import tempfile
from pathlib import Path

import pytest

from brand import build as B

try:
    B.find_resvg()
    _resvg_missing = False
except B.ResvgError:
    _resvg_missing = True

Image = pytest.importorskip("PIL.Image")

pytestmark = pytest.mark.skipif(_resvg_missing, reason="resvg not available")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
NAVY_RGB = (0x0A, 0x1B, 0x35)


def _open(rel):
    return Image.open(OUT / rel).convert("RGBA")


def _corners(img):
    w, h = img.size
    return [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


def _is_navy(px, tol=2):
    return px[3] == 255 and all(abs(px[i] - NAVY_RGB[i]) <= tol for i in range(3))


@pytest.mark.parametrize("plugin", B.PLUGINS)
def test_plugin_icons_meet_validator(plugin):
    path = OUT / f"plugin-{plugin}.png"
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (1024, 1024)
    assert path.stat().st_size < 2 * 1024 * 1024


@pytest.mark.parametrize("plugin", B.PLUGINS)
def test_plugin_icon_corners_transparent(plugin):
    img = _open(f"plugin-{plugin}.png")
    assert img.size == (1024, 1024)
    assert all(px[3] == 0 for px in _corners(img))


@pytest.mark.parametrize(
    "rel,size",
    [("avatar-github.png", 1024), ("avatar-youtube.png", 800), ("favicon/favicon-32.png", 32)],
)
def test_bleed_outputs_opaque(rel, size):
    img = _open(rel)
    assert img.size == (size, size)
    for px in _corners(img):
        assert _is_navy(px), px


# Points taken from brand/src/emblem.svg (GitHub avatar = emblem at 1024, unscaled):
# the dark hood cavity around the cream face (the face itself is cream) and the
# gap between hood/shoulder and the road.
HOLE_POINTS = {
    "hood-cavity": (540, 375),
    "hood-road-gap": (545, 555),
}


@pytest.mark.parametrize("name", HOLE_POINTS)
def test_emblem_holes_show_background(name):
    img = _open("avatar-github.png")
    px = img.getpixel(HOLE_POINTS[name])
    assert _is_navy(px), (name, px)


def test_build_is_reproducible():
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        resvg = B.find_resvg()
        fa = B.build(ROOT / "src", Path(a), resvg)
        fb = B.build(ROOT / "src", Path(b), resvg)
        assert len(fa) == len(fb)
        for x, y in zip(fa, fb):
            assert x.relative_to(a) == y.relative_to(b)
            assert x.read_bytes() == y.read_bytes(), x.name
        # versioned PNGs must match a fresh build (svg/html may get CRLF in a clone)
        for x in fa:
            if x.suffix == ".png":
                rel = x.relative_to(a)
                assert (OUT / rel).read_bytes() == x.read_bytes(), f"stale {rel}"
