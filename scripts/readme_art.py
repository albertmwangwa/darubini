"""Draw the README's banner, architecture diagram and results card in the proposal palette.

Uses the demo video's drawing helpers, so the README, app and video look like one product.
The banner's field and detections are real (NIH development field TF44_UW16); the numbers on
the results card come from docs/calibration/final_test.md.

    python scripts/demo_video.py --prepare   # once: the field image and detections
    python scripts/readme_art.py             # docs/assets/{banner,architecture,results}.png
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_video as v

OUT = v.ROOT / "docs" / "assets"


def banner() -> Image.Image:
    c = Image.new("RGBA", (1920, 640))
    v.background(c, 2.0, "brand")
    v.put(c, v.disc(96, v.PRIMARY_SOFT), 172, 150, 1, 1, "c")
    v.put(c, v.disc(64, v.PRIMARY), 172, 150, 1, 1, "c")
    v.put(c, v.disc(26, v.CHART_4), 172, 150, 1, 1, "c")
    v.text(c, "Darubini", 240, 96, 104, 800, v.WHITE)
    v.para(
        c,
        "A malaria microscopy copilot. A phone or a microscope camera counts the parasites, "
        "Meta's models check the work, and the report comes out in Kiswahili or English.",
        126,
        260,
        34,
        500,
        v.PRIMARY_SOFT,
        980,
        1,
        1.35,
    )
    x = 126
    for s in ("SAM 3.1", "Muse Spark", "Muse Voice Transcribe", "Muse Spark Open"):
        x += v.pill(c, s, x, 470, v.PRIMARY_INK, v.WHITE, 24) + 16
    # A real field with its real detections
    f = json.loads((v.ASSETS / "field.json").read_text())
    size, cx, cy = 470, 1560, 320
    field = v.image(str(v.ASSETS / "field.jpg"), size, size, size // 2, 1.25).copy()
    d = ImageDraw.Draw(field)
    s, off = size * 1.25 / 1000, (size * 1.25 - size) / 2
    for b in f["parasites"]:
        x0, y0, x1, y1 = (q * s - off for q in b)
        r = max(9, (x1 - x0) * 0.9)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        d.ellipse((mx - r, my - r, mx + r, my + r), outline=(*v.PARASITE, 255), width=3)
    for b in f["wbcs"]:
        x0, y0, x1, y1 = (q * s - off for q in b)
        d.rounded_rectangle((x0, y0, x1, y1), 5, outline=(*v.WBC, 255), width=3)
    field.putalpha(v.disc(size, v.WHITE).split()[3])
    v.put(c, v.shadow(size, size, size // 2, 40, 90), cx, cy + 12, 1, 1, "c")
    v.put(c, v.disc(size + 24, v.WHITE), cx, cy, 1, 1, "c")
    v.put(c, field, cx, cy, 1, 1, "c")
    v.pill(
        c,
        f"{len(f['parasites'])} parasites  ·  {len(f['wbcs'])} white blood cells",
        cx,
        575,
        v.PRIMARY_INK,
        v.WHITE,
        22,
        1,
        1,
        "c",
        dot=v.PARASITE,
    )
    return c


def node(
    c: Image.Image, x: int, y: int, w: int, h: int, title: str, body: str, meta: str | None = None
) -> None:
    """A pipeline step; Meta-model steps get a blue frame and a model chip."""
    if meta:
        v.card(c, x, y, w, h, 20, fill=v.PRIMARY_SOFT, border=False)
        v.put(c, v.rrect(w, h, 20, v.PRIMARY_SOFT, v.PRIMARY, 2), x + w / 2, y + h / 2, 1, 1, "c")
        v.pill(c, meta, x + 16, y + 14, v.WHITE, v.PRIMARY, 17)
        ty = y + 62
    else:
        v.card(c, x, y, w, h, 20)
        ty = y + 22
    v.text(c, title, x + 18, ty, 25, 800, v.INK)
    v.para(c, body, x + 18, ty + 38, 18, 500, v.MUTED, w - 34, 1, 1.35)


def arrow(
    c: Image.Image,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    label: str | None = None,
    via: list[tuple[float, float]] | None = None,
    head: bool = True,
) -> None:
    """An arrow from (x0, y0) to (x1, y1), optionally bent through ``via`` points."""
    import math

    layer = Image.new("RGBA", (1920, 1080), (*v.PRIMARY, 0))
    d = ImageDraw.Draw(layer)
    pts = [(x0, y0), *(via or []), (x1, y1)]
    d.line(pts, fill=(*v.MUTED, 255), width=3, joint="curve")
    if not head:
        v.put(c, layer, 0, 0)
        return
    px, py = pts[-2]
    a = math.atan2(y1 - py, x1 - px)
    tip = [
        (x1, y1),
        (x1 - 14 * math.cos(a - 0.45), y1 - 14 * math.sin(a - 0.45)),
        (x1 - 14 * math.cos(a + 0.45), y1 - 14 * math.sin(a + 0.45)),
    ]
    d.polygon(tip, fill=(*v.MUTED, 255))
    v.put(c, layer, 0, 0)
    if label:
        v.pill(c, label, (x0 + x1) / 2, (y0 + y1) / 2 - 18, v.MUTED, v.SURFACE, 15, 1, 1, "c")


def architecture() -> Image.Image:
    c = Image.new("RGBA", (1920, 1080))
    v.background(c, 1.0)
    v.text(c, "HOW DARUBINI WORKS", 80, 54, 22, 700, v.PRIMARY)
    v.text(c, "From a field of view to a checked, bilingual report", 80, 88, 44, 800, v.INK)
    # Row 1: capture -> server -> quality gate
    node(
        c,
        80,
        200,
        330,
        190,
        "Capture",
        "Phone app (Android) or web app with a USB / trinocular microscope camera: photos or a panning clip",
    )
    node(
        c,
        80,
        430,
        330,
        160,
        "Voice",
        "“Next field”, “retake”, “finish”, “note…”",
        "Muse Voice Transcribe",
    )
    node(
        c,
        520,
        200,
        330,
        190,
        "Darubini server",
        "FastAPI, /v1/sessions. Each upload is analysed at once and the reply says what to do next",
    )
    node(
        c,
        960,
        200,
        330,
        190,
        "Quality gate",
        "Focus, exposure and stain checks. Unusable fields are rejected with a reason to retake",
    )
    # Row 2: detection
    node(
        c,
        960,
        470,
        330,
        190,
        "Parasite candidates",
        "Every spot that absorbs green light, as Giemsa chromatin does",
    )
    node(
        c,
        1400,
        470,
        420,
        190,
        "Verifier network",
        "16×16 crop + 8 shape features → 64 hidden → parasite? (threshold 0.75)",
    )
    node(
        c,
        1400,
        200,
        420,
        190,
        "White blood cells",
        "Text prompt “cell”, tiled; the WBC count sets the density",
        "SAM 3.1",
    )
    node(
        c,
        520,
        470,
        330,
        190,
        "Pan tracking",
        "Keyframe detections followed through the clip: each cell counted once",
        "SAM 3.1 video",
    )
    # Row 3: count -> agent -> report
    node(
        c,
        80,
        760,
        360,
        200,
        "Counting engine",
        "WHO thick-film rule: count to 200 WBC (500 if few parasites); density = 8,000 × parasites / WBC",
    )
    node(
        c,
        560,
        740,
        560,
        240,
        "Counting agent",
        "Tools: examine fields, second opinion on quality, exclude a field, audit 20 sampled parasites, check the count, finish. It never sets a number",
        "Muse Spark",
    )
    node(
        c,
        1240,
        760,
        300,
        200,
        "Report",
        "English or Kiswahili, plus the audit flag and excluded fields",
    )
    node(
        c,
        1600,
        760,
        240,
        200,
        "Microscopist",
        "Confirms every result. A counting instrument, not a diagnosis",
    )
    arrow(c, 410, 295, 520, 295, "upload")
    arrow(c, 245, 430, 245, 390)
    arrow(c, 850, 295, 960, 295)
    arrow(c, 1290, 295, 1400, 295)
    arrow(c, 1125, 390, 1125, 470)
    arrow(c, 1290, 565, 1400, 565)
    arrow(c, 685, 390, 685, 470, "clip")
    arrow(c, 1610, 390, 1610, 470, "drop cells inside WBC")
    arrow(c, 1610, 660, 260, 760, "parasites + WBC", via=[(1610, 705), (260, 705)])
    arrow(c, 685, 660, 685, 705, head=False)
    arrow(c, 440, 860, 560, 860)
    arrow(c, 1120, 860, 1240, 860)
    arrow(c, 1540, 860, 1600, 860)
    v.put(c, v.rrect(30, 18, 6, v.PRIMARY_SOFT, v.PRIMARY, 2), 1250, 1036, 1, 1, "c")
    v.text(c, "Meta model", 1274, 1023, 20, 600, v.INK)
    v.put(c, v.rrect(30, 18, 6, v.CARD, v.BORDER, 2), 1460, 1036, 1, 1, "c")
    v.text(c, "Deterministic Darubini code", 1484, 1023, 20, 600, v.INK)
    return c


def results() -> Image.Image:
    c = Image.new("RGBA", (1920, 900))
    v.background(c, 3.0)
    v.text(c, "HELD-OUT TEST SET  ·  SCORED ONCE", 80, 54, 22, 700, v.PRIMARY)
    v.text(c, "Accuracy on patients it never saw", 80, 88, 44, 800, v.INK)
    for i, (big, head, sub) in enumerate(v.METRICS):
        x = 80 + i * 450
        hero = i == 1
        v.card(c, x, 190, 420, 250, 26, fill=v.PRIMARY if hero else v.CARD, border=not hero)
        v.text(c, big, x + 32, 214, 84, 800, v.WHITE if hero else v.PRIMARY)
        v.text(c, head, x + 34, 342, 28, 800, v.WHITE if hero else v.INK)
        v.text(c, sub, x + 34, 384, 21, 400, v.PRIMARY_SOFT if hero else v.MUTED)
    v.text(c, "Parasite F1 on held-out NIH fields: what each part adds", 80, 490, 26, 800, v.INK)
    for i, (label, val, colour) in enumerate(v.BARS):
        y = 545 + i * 66
        v.text(c, label, 80, y + 8, 24, 600, v.INK)
        v.put(c, v.rrect(1000, 40, 20, v.SURFACE), 640, y + 4)
        v.put(c, v.rrect(int(1000 * val), 40, 20, colour), 640, y + 4)
        v.text(
            c,
            f"{val:.2f}",
            640 + int(1000 * val) + 16,
            y + 4,
            28,
            800,
            v.INK if colour in (v.MUTED, v.CHART_4) else colour,
        )
    v.pill(
        c,
        "Tanzanian UDOM smears: F1 0.48. NM-AIST whole 4K frames: failed (scale). Not a screen.",
        80,
        830,
        v.WARN,
        v.WARN_SOFT,
        20,
    )
    return c


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("banner", banner), ("architecture", architecture), ("results", results)):
        im = fn().convert("RGB")
        im.save(OUT / f"{name}.png", optimize=True)
        print(OUT / f"{name}.png", im.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
