"""Render the 3-minute Darubini demo video, with and without narration.

Motion graphics in the Darubini Proposal palette, cut on the music's bar grid. The
craft rules follow the /brag skill (latent-spaces/brag): show the real product,
readable holds, staggered transitions instead of muddy crossfades, a soft
sound-effect layer under the music, and a settled poster as frame 0.

Every figure and image is real project output: the app's screens, a development
field's detections, the SAM 3.1 tracking clip, the verifier's real architecture and
training data, a held-out slide's Kiswahili report and the frozen test numbers. The
roadmap scene is labelled as such on screen.

Audio: "Happy Beats / Business Moves Vol. 1" by Sascha Ende (ende.app, CC BY 4.0);
sound effects by Kenney and unicae_games (CC0), both bundled with /brag; narration
by Kokoro (scripts/narrate.py). See docs/demo/README.md.

    python scripts/demo_video.py --prepare        # field image, detections, report
    python scripts/demo_video.py --still 40 95    # check frames
    python scripts/demo_video.py --script         # write docs/demo/SCRIPT.md
    python scripts/demo_video.py --audio          # both mixes as WAV
    python scripts/demo_video.py                  # both videos
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "datasets" / "processed" / "demo"
AUDIO = ASSETS / "audio"
VOICE = ASSETS / "voice"
FONT = ROOT / "android" / "app" / "src" / "main" / "res" / "font" / "plus_jakarta_sans.ttf"
SHOTS = ROOT / "docs" / "calibration"
TRACK = ROOT / "docs" / "demo" / "tracking_demo.mp4"
NARRATION = ROOT / "docs" / "demo" / "narration.json"
W, H, FPS = 1920, 1080, 30
SR = 48_000

# Darubini Proposal palette (docs/proposal/index.html), light and dark.
BG = (252, 252, 253)
SURFACE = (243, 244, 247)
CARD = (255, 255, 255)
INK = (15, 23, 41)
MUTED = (93, 103, 121)
BORDER = (222, 225, 231)
PRIMARY = (36, 99, 235)
PRIMARY_INK = (24, 66, 180)
PRIMARY_SOFT = (236, 241, 254)
CHART_2 = (96, 168, 251)
CHART_3 = (59, 134, 247)
CHART_4 = (144, 199, 254)
STAIN = (104, 59, 155)
PLASMA = (244, 225, 232)
GOOD = (37, 147, 95)
WARN = (213, 119, 11)
WARN_SOFT = (253, 243, 226)
DANGER = (220, 38, 38)
D_BG = (12, 15, 24)
D_CARD = (18, 22, 33)
D_FG = (235, 239, 245)
D_MUTED = (155, 165, 181)
D_PRIMARY = (70, 138, 246)
D_INK = (136, 188, 251)
D_STAIN = (181, 141, 226)
# Markers on the stained field: bright enough to read on purple.
PARASITE = (219, 39, 119)
WBC = (59, 134, 247)
WHITE = (255, 255, 255)


# ---------------------------------------------------------------- easing


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def prog(t: float, start: float, dur: float) -> float:
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def in_out(x: float) -> float:
    return 4 * x**3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def out_back(x: float, s: float = 1.6) -> float:
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


# ---------------------------------------------------------------- cached layers


@lru_cache(maxsize=64)
def font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_axes([weight])
    return f


@lru_cache(maxsize=4096)
def text_layer(text: str, size: int, weight: int, color: tuple[int, ...]) -> Image.Image:
    f = font(size, weight)
    _, _, x1, _ = f.getbbox(text)
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (max(1, x1 + 4), asc + desc + 4), (*color[:3], 0))
    ImageDraw.Draw(im).text((0, 0), text, font=f, fill=(*color[:3], 255))
    return im


@lru_cache(maxsize=512)
def rrect(
    w: int,
    h: int,
    r: int,
    fill: tuple[int, ...],
    outline: tuple[int, ...] | None = None,
    width: int = 0,
) -> Image.Image:
    k = 3
    big = Image.new("RGBA", (w * k, h * k), (*fill[:3], 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, w * k - 1, h * k - 1),
        r * k,
        fill=(*fill[:3], 255),
        outline=(*outline, 255) if outline else None,
        width=width * k,
    )
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=256)
def shadow(w: int, h: int, r: int, blur: int = 28, alpha: int = 30) -> Image.Image:
    pad = blur * 3
    # Colour everywhere, alpha only where the shape is, so blurring cannot darken the edges.
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (15, 23, 41, 0))
    ImageDraw.Draw(im).rounded_rectangle((pad, pad, pad + w, pad + h), r, fill=(15, 23, 41, alpha))
    return im.filter(ImageFilter.GaussianBlur(blur))


@lru_cache(maxsize=64)
def disc(
    d: int, fill: tuple[int, ...] | None, outline: tuple[int, ...] | None = None, width: int = 0
) -> Image.Image:
    k = 3
    base = fill or outline or (0, 0, 0)
    big = Image.new("RGBA", (d * k, d * k), (*base[:3], 0))
    ImageDraw.Draw(big).ellipse(
        (0, 0, d * k - 1, d * k - 1),
        fill=(*fill, 255) if fill else None,
        outline=(*outline, 255) if outline else None,
        width=width * k,
    )
    return big.resize((d, d), Image.LANCZOS)


@lru_cache(maxsize=8)
def blob(d: int, color: tuple[int, int, int], alpha: int) -> Image.Image:
    im = Image.new("RGBA", (d, d), (*color, 0))
    ImageDraw.Draw(im).ellipse((d * 0.3, d * 0.3, d * 0.7, d * 0.7), fill=(*color, alpha))
    return im.filter(ImageFilter.GaussianBlur(d // 12))


@lru_cache(maxsize=16)
def image(path: str, w: int, h: int, r: int = 0, zoom: float = 1.0) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    if zoom != 1.0:
        cw, ch = im.width / zoom, im.height / zoom
        im = im.crop(
            ((im.width - cw) / 2, (im.height - ch) / 2, (im.width + cw) / 2, (im.height + ch) / 2)
        )
    sw, sh = im.size
    s = max(w / sw, h / sh)
    im = im.resize((round(sw * s), round(sh * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    im = im.crop((x, y, x + w, y + h))
    if r:
        mask = rrect(w, h, r, WHITE).split()[3]
        im.putalpha(Image.fromarray(np.minimum(np.asarray(im.split()[3]), np.asarray(mask))))
    return im


@lru_cache(maxsize=8)
def phone(shot: str, h: int) -> Image.Image:
    """A phone frame around an app screenshot, ``h`` pixels tall."""
    sh = Image.open(SHOTS / shot)
    w = round(h * sh.width / sh.height)
    bezel = 14
    frame = rrect(w + 2 * bezel, h + 2 * bezel, 58, INK).copy()
    frame.alpha_composite(image(str(SHOTS / shot), w, h, 46), (bezel, bezel))
    return frame


@lru_cache(maxsize=4)
def lock(d: int, open_: bool, color: tuple[int, int, int]) -> Image.Image:
    """A padlock, drawn."""
    k = 3
    s = d * k
    im = Image.new("RGBA", (s, s), (*color, 0))
    dr = ImageDraw.Draw(im)
    lift = s * 0.16 if open_ else 0
    dr.arc(
        (s * 0.26, s * 0.06 - lift, s * 0.74, s * 0.56 - lift),
        180,
        0 if not open_ else 330,
        fill=(*color, 255),
        width=int(s * 0.09),
    )
    if not open_:
        dr.line(
            [(s * 0.26 + s * 0.045, s * 0.31), (s * 0.26 + s * 0.045, s * 0.46)],
            fill=(*color, 255),
            width=int(s * 0.09),
        )
    dr.line(
        [(s * 0.74 - s * 0.045, s * 0.31 - lift), (s * 0.74 - s * 0.045, s * 0.46)],
        fill=(*color, 255),
        width=int(s * 0.09),
    )
    dr.rounded_rectangle((s * 0.16, s * 0.44, s * 0.84, s * 0.94), s * 0.08, fill=(*color, 255))
    return im.resize((d, d), Image.LANCZOS)


# ---------------------------------------------------------------- compositing


def put(
    c: Image.Image,
    layer: Image.Image,
    x: float,
    y: float,
    alpha: float = 1.0,
    scale: float = 1.0,
    anchor: str = "tl",
) -> None:
    if alpha <= 0.003 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.002:
        layer = layer.resize(
            (max(1, round(layer.width * scale)), max(1, round(layer.height * scale))),
            Image.BILINEAR,
        )
    if anchor == "c":
        x, y = x - layer.width / 2, y - layer.height / 2
    elif anchor == "tc":
        x = x - layer.width / 2
    elif anchor == "tr":
        x = x - layer.width
    if alpha < 0.997:
        a = np.asarray(layer.split()[3], dtype=np.float32) * alpha
        layer = layer.copy()
        layer.putalpha(Image.fromarray(a.astype(np.uint8)))
    x, y = round(x), round(y)
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(layer.width, W - x), min(layer.height, H - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    if (sx0, sy0, sx1, sy1) != (0, 0, layer.width, layer.height):
        layer = layer.crop((sx0, sy0, sx1, sy1))
    c.alpha_composite(layer, (x + sx0, y + sy0))


def card(
    c: Image.Image,
    x: float,
    y: float,
    w: int,
    h: int,
    r: int = 22,
    fill: tuple[int, ...] = CARD,
    alpha: float = 1.0,
    scale: float = 1.0,
    border: bool = True,
    lift: bool = True,
) -> None:
    """A proposal-style card: soft shadow, white fill, hairline border. Scales about its centre."""
    cx, cy = x + w / 2, y + h / 2
    if lift:
        put(c, shadow(w, h, r), cx, cy + 10 * scale, alpha * 0.9, scale, "c")
    put(
        c,
        rrect(w, h, r, fill, BORDER if border else None, 1 if border else 0),
        cx,
        cy,
        alpha,
        scale,
        "c",
    )


def text(
    c: Image.Image,
    s: str,
    x: float,
    y: float,
    size: int,
    weight: int = 400,
    color: tuple[int, ...] = INK,
    alpha: float = 1.0,
    anchor: str = "tl",
    scale: float = 1.0,
) -> None:
    put(c, text_layer(s, size, weight, color), x, y, alpha, scale, anchor)


def text_width(s: str, size: int, weight: int = 400) -> int:
    return text_layer(s, size, weight, INK).width - 4


def para(
    c: Image.Image,
    s: str,
    x: float,
    y: float,
    size: int,
    weight: int,
    color: tuple[int, ...],
    max_w: int,
    alpha: float = 1.0,
    line_h: float = 1.4,
) -> None:
    """Left-aligned text wrapped to ``max_w`` pixels."""
    line = ""
    for word in s.split(" "):
        trial = f"{line} {word}".strip()
        if line and text_width(trial, size, weight) > max_w:
            text(c, line, x, y, size, weight, color, alpha)
            y += size * line_h
            line = word
        else:
            line = trial
    if line:
        text(c, line, x, y, size, weight, color, alpha)


def words(
    c: Image.Image,
    s: str,
    x: float,
    y: float,
    size: int,
    weight: int,
    color: tuple[int, ...],
    t: float,
    start: float,
    stagger: float = 0.07,
    dur: float = 0.55,
    center: bool = False,
    alpha: float = 1.0,
) -> None:
    """Kinetic type: each word rises and fades in, one after another."""
    parts = s.split(" ")
    space = size * 0.28
    widths = [text_width(p, size, weight) for p in parts]
    total = sum(widths) + space * (len(parts) - 1)
    cx = x - total / 2 if center else x
    for i, (p, w) in enumerate(zip(parts, widths, strict=True)):
        k = out_cubic(prog(t, start + i * stagger, dur))
        text(c, p, cx, y + (1 - k) * size * 0.6, size, weight, color, alpha * k)
        cx += w + space


def pill(
    c: Image.Image,
    s: str,
    x: float,
    y: float,
    fg: tuple[int, ...],
    bg: tuple[int, ...],
    size: int = 24,
    alpha: float = 1.0,
    scale: float = 1.0,
    anchor: str = "tl",
    dot: tuple[int, ...] | None = None,
) -> float:
    tw = text_width(s, size, 600)
    pad = size * 0.8
    extra = size * 0.9 if dot else 0
    w, h = int(tw + 2 * pad + extra), int(size * 2)
    if anchor == "c":
        x -= w / 2
    elif anchor == "tr":
        x -= w
    put(c, rrect(w, h, h // 2, bg), x + w / 2, y + h / 2, alpha, scale, "c")
    if scale > 0.98:
        if dot:
            put(c, disc(int(size * 0.5), dot), x + pad + size * 0.25, y + h / 2, alpha, 1, "c")
        text(c, s, x + pad + extra, y + h / 2 - size * 0.62, size, 600, fg, alpha)
    return w


def check(
    c: Image.Image,
    x: float,
    y: float,
    d: int,
    ok: bool = True,
    alpha: float = 1.0,
    scale: float = 1.0,
) -> None:
    """A filled status disc with a tick or a cross, drawn rather than taken from the font."""
    k = 3
    dd = d * k
    col = GOOD if ok else DANGER
    im = Image.new("RGBA", (dd, dd), (*col, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse((0, 0, dd - 1, dd - 1), fill=(*col, 255))
    lw = max(3, dd // 11)
    if ok:
        dr.line(
            [(dd * 0.28, dd * 0.52), (dd * 0.44, dd * 0.68), (dd * 0.73, dd * 0.35)],
            fill=(*WHITE, 255),
            width=lw,
            joint="curve",
        )
    else:
        dr.line([(dd * 0.32, dd * 0.32), (dd * 0.68, dd * 0.68)], fill=(*WHITE, 255), width=lw)
        dr.line([(dd * 0.68, dd * 0.32), (dd * 0.32, dd * 0.68)], fill=(*WHITE, 255), width=lw)
    put(c, im.resize((d, d), Image.LANCZOS), x, y, alpha, scale, "c")


def eyebrow(
    c: Image.Image,
    s: str,
    x: float,
    y: float,
    t: float,
    start: float,
    color: tuple[int, ...] = PRIMARY,
    center: bool = False,
    alpha: float = 1.0,
) -> None:
    words(c, s, x, y, 24, 700, color, t, start, stagger=0.04, center=center, alpha=alpha)


def background(c: Image.Image, t: float, mode: str = "light") -> None:
    base = {"light": BG, "dark": D_BG, "brand": PRIMARY}[mode]
    c.paste(Image.new("RGBA", (W, H), (*base, 255)))
    if mode == "light":
        g1, g2, a1, a2 = CHART_4, PLASMA, 70, 170
    elif mode == "dark":
        g1, g2, a1, a2 = D_PRIMARY, D_STAIN, 60, 34
    else:
        g1, g2, a1, a2 = CHART_2, PRIMARY_INK, 90, 120
    put(
        c,
        blob(1100, g1, a1),
        1500 + 120 * math.sin(t * 0.35),
        180 + 80 * math.cos(t * 0.3),
        1,
        1,
        "c",
    )
    put(
        c,
        blob(1200, g2, a2),
        300 + 140 * math.cos(t * 0.27),
        950 + 70 * math.sin(t * 0.33),
        1,
        1,
        "c",
    )


# ---------------------------------------------------------------- data

DATA: dict = {}


def load_data() -> dict:
    return {
        "field": json.loads((ASSETS / "field.json").read_text()),
        "report": json.loads((ASSETS / "report.json").read_text(encoding="utf-8")),
    }


@lru_cache(maxsize=1)
def tracking_frames() -> list[Image.Image]:
    from darubini.video import decode

    frames = decode(TRACK.read_bytes(), max_frames=400)
    return [Image.fromarray(f).convert("RGBA").resize((960, 540), Image.LANCZOS) for f in frames]


@lru_cache(maxsize=1)
def candidate_crop() -> Image.Image:
    """The verifier's real input size: a 16 x 16 crop around a detected parasite, shown pixelated."""
    b = DATA["field"]["parasites"][0]
    im = Image.open(ASSETS / "field.jpg").convert("RGB")
    s = 3024 / 1000  # field.jpg is the 3,024 px square scaled to 1,000 px
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    half = 8 / s
    crop = im.crop((cx - half, cy - half, cx + half, cy + half)).resize((16, 16), Image.LANCZOS)
    return crop.resize((176, 176), Image.NEAREST).convert("RGBA")


