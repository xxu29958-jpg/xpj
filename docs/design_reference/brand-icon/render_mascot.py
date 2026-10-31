"""Render 夹夹, the mascot: a little crab that keeps a 票根.

A crab's claws 夹 (hold) things, so 夹夹 is literally the 小票夹: it keeps the brand stub in
its claw. Two states, as MascotArt maps them:
  dozing       hugs its 票根 and naps, blowing bubbles
  celebrating  holds the 票根 up and cheers (debt settled, plan goal reached)

Outputs (paths relative to the repository root):
  android/app/src/main/res/drawable/mascot_{dozing,celebrating}_{paper,midnight}.xml

  python docs/design_reference/brand-icon/render_mascot.py [--preview board.png --chromium /path/to/chrome]
"""
from __future__ import annotations

import argparse
import math

from PIL import Image
from render_art import PALETTE as ART
from render_art import ellipse
from render_icons import ROOT, Chromium, Stub, num, vd_colour

VIEW = 120
INK = "#0D3D38"
PALETTE = {
    "paper": {**ART["paper"], "deep": "#B9432B", "freckle": "#EC7A5F", "ink": INK,
              "blush": "#FFD2C2", "blush_alpha": 0.75, "bubble": "#7FAE9F"},
    "midnight": {**ART["midnight"], "deep": "#C24A31", "freckle": "#F38A6F", "ink": INK,
                 "blush": "#FFD2C2", "blush_alpha": 0.75, "bubble": "#7FAE9F"},
}
PREVIEW_BG = {"paper": "#FAFBF7", "midnight": "#16201C"}  # ThemeVisuals page backgrounds


# A layer is a path with a fill role and/or a stroke (role, width), or a group of layers.
def fill(role: str, d: str, stroke: tuple | None = None) -> dict:
    return {"d": d, "fill": role, "stroke": stroke}


def line(role: str, width: float, d: str) -> dict:
    return {"d": d, "stroke": (role, width)}


def group(children: list, tx: float = 0, ty: float = 0, rot: float = 0) -> dict:
    return {"children": children, "t": (tx, ty, rot)}


# ---- Parts ------------------------------------------------------------------------------
SHELL = "M28,84C28,64 43,57 60,57C77,57 92,64 92,84C92,97 79,103 60,103C41,103 28,97 28,84Z"
FRECKLES = (ellipse(41, 70, 1.9, 1.6) + ellipse(46.5, 65.5, 1.4, 1.2)
            + ellipse(79, 70, 1.9, 1.6) + ellipse(73.5, 65.5, 1.4, 1.2))
BLUSH = ellipse(43, 84, 5.2, 3.2) + ellipse(77, 84, 5.2, 3.2)


def kept_stub(tx: float, ty: float, w: float, h: float, rot: float) -> dict:
    """The brand stub (render_icons.Stub) in the claw; the tail is leaf because the claw is coral."""
    s = Stub(w=w, h=h, r=2.2, cut=h * 0.2, notch=2)
    return group([fill("paper", s.silhouette(), ("edge", 1.1)), fill("leaf", s.tail())], tx, ty, rot)


def claw(cx: float, cy: float, r: float, facing: float, outline: bool = False) -> dict:
    """A round pincer: a disc with a notch that opens toward `facing` degrees."""
    a1, a2, f = (math.radians(facing + s) for s in (-32, 32, 0))
    d = (f"M{num(cx + r * .25 * math.cos(f))},{num(cy + r * .25 * math.sin(f))}"
         f"L{num(cx + r * math.cos(a1))},{num(cy + r * math.sin(a1))}"
         f"A{num(r)},{num(r)} 0 1,0 {num(cx + r * math.cos(a2))},{num(cy + r * math.sin(a2))}Z")
    return fill("coral", d, ("deep", 1.8) if outline else None)


def legs(dangle: bool) -> list:
    d = ""
    for side in (-1, 1):
        for i, (y, dx) in enumerate(((88, 7), (94, 6), (99, 4.5))):
            x0 = 60 + side * (30 - i * 2.5)
            x1 = x0 + side * dx
            d += f"M{num(x0)},{y}Q{num(x1)},{y} {num(x1)},{y + (8 if dangle else 6)}"
    return [line("deep", 3.4, d)]


