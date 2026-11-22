import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from brand import build as B

GLYPHS_DIR = Path(__file__).resolve().parent.parent / "src" / "glyphs"
NAMES = B.PLUGINS
GRAPHIC = {"path", "circle", "rect", "line"}
FORBIDDEN = {"fill", "stroke", "stroke-width"}


def _local(tag):
    return tag.rsplit("}", 1)[-1]


@pytest.mark.parametrize("name", NAMES)
def test_glyph_contract(name):
    path = GLYPHS_DIR / f"{name}.svg"
    assert path.is_file(), f"missing glyph {path}"
    root = ET.parse(path).getroot()
    assert root.get("viewBox") == "0 0 24 24"
    graphic = 0
    for el in root.iter():
        for attr in FORBIDDEN:
            assert attr not in el.attrib, f"<{_local(el.tag)}> has {attr}"
        if _local(el.tag) in GRAPHIC:
            graphic += 1
    assert graphic >= 1


def test_every_glyph_file_is_a_plugin():
    files = {p.stem for p in GLYPHS_DIR.glob("*.svg")}
    assert files == set(NAMES)