# ---------------------------------------------------------------- scenes


def s_cold(c: Image.Image, t: float) -> None:
    """Cold open: a real field, the act of counting by eye."""
    background(c, t, "dark")
    k = out_cubic(prog(t, 0.2, 1.4))
    z = 1.1 + 0.12 * (t / 17)
    put(c, shadow(560, 560, 280, 60, 120), 1480, 560, k, 1, "c")
    put(c, image(str(ASSETS / "field.jpg"), 560, 560, 280, 1.25), 1480, 560, k, z, "c")
    eyebrow(c, "MALARIA MICROSCOPY  ·  AFRICA", 160, 300, t, 0.4, D_INK)
    words(c, "Every malaria diagnosis", 160, 350, 68, 800, D_FG, t, 0.8)
    words(c, "starts with someone", 160, 436, 68, 800, D_FG, t, 1.4)
    words(c, "counting.", 160, 522, 68, 800, D_INK, t, 2.0)
    para(
        c,
        "Parasites against 200 white blood cells, by eye. Field after field. Slide after slide.",
        162,
        680,
        30,
        400,
        D_MUTED,
        820,
        out_cubic(prog(t, 5.6, 0.8)),
    )
    if t > 9.0:  # the tally a technician keeps
        kk = prog(t, 9.0, 0.7)
        card(
            c,
            160,
            790,
            560,
            150,
            22,
            fill=D_CARD,
            alpha=clamp(kk * 2),
            scale=out_back(kk),
            border=False,
        )
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3)
            g = clamp((t - 9.4) / 6.5)
            text(c, "Parasites", 196, 812, 22, 600, D_MUTED, a)
            text(c, f"{int(87 * g)}", 196, 846, 58, 800, (244, 114, 182), a)
            text(c, "White blood cells", 420, 812, 22, 600, D_MUTED, a)
            text(c, f"{int(143 * g)} / 200", 420, 846, 58, 800, D_INK, a)
    rng = np.random.default_rng(3)
    marks = rng.uniform(-210, 210, size=(87, 2))
    for i in range(int(87 * clamp((t - 9.4) / 6.5))):
        x, y = marks[i]
        if x * x + y * y < 210 * 210:
            put(c, disc(14, None, (244, 114, 182), 2), 1480 + x * z, 560 + y * z, 0.9, 1, "c")


PROBLEMS = [
    ("Slow", "Every parasite is counted by eye, field after field, until 200 white blood cells."),
    ("Tiring", "Accuracy falls with fatigue, and with every change in stain and smear thickness."),
    ("Inconsistent", "Two microscopists counting the same slide can reach different numbers."),
]


