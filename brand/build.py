"""Compose brand SVGs per destination and rasterize them with resvg."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

NAVY = "#0A1B35"
ORANGE = "#F7792C"
CREAM = "#FCF3E1"
BADGE_DIAMETER = 0.30
BADGE_INSET = 0.02
BADGE_BORDER = 0.015
GLYPH_PADDING = 0.17
GLYPH_STROKE = 2.6
YOUTUBE_CIRCLE_MARGIN = 0.06
RESVG_VERSION = "0.50.0"
RESVG_RELEASES = "https://github.com/linebender/resvg/releases"
PLUGINS = (
    "rogue-toolkit",
    "rogue-workflow",
    "multisession-dev-plugin",
    "qa-flutter-plugin",
    "rasenshuriken",
    "sharingan",
    "rogue-road",
)

SVG_NS = "http://www.w3.org/2000/svg"
CANVAS = 1024
ET.register_namespace("", SVG_NS)


FONT_FILE = Path(__file__).resolve().parent / "fonts" / "Outfit-Variable.ttf"
FONT_FAMILY = "Outfit"
# Outfit vertical metrics in em, as resvg --query-all reports a text box:
# top = baseline - ASCENT * size, height = LINE * size.
FONT_ASCENT = 1.0
FONT_LINE = 1.26


class ResvgError(RuntimeError):
    pass


class BannerError(ValueError):
    """Invalid banner text data, or copy that does not fit above the minimum size."""


def _q(tag: str) -> str:
    return f"{{{SVG_NS}}}{tag}"


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _by_id(root: ET.Element, ident: str) -> ET.Element:
    for el in root.iter():
        if el.get("id") == ident:
            return el
    raise ValueError(f"element id={ident!r} not found in SVG")


def _tostring(root: ET.Element) -> str:
    return ET.tostring(root, encoding="unicode")


# --- resvg -----------------------------------------------------------------

def find_resvg(env: Mapping[str, str] = os.environ) -> Path:
    candidate = env.get("RESVG")
    if candidate:
        found = candidate if Path(candidate).exists() else shutil.which(candidate, path=env.get("PATH", ""))
    else:
        found = shutil.which("resvg", path=env.get("PATH", ""))
    if not found:
        raise ResvgError(
            f"resvg {RESVG_VERSION} not found. Install the official binary from "
            f"{RESVG_RELEASES} (version {RESVG_VERSION}) and put it on PATH "
            "or set the RESVG environment variable to its path."
        )
    try:
        proc = subprocess.run(
            [found, "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ResvgError(
            f"could not run {found} --version ({exc}). Expected resvg "
            f"{RESVG_VERSION}, see {RESVG_RELEASES}"
        ) from exc
    got = proc.stdout.strip()
    if got.startswith("resvg "):
        got = got[len("resvg "):].strip()
    if got != RESVG_VERSION:
        raise ResvgError(
            f"resvg version mismatch: found {got or 'unknown'}, expected "
            f"{RESVG_VERSION}. Install it from {RESVG_RELEASES}"
        )
    return Path(found)


RESVG_TIMEOUT = 120  # seconds per render call


def _font_args(font_file: Path | None) -> list[str]:
    if font_file is None:
        return []
    return ["--skip-system-fonts", "--use-font-file", str(font_file)]


def _run_resvg(args: list[str], label: str) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", timeout=RESVG_TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise ResvgError(
            f"resvg timed out after {RESVG_TIMEOUT}s rendering {label}"
            f" (stderr: {(exc.stderr or '').strip() if isinstance(exc.stderr, str) else ''})"
        ) from exc
    if proc.returncode != 0:
        raise ResvgError(f"resvg failed for {label}: {proc.stderr.strip()}")
    return proc


def render(
    svg: str,
    out: Path,
    size: int,
    resvg: Path,
    *,
    height: int | None = None,
    font_file: Path | None = None,
) -> None:
    """Rasterize svg to out. `size` is the width; `height` defaults to `size`.

    With `font_file`, system fonts are skipped so the PNG does not depend on the
    machine that builds it.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    h = size if height is None else height
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.svg"
        src.write_text(svg, encoding="utf-8")
        _run_resvg(
            [str(resvg), *_font_args(font_file), "-w", str(size), "-h", str(h), str(src), str(out)],
            out.name,
        )


Box = tuple[float, float, float, float]  # x, y, width, height


