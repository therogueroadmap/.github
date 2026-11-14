import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from brand import build as B

FIX = Path(__file__).parent / "fixtures"
SRC = Path(B.__file__).resolve().parent / "src"
EMBLEM = (SRC / "emblem.svg").read_text(encoding="utf-8")
TEXT = B.load_banner_text(SRC / "banner-text.json")
PALETTE = {B.NAVY, B.ORANGE, B.CREAM}


def _by_id(root, ident):
    for el in root.iter():
        if el.get("id") == ident:
            return el
    return None


def _resvg():
    try:
        return B.find_resvg()
    except B.ResvgError:
        pytest.skip("resvg not available")


def _measure(resvg):
    return lambda svg: B.query_boxes(svg, resvg, B.FONT_FILE)


# --- composition (no resvg) -------------------------------------------------

@pytest.mark.parametrize("spec", B.BANNERS, ids=lambda s: s.name)
def test_banner_composition(spec):
    root = ET.fromstring(B.compose_banner(spec, TEXT, EMBLEM, spec.title_size, spec.subtitle_size))
    assert root.get("width") == str(spec.width) and root.get("height") == str(spec.height)
    bg = _by_id(root, "background")
    assert bg is not None and list(root)[0] is bg
    assert (bg.get("x"), bg.get("y"), bg.get("width"), bg.get("height")) == (
        "0", "0", str(spec.width), str(spec.height))
    assert bg.get("fill") == B.NAVY and bg.get("rx") is None
    assert _by_id(root, "bg") is None  # emblem's rounded square is dropped
    assert _by_id(root, "sun") is not None and _by_id(root, "figure") is not None
    texts = [el for el in root.iter(B._q("text"))]
    assert [t.get("id") for t in texts] == ["title", "sub-es", "sub-en", "sub-fr"]
    for t in texts:
        assert t.get("font-family") == "Outfit"
        assert t.get("fill") == B.CREAM
        assert "\n" not in t.text
    assert texts[0].get("font-weight") == "700"
    assert all(t.get("font-weight") == "400" for t in texts[1:])
    assert texts[1].get("fill-opacity") is None
    assert all(t.get("fill-opacity") == "0.72" for t in texts[2:])
    assert _by_id(root, "rule").get("fill") == B.ORANGE
    fills = {el.get("fill") for el in root.iter() if el.get("fill")}
    assert fills <= PALETTE


def test_banner_escapes_copy():
    data = {"title": "R&D <Roadmap>", "subtitles": [{"lang": "en", "text": "a < b & c"}]}
    svg = B.compose_banner(B.X_BANNER, data, EMBLEM, 70, 25)
    root = ET.fromstring(svg)
    assert _by_id(root, "title").text == "R&D <Roadmap>"
    assert _by_id(root, "sub-en").text == "a < b & c"


# --- data -------------------------------------------------------------------

def _sub(lang, text="x"):
    return {"lang": lang, "text": text}


@pytest.mark.parametrize("data,match", [
    ({"subtitles": [_sub("es")]}, "title"),
    ({"title": "  ", "subtitles": [_sub("es")]}, "title"),
    ({"title": "T", "subtitles": []}, "1 to 3"),
    ({"title": "T", "subtitles": [_sub("es"), _sub("en"), _sub("fr"), _sub("de")]}, "1 to 3"),
    ({"title": "T", "subtitles": [_sub("es", "")]}, "empty text"),
    ({"title": "T", "subtitles": [_sub("es"), _sub("es")]}, "twice"),
    ({"title": "T", "subtitles": [{"text": "x"}]}, "lang"),
    (["not", "an", "object"], "object"),
])
def test_invalid_banner_text(data, match):
    with pytest.raises(B.BannerError, match=match):
        B.validate_banner_text(data)


def test_load_banner_text_bad_json(tmp_path):
    p = tmp_path / "banner-text.json"
    p.write_text("{nope", encoding="utf-8")
    with pytest.raises(B.BannerError, match="not valid JSON"):
        B.load_banner_text(p)