def s_issue(c: Image.Image, t: float) -> None:
    """The issue before Darubini."""
    background(c, t)
    out = out_cubic(prog(t, 7.8, 0.6))
    eyebrow(c, "THE PROBLEM, BEFORE DARUBINI", 160, 150, t, 0.2)
    words(c, "Counting by hand does not scale.", 160, 195, 64, 800, INK, t, 0.4, alpha=1 - out)
    for i, (head, body) in enumerate(PROBLEMS):
        kk = prog(t, 1.0 + i * 0.9, 0.7)
        if kk <= 0 or out >= 1:
            continue
        x, y = 160 + i * 540, 380 - out * 60
        card(c, x, y, 500, 380, 26, alpha=clamp(kk * 2) * (1 - out), scale=out_back(kk))
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3) * (1 - out)
            put(c, disc(64, PRIMARY_SOFT), x + 72, y + 80, a, 1, "c")
            text(c, str(i + 1), x + 72, y + 58, 32, 800, PRIMARY, a, "tc")
            text(c, head, x + 40, y + 150, 46, 800, INK, a)
            para(c, body, x + 42, y + 220, 25, 400, MUTED, 420, a)
    if t > 8.2:
        tt = t - 8.2
        words(c, "The burden is African.", 160, 195, 64, 800, INK, tt, 0.1)
        stats = [
            ("282M", "malaria cases in 2024"),
            ("610K", "malaria deaths in 2024"),
            ("#4", "Tanzania's rank in deaths"),
        ]
        for i, (big, small) in enumerate(stats):
            kk = prog(tt, 0.5 + i * 0.35, 0.7)
            if kk <= 0:
                continue
            x = 160 + i * 540
            card(
                c,
                x,
                380,
                500,
                300,
                26,
                fill=D_BG,
                alpha=clamp(kk * 2),
                scale=out_back(kk),
                border=False,
            )
            if kk > 0.6:
                a = clamp((kk - 0.6) * 3)
                text(c, big, x + 44, 420, 110, 800, D_INK, a)
                text(c, small, x + 46, 590, 28, 500, D_MUTED, a)
        text(
            c,
            "Source: WHO World Malaria Report 2025",
            160,
            730,
            22,
            400,
            MUTED,
            out_cubic(prog(tt, 2.0, 0.5)),
        )
        para(
            c,
            "Labs have microscopes. What they lack is time, and a second pair of eyes.",
            160,
            800,
            34,
            700,
            PRIMARY_INK,
            1500,
            out_cubic(prog(tt, 4.4, 0.7)),
        )


MUSE = [
    ("SAM 3.1", "Segments white blood cells and tracks every cell through video", CHART_4),
    ("Muse Spark", "Runs the count as an agent, audits itself, writes Kiswahili", WHITE),
    ("Muse Voice", "Transcribes spoken commands, so hands stay on the microscope", CHART_4),
]


def s_reveal(c: Image.Image, t: float) -> None:
    background(c, t, "brand")
    up = out_cubic(prog(t, 4.2, 0.8))
    k = out_back(prog(t, 0.1, 0.8))
    cy = 330 - up * 170
    put(c, disc(150, PRIMARY_SOFT), W / 2, cy, clamp(k), k, "c")
    put(c, disc(100, PRIMARY), W / 2, cy, clamp(k), k, "c")
    put(c, disc(42, CHART_4), W / 2, cy, clamp(k), k, "c")
    name = "Darubini"
    size = int(140 - 40 * up)
    x = W / 2 - text_width(name, size, 800) / 2
    for i, ch in enumerate(name):
        kk = out_cubic(prog(t, 0.5 + i * 0.05, 0.5))
        text(c, ch, x, 450 - up * 210 + (1 - kk) * 50, size, 800, WHITE, kk)
        x += text_width(ch, size, 800) + 1
    words(
        c,
        "A malaria counting copilot, built on Meta's models.",
        W / 2,
        640 - up * 250,
        36,
        500,
        PRIMARY_SOFT,
        t,
        1.4,
        center=True,
        stagger=0.04,
    )
    for i, (head, body, colour) in enumerate(MUSE):
        kk = prog(t, 4.6 + i * 0.35, 0.7)
        if kk <= 0:
            continue
        x = 200 + i * 520
        card(
            c,
            x,
            520,
            480,
            300,
            26,
            fill=PRIMARY_INK,
            alpha=clamp(kk * 2),
            scale=out_back(kk),
            border=False,
        )
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3)
            text(c, head, x + 40, 560, 44, 800, colour, a)
            para(c, body, x + 42, 632, 26, 500, PRIMARY_SOFT, 400, a)


APP_SHOTS = [("android_capture.png", 0.0), ("android_voice.png", 6.0), ("android_report.png", 12.0)]


def s_app(c: Image.Image, t: float) -> None:
    background(c, t)
    k = out_cubic(prog(t, 0, 0.9))
    px, py = 470, 560 + (1 - k) * 500
    put(c, shadow(420, 900, 60, 46, 60), px, py + 24, k, 1, "c")
    for i, (shot, start) in enumerate(APP_SHOTS):
        nxt = APP_SHOTS[i + 1][1] if i + 1 < len(APP_SHOTS) else 99
        a = (1 if i == 0 else out_cubic(prog(t, start, 0.45))) * (1 - out_cubic(prog(t, nxt, 0.45)))
        if a > 0:
            put(c, phone(shot, 880), px, py, a * k, 1, "c")
    chips = [
        ("Photograph or pan", 0.8, 6.0, 250),
        ("Muse Voice Transcribe", 6.4, 12.0, 560),
        ("Muse Spark audit", 12.4, 99, 380),
    ]
    for s, start, end, y in chips:
        kk = prog(t, start, 0.6) * (1 - out_cubic(prog(t, end, 0.4)))
        if kk > 0:
            pill(c, s, 640, y, WHITE, PRIMARY, 24, clamp(kk * 2), out_back(min(1, kk)), dot=CHART_4)
    if 6.8 < t < 12.0:  # level meter while listening
        for i in range(9):
            hgt = 14 + 40 * abs(math.sin(t * 7 + i * 0.9)) * (0.5 + 0.5 * math.sin(i))
            put(
                c,
                rrect(10, int(hgt), 5, PRIMARY),
                680 + i * 18,
                660,
                out_cubic(prog(t, 6.8, 0.4)),
                1,
                "c",
            )
    items = [
        (
            "1",
            "Capture",
            "Phone on the eyepiece: photograph a field, or record a pan. Blurry fields are rejected.",
            0.6,
        ),
        (
            "2",
            "Speak",
            "“Next field”, “retake”, “finish”, “note…”. Hands stay on the microscope.",
            6.4,
        ),
        (
            "3",
            "Check",
            "Muse Spark audits its own count and flags doubtful slides for review.",
            12.4,
        ),
    ]
    for n, head, body, start in items:
        kk = out_cubic(prog(t, start, 0.6))
        y = 290 + (int(n) - 1) * 210
        active = start <= t < start + 5.8 or (n == "3" and t >= start)
        put(c, disc(64, PRIMARY if active else PRIMARY_SOFT), 1150, y + 34, kk, 1, "c")
        text(c, n, 1150, y + 12, 32, 800, WHITE if active else PRIMARY, kk, "tc")
        text(c, head, 1210, y, 44, 800, INK if active else MUTED, kk)
        para(c, body, 1212, y + 62, 26, 400, MUTED, 600, kk * (1 if active else 0.7))


def s_detect(c: Image.Image, t: float) -> None:
    background(c, t)
    f = DATA["field"]
    k = out_cubic(prog(t, 0, 0.8))
    size = 760
    fx, fy = 140, 160 + (1 - k) * 60
    s = size / 1000
    card(c, fx - 20, fy - 20, size + 40, size + 40, 30, alpha=k)
    put(c, image(str(ASSETS / "field.jpg"), size, size, 18), fx, fy, k)
    ov = Image.new("RGBA", (size, size), (*WHITE, 0))
    d = ImageDraw.Draw(ov)
    t1, t2, t3 = 1.2, 6.0, 9.6
    n_c = len(f["cands"])
    fade = out_cubic(prog(t, t2, 1.0))
    for i, b in enumerate(f["cands"]):
        appear = prog(t, t1 + 2.6 * i / n_c, 0.25)
        if appear <= 0 or fade >= 1:
            continue
        cx, cy = (b[0] + b[2]) / 2 * s, (b[1] + b[3]) / 2 * s
        r = 9 * out_back(appear)
        d.ellipse(
            (cx - r, cy - r, cx + r, cy + r), outline=(*WHITE, int(210 * (1 - fade))), width=2
        )
    for b in f["parasites"]:
        kk = out_back(prog(t, t2 + 0.3, 0.6))
        if kk <= 0:
            continue
        cx, cy = (b[0] + b[2]) / 2 * s, (b[1] + b[3]) / 2 * s
        r = max(10, (b[2] - b[0]) * s * 0.9) * kk
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*PARASITE, 255), width=3)
    for i, b in enumerate(f["wbcs"]):
        kk = out_cubic(prog(t, t3 + 0.08 * i, 0.4))
        if kk <= 0:
            continue
        x0, y0, x1, y1 = (v * s for v in b)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hw, hh = (x1 - x0) / 2 * (0.6 + 0.4 * kk), (y1 - y0) / 2 * (0.6 + 0.4 * kk)
        d.rounded_rectangle(
            (cx - hw, cy - hh, cx + hw, cy + hh), 6, outline=(*WBC, int(255 * kk)), width=3
        )
    put(c, ov, fx, fy, k)
    steps = [
        ("Candidates", "Every spot that takes up the stain", t1, n_c, MUTED),
        ("Verifier", "A small network keeps the real parasites", t2, len(f["parasites"]), PARASITE),
        ("SAM 3.1", "Finds white blood cells from one word: “cell”", t3, len(f["wbcs"]), WBC),
    ]
    words(c, "Two models, one count", 1040, 150, 54, 800, INK, t, 0.3)
    for i, (head, body, start, num, colour) in enumerate(steps):
        kk = out_cubic(prog(t, start, 0.6))
        y = 270 + i * 190
        nxt = steps[i + 1][2] if i + 1 < len(steps) else 99
        active = start <= t < nxt
        card(
            c,
            1040,
            y,
            740,
            160,
            22,
            fill=CARD if active else SURFACE,
            alpha=kk,
            scale=0.96 + 0.04 * kk,
        )
        put(c, rrect(8, 110, 4, colour), 1066, y + 80, kk if active else kk * 0.35, 1, "c")
        text(c, head, 1094, y + 28, 36, 800, INK, kk)
        text(c, body, 1095, y + 82, 24, 400, MUTED, kk)
        text(
            c,
            str(round(num * out_cubic(prog(t, start + 0.2, 1.2)))),
            1750,
            y + 36,
            64,
            800,
            colour if i else INK,
            kk,
            "tr",
        )
    if t > 13.6:
        kk = prog(t, 13.6, 0.7)
        pill(
            c,
            "Expert labels on this field: 35 parasites, 18 white blood cells",
            1040,
            870,
            PRIMARY_INK,
            PRIMARY_SOFT,
            24,
            clamp(kk * 2),
            out_back(kk),
            dot=GOOD,
        )