def query_boxes(svg: str, resvg: Path, font_file: Path | None = None) -> dict[str, Box]:
    """Bounding boxes of every element with an id, as resvg lays them out."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.svg"
        src.write_text(svg, encoding="utf-8")
        proc = _run_resvg(
            [str(resvg), *_font_args(font_file), "--query-all", str(src)], "query"
        )
    boxes: dict[str, Box] = {}
    for line in proc.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) != 5:
            continue
        ident, *nums = parts
        boxes[ident] = tuple(float(n) for n in nums)  # type: ignore[assignment]
    return boxes


# --- composition -----------------------------------------------------------

def compose_plugin_icon(emblem_svg: str, glyph_svg: str) -> str:
    root = ET.fromstring(emblem_svg)
    glyph = ET.fromstring(glyph_svg)
    # BADGE_DIAMETER is the outer diameter (border included). The stroke is
    # centred on r, so r = (D - w) / 2 keeps the outer edge at exactly D.
    diameter = CANVAS * BADGE_DIAMETER
    border = CANVAS * BADGE_BORDER
    r = (diameter - border) / 2
    c = CANVAS - CANVAS * BADGE_INSET - diameter / 2
    ET.SubElement(root, _q("circle"), {
        "id": "badge",
        "cx": _fmt(c), "cy": _fmt(c), "r": _fmt(r),
        "fill": ORANGE, "stroke": NAVY, "stroke-width": _fmt(border),
    })
    inner = diameter * (1 - 2 * GLYPH_PADDING)
    scale = inner / 24
    t = c - inner / 2
    g = ET.SubElement(root, _q("g"), {
        "id": "glyph",
        "transform": f"translate({_fmt(t)} {_fmt(t)}) scale({_fmt(scale)})",
        "fill": "none", "stroke": NAVY, "stroke-width": _fmt(GLYPH_STROKE),
        "stroke-linecap": "round", "stroke-linejoin": "round",
    })
    for child in list(glyph):
        g.append(copy.deepcopy(child))
    return _tostring(root)


def compose_bleed(emblem_svg: str, *, scale: float = 1.0) -> str:
    root = ET.fromstring(emblem_svg)
    bg = _by_id(root, "bg")
    for key in list(bg.attrib):
        if key != "id":
            del bg.attrib[key]
    bg.tag = _q("rect")
    bg.attrib.update({
        "x": "0", "y": "0", "width": str(CANVAS), "height": str(CANVAS), "fill": NAVY,
    })
    if scale != 1.0:
        parent_map = {c: p for p in root.iter() for c in p}
        motif = [el for el in root.iter() if el.get("id") in ("sun", "figure")]
        if motif:
            parent = parent_map[motif[0]]
            half = CANVAS / 2
            g = ET.Element(_q("g"), {
                "transform": f"translate({_fmt(half)} {_fmt(half)}) scale({_fmt(scale)}) "
                             f"translate({_fmt(-half)} {_fmt(-half)})",
            })
            idx = list(parent).index(motif[0])
            for el in motif:
                parent_map[el].remove(el)
                g.append(el)
            parent.insert(idx, g)
    return _tostring(root)


# --- bounding box ----------------------------------------------------------

_TOKEN = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
# Emblem contract: only these commands are admitted. Arcs (A) and smooth/reflected
# curves (S, T) can bulge outside their endpoints/control points, so the bbox
# from _path_points would undercount them; they are rejected instead.
_SUPPORTED_PATH_CMDS = frozenset("MLCQZ")


def _path_points(d: str) -> list[tuple[float, float]]:
    """Endpoints and control points of a path (conservative bound for curves)."""
    tokens = [(m.group(1), m.group(2)) for m in _TOKEN.finditer(d)]
    pts: list[tuple[float, float]] = []
    x = y = sx = sy = 0.0
    i = 0
    cmd = None
    while i < len(tokens):
        if tokens[i][0]:
            cmd = tokens[i][0]
            i += 1
            if cmd in "Zz":
                if i < len(tokens) and tokens[i][1] is not None:
                    raise ValueError("numbers after Z are not allowed in path data")
                x, y = sx, sy
                continue
        if cmd is None:
            raise ValueError("path data does not start with a command")
        up = cmd.upper()
        if up not in _SUPPORTED_PATH_CMDS:
            raise ValueError(
                f"unsupported path command {cmd!r}: emblem paths may only use M L C Q Z"
            )
        rel = cmd.islower()
        n = _ARITY[up]
        nums = []
        while len(nums) < n and i < len(tokens) and tokens[i][1] is not None:
            nums.append(float(tokens[i][1]))
            i += 1
        if len(nums) < n:
            raise ValueError(f"truncated path command {cmd!r}")
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if up == "H":
            x = nums[0] + ox
            pts.append((x, y))
        elif up == "V":
            y = nums[0] + oy
            pts.append((x, y))
        elif up == "A":
            x, y = nums[5] + ox, nums[6] + oy
            pts.append((x, y))
        else:
            for k in range(0, n, 2):
                pts.append((nums[k] + ox, nums[k + 1] + oy))
            x, y = pts[-1]
        if up == "M":
            sx, sy = x, y
            cmd = "l" if rel else "L"  # implicit lineto after moveto
    return pts


def _element_points(el: ET.Element) -> list[tuple[float, float]]:
    tag = el.tag.split("}")[-1]

    def f(k: str) -> float:
        return float(el.get(k, "0"))

    if tag == "circle":
        cx, cy, r = f("cx"), f("cy"), f("r")
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if tag == "ellipse":
        cx, cy, rx, ry = f("cx"), f("cy"), f("rx"), f("ry")
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)]
    if tag == "rect":
        return [(f("x"), f("y")), (f("x") + f("width"), f("y") + f("height"))]
    if tag == "path":
        return _path_points(el.get("d", ""))
    raise ValueError(f"unsupported motif element <{tag}>")


def motif_bbox(emblem_svg: str) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of sun + figure in emblem viewBox units (conservative)."""
    root = ET.fromstring(emblem_svg)
    pts = _element_points(_by_id(root, "sun")) + _element_points(_by_id(root, "figure"))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def youtube_scale(emblem_svg: str) -> float:
    x0, y0, x1, y1 = motif_bbox(emblem_svg)
    half = CANVAS / 2
    far = max(
        math.hypot(x - half, y - half)
        for x in (x0, x1) for y in (y0, y1)
    )
    limit = half * (1 - YOUTUBE_CIRCLE_MARGIN)
    return min(1.0, limit / far) if far > 0 else 1.0


