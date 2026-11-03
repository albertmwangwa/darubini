"""Render the Darubini demo video: SaaS-style motion graphics over real results.

Everything shown is real hackathon output: the app's screens, one development field
with its actual candidates and detections, the SAM 3.1 tracking clip, the Muse Spark
tool names, a Kiswahili report for a held-out test slide, and the frozen test-set
numbers from docs/calibration/final_test.md. The music bed is synthesised here.

Needs the cached detections from ``scripts/final_eval.py``. Then:

    python scripts/demo_video.py --prepare       # field image, detections, report
    python scripts/demo_video.py                 # full video, about 2 minutes
    python scripts/demo_video.py --still 40      # one frame at 40 s, for checking
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
OUT = ASSETS / "darubini_demo.mp4"
FONT = ROOT / "android" / "app" / "src" / "main" / "res" / "font" / "plus_jakarta_sans.ttf"
SHOTS = ROOT / "docs" / "calibration"
TRACK = ROOT / "docs" / "demo" / "tracking_demo.mp4"
W, H, FPS = 1920, 1080, 30
SR = 48_000

# Credit Design tokens, as in the Android app.
PRIMARY = (33, 87, 50)
PRIMARY_STRONG = (22, 57, 31)
PRIMARY_SOFT = (232, 243, 227)
LIME = (67, 176, 42)
LIME_SOFT = (221, 240, 213)
LIME_BRIGHT = (155, 227, 111)
BG = (244, 246, 245)
CARD = (255, 255, 255)
INK = (21, 26, 23)
MUTED = (107, 115, 110)
BORDER = (229, 232, 230)
DARK = (14, 24, 18)
PARASITE = (233, 30, 140)
WBC = (59, 130, 246)
DANGER = (200, 65, 47)
DANGER_SOFT = (251, 233, 230)
WARN_SOFT = (253, 242, 225)
WARN_STRONG = (154, 91, 7)


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


def lerp(a: float, b: float, x: float) -> float:
    return a + (b - a) * x


# ---------------------------------------------------------------- cached layers


@lru_cache(maxsize=64)
def font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_axes([weight])
    return f


@lru_cache(maxsize=2048)
def text_layer(text: str, size: int, weight: int, color: tuple[int, ...]) -> Image.Image:
    f = font(size, weight)
    _x0, _y0, x1, _y1 = f.getbbox(text)
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (max(1, x1 + 4), asc + desc + 4), (0, 0, 0, 0))
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
    big = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle(
        (0, 0, w * k - 1, h * k - 1),
        r * k,
        fill=fill if len(fill) == 4 else (*fill, 255),
        outline=(*outline, 255) if outline else None,
        width=width * k,
    )
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=256)
def shadow(w: int, h: int, r: int, blur: int = 28, alpha: int = 34) -> Image.Image:
    pad = blur * 3
    # Colour everywhere, alpha only where the shape is, so blurring cannot darken the edges.
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (16, 40, 24, 0))
    ImageDraw.Draw(im).rounded_rectangle((pad, pad, pad + w, pad + h), r, fill=(16, 40, 24, alpha))
    return im.filter(ImageFilter.GaussianBlur(blur))


@lru_cache(maxsize=64)
def disc(
    d: int, fill: tuple[int, ...], outline: tuple[int, ...] | None = None, width: int = 0
) -> Image.Image:
    k = 3
    big = Image.new("RGBA", (d * k, d * k), (0, 0, 0, 0))
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
        mask = rrect(w, h, r, (255, 255, 255)).split()[3]
        im.putalpha(Image.fromarray(np.minimum(np.asarray(im.split()[3]), np.asarray(mask))))
    return im


@lru_cache(maxsize=8)
def phone(shot: str, h: int) -> Image.Image:
    """A phone frame around an app screenshot, ``h`` pixels tall."""
    sh = Image.open(SHOTS / shot)
    w = round(h * sh.width / sh.height)
    bezel = 14
    frame = rrect(w + 2 * bezel, h + 2 * bezel, 58, (17, 20, 18))
    screen = image(str(SHOTS / shot), w, h, 46)
    frame = frame.copy()
    frame.alpha_composite(screen, (bezel, bezel))
    return frame


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
    """A Figma-style card: soft shadow, white fill, hairline border. Scales about its centre."""
    cx, cy = x + w / 2, y + h / 2
    if lift:
        sh = shadow(w, h, r)
        put(c, sh, cx, cy + 10 * scale, alpha * 0.9, scale, "c")
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
    im = Image.new("RGBA", (dd, dd), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse((0, 0, dd - 1, dd - 1), fill=(*(LIME if ok else DANGER), 255))
    lw = max(3, dd // 11)
    if ok:
        dr.line(
            [(dd * 0.28, dd * 0.52), (dd * 0.44, dd * 0.68), (dd * 0.73, dd * 0.35)],
            fill=(255, 255, 255, 255),
            width=lw,
            joint="curve",
        )
    else:
        dr.line(
            [(dd * 0.32, dd * 0.32), (dd * 0.68, dd * 0.68)], fill=(255, 255, 255, 255), width=lw
        )
        dr.line(
            [(dd * 0.68, dd * 0.32), (dd * 0.32, dd * 0.68)], fill=(255, 255, 255, 255), width=lw
        )
    put(c, im.resize((d, d), Image.LANCZOS), x, y, alpha, scale, "c")


def background(c: Image.Image, t: float, dark: bool = False, brand: bool = False) -> None:
    base = PRIMARY if brand else DARK if dark else BG
    c.paste(Image.new("RGBA", (W, H), (*base, 255)))
    a, b = (LIME, PRIMARY_SOFT) if not (dark or brand) else (LIME, LIME_BRIGHT)
    alpha1, alpha2 = (70, 90) if not (dark or brand) else (60, 30)
    put(
        c,
        blob(1100, a, alpha1),
        1500 + 120 * math.sin(t * 0.35),
        160 + 80 * math.cos(t * 0.3),
        1,
        1,
        "c",
    )
    put(
        c,
        blob(1200, b, alpha2),
        300 + 140 * math.cos(t * 0.27),
        950 + 70 * math.sin(t * 0.33),
        1,
        1,
        "c",
    )


# ---------------------------------------------------------------- data


def load_data() -> dict:
    field = json.loads((ASSETS / "field.json").read_text())
    report = json.loads((ASSETS / "report.json").read_text(encoding="utf-8"))
    return {"field": field, "report": report}


@lru_cache(maxsize=1)
def tracking_frames() -> list[Image.Image]:
    from darubini.video import decode

    frames = decode(TRACK.read_bytes(), max_frames=400)
    return [Image.fromarray(f).convert("RGBA").resize((960, 540), Image.LANCZOS) for f in frames]


DATA: dict = {}


# ---------------------------------------------------------------- scenes


def s_hook(c: Image.Image, t: float) -> None:
    background(c, t, dark=True)
    a = 1 - out_cubic(prog(t, 4.0, 0.6))
    words(c, "MALARIA MICROSCOPY", W / 2, 330, 26, 700, LIME_BRIGHT, t, 0.2, center=True, alpha=a)
    words(
        c, "Every malaria count", W / 2, 400, 96, 800, (255, 255, 255), t, 0.5, center=True, alpha=a
    )
    words(
        c,
        "is still done by eye.",
        W / 2,
        520,
        96,
        800,
        (255, 255, 255),
        t,
        1.1,
        center=True,
        alpha=a,
    )
    words(
        c,
        "Field by field, against 200 white blood cells.",
        W / 2,
        680,
        34,
        400,
        (190, 205, 195),
        t,
        2.0,
        center=True,
        alpha=a,
    )
    stats = [
        ("282M", "malaria cases in 2024"),
        ("610K", "malaria deaths in 2024"),
        ("#4", "Tanzania's rank in deaths"),
    ]
    for i, (big, small) in enumerate(stats):
        k = prog(t, 4.5 + i * 0.25, 0.7)
        if k <= 0:
            continue
        s = out_back(k)
        x = 240 + i * 500
        card(c, x, 390, 440, 300, 26, fill=(26, 40, 31), alpha=clamp(k * 2), scale=s, border=False)
        if k > 0.5:
            al = clamp((k - 0.5) * 2)
            text(c, big, x + 40, 430, 104, 800, LIME_BRIGHT, al)
            text(c, small, x + 42, 590, 28, 500, (200, 214, 204), al)
    if t > 6.2:
        text(
            c,
            "WHO World Malaria Report 2025",
            W / 2,
            760,
            22,
            400,
            (120, 140, 128),
            out_cubic(prog(t, 6.2, 0.5)),
            "tc",
        )


def s_problem(c: Image.Image, t: float) -> None:
    background(c, t)
    k = out_cubic(prog(t, 0, 0.8))
    z = 1.0 + 0.06 * (t / 8)
    field = image(str(ASSETS / "field.jpg"), 640, 640, 320, 1.25)
    put(c, shadow(640, 640, 320, 40, 50), 520, 560 + 14, k, 1, "c")
    put(c, field, 520 - (1 - k) * 80, 560, k, z, "c")
    # a hand tally, ticking upward
    n = int(137 * clamp((t - 1.2) / 5.5))
    if t > 1.2:
        card(
            c,
            640,
            760,
            300,
            120,
            22,
            alpha=out_cubic(prog(t, 1.2, 0.5)),
            scale=out_back(prog(t, 1.2, 0.6)),
        )
        text(c, "Tally", 670, 778, 22, 600, MUTED, out_cubic(prog(t, 1.5, 0.4)))
        text(c, f"{n}", 670, 806, 52, 800, INK, out_cubic(prog(t, 1.5, 0.4)))
    words(c, "200 white blood cells.", 1000, 330, 62, 800, INK, t, 0.6)
    words(c, "Hundreds of parasites.", 1000, 420, 62, 800, INK, t, 1.4)
    words(c, "One tired pair of eyes.", 1000, 510, 62, 800, PRIMARY, t, 2.2)
    words(
        c,
        "Slow, and it varies with fatigue, stain and smear.",
        1002,
        640,
        30,
        400,
        MUTED,
        t,
        3.2,
        stagger=0.04,
    )


def s_logo(c: Image.Image, t: float) -> None:
    background(c, t, brand=True)
    k = out_back(prog(t, 0.1, 0.8))
    put(c, disc(190, LIME_SOFT), W / 2, 330, clamp(k), k, "c")
    put(c, disc(130, PRIMARY), W / 2, 330, clamp(k), k, "c")
    put(c, disc(56, LIME_BRIGHT), W / 2, 330, clamp(k), k, "c")
    name = "Darubini"
    x = W / 2 - text_width(name, 150, 800) / 2
    for i, ch in enumerate(name):
        kk = out_cubic(prog(t, 0.5 + i * 0.05, 0.5))
        text(c, ch, x, 470 + (1 - kk) * 50, 150, 800, (255, 255, 255), kk)
        x += text_width(ch, 150, 800) + 1
    words(
        c,
        "A malaria microscopy copilot, in English and Kiswahili.",
        W / 2,
        680,
        36,
        500,
        LIME_SOFT,
        t,
        1.4,
        center=True,
        stagger=0.04,
    )
    chips = ["Meta SAM 3.1", "Muse Spark", "Muse Voice Transcribe"]
    total = sum(text_width(s, 26, 600) + 2 * 21 for s in chips) + 24 * 2
    x = W / 2 - total / 2
    for i, s in enumerate(chips):
        kk = prog(t, 2.4 + i * 0.18, 0.5)
        w = pill(c, s, x, 780, PRIMARY_STRONG, LIME_BRIGHT, 26, clamp(kk * 2), out_back(kk))
        x += w + 24


APP_SHOTS = [("android_start.png", 0.0), ("android_voice.png", 4.6), ("android_report.png", 9.4)]


def s_app(c: Image.Image, t: float) -> None:
    background(c, t)
    k = out_cubic(prog(t, 0, 0.9))
    px, py = 470, 560 + (1 - k) * 500
    tilt = 0
    put(c, shadow(420, 900, 60, 46, 60), px, py + 24, k, 1, "c")
    for i, (shot, start) in enumerate(APP_SHOTS):
        nxt = APP_SHOTS[i + 1][1] if i + 1 < len(APP_SHOTS) else 99
        a = out_cubic(prog(t, start, 0.45)) * (1 - out_cubic(prog(t, nxt, 0.45)))
        if i == 0:
            a = 1 - out_cubic(prog(t, nxt, 0.45))
        if a > 0:
            put(c, phone(shot, 880), px + tilt, py, a * k, 1, "c")
    # floating chips beside the phone, one per stage
    chips = [
        ("Photograph or pan", 0.8, 0.0, 4.6, 250),
        ("Muse Voice Transcribe", 5.0, 4.6, 9.4, 560),
        ("Muse Spark audit", 9.8, 9.4, 99, 380),
    ]
    for s, start, _a0, a1, y in chips:
        kk = prog(t, start, 0.6) * (1 - out_cubic(prog(t, a1, 0.4)))
        if kk > 0:
            pill(
                c,
                s,
                640,
                y,
                (255, 255, 255),
                PRIMARY,
                24,
                clamp(kk * 2),
                out_back(min(1, kk)),
                dot=LIME_BRIGHT,
            )
    if 5.2 < t < 9.4:  # voice level bars while "listening"
        for i in range(9):
            hgt = 14 + 40 * abs(math.sin(t * 7 + i * 0.9)) * (0.5 + 0.5 * math.sin(i))
            put(
                c,
                rrect(10, int(hgt), 5, LIME),
                680 + i * 18,
                660,
                out_cubic(prog(t, 5.2, 0.4)),
                1,
                "c",
            )
    items = [
        ("1", "Capture", "Phone on the eyepiece: photograph a field, or record a pan.", 0.6),
        ("2", "Speak", "“Next field”, “retake”, “note…”. Hands stay on the microscope.", 4.8),
        ("3", "Check", "Muse Spark audits its own count and flags doubtful slides.", 9.6),
    ]
    for n, head, body, start in items:
        kk = out_cubic(prog(t, start, 0.6))
        y = 300 + (int(n) - 1) * 200
        active = start <= t < start + 4.6 or (n == "3" and t >= start)
        put(c, disc(64, PRIMARY if active else LIME_SOFT), 1150, y + 34, kk, 1, "c")
        text(c, n, 1150, y + 12, 32, 800, (255, 255, 255) if active else PRIMARY, kk, "tc")
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
    ov = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    t1, t2, t3 = 1.2, 5.5, 9.5
    kept = {tuple(b) for b in f["parasites"]}
    n_c = len(f["cands"])
    fade = out_cubic(prog(t, t2, 1.0))
    for i, b in enumerate(f["cands"]):
        appear = prog(t, t1 + 2.2 * i / n_c, 0.25)
        if appear <= 0 or fade >= 1:
            continue
        cx, cy = (b[0] + b[2]) / 2 * s, (b[1] + b[3]) / 2 * s
        r = 9 * out_back(appear)
        d.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            outline=(255, 255, 255, int(210 * (1 - fade))),
            width=2,
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
    del kept
    steps = [
        ("Candidates", "Every stain spot that absorbs green light", t1, f"{n_c}"),
        ("Verifier", "A small network keeps the real parasites", t2, f"{len(f['parasites'])}"),
        ("SAM 3.1", "Finds the white blood cells from one word: “cell”", t3, f"{len(f['wbcs'])}"),
    ]
    words(c, "Two models, one count", 1040, 150, 54, 800, INK, t, 0.3)
    for i, (head, body, start, num) in enumerate(steps):
        kk = out_cubic(prog(t, start, 0.6))
        y = 270 + i * 190
        nxt = steps[i + 1][2] if i + 1 < len(steps) else 99
        active = start <= t < nxt
        colour = [MUTED, PARASITE, WBC][i]
        card(
            c,
            1040,
            y,
            740,
            160,
            22,
            fill=CARD if active else (250, 251, 250),
            alpha=kk,
            scale=0.96 + 0.04 * kk,
        )
        put(c, rrect(8, 110, 4, colour), 1066, y + 80, kk if active else kk * 0.35, 1, "c")
        text(c, head, 1094, y + 28, 36, 800, INK, kk)
        text(c, body, 1095, y + 82, 24, 400, MUTED, kk)
        cnt = round(float(num) * out_cubic(prog(t, start + 0.2, 1.2)))
        text(c, str(cnt), 1750, y + 36, 64, 800, colour if i else INK, kk, "tr")
    if t > 11.8:
        kk = prog(t, 11.8, 0.7)
        pill(
            c,
            "Expert labels on this field: 35 parasites, 18 white blood cells",
            1040,
            870,
            PRIMARY_STRONG,
            LIME_SOFT,
            24,
            clamp(kk * 2),
            out_back(kk),
            dot=LIME,
        )


def s_track(c: Image.Image, t: float) -> None:
    background(c, t)
    frames = tracking_frames()
    k = out_cubic(prog(t, 0, 0.8))
    idx = min(len(frames) - 1, max(0, int((t - 0.6) * 15)))
    fx, fy = 120, 270 + (1 - k) * 60
    card(c, fx - 16, fy - 16, 992, 572, 28, alpha=k)
    vid = frames[idx].copy()
    mask = rrect(960, 540, 16, (255, 255, 255)).split()[3]
    vid.putalpha(mask)
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
        strike = out_cubic(prog(t, 4.6, 0.5))
        if strike > 0:
            put(c, rrect(max(2, int(110 * strike)), 6, 3, DANGER), 1206, 650, a, 1)
    k2 = out_back(prog(t, 4.2, 0.6))
    card(c, 1500, 540, 300, 190, 22, fill=PRIMARY, alpha=clamp(k2), scale=k2, border=False)
    if k2 > 0.6:
        a = clamp((k2 - 0.6) * 3)
        text(c, "Tracked, once each", 1526, 562, 22, 600, LIME_BRIGHT, a)
        n = round(12 * out_cubic(prog(t, 4.4, 1.0)))
        text(c, str(n), 1526, 600, 84, 800, (255, 255, 255), a)
    if t > 6.4:
        kk = prog(t, 6.4, 0.6)
        pill(
            c,
            "0 objects counted twice, checked against expert labels",
            1180,
            770,
            PRIMARY_STRONG,
            LIME_SOFT,
            22,
            clamp(kk * 2),
            out_back(kk),
            dot=LIME,
        )


AGENT_STEPS = [
    ("examine_next_fields", "Examined the captured fields"),
    ("review_field", "Second opinion on image quality"),
    ("audit_parasites", "Audited 20 sampled parasites"),
    ("get_count", "Checked the WHO counting rule"),
    ("finish", "Wrote the report in Kiswahili"),
]


def s_agent(c: Image.Image, t: float) -> None:
    background(c, t)
    k = out_cubic(prog(t, 0, 0.8))
    card(c, 110, 150 + (1 - k) * 60, 760, 760, 28, alpha=k)
    put(c, disc(56, PRIMARY_SOFT), 170, 222, k, 1, "c")
    put(c, disc(22, LIME), 170, 222, k, 1, "c")
    text(c, "Muse Spark agent", 214, 196, 36, 800, INK, k)
    text(c, "Runs the slide through deterministic tools", 216, 244, 22, 400, MUTED, k)
    for i, (tool, label) in enumerate(AGENT_STEPS):
        start = 1.0 + i * 1.1
        kk = out_cubic(prog(t, start, 0.5))
        y = 320 + i * 112
        done = t > start + 0.9
        if i < len(AGENT_STEPS) - 1:
            put(
                c,
                rrect(3, int(112 * out_cubic(prog(t, start + 0.4, 0.6))) + 1, 1, LIME_SOFT),
                168,
                y + 22,
                kk,
                1,
                "tc",
            )
        if done:
            check(c, 170, y + 20, 40, True, kk, out_back(prog(t, start + 0.9, 0.4)))
        else:
            spin = (t * 4) % (2 * math.pi)
            put(c, disc(40, (255, 255, 255), LIME_SOFT, 4), 170, y + 20, kk, 1, "c")
            put(
                c,
                disc(10, LIME),
                170 + 13 * math.cos(spin),
                y + 20 + 13 * math.sin(spin),
                kk,
                1,
                "c",
            )
        text(c, label, 214, y, 30, 700, INK, kk)
        text(c, tool, 216, y + 42, 20, 500, MUTED, kk)
    # the report, typed out
    rep = DATA["report"]["sw"].split("\n")[:5]
    k2 = out_cubic(prog(t, 2.2, 0.8))
    card(c, 950, 150 + (1 - k2) * 60, 860, 560, 28, alpha=k2)
    text(c, "Ripoti", 990, 190, 40, 800, INK, k2)
    pill(c, "Kiswahili", 1770, 192, PRIMARY_STRONG, LIME_SOFT, 20, k2, 1, "tr")
    chars = int(max(0, t - 3.0) * 70)
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
    if t > 9.5:
        kk = prog(t, 9.5, 0.7)
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
            text(c, "Held-out test slide TF65", 990, 784, 22, 600, LIME_BRIGHT, a)
            text(
                c,
                "Darubini 16,383 /µL  ·  expert 16,142 /µL",
                990,
                822,
                40,
                800,
                (255, 255, 255),
                a,
            )


METRICS = [
    ("0.80", "Parasite F1", "NIH held-out patients"),
    ("19/24", "Slides within 2×", "of the expert's density"),
    ("0.93", "Correlation", "with expert density (log)"),
    ("8/8", "Over-counts caught", "by the Muse Spark audit"),
]
BARS = [
    ("Stain threshold (baseline)", 0.30, MUTED),
    ("SAM 3.1 text prompt alone", 0.64, (150, 170, 158)),
    ("Candidates + verifier (offline)", 0.76, LIME),
    ("Hybrid: SAM 3.1 + verifier", 0.80, PRIMARY),
]


def s_results(c: Image.Image, t: float) -> None:
    background(c, t)
    out = out_cubic(prog(t, 10.5, 0.6))
    words(c, "TEST SET  ·  SCORED ONCE", 140, 130, 24, 700, LIME, t, 0.2, alpha=1 - out)
    words(c, "Tested on slides it never saw.", 140, 175, 64, 800, INK, t, 0.4, alpha=1 - out)
    for i, (big, head, sub) in enumerate(METRICS):
        kk = prog(t, 1.4 + i * 0.3, 0.7)
        if kk <= 0 or out >= 1:
            continue
        x = 140 + i * 420
        y = 380 - out * 80
        fill = PRIMARY if i == 1 else CARD
        card(
            c,
            x,
            y,
            380,
            360,
            28,
            fill=fill,
            alpha=clamp(kk * 2) * (1 - out),
            scale=out_back(kk),
            border=i != 1,
        )
        if kk > 0.6:
            a = clamp((kk - 0.6) * 3) * (1 - out)
            fg = (255, 255, 255) if i == 1 else INK
            sub_c = LIME_SOFT if i == 1 else MUTED
            text(c, big, x + 34, y + 50, 96, 800, LIME_BRIGHT if i == 1 else PRIMARY, a)
            text(c, head, x + 36, y + 200, 32, 800, fg, a)
            text(c, sub, x + 36, y + 248, 24, 400, sub_c, a)
    if t > 10.8:
        tt = t - 10.8
        words(c, "What each part adds", 140, 140, 60, 800, INK, tt, 0.1)
        words(
            c, "Parasite F1 on held-out NIH fields", 142, 222, 28, 400, MUTED, tt, 0.4, stagger=0.03
        )
        for i, (label, v, colour) in enumerate(BARS):
            kk = out_cubic(prog(tt, 0.8 + i * 0.35, 1.0))
            y = 330 + i * 140
            text(c, label, 140, y + 18, 30, 600, INK, clamp(kk * 3))
            put(c, rrect(1000, 56, 28, (232, 236, 233)), 760, y + 6, clamp(kk * 3))
            wv = max(56, int(1000 * v * kk))
            put(c, rrect(wv, 56, 28, colour), 760, y + 6, clamp(kk * 3))
            text(
                c,
                f"{v * kk:.2f}",
                760 + wv + 20,
                y + 10,
                36,
                800,
                colour if colour != MUTED else INK,
                clamp(kk * 3),
            )
        if tt > 3.6:
            kk = prog(tt, 3.6, 0.6)
            pill(
                c,
                "Tanzanian UDOM smears: parasite F1 0.48. Harder, and honest about it.",
                140,
                900,
                WARN_STRONG,
                WARN_SOFT,
                24,
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
        "Not a diagnosis, and never treatment advice",
    ]
    k = out_cubic(prog(t, 0.6, 0.7))
    card(c, 150, 330, 780, 520, 28, alpha=k, scale=0.97 + 0.03 * k)
    card(c, 990, 330, 780, 520, 28, fill=(253, 249, 248), alpha=k, scale=0.97 + 0.03 * k)
    text(c, "It is", 200, 370, 36, 800, PRIMARY, k)
    text(c, "It is not", 1040, 370, 36, 800, DANGER, k)
    for i, s in enumerate(left):
        kk = out_cubic(prog(t, 1.2 + i * 0.4, 0.5))
        check(c, 222, 480 + i * 120, 40, True, kk, out_back(kk))
        para(c, s, 262, 462 + i * 120, 27, 600, INK, 620, kk, 1.3)
    for i, s in enumerate(right):
        kk = out_cubic(prog(t, 2.6 + i * 0.4, 0.5))
        check(c, 1062, 480 + i * 120, 40, False, kk, out_back(kk))
        para(c, s, 1102, 462 + i * 120, 27, 600, INK, 620, kk, 1.3)


def s_outro(c: Image.Image, t: float) -> None:
    background(c, t, brand=True)
    k = out_back(prog(t, 0.1, 0.7))
    put(c, disc(120, LIME_SOFT), W / 2, 270, clamp(k), k, "c")
    put(c, disc(80, PRIMARY), W / 2, 270, clamp(k), k, "c")
    put(c, disc(34, LIME_BRIGHT), W / 2, 270, clamp(k), k, "c")
    words(c, "Darubini", W / 2, 360, 130, 800, (255, 255, 255), t, 0.3, center=True)
    words(
        c,
        "A counting instrument, not a diagnosis.",
        W / 2,
        540,
        44,
        700,
        LIME_BRIGHT,
        t,
        0.9,
        center=True,
        stagger=0.05,
    )
    words(
        c,
        "A qualified microscopist confirms every result.",
        W / 2,
        610,
        30,
        400,
        LIME_SOFT,
        t,
        1.4,
        center=True,
        stagger=0.04,
    )
    kk = prog(t, 2.2, 0.6)
    pill(
        c,
        "github.com/albertmwangwa/darubini",
        W / 2,
        720,
        PRIMARY_STRONG,
        LIME_BRIGHT,
        28,
        clamp(kk * 2),
        out_back(kk),
        "c",
    )
    text(
        c,
        "Meta Global AI Developer Hackathon 2026  ·  Indie track",
        W / 2,
        860,
        24,
        500,
        LIME_SOFT,
        out_cubic(prog(t, 2.8, 0.6)),
        "tc",
    )
    if t > 6.2:  # fade to black at the very end
        a = out_cubic(prog(t, 6.2, 0.8))
        c.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, int(255 * a))))


SCENES = [
    (s_hook, 9.0),
    (s_problem, 8.0),
    (s_logo, 6.0),
    (s_app, 14.5),
    (s_detect, 15.0),
    (s_track, 11.0),
    (s_agent, 13.5),
    (s_results, 16.5),
    (s_honest, 7.5),
    (s_outro, 7.0),
]
XFADE = 0.45
STARTS = np.cumsum([0.0] + [d for _, d in SCENES[:-1]]).tolist()
TOTAL = sum(d for _, d in SCENES)


def frame(t: float) -> Image.Image:
    i = max(j for j, s in enumerate(STARTS) if s <= t)
    fn, _ = SCENES[i]
    local = t - STARTS[i]
    cur = Image.new("RGBA", (W, H))
    fn(cur, local)
    if i > 0 and local < XFADE:
        # Zoom-through: the old scene grows and fades, the new one settles in.
        prev = Image.new("RGBA", (W, H))
        SCENES[i - 1][0](prev, SCENES[i - 1][1] + local)
        x = in_out(local / XFADE)
        cur = (
            cur.resize(
                (round(W * (1.04 - 0.04 * x)), round(H * (1.04 - 0.04 * x))), Image.BILINEAR
            ).crop((0, 0, W, H))
            if x < 1
            else cur
        )
        if cur.size != (W, H):
            cur = cur.resize((W, H))
        big = prev.resize((round(W * (1 + 0.08 * x)), round(H * (1 + 0.08 * x))), Image.BILINEAR)
        ox, oy = (big.width - W) // 2, (big.height - H) // 2
        prev = big.crop((ox, oy, ox + W, oy + H))
        cur = Image.blend(prev, cur, x)
    return cur.convert("RGB")


# ---------------------------------------------------------------- audio


def soundtrack(seconds: float) -> np.ndarray:
    """A calm 100 BPM bed: pad chords, soft kick and hats, a whoosh at each scene change."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    beat = 60 / 100
    bar = 4 * beat
    chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]  # Am F C G
    rng = np.random.default_rng(0)
    for b in range(int(seconds / bar) + 1):
        notes = chords[b % 4]
        s0, s1 = int(b * bar * SR), min(n, int((b + 1) * bar * SR))
        if s0 >= n:
            break
        tt = t[s0:s1] - b * bar
        env = np.minimum(1, tt / 0.6) * np.minimum(1, (bar - tt) / 0.5)
        for m in notes:
            fq = 440 * 2 ** ((m - 69) / 12)
            for det in (-0.12, 0.12):
                out[s0:s1] += 0.035 * env * np.sin(2 * np.pi * fq * (1 + det / 100) * tt)
        bass = 440 * 2 ** ((notes[0] - 12 - 69) / 12)
        out[s0:s1] += 0.06 * env * np.sin(2 * np.pi * bass * tt)
    for k in range(int(seconds / beat)):
        s0 = int(k * beat * SR)
        if k >= 8 and k % 1 == 0:  # kick from bar 3
            ln = int(0.25 * SR)
            tk = np.arange(min(ln, n - s0)) / SR
            out[s0 : s0 + len(tk)] += (
                0.22 * np.exp(-tk * 18) * np.sin(2 * np.pi * (45 + 80 * np.exp(-tk * 30)) * tk)
            )
        h0 = int((k + 0.5) * beat * SR)
        if k >= 8 and h0 < n:
            ln = min(int(0.05 * SR), n - h0)
            out[h0 : h0 + ln] += 0.03 * rng.standard_normal(ln) * np.exp(-np.arange(ln) / SR * 90)
    for s in STARTS[1:]:  # whooshes
        ln = int(0.7 * SR)
        s0 = int((s - 0.4) * SR)
        if s0 + ln > n:
            continue
        noise = rng.standard_normal(ln)
        from scipy.signal import lfilter

        env = np.sin(np.linspace(0, np.pi, ln)) ** 2
        lp = lfilter([0.08], [1, -0.92], noise)
        out[s0 : s0 + ln] += 0.35 * env * lp
    fade = np.minimum(1, t / 1.5) * np.minimum(1, (seconds - t) / 2.0)
    out *= fade
    out /= max(1e-9, np.abs(out).max()) / 0.6
    return out.astype(np.float32)