def s_track(c: Image.Image, t: float) -> None:
    background(c, t)
    frames = tracking_frames()
    k = out_cubic(prog(t, 0, 0.8))
    idx = min(len(frames) - 1, max(0, int((t - 0.6) * 15)))
    fx, fy = 120, 270 + (1 - k) * 60
    card(c, fx - 16, fy - 16, 992, 572, 28, alpha=k)
    vid = frames[idx].copy()
    vid.putalpha(rrect(960, 540, 16, WHITE).split()[3])
    put(c, vid, fx, fy, k)
    words(c, "Pan the slide.", 1180, 250, 60, 800, INK, t, 0.4)
    words(c, "Count each cell once.", 1180, 330, 60, 800, PRIMARY, t, 0.9)
    para(
        c,
        "SAM 3.1 video tracking follows every object through the clip.",
        1182,
        440,
        26,
        400,
        MUTED,
        620,
        out_cubic(prog(t, 1.6, 0.6)),
    )
    k1 = out_back(prog(t, 2.6, 0.6))
    card(c, 1180, 540, 290, 190, 22, alpha=clamp(k1), scale=k1)
    if k1 > 0.6:
        a = clamp((k1 - 0.6) * 3)
        text(c, "Frame by frame", 1206, 562, 22, 600, MUTED, a)
        text(c, "31", 1206, 600, 84, 800, MUTED, a)
        strike = out_cubic(prog(t, 5.0, 0.5))
        if strike > 0:
            put(c, rrect(max(2, int(110 * strike)), 6, 3, DANGER), 1206, 650, a, 1)
    k2 = out_back(prog(t, 4.4, 0.6))
    card(c, 1500, 540, 300, 190, 22, fill=PRIMARY, alpha=clamp(k2), scale=k2, border=False)
    if k2 > 0.6:
        a = clamp((k2 - 0.6) * 3)
        text(c, "Tracked, once each", 1526, 562, 22, 600, PRIMARY_SOFT, a)
        text(c, str(round(12 * out_cubic(prog(t, 4.6, 1.0)))), 1526, 600, 84, 800, WHITE, a)
    if t > 6.8:
        kk = prog(t, 6.8, 0.6)
        pill(
            c,
            "0 objects counted twice, checked against expert labels",
            1180,
            770,
            PRIMARY_INK,
            PRIMARY_SOFT,
            22,
            clamp(kk * 2),
            out_back(kk),
            dot=GOOD,
        )


PRACTICES = [
    "Split by patient and by photo, never by image",
    "Thresholds chosen on development data only",
    "Test protocol written down before any test image ran",
    "Test set scored once, with 95% intervals",
    "Every SAM reply cached: repeatable, about US$21 in all",
]
BEST = [
    ("0.81", "Parasite F1, verifier", "NIH validation patients"),
    ("0.95", "WBC F1, SAM 3.1 “cell”", "NIH tuning fields"),
    ("0.80", "Parasite F1, hybrid", "held-out test patients"),
]


def s_train(c: Image.Image, t: float) -> None:
    """How it was trained, the practices behind it, and the best results."""
    background(c, t)
    out = out_cubic(prog(t, 12.6, 0.6))
    eyebrow(c, "TRAINING  ·  BEST PRACTICE", 120, 110, t, 0.2, alpha=1 - out)
    words(c, "How it was trained", 120, 150, 56, 800, INK, t, 0.4, alpha=1 - out)
    # 1. Patients flow into train / validation / test, by patient.
    a1 = 1 - out
    buckets = [("Train", 102, PRIMARY, 120), ("Validate", 24, CHART_3, 420), ("Test", 24, INK, 620)]
    if a1 > 0:
        card(c, 100, 250, 820, 600, 26, alpha=a1 * out_cubic(prog(t, 0.6, 0.6)))
        text(
            c,
            "150 NIH patients, split by patient",
            140,
            280,
            28,
            800,
            INK,
            a1 * out_cubic(prog(t, 0.8, 0.5)),
        )
        rng = np.random.default_rng(5)
        order = rng.permutation(150)
        labels = np.array([0] * 102 + [1] * 24 + [2] * 24)[order]
        slots = [0, 0, 0]
        for j in range(150):
            g = labels[j]
            appear = prog(t, 1.0 + j * 0.022, 0.6)
            if appear <= 0:
                continue
            col = slots[g]
            slots[g] += 1
            bx = buckets[g][3]
            per_row = 12 if g == 0 else 6
            tx = bx + 40 + (col % per_row) * 22
            ty = 640 - (col // per_row) * 22
            sx, sy = 510 + 40 * math.sin(j), 350
            e = out_cubic(appear)
            put(
                c,
                disc(16, buckets[g][2]),
                sx + (tx - sx) * e,
                sy + (ty - sy) * e - 60 * math.sin(math.pi * e),
                a1,
                1,
                "c",
            )
        for name, n, colour, bx in buckets:
            kk = out_cubic(prog(t, 0.8, 0.6))
            w = 300 if name == "Train" else 170
            put(c, rrect(w, 4, 2, colour), bx + 20, 668, a1 * kk)
            text(c, name, bx + 20, 684, 26, 800, colour, a1 * kk)
            text(c, f"{n}", bx + 20, 720, 40, 800, INK, a1 * out_cubic(prog(t, 4.4, 0.5)))
        unlocked = t > 11.4
        put(
            c,
            lock(44, unlocked, GOOD if unlocked else INK),
            860,
            560,
            a1 * out_cubic(prog(t, 4.6, 0.5)),
            1,
            "c",
        )
        text(
            c,
            "Tanzania (UDOM): 431 photos train, 180 test, split by photo",
            140,
            790,
            22,
            500,
            MUTED,
            a1 * out_cubic(prog(t, 4.8, 0.6)),
        )
    # 2. The verifier network learns: a real 16 x 16 crop in, one probability out.
    if a1 > 0:
        kk = out_cubic(prog(t, 5.2, 0.7))
        card(c, 960, 250, 860, 600, 26, alpha=a1 * kk)
        text(c, "The verifier: a small network", 1000, 280, 28, 800, INK, a1 * kk)
        put(c, candidate_crop(), 1000, 380, a1 * kk)
        text(c, "16 × 16 crop", 1000, 568, 20, 600, MUTED, a1 * kk)
        text(c, "+ 8 shape features", 1000, 594, 20, 600, MUTED, a1 * kk)
        layers = [(1250, 12, "776 in"), (1460, 9, "64 hidden"), (1650, 1, "parasite?")]
        nodes = []
        for x, n, _ in layers:
            ys = [470] if n == 1 else list(np.linspace(340, 600, n))
            nodes.append([(x, y) for y in ys])
        epoch = clamp((t - 6.0) / 4.6)
        ov = Image.new("RGBA", (W, H), (*PRIMARY, 0))
        d = ImageDraw.Draw(ov)
        for li in range(2):
            for a_i, (x0, y0) in enumerate(nodes[li]):
                for b_i, (x1, y1) in enumerate(nodes[li + 1]):
                    pulse = 0.5 + 0.5 * math.sin(t * 6 - (a_i + b_i) * 0.7 - li * 1.5)
                    alpha = int(255 * a1 * kk * (0.12 + 0.5 * pulse * (epoch > 0)))
                    d.line([(x0, y0), (x1, y1)], fill=(*PRIMARY, alpha), width=2)
        put(c, ov, 0, 0)
        for li, (x, _n, label) in enumerate(layers):
            for x0, y0 in nodes[li]:
                put(
                    c,
                    disc(22 if li < 2 else 44, PRIMARY_SOFT if li == 0 else PRIMARY),
                    x0,
                    y0,
                    a1 * kk,
                    1,
                    "c",
                )
            text(c, label, x, 640, 20, 600, MUTED, a1 * kk, "tc")
        out_p = 0.5 + 0.47 * out_cubic(epoch)
        text(c, f"{out_p:.2f}", 1650, 500, 24, 800, PRIMARY, a1 * kk * clamp(epoch * 4), "tc")
        text(
            c,
            f"Epoch {max(1, int(40 * epoch))} / 40  ·  Adam",
            1000,
            690,
            24,
            700,
            INK,
            a1 * out_cubic(prog(t, 6.0, 0.4)),
        )
        f1 = 0.29 + (0.81 - 0.29) * out_cubic(epoch)
        put(c, rrect(780, 18, 9, SURFACE), 1000, 740, a1 * kk)
        put(c, rrect(max(18, int(780 * f1)), 18, 9, PRIMARY), 1000, 740, a1 * kk)
        text(c, f"F1 on validation  {f1:.2f}", 1000, 770, 22, 700, PRIMARY_INK, a1 * kk)
        if t > 10.8:
            kk2 = out_cubic(prog(t, 10.8, 0.8))
            text(
                c,
                f"threshold {0.5 + 0.25 * kk2:.2f}, chosen on held-out tuning patients",
                1300,
                770,
                20,
                500,
                MUTED,
                a1 * kk2,
            )
    # 3. Best practices and best performances.
    if t > 13.0:
        tt = t - 13.0
        eyebrow(c, "BEST PRACTICE  ·  BEST RESULTS", 120, 110, tt, 0.0)
        words(c, "Trained carefully, tested once", 120, 150, 56, 800, INK, tt, 0.1)
        k3 = out_cubic(prog(tt, 0.2, 0.6))
        card(c, 100, 260, 900, 600, 26, alpha=k3)
        for i, s in enumerate(PRACTICES):
            kk = out_cubic(prog(tt, 0.5 + i * 0.45, 0.5))
            check(c, 160, 330 + i * 106, 40, True, kk, out_back(kk))
            para(c, s, 200, 313 + i * 106, 27, 600, INK, 760, kk, 1.25)
        for i, (big, head, sub) in enumerate(BEST):
            kk = prog(tt, 1.0 + i * 0.6, 0.7)
            if kk <= 0:
                continue
            y = 260 + i * 205
            hero = i == 2
            card(
                c,
                1060,
                y,
                760,
                180,
                24,
                fill=PRIMARY if hero else CARD,
                alpha=clamp(kk * 2),
                scale=out_back(kk),
                border=not hero,
            )
            if kk > 0.6:
                a = clamp((kk - 0.6) * 3)
                text(c, big, 1100, y + 34, 88, 800, WHITE if hero else PRIMARY, a)
                text(c, head, 1370, y + 52, 28, 800, WHITE if hero else INK, a)
                text(c, sub, 1370, y + 96, 22, 400, PRIMARY_SOFT if hero else MUTED, a)


AGENT_STEPS = [
    ("examine_next_fields", "Examined the captured fields"),
    ("review_field", "Second opinion on image quality"),
    ("audit_parasites", "Audited 20 sampled parasites"),
    ("get_count", "Applied the WHO counting rule"),
    ("finish", "Wrote the report in Kiswahili"),
]


def s_agent(c: Image.Image, t: float) -> None:
    background(c, t)
    k = out_cubic(prog(t, 0, 0.8))
    card(c, 110, 150 + (1 - k) * 60, 760, 760, 28, alpha=k)
    put(c, disc(56, PRIMARY_SOFT), 170, 222, k, 1, "c")
    put(c, disc(22, PRIMARY), 170, 222, k, 1, "c")
    text(c, "Muse Spark agent", 214, 196, 36, 800, INK, k)
    text(c, "Runs the slide through deterministic tools", 216, 244, 22, 400, MUTED, k)
    for i, (tool, label) in enumerate(AGENT_STEPS):
        start = 1.2 + i * 1.5
        kk = out_cubic(prog(t, start, 0.5))
        y = 320 + i * 112
        done = t > start + 1.1
        if i < len(AGENT_STEPS) - 1:
            put(
                c,
                rrect(3, int(112 * out_cubic(prog(t, start + 0.5, 0.7))) + 1, 1, PRIMARY_SOFT),
                168,
                y + 22,
                kk,
                1,
                "tc",
            )
        if done:
            check(c, 170, y + 20, 40, True, kk, out_back(prog(t, start + 1.1, 0.4)))
        else:
            spin = (t * 4) % (2 * math.pi)
            put(c, disc(40, WHITE, PRIMARY_SOFT, 4), 170, y + 20, kk, 1, "c")
            put(
                c,
                disc(10, PRIMARY),
                170 + 13 * math.cos(spin),
                y + 20 + 13 * math.sin(spin),
                kk,
                1,
                "c",
            )
        text(c, label, 214, y, 30, 700, INK, kk)
        text(c, tool, 216, y + 42, 20, 500, MUTED, kk)
    rep = DATA["report"]["sw"].split("\n")[:5]
    k2 = out_cubic(prog(t, 2.6, 0.8))
    card(c, 950, 150 + (1 - k2) * 60, 860, 560, 28, alpha=k2)
    text(c, "Ripoti", 990, 190, 40, 800, INK, k2)
    pill(c, "Kiswahili", 1770, 192, PRIMARY_INK, PRIMARY_SOFT, 20, k2, 1, "tr")
    chars = int(max(0, t - 3.4) * 45)
    y = 270
    for line in rep:
        if not line:
            continue
        shown = line[: max(0, chars)]
        chars -= len(line)
        if shown:
            key, _, val = shown.partition(": ")
            text(c, key + (":" if val or shown.endswith(":") else ""), 990, y, 26, 400, MUTED, k2)
            if val:
                text(c, val, 1770, y - 4, 30, 800, INK, k2, "tr")
        put(c, rrect(780, 1, 0, BORDER), 990, y + 52, k2 * 0.9)
        y += 76
    if t > 10.8:
        kk = prog(t, 10.8, 0.7)
        card(
            c,
            950,
            760,
            860,
            150,
            24,
            fill=PRIMARY,
            alpha=clamp(kk * 2),
            scale=out_back(kk),
            border=False,
        )
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3)
            text(c, "Held-out test slide TF65", 990, 784, 22, 600, PRIMARY_SOFT, a)
            text(c, "Darubini 16,383 /µL  ·  expert 16,142 /µL", 990, 822, 40, 800, WHITE, a)