# --- banners ---------------------------------------------------------------

# Block layout, relative to the title size T and the subtitle size S.
RULE_GAP_ABOVE = 0.06    # x T, from the title line box to the rule
RULE_THICKNESS = 0.07    # x T
RULE_WIDTH = 1.6         # x T
RULE_GAP_BELOW = 0.42    # x T, from the rule to the first subtitle line box
SUBTITLE_GAP = 0.32      # x S, between subtitle line boxes
MAX_SUBTITLES = 3


@dataclass(frozen=True)
class BannerSpec:
    name: str
    width: int
    height: int
    emblem_x: float
    emblem_y: float
    emblem_size: float       # side of the emblem's 1024 viewBox frame
    text_x: float
    emblem_gap: float        # min distance from the text to the emblem frame
    title_size: float
    title_min: float
    subtitle_size: float
    subtitle_min: float
    # Vertical placement: centred in [area_top, area_bottom] when block_top is
    # None, else the title line box starts at block_top.
    area_top: float
    area_bottom: float
    block_top: float | None = None
    # Box that must contain every text line (x0, y0, x1, y1).
    text_bounds: tuple[float, float, float, float] = (0, 0, 0, 0)
    # Profile picture overlap to avoid (cx, cy, r), X only.
    avatar: tuple[float, float, float] | None = None
    max_bytes: int = 0


YOUTUBE_SAFE = (507.0, 508.5, 2053.0, 931.5)  # 1546 x 423 centred in 2560 x 1440

YOUTUBE_BANNER = BannerSpec(
    name="banner-youtube.png",
    width=2560, height=1440,
    emblem_x=1673, emblem_y=530, emblem_size=380,
    text_x=530, emblem_gap=40,
    title_size=112, title_min=90,
    subtitle_size=40, subtitle_min=28,
    area_top=YOUTUBE_SAFE[1], area_bottom=YOUTUBE_SAFE[3],
    text_bounds=YOUTUBE_SAFE,
    max_bytes=6 * 1024 * 1024,
)

X_BANNER = BannerSpec(
    name="banner-x.png",
    width=1500, height=500,
    emblem_x=1180, emblem_y=85, emblem_size=290,
    text_x=400, emblem_gap=30,
    title_size=70, title_min=56,
    subtitle_size=25, subtitle_min=18,
    area_top=60, area_bottom=440, block_top=70,
    text_bounds=(0, 60, 1500, 440),
    avatar=(206, 500, 166),
    max_bytes=5 * 1024 * 1024,
)