def eyes(awake: bool) -> list:
    """Eyes on short stalks: upright and curved up to cheer, flopped outward and closed to doze."""
    tips = ((46, 46), (74, 46)) if awake else ((42, 53), (78, 53))
    bases = ((50, 60), (70, 60)) if awake else ((51, 60), (69, 60))
    stalks = "".join(f"M{x0},{y0}Q{x0},{min(y0, y1) - 3} {x1},{y1}" for (x0, y0), (x1, y1) in zip(bases, tips, strict=True))
    lids = "".join(f"M{num(x - 3.6)},{num(y + 1.4)}Q{x},{num(y - 4.2)} {num(x + 3.6)},{num(y + 1.4)}" if awake else
                   f"M{num(x - 3.6)},{y}Q{x},{num(y + 3.6)} {num(x + 3.6)},{y}" for x, y in tips)
    return [line("deep", 4, stalks),
            fill("paper", "".join(ellipse(x, y, 7, 7) for x, y in tips), ("deep", 2.4)),
            line("ink", 2.5 if awake else 2.4, lids)]


def body(awake: bool) -> list:
    face = ([fill("ink", "M55.6,82H64.4Q64.4,89.4 60,89.4Q55.6,89.4 55.6,82Z"), fill("freckle", ellipse(60, 87.4, 2.6, 1.6))]
            if awake else [line("ink", 1.9, "M56.6,82Q58.3,84.4 60,82Q61.7,84.4 63.4,82")])
    return [fill("coral", SHELL), fill("freckle", FRECKLES), fill("blush", BLUSH), *face]


def sparkle(x: float, y: float, s: float) -> str:
    k = s * .18
    return (f"M{num(x)},{num(y - s)}Q{num(x + k)},{num(y - k)} {num(x + s)},{num(y)}"
            f"Q{num(x + k)},{num(y + k)} {num(x)},{num(y + s)}Q{num(x - k)},{num(y + k)} {num(x - s)},{num(y)}"
            f"Q{num(x - k)},{num(y - k)} {num(x)},{num(y - s)}Z")


MASCOT = {
    "dozing": [
        fill("shadow", ellipse(60, 106, 36, 3.6)),
        *legs(dangle=False), *eyes(awake=False), *body(awake=False),
        kept_stub(60, 95, 13, 19, -6),                      # hugged like a pillow
        claw(46, 95, 9.5, -20, outline=True), claw(74, 95, 9.5, 200, outline=True),
        line("bubble", 1.6, ellipse(86, 62, 4, 4)), line("bubble", 1.8, ellipse(94, 49, 6, 6)),
        fill("bubble", ellipse(92.2, 46.8, 1.6, 1.2)),
    ],
    "celebrating": [
        fill("shadow", ellipse(60, 108, 28, 3)),
        group([
            *legs(dangle=True),
            line("deep", 4.4, "M33,80Q22,70 22,56M87,80Q98,70 98,58"),
            kept_stub(20, 33, 15, 22, -12),                 # held up high
            claw(21, 50, 10, -95), claw(99, 50, 10, -80),
            *eyes(awake=True), *body(awake=True),
        ], ty=-5),
        fill("leaf", sparkle(44, 22, 4.6) + sparkle(110, 74, 3.4) + ellipse(83, 14, 2.2, 2.2)),
        fill("coral", sparkle(104, 24, 5) + ellipse(60, 10, 2, 2) + ellipse(10, 70, 2, 2)),
    ],
}


# ---- Writers ----------------------------------------------------------------------------
def _stroke(layer: dict, colours: dict) -> tuple | None:
    """A stroke in the fill's own colour adds nothing (midnight's stub edge), so it is dropped."""
    stroke = layer.get("stroke")
    if stroke and layer.get("fill") and colours[stroke[0]] == colours[layer["fill"]]:
        return None
    return stroke