METRICS = [
    ("0.80", "Parasite F1", "NIH held-out patients"),
    ("19/24", "Slides within 2×", "of the expert's density"),
    ("0.93", "Correlation", "with expert density (log)"),
    ("8/8", "Over-counts caught", "by the Muse Spark audit"),
]
META_GAINS = [
    ("SAM 3.1", "White blood cells found (F1)", "0.50", "0.90"),
    ("SAM 3.1", "Slides within 2× of the expert's density", "13/24", "19/24"),
    ("Muse Spark", "Over-counted slides caught by the audit", "–", "8/8"),
    ("SAM 3.1 video", "Parasites on a panned clip, each counted once", "31", "12"),
]
BARS = [
    ("Stain threshold (baseline)", 0.30, MUTED),
    ("SAM 3.1 text prompt alone", 0.64, CHART_4),
    ("Candidates + verifier (offline)", 0.76, CHART_3),
    ("Hybrid: SAM 3.1 + verifier", 0.80, PRIMARY),
]


def s_results(c: Image.Image, t: float) -> None:
    background(c, t)
    out = out_cubic(prog(t, 10.6, 0.6))
    eyebrow(c, "TEST SET  ·  SCORED ONCE", 140, 130, t, 0.2, alpha=1 - out)
    words(c, "Tested on patients it never saw.", 140, 175, 64, 800, INK, t, 0.4, alpha=1 - out)
    for i, (big, head, sub) in enumerate(METRICS):
        kk = prog(t, 1.4 + i * 2.4, 0.7)
        if kk <= 0 or out >= 1:
            continue
        x, y = 140 + i * 420, 380 - out * 80
        hero = i == 1
        card(
            c,
            x,
            y,
            380,
            360,
            28,
            fill=PRIMARY if hero else CARD,
            alpha=clamp(kk * 2) * (1 - out),
            scale=out_back(kk),
            border=not hero,
        )
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3) * (1 - out)
            text(c, big, x + 34, y + 50, 96, 800, WHITE if hero else PRIMARY, a)
            text(c, head, x + 36, y + 200, 32, 800, WHITE if hero else INK, a)
            text(c, sub, x + 36, y + 248, 24, 400, PRIMARY_SOFT if hero else MUTED, a)
    if t > 10.9:
        tt = t - 10.9
        eyebrow(c, "SAME TEST SET  ·  SAME PARASITE DETECTOR", 140, 130, tt, 0.0)
        words(c, "Where Meta's AI moves the number", 140, 175, 60, 800, INK, tt, 0.1)
        for i, (model, label, before, after) in enumerate(META_GAINS):
            kk = prog(tt, 0.6 + i * 0.45, 0.7)
            if kk <= 0:
                continue
            y = 290 + i * 132
            card(c, 140, y, 1640, 112, 22, alpha=clamp(kk * 2), scale=0.97 + 0.03 * out_back(kk))
            if kk > 0.5:
                a = clamp((kk - 0.5) * 2)
                pill(c, model, 172, y + 33, WHITE, PRIMARY, 20, a)
                text(c, label, 470, y + 34, 30, 700, INK, a)
                text(c, before, 1330, y + 24, 46, 800, MUTED, a, "tr")
                text(c, "→", 1400, y + 26, 42, 800, MUTED, a, "tc")
                g = out_cubic(prog(tt, 1.0 + i * 0.45, 0.6))
                text(c, after, 1740, y + 24, 46, 800, PRIMARY, a * g, "tr")
        if tt > 3.2:
            kk = prog(tt, 3.2, 0.6)
            pill(
                c,
                "Parasites themselves come from our own verifier network. SAM 3.1 alone scored parasite F1 0.64.",
                140,
                830,
                MUTED,
                SURFACE,
                22,
                clamp(kk * 2),
                out_back(kk),
            )


def s_honest(c: Image.Image, t: float) -> None:
    background(c, t)
    words(c, "What it is, and what it isn't", W / 2, 170, 64, 800, INK, t, 0.2, center=True)
    left = [
        "Estimates parasite density on a positive slide",
        "Flags doubtful counts for a microscopist",
        "Reports in English and Kiswahili",
    ]
    right = [
        "Not a screen: uninfected slides show false positives",
        "Not yet strong on Tanzanian smears (F1 0.48)",
        "Not a diagnosis, and never treatment advice",
    ]
    k = out_cubic(prog(t, 0.6, 0.7))
    card(c, 150, 330, 780, 520, 28, alpha=k, scale=0.97 + 0.03 * k)
    card(c, 990, 330, 780, 520, 28, fill=(254, 250, 250), alpha=k, scale=0.97 + 0.03 * k)
    text(c, "It is", 200, 370, 36, 800, GOOD, k)
    text(c, "It is not", 1040, 370, 36, 800, DANGER, k)
    for i, s in enumerate(left):
        kk = out_cubic(prog(t, 1.2 + i * 0.4, 0.5))
        check(c, 222, 480 + i * 120, 40, True, kk, out_back(kk))
        para(c, s, 262, 462 + i * 120, 27, 600, INK, 620, kk, 1.3)
    for i, s in enumerate(right):
        kk = out_cubic(prog(t, 2.6 + i * 0.4, 0.5))
        check(c, 1062, 480 + i * 120, 40, False, kk, out_back(kk))
        para(c, s, 1102, 462 + i * 120, 27, 600, INK, 620, kk, 1.3)