# ---------------------------------------------------------------- assets

#: A development field (NIH val) where hybrid detection matches the expert closely.
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
    # The held-out test slide whose density came closest to the expert's.
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


# ---------------------------------------------------------------- render


def render(path: Path, start: float = 0.0, end: float | None = None) -> None:
    import av

    end = TOTAL if end is None else end
    with av.open(str(path), "w") as out:
        v = out.add_stream("libx264", rate=FPS)
        v.width, v.height, v.pix_fmt = W, H, "yuv420p"
        v.options = {"crf": "19", "preset": "medium", "tune": "animation"}
        a = out.add_stream("aac", rate=SR)
        a.layout = "mono"
        n = int((end - start) * FPS)
        for i in range(n):
            t = start + i / FPS
            vf = av.VideoFrame.from_image(frame(t))
            for p in v.encode(vf):
                out.mux(p)
            if i % (FPS * 5) == 0:
                print(f"  {t:6.1f} / {end:.1f} s", flush=True)
        for p in v.encode(None):
            out.mux(p)
        audio = soundtrack(end - start)
        hop = 1024
        for k in range(0, len(audio), hop):
            chunk = audio[k : k + hop]
            af = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="flt", layout="mono")
            af.sample_rate = SR
            af.pts = k
            af.time_base = Fraction(1, SR)
            for p in a.encode(af):
                out.mux(p)
        for p in a.encode(None):
            out.mux(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true", help="write the field and report assets")
    ap.add_argument(
        "--still", type=float, nargs="*", help="render frames at these times (s) as PNG"
    )
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    args = ap.parse_args()
    if args.prepare:
        prepare()
        return 0
    DATA.update(load_data())
    if args.still:
        for s in args.still:
            p = ASSETS / f"still_{s:05.1f}.png"
            frame(s).save(p)
            print(p)
        return 0
    print(f"Rendering {TOTAL:.1f} s at {W}x{H}, {FPS} fps to {args.out}")
    render(args.out, args.start, args.end)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
