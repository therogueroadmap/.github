import math
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from brand import build as B

FIX = Path(__file__).parent / "fixtures"
NS = {"s": "http://www.w3.org/2000/svg"}
EMBLEM = (FIX / "emblem.svg").read_text(encoding="utf-8")
GLYPH = (FIX / "glyph.svg").read_text(encoding="utf-8")


def _by_id(root, ident):
    for el in root.iter():
        if el.get("id") == ident:
            return el
    return None


def test_plugin_icon_has_badge_geometry():
    root = ET.fromstring(B.compose_plugin_icon(EMBLEM, GLYPH))
    # BADGE_DIAMETER is the outer diameter: stroke centred on r, outer edge = D/2.
    r = (1024 * 0.30 - 1024 * 0.015) / 2
    c = 1024 - 1024 * 0.02 - 1024 * 0.30 / 2
    badges = [
        el for el in root.iter("{http://www.w3.org/2000/svg}circle")
        if el.get("fill") == B.ORANGE and abs(float(el.get("r")) - r) <= 0.5
    ]
    assert len(badges) == 1
    badge = badges[0]
    assert abs(float(badge.get("cx")) - c) <= 0.5
    assert abs(float(badge.get("cy")) - c) <= 0.5
    assert badge.get("stroke") == B.NAVY
    assert abs(float(badge.get("stroke-width")) - 1024 * 0.015) <= 0.5


def test_plugin_icon_keeps_rounded_bg():
    root = ET.fromstring(B.compose_plugin_icon(EMBLEM, GLYPH))
    bg = _by_id(root, "bg")
    assert bg is not None and bg.get("rx") == "184"
    assert root.get("viewBox") == "0 0 1024 1024"


def test_glyph_stroke_and_scale():
    root = ET.fromstring(B.compose_plugin_icon(EMBLEM, GLYPH))
    g = _by_id(root, "glyph")
    assert g is not None
    assert g.get("stroke") == B.NAVY
    assert g.get("fill") == "none"
    assert g.get("stroke-width") == "2.6"
    assert g.get("stroke-linecap") == "round"
    m = re.fullmatch(
        r"translate\(([-\d.]+) ([-\d.]+)\) scale\(([-\d.]+)\)", g.get("transform")
    )
    assert m, g.get("transform")
    tx, ty, s = map(float, m.groups())
    d = 1024 * 0.30
    r = d / 2
    c = 1024 - 1024 * 0.02 - r
    margin = 0.17 * d
    assert abs((tx - (c - r)) - margin) <= 0.5
    assert abs((ty - (c - r)) - margin) <= 0.5
    assert abs((tx + 24 * s) - (c + r - margin)) <= 0.5
    assert abs((ty + 24 * s) - (c + r - margin)) <= 0.5


def test_bleed_replaces_bg():
    root = ET.fromstring(B.compose_bleed(EMBLEM))
    bg = _by_id(root, "bg")
    assert bg.tag.endswith("rect")
    assert bg.get("width") == "1024" and bg.get("height") == "1024"
    assert bg.get("rx") is None
    assert bg.get("fill") == B.NAVY
    assert _by_id(root, "sun") is not None
    assert _by_id(root, "figure") is not None


def test_bleed_scales_motif_only():
    root = ET.fromstring(B.compose_bleed(EMBLEM, scale=0.5))
    sun = _by_id(root, "sun")
    parents = {c: p for p in root.iter() for c in p}
    assert "scale(0.5)" in parents[sun].get("transform")
    assert _by_id(root, "bg") in list(root)


@pytest.mark.parametrize("cmd", ["A", "a", "S", "s", "T", "t", "H", "h", "V", "v"])
def test_path_rejects_unsupported_commands(cmd):
    d = f"M300 900 L300 500 {cmd} 40 40 0 0 1 400 500 Z"
    with pytest.raises(ValueError, match=f"unsupported path command '{cmd}'"):
        B._path_points(d)


def test_youtube_scale_rejects_arc_in_motif():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        '<circle id="sun" cx="512" cy="512" r="100"/>'
        '<path id="figure" d="M300 900 A60 60 0 0 1 420 900 L420 300 Z"/>'
        "</svg>"
    )
    with pytest.raises(ValueError, match="emblem paths may only use M L C Q Z"):
        B.youtube_scale(svg)