@lru_cache(maxsize=8)
def specimen(kind: str, w: int = 330, h: int = 190) -> Image.Image:
    """Procedural sketches of other microscopy targets: illustrations, not data."""
    rng = np.random.default_rng({"tb": 1, "schisto": 2, "tryp": 3, "helminth": 4}[kind])
    k = 2
    bgc = {
        "tb": (205, 226, 244),
        "schisto": (238, 230, 210),
        "tryp": (246, 222, 232),
        "helminth": (214, 222, 206),
    }[kind]
    im = Image.new("RGBA", (w * k, h * k), (*bgc, 255))
    d = ImageDraw.Draw(im)
    if kind == "tb":  # Ziehl-Neelsen: red rods on blue
        for _ in range(26):
            x, y = rng.uniform(20, w * k - 20), rng.uniform(20, h * k - 20)
            a = rng.uniform(0, math.pi)
            ln = rng.uniform(16, 30)
            pts = [
                (x + math.cos(a) * s * ln / 2 + math.sin(s * 3) * 2, y + math.sin(a) * s * ln / 2)
                for s in np.linspace(-1, 1, 6)
            ]
            d.line(pts, fill=(200, 30, 70, 255), width=5, joint="curve")
    elif kind == "schisto":  # eggs with a terminal spine
        for cx, cy, a in ((w * 0.7, h * 0.95, 0.3), (w * 1.35, h * 1.05, -0.5)):
            egg = Image.new("RGBA", (220, 120), (196, 160, 98, 0))
            ed = ImageDraw.Draw(egg)
            ed.ellipse(
                (20, 10, 190, 110), fill=(196, 160, 98, 255), outline=(140, 104, 52, 255), width=4
            )
            ed.polygon([(188, 52), (218, 60), (188, 68)], fill=(140, 104, 52, 255))
            egg = egg.rotate(math.degrees(a), expand=True, resample=Image.BICUBIC)
            im.alpha_composite(egg, (int(cx - egg.width / 2), int(cy - egg.height / 2)))
    elif kind == "tryp":  # red cells and wavy trypanosomes
        for _ in range(26):
            x, y, r = rng.uniform(0, w * k), rng.uniform(0, h * k), rng.uniform(22, 30)
            d.ellipse(
                (x - r, y - r, x + r, y + r),
                fill=(236, 186, 204, 255),
                outline=(222, 160, 184, 255),
                width=2,
            )
        for cx, cy in ((w * 0.6, h * 0.8), (w * 1.3, h * 1.2)):
            pts = [(cx + s, cy + 14 * math.sin(s / 14)) for s in np.linspace(-80, 80, 40)]
            d.line(pts, fill=(*STAIN, 255), width=7, joint="curve")
            d.ellipse((cx - 8, cy - 6, cx + 8, cy + 8), fill=(70, 30, 110, 255))
    else:  # mammillated roundworm eggs (Kato-Katz)
        for cx, cy in ((w * 0.75, h * 1.0), (w * 1.35, h * 0.9)):
            for j in range(40):
                a = j / 40 * 2 * math.pi
                d.ellipse(
                    (
                        cx + 62 * math.cos(a) - 8,
                        cy + 52 * math.sin(a) - 8,
                        cx + 62 * math.cos(a) + 8,
                        cy + 52 * math.sin(a) + 8,
                    ),
                    fill=(150, 104, 50, 255),
                )
            d.ellipse((cx - 60, cy - 50, cx + 60, cy + 50), fill=(178, 132, 70, 255))
            d.ellipse((cx - 36, cy - 28, cx + 36, cy + 28), fill=(150, 112, 60, 255))
    im = im.resize((w, h), Image.LANCZOS)
    im.putalpha(rrect(w, h, 16, WHITE).split()[3])
    return im


FUTURE = [
    ("tb", "Tuberculosis", "Sputum smear, Ziehl–Neelsen"),
    ("schisto", "Schistosomiasis", "Eggs in urine"),
    ("tryp", "Sleeping sickness", "Trypanosomes in blood"),
    ("helminth", "Helminths", "Worm eggs in stool, Kato-Katz"),
]


@lru_cache(maxsize=1)
def colonies() -> np.ndarray:
    rng = np.random.default_rng(7)
    n = 46
    r = 230 * np.sqrt(rng.uniform(0, 1, n))
    a = rng.uniform(0, 2 * math.pi, n)
    onset = rng.lognormal(math.log(16), 0.35, n)  # days until visible
    size = rng.uniform(8, 20, n)
    return np.stack([r * np.cos(a), r * np.sin(a), onset, size], axis=1)


def s_future(c: Image.Image, t: float) -> None:
    background(c, t)
    pill(
        c, "ROADMAP  ·  NOT YET BUILT", 120, 110, WARN, WARN_SOFT, 20, out_cubic(prog(t, 0.2, 0.5))
    )
    words(c, "Next: more of Africa's microscopy", 120, 170, 56, 800, INK, t, 0.3)
    for i, (kind, head, sub) in enumerate(FUTURE):
        kk = prog(t, 1.0 + i * 0.9, 0.7)
        if kk <= 0:
            continue
        x, y = 120 + (i % 2) * 420, 290 + (i // 2) * 360
        card(c, x, y, 390, 330, 24, alpha=clamp(kk * 2), scale=out_back(kk))
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3)
            put(c, specimen(kind), x + 30, y + 30, a)
            text(c, head, x + 32, y + 236, 28, 800, INK, a)
            text(c, sub, x + 32, y + 278, 21, 400, MUTED, a)
    # A simulated TB culture plate: colonies appear and grow over 42 days.
    k = out_cubic(prog(t, 4.2, 0.8))
    card(c, 1040, 250, 840, 760, 30, alpha=k)
    text(c, "Simulated TB culture", 1080, 284, 32, 800, INK, k)
    text(c, "Löwenstein–Jensen medium, 42 days", 1082, 330, 22, 400, MUTED, k)
    day = clamp((t - 4.8) / 6.2) * 42
    plate = Image.new("RGBA", (520, 520), (214, 220, 196, 0))
    pd = ImageDraw.Draw(plate)
    pd.ellipse((0, 0, 519, 519), fill=(214, 220, 196, 255), outline=(190, 196, 170, 255), width=6)
    pd.ellipse((14, 14, 505, 505), fill=(196, 214, 170, 255))
    shown = 0
    for x, y, onset, size in colonies():
        g = clamp((day - onset) / 12)
        if g <= 0:
            continue
        shown += 1
        r = size * (0.25 + 0.75 * g)
        pts = [
            (
                260 + x + r * (1 + 0.15 * math.sin(5 * a + x)) * math.cos(a),
                260 + y + r * (1 + 0.15 * math.sin(5 * a + x)) * math.sin(a),
            )
            for a in np.linspace(0, 2 * math.pi, 18)
        ]
        pd.polygon(pts, fill=(236, 222, 186, 255), outline=(200, 182, 140, 255))
    put(c, plate, 1460, 640, k, 1, "c")
    if k > 0.5:
        pill(c, f"Day {int(day)}", 1080, 940, PRIMARY_INK, PRIMARY_SOFT, 24, k)
        pill(c, f"Colonies {shown}", 1840, 940, WHITE, PRIMARY, 24, k, 1, "tr")


def s_outro(c: Image.Image, t: float) -> None:
    background(c, t, "brand")
    k = out_back(prog(t, 0.1, 0.7))
    put(c, disc(120, PRIMARY_SOFT), W / 2, 230, clamp(k), k, "c")
    put(c, disc(80, PRIMARY), W / 2, 230, clamp(k), k, "c")
    put(c, disc(34, CHART_4), W / 2, 230, clamp(k), k, "c")
    words(c, "Darubini", W / 2, 310, 130, 800, WHITE, t, 0.3, center=True)
    words(
        c,
        "Count faster. Count once. Count with confidence.",
        W / 2,
        490,
        44,
        700,
        CHART_4,
        t,
        1.1,
        center=True,
        stagger=0.06,
    )
    words(
        c,
        "A counting instrument, not a diagnosis. A microscopist confirms every result.",
        W / 2,
        565,
        28,
        400,
        PRIMARY_SOFT,
        t,
        2.2,
        center=True,
        stagger=0.03,
    )
    kk = prog(t, 3.2, 0.6)
    pill(
        c,
        "github.com/albertmwangwa/darubini",
        W / 2,
        670,
        PRIMARY_INK,
        WHITE,
        28,
        clamp(kk * 2),
        out_back(kk),
        "c",
    )
    a = out_cubic(prog(t, 4.0, 0.8))
    text(
        c,
        "Meta Global AI Developer Hackathon 2026  ·  Indie track",
        W / 2,
        800,
        24,
        500,
        PRIMARY_SOFT,
        a,
        "tc",
    )
    text(
        c,
        "Music: Sascha Ende, ende.app (CC BY 4.0)  ·  Sound effects: Kenney, unicae_games (CC0)",
        W / 2,
        960,
        20,
        400,
        CHART_4,
        a,
        "tc",
    )
    if t > 7.7:
        c.alpha_composite(
            Image.new("RGBA", (W, H), (0, 0, 0, int(255 * out_cubic(prog(t, 7.7, 1.2)))))
        )


# Durations sit on the music's 2-second bar grid; the first downbeat is at 3.02 s.
SCENES = [
    ("cold", s_cold, 17.02, "dark"),
    ("issue", s_issue, 18.0, "light"),
    ("reveal", s_reveal, 10.0, "brand"),
    ("app", s_app, 18.0, "light"),
    ("detect", s_detect, 18.0, "light"),
    ("track", s_track, 12.0, "light"),
    ("train", s_train, 20.0, "light"),
    ("agent", s_agent, 18.0, "light"),
    ("results", s_results, 20.0, "light"),
    ("honest", s_honest, 8.0, "light"),
    ("future", s_future, 12.0, "light"),
    ("outro", s_outro, 8.98, "brand"),
]
STARTS = dict(
    zip(
        [s[0] for s in SCENES], np.cumsum([0.0] + [s[2] for s in SCENES[:-1]]).tolist(), strict=True
    )
)
TOTAL = sum(s[2] for s in SCENES)
DIP = 0.6  # old content out, then new content in, through the new scene's background
POSTER = ("train", 19.0)