BANNERS = (YOUTUBE_BANNER, X_BANNER)
_LANG = re.compile(r"[a-z]{2,3}")


def load_banner_text(path: Path) -> dict:
    """Read and validate banner-text.json. Raises BannerError with a clear message."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BannerError(f"banner text not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise BannerError(f"{path.name} is not valid JSON: {exc}") from exc
    return validate_banner_text(data, path.name)


def validate_banner_text(data: object, label: str = "banner text") -> dict:
    if not isinstance(data, dict):
        raise BannerError(f"{label}: expected an object with 'title' and 'subtitles'")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise BannerError(f"{label}: 'title' must be a non-empty string")
    subs = data.get("subtitles")
    if not isinstance(subs, list) or not 1 <= len(subs) <= MAX_SUBTITLES:
        raise BannerError(f"{label}: 'subtitles' must list 1 to {MAX_SUBTITLES} lines")
    seen = set()
    for i, sub in enumerate(subs):
        if not isinstance(sub, dict):
            raise BannerError(f"{label}: subtitle {i + 1} must be an object with 'lang' and 'text'")
        lang, text = sub.get("lang"), sub.get("text")
        if not isinstance(lang, str) or not _LANG.fullmatch(lang):
            raise BannerError(f"{label}: subtitle {i + 1} needs a 'lang' code like 'es'")
        if lang in seen:
            raise BannerError(f"{label}: subtitle language {lang!r} appears twice")
        seen.add(lang)
        if not isinstance(text, str) or not text.strip():
            raise BannerError(f"{label}: subtitle {lang!r} has empty text")
    return data


def text_ids(data: dict) -> list[str]:
    return ["title"] + [f"sub-{s['lang']}" for s in data["subtitles"]]


def emblem_content_box(spec: BannerSpec, emblem_svg: str) -> tuple[float, float, float, float]:
    """Visible emblem (sun + figure bbox) in banner coordinates."""
    k = spec.emblem_size / CANVAS
    x0, y0, x1, y1 = motif_bbox(emblem_svg)
    return (spec.emblem_x + x0 * k, spec.emblem_y + y0 * k,
            spec.emblem_x + x1 * k, spec.emblem_y + y1 * k)


def _block_height(title_size: float, subtitle_size: float, n_subs: int) -> float:
    t, s = title_size, subtitle_size
    return (FONT_LINE * t + (RULE_GAP_ABOVE + RULE_THICKNESS + RULE_GAP_BELOW) * t
            + n_subs * FONT_LINE * s + (n_subs - 1) * SUBTITLE_GAP * s)


def compose_banner(
    spec: BannerSpec, data: dict, emblem_svg: str, title_size: float, subtitle_size: float
) -> str:
    t, s = title_size, subtitle_size
    n = len(data["subtitles"])
    if spec.block_top is None:
        top = spec.area_top + (spec.area_bottom - spec.area_top - _block_height(t, s, n)) / 2
    else:
        top = spec.block_top

    root = ET.Element(_q("svg"), {
        "width": str(spec.width), "height": str(spec.height),
        "viewBox": f"0 0 {spec.width} {spec.height}",
    })
    ET.SubElement(root, _q("rect"), {
        "id": "background", "x": "0", "y": "0",
        "width": str(spec.width), "height": str(spec.height), "fill": NAVY,
    })

    emblem = ET.fromstring(emblem_svg)
    g = ET.SubElement(root, _q("g"), {
        "id": "emblem",
        "transform": f"translate({_fmt(spec.emblem_x)} {_fmt(spec.emblem_y)}) "
                     f"scale({_fmt(spec.emblem_size / CANVAS)})",
    })
    for ident in ("sun", "figure"):
        g.append(copy.deepcopy(_by_id(emblem, ident)))

    def line(ident: str, text: str, y_top: float, size: float, weight: str) -> None:
        attrs = {
            "id": ident, "x": _fmt(spec.text_x), "y": _fmt(y_top + FONT_ASCENT * size),
            "font-family": FONT_FAMILY, "font-weight": weight,
            "font-size": _fmt(size), "fill": CREAM,
        }
        ET.SubElement(root, _q("text"), attrs).text = text

    y = top
    line("title", data["title"], y, t, "700")
    y += FONT_LINE * t + RULE_GAP_ABOVE * t
    ET.SubElement(root, _q("rect"), {
        "id": "rule", "x": _fmt(spec.text_x), "y": _fmt(y),
        "width": _fmt(RULE_WIDTH * t), "height": _fmt(RULE_THICKNESS * t), "fill": ORANGE,
    })
    y += (RULE_THICKNESS + RULE_GAP_BELOW) * t
    for sub in data["subtitles"]:
        line(f"sub-{sub['lang']}", sub["text"], y, s, "400")
        y += (FONT_LINE + SUBTITLE_GAP) * s
    return _tostring(root)


Measure = Callable[[str], dict[str, Box]]


def fit_banner(
    spec: BannerSpec, data: dict, emblem_svg: str, measure: Measure
) -> tuple[str, float, float]:
    """Compose the banner, shrinking title/subtitles until every line clears the emblem.

    Returns (svg, title_size, subtitle_size). Raises BannerError when a line only
    fits below the minimum size (the copy is too long), or ResvgError when a line
    is not drawn (font not found).
    """
    limit = spec.emblem_x - spec.emblem_gap
    avail = limit - spec.text_x
    sizes = {"title": spec.title_size, "sub": spec.subtitle_size}
    minimum = {"title": spec.title_min, "sub": spec.subtitle_min}
    ids = text_ids(data)
    for _ in range(20):
        svg = compose_banner(spec, data, emblem_svg, sizes["title"], sizes["sub"])
        boxes = measure(svg)
        for ident in ids:
            box = boxes.get(ident)
            if box is None or box[2] <= 0 or box[3] <= 0:
                raise ResvgError(
                    f"{spec.name}: text {ident!r} was not drawn; is {FONT_FAMILY} "
                    f"available in {FONT_FILE.name}?"
                )
        fits = True
        for group, members in (("title", ids[:1]), ("sub", ids[1:])):
            widest = max(members, key=lambda i: boxes[i][0] + boxes[i][2])
            used = boxes[widest][0] + boxes[widest][2] - spec.text_x
            if used <= avail:
                continue
            fits = False
            new = math.floor(sizes[group] * avail / used * 2) / 2
            if new >= sizes[group]:
                new = sizes[group] - 0.5
            if new < minimum[group]:
                raise BannerError(
                    f"{spec.name}: line {widest!r} is {used:.1f} px wide but only "
                    f"{avail:.1f} px fit, even at the minimum size {minimum[group]}; "
                    "shorten the copy"
                )
            sizes[group] = new
        if fits:
            return svg, sizes["title"], sizes["sub"]
    raise BannerError(f"{spec.name}: text sizes did not converge")


# --- build -----------------------------------------------------------------

def _preview(plugin_files: list[str]) -> str:
    def section(bg: str, fg: str, label: str) -> str:
        big = "".join(
            f'<img src="{f}" width="256" height="256">' for f in plugin_files
        )
        small = "".join(
            f'<img src="{f}" width="48" height="48">' for f in plugin_files
        )
        return (
            f'<section style="background:{bg};color:{fg}">\n<h2>{label}</h2>\n'
            f'<div class="row">{big}</div>\n<div class="row">{small}</div>\n'
            '<div class="row">\n'
            '<img src="avatar-github.png" width="128" height="128" style="border-radius:12.5%">\n'
            '<img src="avatar-youtube.png" width="128" height="128" style="border-radius:50%">\n'
            '<img src="favicon/favicon-32.png" width="32" height="32">\n'
            '<img src="favicon/favicon-32.png" width="16" height="16">\n'
            "</div>\n</section>\n"
        )

    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        "<title>Brand preview</title>\n<style>body{margin:0;font-family:sans-serif}"
        "section{padding:16px}.row{display:flex;gap:16px;align-items:center;margin:8px 0}"
        ".banner{position:relative;overflow:hidden;width:100%;margin:8px 0}"
        ".banner img{display:block;width:100%;height:auto}"
        ".guide{position:absolute;pointer-events:none;box-sizing:border-box}"
        ".safe{border:2px dashed #00e5ff}.avatar{border:2px dashed #ff3df2;border-radius:50%}"
        "body:not(.guides) .guide{display:none}"
        "</style>\n</head><body class=\"guides\">\n"
        + section("#ffffff", "#000000", "Light background")
        + section("#0d1117", "#ffffff", "Dark background")
        + _preview_banners()
        + "</body></html>\n"
    )


def _pct(v: float, total: float) -> str:
    return f"{_fmt(100 * v / total)}%"


def _preview_banners() -> str:
    yt, x = YOUTUBE_BANNER, X_BANNER
    sx0, sy0, sx1, sy1 = YOUTUBE_SAFE
    safe = (
        f'<div class="guide safe" style="left:{_pct(sx0, yt.width)};top:{_pct(sy0, yt.height)};'
        f'width:{_pct(sx1 - sx0, yt.width)};height:{_pct(sy1 - sy0, yt.height)}"></div>'
    )
    cx, cy, r = x.avatar
    avatar = (
        f'<div class="guide avatar" style="left:{_pct(cx - r, x.width)};top:{_pct(cy - r, x.height)};'
        f'width:{_pct(2 * r, x.width)};height:{_pct(2 * r, x.height)}"></div>'
    )
    # Mobile: YouTube shows only the safe zone, about 400 px wide.
    k = 400 / (sx1 - sx0)
    mobile = (
        f'<div style="width:400px;height:{_fmt((sy1 - sy0) * k)}px;overflow:hidden">'
        f'<img src="{yt.name}" style="display:block;width:{_fmt(yt.width * k)}px;'
        f'max-width:none;margin-left:{_fmt(-sx0 * k)}px;margin-top:{_fmt(-sy0 * k)}px"></div>'
    )
    return (
        '<section style="background:#0d1117;color:#ffffff">\n<h2>Banners</h2>\n'
        '<label><input type="checkbox" checked '
        "onchange=\"document.body.classList.toggle('guides',this.checked)\"> "
        "Show guides (YouTube safe zone, X profile picture)</label>\n"
        f'<h3>YouTube {yt.width} x {yt.height}</h3>\n'
        f'<div class="banner"><img src="{yt.name}">{safe}</div>\n'
        "<h3>YouTube on mobile (safe zone at 400 px)</h3>\n" + mobile + "\n"
        f'<h3>X {x.width} x {x.height}</h3>\n'
        f'<div class="banner"><img src="{x.name}">{avatar}</div>\n'
        "</section>\n"
    )


def build(src: Path, out: Path, resvg: Path) -> list[Path]:
    emblem = (src / "emblem.svg").read_text(encoding="utf-8")
    small = (src / "emblem-small.svg").read_text(encoding="utf-8")
    out.mkdir(parents=True, exist_ok=True)
    (out / "favicon").mkdir(exist_ok=True)
    written: list[Path] = []

    def png(svg: str, rel: str, size: int) -> None:
        path = out / rel
        render(svg, path, size, resvg)
        written.append(path)

    plugin_files = []
    for plugin in PLUGINS:
        glyph = (src / "glyphs" / f"{plugin}.svg").read_text(encoding="utf-8")
        name = f"plugin-{plugin}.png"
        png(compose_plugin_icon(emblem, glyph), name, 1024)
        plugin_files.append(name)
    png(compose_bleed(emblem), "avatar-github.png", 1024)
    png(compose_bleed(emblem, scale=youtube_scale(emblem)), "avatar-youtube.png", 800)

    favicon_svg = compose_bleed(small)
    svg_path = out / "favicon" / "favicon.svg"
    svg_path.write_text(favicon_svg, encoding="utf-8", newline="\n")
    written.append(svg_path)
    png(favicon_svg, "favicon/favicon-32.png", 32)
    png(favicon_svg, "favicon/apple-touch-icon.png", 180)
    png(favicon_svg, "favicon/favicon-512.png", 512)

    text = load_banner_text(src / "banner-text.json")

    def measure(svg: str) -> dict[str, Box]:
        return query_boxes(svg, resvg, FONT_FILE)

    for spec in BANNERS:
        svg, _, _ = fit_banner(spec, text, emblem, measure)
        path = out / spec.name
        render(svg, path, spec.width, resvg, height=spec.height, font_file=FONT_FILE)
        written.append(path)

    preview = out / "preview.html"
    preview.write_text(_preview(plugin_files), encoding="utf-8", newline="\n")
    written.append(preview)
    return written


def main(argv: list[str] | None = None) -> int:
    del argv  # no options yet
    try:
        resvg = find_resvg()
    except ResvgError as exc:
        print(exc)
        return 2
    here = Path(__file__).resolve().parent
    try:
        files = build(here / "src", here / "out", resvg)
    except (ResvgError, BannerError) as exc:
        print(exc)
        return 2
    print(f"built {len(files)} files in {here / 'out'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