def test_youtube_motif_inside_circle():
    s = B.youtube_scale(EMBLEM)
    assert 0 < s < 1
    # fixture bbox: x 300..820, y 180..900
    x0, x1, y0, y1 = 300, 820, 180, 900
    limit = 512 * (1 - 0.06)
    for x in (x0, x1):
        for y in (y0, y1):
            dist = math.hypot((x - 512) * s, (y - 512) * s)
            assert dist <= limit + 1e-6
    # tight: the farthest corner touches the limit
    far = max(math.hypot(x - 512, y - 512) for x in (x0, x1) for y in (y0, y1))
    assert far * s == pytest.approx(limit, abs=0.01)


def test_find_resvg_missing_message(monkeypatch):
    with pytest.raises(B.ResvgError) as e:
        B.find_resvg(env={"PATH": ""})
    msg = str(e.value)
    assert B.RESVG_VERSION in msg
    assert "github.com/linebender/resvg/releases" in msg


def test_find_resvg_wrong_version(tmp_path):
    if os.name == "nt":
        fake = tmp_path / "resvg.cmd"
        fake.write_text("@echo resvg 0.0.1\r\n")
    else:
        fake = tmp_path / "resvg"
        fake.write_text("#!/bin/sh\necho resvg 0.0.1\n")
        fake.chmod(0o755)
    with pytest.raises(B.ResvgError) as e:
        B.find_resvg(env={"RESVG": str(fake), "PATH": ""})
    msg = str(e.value)
    assert "0.0.1" in msg and B.RESVG_VERSION in msg


def test_main_returns_2_without_resvg(monkeypatch, capsys):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("RESVG", raising=False)
    assert B.main([]) == 2
    assert B.RESVG_VERSION in capsys.readouterr().out


def test_build_with_fixtures(tmp_path):
    try:
        resvg = B.find_resvg()
    except B.ResvgError:
        pytest.skip("resvg not available")
    src = tmp_path / "src"
    (src / "glyphs").mkdir(parents=True)
    shutil.copy(FIX / "emblem.svg", src / "emblem.svg")
    shutil.copy(FIX / "emblem.svg", src / "emblem-small.svg")
    for p in B.PLUGINS:
        shutil.copy(FIX / "glyph.svg", src / "glyphs" / f"{p}.svg")
    out = tmp_path / "out"
    files = B.build(src, out, resvg)
    names = {f.relative_to(out).as_posix() for f in files}
    assert "plugin-rogue-toolkit.png" in names
    assert "favicon/favicon.svg" in names
    html = (out / "preview.html").read_text(encoding="utf-8")
    assert str(tmp_path) not in html
    assert "plugin-rogue-workflow.png" in html


def test_path_points_rejects_numbers_after_z():
    with pytest.raises(ValueError, match="after Z"):
        B._path_points("M0 0 L1 1 Z 5 5")


class _Proc:
    returncode = 1
    stderr = "boom"
    stdout = ""


def test_render_nonzero_exit_raises_resvgerror(monkeypatch, tmp_path):
    monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(B.ResvgError) as e:
        B.render("<svg/>", tmp_path / "x.png", 32, Path("fake"))
    assert "x.png" in str(e.value) and "boom" in str(e.value)


def test_render_timeout_raises_resvgerror(monkeypatch, tmp_path):
    seen = {}

    def fake(*a, **k):
        seen.update(k)
        raise B.subprocess.TimeoutExpired(cmd="resvg", timeout=k["timeout"])

    monkeypatch.setattr(B.subprocess, "run", fake)
    with pytest.raises(B.ResvgError) as e:
        B.render("<svg/>", tmp_path / "x.png", 32, Path("fake"))
    assert seen["timeout"] == 120 and "x.png" in str(e.value)


def test_main_returns_2_on_build_resvgerror(monkeypatch, capsys):
    monkeypatch.setattr(B, "find_resvg", lambda *a, **k: Path("fake"))

    def boom(*a, **k):
        raise B.ResvgError("resvg failed for y.png: nope")

    monkeypatch.setattr(B, "build", boom)
    assert B.main([]) == 2
    assert "y.png" in capsys.readouterr().out


def test_emblem_small_matches_master_paths():
    src = Path(B.__file__).resolve().parent / "src"
    big = ET.parse(src / "emblem.svg").getroot()
    small = ET.parse(src / "emblem-small.svg").getroot()
    for ident in ("sun", "figure"):
        a, b = _by_id(big, ident), _by_id(small, ident)
        assert a is not None and b is not None
        assert a.get("d") == b.get("d"), ident
        assert a.get("fill") == b.get("fill"), ident
    assert _by_id(small, "bg").get("rx") is None