def render_scene(i: int, local: float) -> Image.Image:
    im = Image.new("RGBA", (W, H))
    SCENES[i][1](im, local)
    return im


def frame(t: float) -> Image.Image:
    i = max(j for j, s in enumerate(SCENES) if STARTS[s[0]] <= t)
    local = t - STARTS[SCENES[i][0]]
    cur = render_scene(i, local)
    if i > 0 and local < DIP:
        x = local / DIP
        bg = Image.new("RGBA", (W, H))
        background(bg, local, SCENES[i][3])
        if x < 0.5:  # the old scene lifts away
            prev = render_scene(i - 1, SCENES[i - 1][2] + local)
            y = in_out(x * 2)
            big = prev.resize(
                (round(W * (1 + 0.04 * y)), round(H * (1 + 0.04 * y))), Image.BILINEAR
            )
            ox, oy = (big.width - W) // 2, (big.height - H) // 2
            cur = Image.blend(big.crop((ox, oy, ox + W, oy + H)), bg, y)
        else:  # the new scene settles in
            cur = Image.blend(bg, cur, in_out((x - 0.5) * 2))
    return cur.convert("RGB")


# ---------------------------------------------------------------- audio


def load_audio(path: Path) -> np.ndarray:
    """Any file PyAV reads, as mono float32 at 48 kHz."""
    import av

    with av.open(str(path)) as c:
        rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
        parts = [f.to_ndarray().reshape(-1) for fr in c.decode(audio=0) for f in rs.resample(fr)]
        parts += [f.to_ndarray().reshape(-1) for f in rs.resample(None)]
    return np.concatenate(parts).astype(np.float32)


def music_bed() -> np.ndarray:
    """Vol. 1 (2:44) stretched to 3:00 by repeating bars 38-45 (79-95 s), cut on downbeats."""
    x = load_audio(AUDIO / "music.mp3")
    a, b = int(79.02 * SR), int(95.02 * SR)
    xf = int(0.012 * SR)
    ramp = np.linspace(0, 1, xf, dtype=np.float32)
    head, loop, tail = x[:b], x[a:b].copy(), x[b:].copy()
    loop[:xf] = loop[:xf] * ramp + head[-xf:] * (1 - ramp)
    tail[:xf] = tail[:xf] * ramp + loop[-xf:] * (1 - ramp)
    out = np.concatenate([head, loop, tail])
    n = int(TOTAL * SR)
    out = np.pad(out, (0, max(0, n - len(out))))[:n]
    t = np.arange(n) / SR
    return out * np.clip((TOTAL - t) / 3.0, 0, 1)