def test_load_banner_text_missing(tmp_path):
    with pytest.raises(B.BannerError, match="not found"):
        B.load_banner_text(tmp_path / "banner-text.json")


def test_fixture_matches_source_text():
    assert json.loads((FIX / "banner-text.json").read_text(encoding="utf-8")) == TEXT


def test_main_returns_2_on_banner_error(monkeypatch, capsys):
    monkeypatch.setattr(B, "find_resvg", lambda *a, **k: Path("fake"))

    def boom(*a, **k):
        raise B.BannerError("banner-text.json: 'title' must be a non-empty string")

    monkeypatch.setattr(B, "build", boom)
    assert B.main([]) == 2
    assert "title" in capsys.readouterr().out


def test_fit_raises_when_text_not_drawn():
    def empty(svg):
        return {"title": (0, 0, 0, 0)}

    with pytest.raises(B.ResvgError, match="not drawn"):
        B.fit_banner(B.X_BANNER, TEXT, EMBLEM, empty)


# --- fit (resvg) --------------------------------------------------------------

def _inside(box, bounds):
    x, y, w, h = box
    x0, y0, x1, y1 = bounds
    return x >= x0 and y >= y0 and x + w <= x1 and y + h <= y1


def _overlaps(box, rect):
    x, y, w, h = box
    x0, y0, x1, y1 = rect
    return x < x1 and x + w > x0 and y < y1 and y + h > y0


@pytest.mark.parametrize("spec", B.BANNERS, ids=lambda s: s.name)
def test_banner_text_fits(spec):
    resvg = _resvg()
    svg, title, sub = B.fit_banner(spec, TEXT, EMBLEM, _measure(resvg))
    assert title >= spec.title_min and sub >= spec.subtitle_min
    boxes = B.query_boxes(svg, resvg, B.FONT_FILE)
    emblem = B.emblem_content_box(spec, EMBLEM)
    for ident in B.text_ids(TEXT) + ["rule"]:
        box = boxes[ident]
        assert box[2] > 0 and box[3] > 0, ident  # text actually drawn
        assert _inside(box, spec.text_bounds), (ident, box)
        assert not _overlaps(box, emblem), (ident, box)
        assert box[0] + box[2] <= spec.emblem_x - spec.emblem_gap + 0.01, (ident, box)
        if spec.avatar:
            cx, cy, r = spec.avatar
            x, y, w, h = box
            for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                assert (px - cx) ** 2 + (py - cy) ** 2 > r * r, (ident, box)


def test_youtube_subtitles_are_reduced():
    resvg = _resvg()
    _, title, sub = B.fit_banner(B.YOUTUBE_BANNER, TEXT, EMBLEM, _measure(resvg))
    assert title == B.YOUTUBE_BANNER.title_size
    assert B.YOUTUBE_BANNER.subtitle_min <= sub < B.YOUTUBE_BANNER.subtitle_size


def _with_first_subtitle(text):
    data = copy.deepcopy(TEXT)
    data["subtitles"][0]["text"] = text
    return data


def test_long_subtitle_shrinks_and_fits():
    resvg = _resvg()
    data = _with_first_subtitle(TEXT["subtitles"][0]["text"] + " Y un poco más.")
    svg, _, sub = B.fit_banner(B.X_BANNER, data, EMBLEM, _measure(resvg))
    assert B.X_BANNER.subtitle_min <= sub < B.X_BANNER.subtitle_size
    box = B.query_boxes(svg, resvg, B.FONT_FILE)["sub-es"]
    assert box[0] + box[2] <= B.X_BANNER.emblem_x - B.X_BANNER.emblem_gap + 0.01


def test_too_long_subtitle_fails():
    resvg = _resvg()
    data = _with_first_subtitle(TEXT["subtitles"][0]["text"] * 2)
    with pytest.raises(B.BannerError, match=r"'sub-es' is [\d.]+ px wide.*shorten the copy"):
        B.fit_banner(B.X_BANNER, data, EMBLEM, _measure(resvg))
