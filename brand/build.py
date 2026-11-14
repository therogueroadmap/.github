"""Compose brand SVGs per destination and rasterize them with resvg."""
from __future__ import annotations

import copy
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping

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
)

SVG_NS = "http://www.w3.org/2000/svg"
CANVAS = 1024
ET.register_namespace("", SVG_NS)


class ResvgError(RuntimeError):
    pass


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


def render(svg: str, out: Path, size: int, resvg: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.svg"
        src.write_text(svg, encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(resvg), "-w", str(size), "-h", str(size), str(src), str(out)],
                capture_output=True,
                text=True,
                timeout=RESVG_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise ResvgError(
                f"resvg timed out after {RESVG_TIMEOUT}s rendering {out.name}"
                f" (stderr: {(exc.stderr or '').strip() if isinstance(exc.stderr, str) else ''})"
            ) from exc
    if proc.returncode != 0:
        raise ResvgError(f"resvg failed for {out.name}: {proc.stderr.strip()}")


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


def youtube_scale(emblem_svg: str) -> float:
    root = ET.fromstring(emblem_svg)
    pts = _element_points(_by_id(root, "sun")) + _element_points(_by_id(root, "figure"))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    half = CANVAS / 2
    far = max(
        math.hypot(x - half, y - half)
        for x in (min(xs), max(xs)) for y in (min(ys), max(ys))
    )
    limit = half * (1 - YOUTUBE_CIRCLE_MARGIN)
    return min(1.0, limit / far) if far > 0 else 1.0


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
        "</style>\n</head><body>\n"
        + section("#ffffff", "#000000", "Light background")
        + section("#0d1117", "#ffffff", "Dark background")
        + "</body></html>\n"
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
    except ResvgError as exc:
        print(exc)
        return 2
    print(f"built {len(files)} files in {here / 'out'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