def sfx_plan() -> list[tuple[float, str, float]]:
    """(time, file, gain): soft hits on cuts, drops on card entrances, bells on payoffs."""
    s = STARTS
    plan = [(s[name] - 0.05, "impactSoft_medium_001.ogg", 0.45) for name, *_ in SCENES[1:]]
    plan += [
        (s["cold"] + 9.0, "drop_001.ogg", 0.5),
        *[(s["issue"] + 1.0 + i * 0.9, "card-slide-1.ogg", 0.45) for i in range(3)],
        *[(s["issue"] + 8.7 + i * 0.35, "drop_002.ogg", 0.5) for i in range(3)],
        (s["reveal"] + 0.15, "impactBell_heavy_000.ogg", 0.55),
        *[(s["reveal"] + 4.6 + i * 0.35, "drop_001.ogg", 0.5) for i in range(3)],
        (s["app"] + 6.0, "click_003.ogg", 0.6),
        (s["app"] + 12.0, "click_003.ogg", 0.6),
        (s["detect"] + 1.2, "card-slide-1.ogg", 0.45),
        (s["detect"] + 6.0, "chip-lay-1.ogg", 0.55),
        (s["detect"] + 9.6, "chips-stack-1.ogg", 0.5),
        (s["detect"] + 13.6, "impactBell_heavy_003.ogg", 0.4),
        (s["track"] + 2.6, "drop_001.ogg", 0.5),
        (s["track"] + 4.4, "chip-lay-1.ogg", 0.5),
        (s["track"] + 5.0, "click_003.ogg", 0.6),
        (s["train"] + 1.0, "card-slide-1.ogg", 0.4),
        (s["train"] + 4.6, "click_003.ogg", 0.5),
        (s["train"] + 5.2, "drop_001.ogg", 0.45),
        (s["train"] + 10.6, "impactBell_heavy_003.ogg", 0.35),
        (
            s["train"] + 11.4,
            "switch_007.ogg" if (AUDIO / "switch_007.ogg").exists() else "click_003.ogg",
            0.5,
        ),
        *[(s["train"] + 13.5 + i * 0.45, "drop_002.ogg", 0.35) for i in range(5)],
        *[(s["train"] + 14.0 + i * 0.6, "chip-lay-1.ogg", 0.4) for i in range(3)],
        *[(s["agent"] + 1.2 + i * 1.5 + 1.1, "rollover2.ogg", 0.45) for i in range(5)],
        (s["agent"] + 10.8, "impactBell_heavy_000.ogg", 0.45),
        *[(s["results"] + 1.4 + i * 2.4, "drop_002.ogg", 0.5) for i in range(4)],
        (s["results"] + 3.8, "impactBell_heavy_003.ogg", 0.35),
        *[(s["results"] + 11.5 + i * 0.45, "card-slide-1.ogg", 0.4) for i in range(4)],
        (s["results"] + 10.9 + 1.0 + 2 * 0.45, "impactBell_heavy_003.ogg", 0.35),
        (s["honest"] + 1.2, "drop_001.ogg", 0.45),
        (s["honest"] + 2.6, "bong_001.ogg", 0.4),
        *[(s["future"] + 1.0 + i * 0.9, "card-slide-1.ogg", 0.4) for i in range(4)],
        (s["outro"] + 0.2, "impactBell_heavy_000.ogg", 0.55),
    ]
    chars = sum(len(x) for x in DATA["report"]["sw"].split("\n")[:5])
    keys = [
        "keypress-003.wav",
        "keypress-007.wav",
        "keypress-011.wav",
        "keypress-015.wav",
        "keypress-019.wav",
        "keypress-023.wav",
    ]
    plan += [
        (s["agent"] + 3.4 + j / 45, keys[(j // 3) % len(keys)], 0.18) for j in range(0, chars, 3)
    ]
    return plan


def narration_track(n: int) -> tuple[np.ndarray, np.ndarray]:
    """The voice, placed per narration.json, and a 0-1 envelope of where it speaks."""
    spec = json.loads(NARRATION.read_text(encoding="utf-8"))
    voice = np.zeros(n, dtype=np.float32)
    env = np.zeros(n, dtype=np.float32)
    for i, line in enumerate(spec["lines"]):
        clip = load_audio(VOICE / f"{i:02d}_{line['scene']}.wav")
        start = int((STARTS[line["scene"]] + line["at"]) * SR)
        end = min(n, start + len(clip))
        voice[start:end] += clip[: end - start]
        env[start:end] = 1
    k = np.ones(int(0.5 * SR), dtype=np.float32) / int(0.5 * SR)
    env = np.convolve(env, k, mode="same").clip(0, 1)
    return voice / (np.abs(voice).max() or 1) * 0.9, env


def mixdown(narrated: bool) -> np.ndarray:
    n = int(TOTAL * SR)
    music = music_bed()
    fx = np.zeros(n, dtype=np.float32)
    cache: dict[str, np.ndarray] = {}
    for t, name, gain in sfx_plan():
        clip = cache.setdefault(name, load_audio(AUDIO / name))
        s0 = max(0, int(t * SR))
        e = min(n, s0 + len(clip))
        fx[s0:e] += gain * clip[: e - s0] / (np.abs(clip).max() or 1)
    if narrated:
        voice, env = narration_track(n)
        mix = 0.42 * music * (1 - 0.62 * env) + 0.38 * fx + voice
    else:
        mix = 0.42 * music + 0.5 * fx
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)  # gentle limiter
    return (mix * 0.95 / (np.abs(mix).max() or 1)).astype(np.float32)  # both cuts peak at -0.4 dBFS


# ---------------------------------------------------------------- render


def render_segment(args: tuple[int, int, str]) -> str:
    """Encode frames [a, b) to a video-only MP4 segment."""
    import av

    a, b, path = args
    DATA.update(load_data())
    with av.open(path, "w") as out:
        v = out.add_stream("libx264", rate=FPS)
        v.width, v.height, v.pix_fmt = W, H, "yuv420p"
        v.options = {"crf": "18", "preset": "medium", "tune": "animation"}
        for i in range(a, b):
            t = STARTS[POSTER[0]] + POSTER[1] if i == 0 else i / FPS  # the poster is frame 0
            for p in v.encode(av.VideoFrame.from_image(frame(t))):
                out.mux(p)
            if (i - a) % 150 == 0:
                print(f"  frame {i} / {b}", flush=True)
        for p in v.encode(None):
            out.mux(p)
    return path


def concat_and_mux(segments: list[str], audio: np.ndarray, path: Path) -> None:
    import av

    with av.open(str(path), "w") as out:
        with av.open(segments[0]) as first:
            vs = out.add_stream_from_template(first.streams.video[0])
        a = out.add_stream("aac", rate=SR)
        a.layout = "stereo"
        a.bit_rate = 192_000
        offset = 0
        for seg in segments:
            with av.open(seg) as inp:
                last = 0
                for pkt in inp.demux(inp.streams.video[0]):
                    if pkt.dts is None:
                        continue
                    pkt.pts += offset
                    pkt.dts += offset
                    last = max(last, pkt.pts + (pkt.duration or 0))
                    pkt.stream = vs
                    out.mux(pkt)
                offset = last
        stereo = np.stack([audio, audio])
        for k in range(0, stereo.shape[1], 1024):
            af = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(stereo[:, k : k + 1024]), format="fltp", layout="stereo"
            )
            af.sample_rate = SR
            af.pts = k
            af.time_base = Fraction(1, SR)
            for p in a.encode(af):
                out.mux(p)
        for p in a.encode(None):
            out.mux(p)


def render_all(workers: int) -> None:
    from concurrent.futures import ProcessPoolExecutor

    n = round(TOTAL * FPS)
    tmp = ASSETS / "segments"
    tmp.mkdir(parents=True, exist_ok=True)
    bounds = np.linspace(0, n, workers + 1).astype(int)
    jobs = [(int(bounds[i]), int(bounds[i + 1]), str(tmp / f"seg{i}.mp4")) for i in range(workers)]
    with ProcessPoolExecutor(workers) as pool:
        segments = list(pool.map(render_segment, jobs))
    for narrated, name in ((False, "darubini_demo_sfx.mp4"), (True, "darubini_demo_narrated.mp4")):
        concat_and_mux(segments, mixdown(narrated), ASSETS / name)
        print(f"Wrote {ASSETS / name}")
    frame(STARTS[POSTER[0]] + POSTER[1]).save(ASSETS / "poster.jpg", quality=92)


# ---------------------------------------------------------------- script document

SCREEN = {
    "cold": "A real thick-film field; “Every malaria diagnosis starts with someone counting”; a hand tally ticking up",
    "issue": "Slow, tiring, inconsistent; 282M cases, 610K deaths, Tanzania #4 (WHO 2025)",
    "reveal": "Darubini logo; SAM 3.1, Muse Spark and Muse Voice capability cards",
    "app": "The Android app, in the proposal palette: a captured field with its detections, voice listening, the report with the Muse Spark audit",
    "detect": "281 candidates, 34 parasites kept, 17 white blood cells on a real field; expert 35 / 18",
    "track": "The SAM 3.1 tracking clip: 31 frame by frame against 12 counted once",
    "train": "150 patients flowing into train/validate/test (102/24/24) with the test set locked; UDOM 431/180 photos; "
    "the verifier network (16×16 crop + 8 features → 776 → 64 → 1) training over 40 epochs as validation F1 rises "
    "0.29 → 0.81 and the threshold settles at 0.75; five best-practice checks; best results 0.81, 0.95, 0.80",
    "agent": "Muse Spark tool-call timeline; Kiswahili report typing; TF65: 16,383 vs 16,142 /µL",
    "results": "0.80 F1, 19/24 within 2×, r 0.93, 8/8 over-counts caught; then **where Meta's AI moves the number**: "
    "SAM 3.1 WBC F1 0.50 → 0.90, slides within 2× 13/24 → 19/24, Muse Spark audit 8/8, SAM 3.1 video 31 → 12; "
    "note that parasites come from our own verifier (SAM 3.1 alone 0.64)",
    "honest": "It is / it is not (not a screen; not yet strong on Tanzanian smears, F1 0.48; not a diagnosis)",
    "future": "Roadmap: TB smears, schistosomiasis, sleeping sickness, helminths; a simulated TB culture plate growing over 42 days",
    "outro": "Darubini; tagline; repository; credits",
}


def write_script() -> Path:
    spec = json.loads(NARRATION.read_text(encoding="utf-8"))
    durations = (
        json.loads((VOICE / "durations.json").read_text())
        if (VOICE / "durations.json").exists()
        else {}
    )

    def mmss(x: float) -> str:
        x = round(x, 1)
        return f"{int(x // 60)}:{x % 60:04.1f}"

    lines = [
        "# Darubini demo video: script",
        "",
        "Generated by `python scripts/demo_video.py --script` from [narration.json](narration.json) and the scene list in "
        "`scripts/demo_video.py`. Length 3:00, cut on the music's 2-second bar grid (120 BPM).",
        "",
        "Two cuts share the same picture:",
        "- `darubini_demo_sfx.mp4`: music and sound effects only.",
        f"- `darubini_demo_narrated.mp4`: the same, plus a female narrator (Kokoro, voice `{spec['voice']}` at "
        f"{spec['speed']}× speed), with the music ducked under her.",
        "",
        "| Time | Scene | On screen | Narration |",
        "| --- | --- | --- | --- |",
    ]
    for i, (name, _, dur, _) in enumerate(SCENES):
        start = STARTS[name]
        said = [(j, ln) for j, ln in enumerate(spec["lines"]) if ln["scene"] == name]
        narr = "<br>".join(
            f"**{mmss(start + ln['at'])}** {ln['text']}"
            + (
                f" *({durations[f'{j:02d}_{name}.wav']:.1f} s)*"
                if f"{j:02d}_{name}.wav" in durations
                else ""
            )
            for j, ln in said
        )
        lines.append(
            f"| {mmss(start)}–{mmss(start + dur)} | {i + 1}. {name} | {SCREEN[name]} | {narr} |"
        )
    lines += [
        "",
        "## Sources",
        "",
        "- Field image and detections: NIH development field TF44_UW16; hybrid detections; expert labels.",
        "- Tracking: `docs/demo/tracking_demo.mp4` (STATUS step 17).",
        "- Training: `docs/calibration/verifier.md` (verifier v3), `docs/splits/`, the protocol in `docs/EVALUATION.md`.",
        "- Report and density: held-out test slide TF65_CS33.",
        "- Test numbers: [`docs/calibration/final_test.md`](../calibration/final_test.md).",
        "- Burden: WHO World Malaria Report 2025.",
        "- The patient dots, network pulses and roadmap scene are illustrations; the counts, sizes and scores on them are real, "
        "and the culture plate is labelled as a simulation.",
        "",
        "## Credits",
        "",
        "- Music: “Happy Beats / Business Moves Vol. 1” by Sascha Ende, ende.app (CC BY 4.0).",
        "- Sound effects: Kenney (CC0) and unicae_games' Keyboard Soundpack #1 (CC0), both via the /brag skill.",
        f"- Narration voice: Kokoro-82M (Apache 2.0), voice `{spec['voice']}`.",
    ]
    out = ROOT / "docs" / "demo" / "SCRIPT.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- assets

#: The cache key, exactly as final_eval.py wrote it (a Windows path).
DEMO_FIELD = "datasets\\raw\\nih-thick-pf-150\\TF44_UW16\\20170807_152445.jpg"


def prepare() -> None:
    """Write the field image, its real detections and a held-out slide's Kiswahili report."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import final_eval as fe

    from darubini.counting import evaluate_slide
    from darubini.pipeline import load_image
    from darubini.report import render as render_report
    from darubini.segmentation.candidates import CandidateDetector
    from darubini.segmentation.sam import drop_parasites_in_wbc
    from darubini.types import Detection, FieldResult, ObjectClass

    ASSETS.mkdir(parents=True, exist_ok=True)
    row = fe.load_cache("nih_val", "hybrid")[DEMO_FIELD]
    img = load_image(ROOT / DEMO_FIELD)
    h, w = img.shape[:2]
    par, wbc = fe.dets_of(row, ObjectClass.PARASITE), fe.dets_of(row, ObjectClass.WBC)
    found = [d for d in CandidateDetector().segment(img) if d.cls is ObjectClass.PARASITE]
    cands = [d for d in drop_parasites_in_wbc([*wbc, *found]) if d.cls is ObjectClass.PARASITE]
    side = min(h, w)
    x0, y0, s = (w - side) // 2, (h - side) // 2, 1000 / side
    Image.fromarray(img[y0 : y0 + side, x0 : x0 + side]).resize((1000, 1000), Image.LANCZOS).save(
        ASSETS / "field.jpg", quality=92
    )

    def box(d: Detection) -> list[float]:
        b = d.box
        return [
            round((b.x_min - x0) * s, 1),
            round((b.y_min - y0) * s, 1),
            round((b.x_max - x0) * s, 1),
            round((b.y_max - y0) * s, 1),
        ]

    field = {
        "cands": [box(d) for d in cands],
        "parasites": [box(d) for d in par],
        "wbcs": [box(d) for d in wbc],
    }
    (ASSETS / "field.json").write_text(json.dumps(field))
    slides = fe.per_slide("nih_test", "hybrid")
    best = min(
        (k for k, v in slides.items() if v["w"] and v["tw"] and v["tp_"]),
        key=lambda k: abs(
            (slides[k]["p"] / slides[k]["w"]) / (slides[k]["tp_"] / slides[k]["tw"]) - 1
        ),
    )
    rows = [r for r in fe.load_cache("nih_test", "hybrid").values() if r["slide"] == best]
    count = evaluate_slide(
        [
            FieldResult(
                r["key"],
                fe.dets_of(r, ObjectClass.PARASITE) + fe.dets_of(r, ObjectClass.WBC),
                list(r["flags"]),
            )
            for r in rows
        ]
    )
    v = slides[best]
    report = {
        "slide": best,
        "expert_density": 8000 * v["tp_"] / v["tw"],
        "sw": render_report(count, "sw").text,
        "en": render_report(count, "en").text,
    }
    (ASSETS / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cands)} candidates, {len(par)} parasites, {len(wbc)} WBC; report for {best}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true", help="write the field and report assets")
    ap.add_argument("--script", action="store_true", help="write docs/demo/SCRIPT.md")
    ap.add_argument(
        "--still", type=float, nargs="*", help="render frames at these times (s) as PNG"
    )
    ap.add_argument("--audio", action="store_true", help="write both mixes as WAV, for listening")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.prepare:
        prepare()
        return 0
    if args.script:
        print(write_script())
        return 0
    DATA.update(load_data())
    if args.audio:
        import wave

        for narrated in (False, True):
            p = ASSETS / f"mix_{'narrated' if narrated else 'sfx'}.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes((mixdown(narrated) * 32767).astype("<i2").tobytes())
            print(p)
        return 0
    if args.still:
        for s in args.still:
            p = ASSETS / f"still_{s:05.1f}.png"
            frame(s).save(p)
            print(p)
        return 0
    print(f"Rendering {TOTAL:.2f} s at {W}x{H}, {FPS} fps with {args.workers} workers")
    render_all(args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