def vd_layers(layers: list, colours: dict, indent: str = "    ") -> list[str]:
    out = []
    for layer in layers:
        if "children" in layer:
            tx, ty, rot = layer["t"]
            attrs = [a for v, a in ((tx, f'android:translateX="{num(tx)}"'), (ty, f'android:translateY="{num(ty)}"'),
                                    (rot, f'android:rotation="{num(rot)}"')) if v]
            out.append(f"{indent}<group" + "".join(f"\n{indent}    {a}" for a in attrs) + ">")
            out += vd_layers(layer["children"], colours, indent + "    ")
            out.append(f"{indent}</group>")
            continue
        attrs = []
        if layer.get("fill"):
            attrs.append(f'android:fillColor="{vd_colour(colours[layer["fill"]])}"')
            if f'{layer["fill"]}_alpha' in colours:
                attrs.append(f'android:fillAlpha="{num(colours[layer["fill"] + "_alpha"])}"')
        stroke = _stroke(layer, colours)
        if stroke:
            attrs += [f'android:strokeColor="{vd_colour(colours[stroke[0]])}"', f'android:strokeWidth="{num(stroke[1])}"',
                      'android:strokeLineCap="round"', 'android:strokeLineJoin="round"']
        out.append(f"{indent}<path" + "".join(f"\n{indent}    {a}" for a in attrs)
                   + f'\n{indent}    android:pathData="{layer["d"]}" />')
    return out


def vector(state: str, skin: str) -> str:
    return "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        f"<!-- 夹夹 mascot, {state}, {skin}. Generated by docs/design_reference/brand-icon/render_mascot.py;",
        "     edit the generator, not this file. -->",
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"',
        f'    android:width="{VIEW}dp"', f'    android:height="{VIEW}dp"',
        f'    android:viewportWidth="{VIEW}"', f'    android:viewportHeight="{VIEW}">',
        *vd_layers(MASCOT[state], PALETTE[skin]),
        "</vector>",
    ]) + "\n"


def svg_layers(layers: list, colours: dict) -> str:
    out = ""
    for layer in layers:
        if "children" in layer:
            tx, ty, rot = layer["t"]
            out += f'<g transform="translate({num(tx)} {num(ty)}) rotate({num(rot)})">'
            out += svg_layers(layer["children"], colours) + "</g>"
            continue
        role = layer.get("fill")
        attrs = f' fill="{colours[role]}"' if role else ' fill="none"'
        if f"{role}_alpha" in colours:
            attrs += f' fill-opacity="{num(colours[role + "_alpha"])}"'
        stroke = _stroke(layer, colours)
        if stroke:
            attrs += (f' stroke="{colours[stroke[0]]}" stroke-width="{num(stroke[1])}"'
                      ' stroke-linecap="round" stroke-linejoin="round"')
        out += f'<path d="{layer["d"]}"{attrs}/>'
    return out


def svg(state: str, skin: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW} {VIEW}">'
            f"{svg_layers(MASCOT[state], PALETTE[skin])}</svg>")


def preview(path: str, chromium: str | None, size: int = 360) -> None:
    chrome = Chromium(chromium)
    try:
        board = Image.new("RGBA", (size * len(MASCOT), size * len(PALETTE)))
        for row, skin in enumerate(PALETTE):
            for col, state in enumerate(MASCOT):
                board.paste(Image.new("RGBA", (size, size), PREVIEW_BG[skin]), (col * size, row * size))
                board.alpha_composite(chrome.png(svg(state, skin), size), (col * size, row * size))
        board.save(path)
    finally:
        chrome.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", help="also write a states × skins board PNG here")
    parser.add_argument("--chromium", help="Chromium/Chrome executable for --preview (defaults to Playwright's)")
    args = parser.parse_args()
    res = ROOT / "android/app/src/main/res/drawable"
    for state in MASCOT:
        for skin in PALETTE:
            (res / f"mascot_{state}_{skin}.xml").write_text(vector(state, skin), encoding="utf-8")
    if args.preview:
        preview(args.preview, args.chromium)


if __name__ == "__main__":
    main()
