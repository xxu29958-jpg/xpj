"""Render every shipped Ticketbox icon from one geometry source (direction A · 票根 Pair).

Outputs (paths relative to the repository root):
  android/app/src/main/res/drawable/ic_launcher_foreground.xml
  android/app/src/main/res/drawable/ic_launcher_monochrome.xml
  android/app/src/main/res/drawable/ic_notification_receipt.xml
  backend/packaging/ticketbox.ico                     (Manager/lifecycle exe, Start menu, installer)
  backend/app/static/web/product/brand/*.png          (favicon, PWA, sidebar mark)
  docs/design_reference/brand-icon/masters/*.svg      (editable masters)

Needs Pillow and Playwright's Chromium (the same browser the Web journey tests use):
  python docs/design_reference/brand-icon/render_icons.py --chromium /path/to/chrome
"""
from __future__ import annotations

import argparse
import base64
import io
import math
import struct
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

INK = "#0D3D38"      # brand-primary-strong: adaptive background and plate
INK_LIFT = "#14504A"  # plate on the midnight sidebar
LEAF = "#2B6E5C"     # the second stub
CREAM = "#F7F1E3"    # paper body
CORAL = "#E0583B"    # the kept tail — successor of the coral side clip


def num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def circle(cx: float, cy: float, r: float) -> str:
    return (f"M{num(cx + r)},{num(cy)}A{num(r)},{num(r)} 0 1,0 {num(cx - r)},{num(cy)}"
            f"A{num(r)},{num(r)} 0 1,0 {num(cx + r)},{num(cy)}Z")


class Stub:
    """Vertical ticket stub centred on the origin: paper body, tear line with side notches, kept tail."""

    def __init__(self, w: float, h: float, r: float, cut: float, notch: float, gap: float = 0):
        self.w, self.h, self.r, self.cut, self.notch, self.gap = w, h, r, cut, notch, gap

    def _dx(self) -> float:
        return math.sqrt(max(self.notch ** 2 - (self.gap / 2) ** 2, 0))

    def silhouette(self) -> str:
        w2, h2, r, n, cy = self.w / 2, self.h / 2, self.r, self.notch, self.cut
        return (f"M{num(-w2 + r)},{num(-h2)}H{num(w2 - r)}A{num(r)},{num(r)} 0 0,1 {num(w2)},{num(-h2 + r)}"
                f"V{num(cy - n)}A{num(n)},{num(n)} 0 0,0 {num(w2)},{num(cy + n)}V{num(h2 - r)}"
                f"A{num(r)},{num(r)} 0 0,1 {num(w2 - r)},{num(h2)}H{num(-w2 + r)}"
                f"A{num(r)},{num(r)} 0 0,1 {num(-w2)},{num(h2 - r)}V{num(cy + n)}"
                f"A{num(n)},{num(n)} 0 0,0 {num(-w2)},{num(cy - n)}V{num(-h2 + r)}"
                f"A{num(r)},{num(r)} 0 0,1 {num(-w2 + r)},{num(-h2)}Z")

    def body(self) -> str:
        w2, h2, r, n, cy = self.w / 2, self.h / 2, self.r, self.notch, self.cut
        yb, dx = cy - self.gap / 2, self._dx()
        return (f"M{num(-w2 + r)},{num(-h2)}H{num(w2 - r)}A{num(r)},{num(r)} 0 0,1 {num(w2)},{num(-h2 + r)}"
                f"V{num(cy - n)}A{num(n)},{num(n)} 0 0,0 {num(w2 - dx)},{num(yb)}H{num(-w2 + dx)}"
                f"A{num(n)},{num(n)} 0 0,0 {num(-w2)},{num(cy - n)}V{num(-h2 + r)}"
                f"A{num(r)},{num(r)} 0 0,1 {num(-w2 + r)},{num(-h2)}Z")

    def tail(self) -> str:
        w2, h2, r, n, cy = self.w / 2, self.h / 2, self.r, self.notch, self.cut
        yt, dx = cy + self.gap / 2, self._dx()
        return (f"M{num(-w2 + dx)},{num(yt)}H{num(w2 - dx)}A{num(n)},{num(n)} 0 0,0 {num(w2)},{num(cy + n)}"
                f"V{num(h2 - r)}A{num(r)},{num(r)} 0 0,1 {num(w2 - r)},{num(h2)}H{num(-w2 + r)}"
                f"A{num(r)},{num(r)} 0 0,1 {num(-w2)},{num(h2 - r)}V{num(cy + n)}"
                f"A{num(n)},{num(n)} 0 0,0 {num(-w2 + dx)},{num(yt)}Z")

    def perforation(self, count: int = 4, r: float = 1.2, lift: float = 2.5) -> str:
        step = (self.w - 2 * self.notch) / (count + 1)
        return "".join(circle(-self.w / 2 + self.notch + step * (i + 1), self.cut - lift, r) for i in range(count))


# ---- Composition on Android's 108-unit adaptive canvas --------------------------------
FRONT = Stub(w=30, h=52, r=4.2, cut=9, notch=5.5)
FRONT_MONO = Stub(w=30, h=52, r=4.2, cut=9, notch=5.5, gap=1.6)
FRONT_AT = {"tx": 50, "ty": 56, "rot": -10, "scale": 1}
BACK_AT = {"tx": 64, "ty": 45, "rot": 18, "scale": 0.9}
# Fits the pair inside the launcher's visible circle (r 34.2 of 36); the front stub stays in the 33 safe zone.
COMP = {"px": 54, "py": 54, "tx": -1.5, "ty": 1.0, "scale": 0.92}


def node(paths: list[tuple], **t) -> dict:
    return dict(paths=paths, **t)


def pair(mono: bool) -> dict:
    """paths are (d, colour, alpha, evenodd). Colour: the tail overlays the body; mono: a tear gap splits them."""
    if mono:
        white = "#FFFFFF"
        back = node([(FRONT.silhouette(), white, 0.5, False)], **BACK_AT)
        fore = node([(FRONT_MONO.body() + FRONT_MONO.perforation(), white, 1, True),
                     (FRONT_MONO.tail(), white, 1, False)], **FRONT_AT)
    else:
        back = node([(FRONT.silhouette(), LEAF, 1, False)], **BACK_AT)
        fore = node([(FRONT.silhouette() + FRONT.perforation(), CREAM, 1, True),
                     (FRONT.tail(), CORAL, 1, False)], **FRONT_AT)
    return dict(children=[back, fore], **COMP)


def svg_group(g: dict) -> str:
    px, py = g.get("px", 0), g.get("py", 0)
    tf = (f"translate({num(px + g['tx'])} {num(py + g['ty'])}) rotate({num(g.get('rot', 0))}) "
          f"scale({num(g['scale'])}) translate({num(-px)} {num(-py)})")
    inner = "".join(svg_group(c) for c in g.get("children", []))
    for d, colour, alpha, evenodd in g.get("paths", []):
        attrs = ' fill-rule="evenodd"' if evenodd else ""
        attrs += f' fill-opacity="{num(alpha)}"' if alpha != 1 else ""
        inner += f'<path d="{d}" fill="{colour}"{attrs}/>'
    return f'<g transform="{tf}">{inner}</g>'


def vd_colour(hex_rgb: str) -> str:
    return "#FF" + hex_rgb.lstrip("#").upper()


def vd_group(g: dict, indent: str = "    ") -> str:
    attrs = []
    if g.get("px"):
        attrs += [f'android:pivotX="{num(g["px"])}"', f'android:pivotY="{num(g["py"])}"']
    attrs += [f'android:translateX="{num(g["tx"])}"', f'android:translateY="{num(g["ty"])}"']
    if g.get("rot"):
        attrs.append(f'android:rotation="{num(g["rot"])}"')
    if g["scale"] != 1:
        attrs += [f'android:scaleX="{num(g["scale"])}"', f'android:scaleY="{num(g["scale"])}"']
    lines = [f"{indent}<group", *[f"{indent}    {a}" for a in attrs[:-1]], f"{indent}    {attrs[-1]}>"]
    for c in g.get("children", []):
        lines.append(vd_group(c, indent + "    "))
    for d, colour, alpha, evenodd in g.get("paths", []):
        p = [f"{indent}    <path", f'{indent}        android:fillColor="{vd_colour(colour)}"']
        if alpha != 1:
            p.append(f'{indent}        android:fillAlpha="{num(alpha)}"')
        if evenodd:
            p.append(f'{indent}        android:fillType="evenOdd"')
        p.append(f'{indent}        android:pathData="{d}" />')
        lines += p
    lines.append(f"{indent}</group>")
    return "\n".join(lines)


def vector(comment: str, body: str, size_dp: int = 108, viewport: int = 108) -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<!-- {comment}\n     Generated by '
            f'docs/design_reference/brand-icon/render_icons.py; edit the generator, not this file. -->\n'
            f'<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
            f'    android:width="{size_dp}dp"\n    android:height="{size_dp}dp"\n'
            f'    android:viewportWidth="{viewport}"\n    android:viewportHeight="{viewport}">\n{body}\n</vector>\n')


# ---- Status-bar icon: one upright stub, tear gap instead of colour --------------------
STATUS = Stub(w=12, h=20, r=2, cut=5, notch=2.2, gap=1.2)


def status_paths() -> str:
    d = STATUS.body() + STATUS.perforation(count=2, r=0.75, lift=2.1)
    return (f'    <group android:translateX="12" android:translateY="12">\n'
            f'        <path\n            android:fillColor="#FFFFFFFF"\n            android:fillType="evenOdd"\n'
            f'            android:pathData="{d}" />\n'
            f'        <path\n            android:fillColor="#FFFFFFFF"\n            android:pathData="{STATUS.tail()}" />\n'
            f'    </group>')


# ---- SVG documents --------------------------------------------------------------------
def svg_doc(view_box: str, body: str, defs: str = "") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">{defs}{body}</svg>'


def plated(plate: str = INK, radius: float = 16, view_box: str = "16 16 76 76", holes: bool = True) -> str:
    art = pair(mono=False)
    if not holes:  # perforation holes are ~1.5 px at 48 px and read as grey specks; drop them below 64
        art["children"][1]["paths"][0] = (FRONT.silhouette(), CREAM, 1, False)
    clip = f'<clipPath id="p"><rect x="18" y="18" width="72" height="72" rx="{num(radius)}"/></clipPath>'
    body = (f'<rect x="18" y="18" width="72" height="72" rx="{num(radius)}" fill="{plate}"/>'
            f'<g clip-path="url(#p)">{svg_group(art)}</g>')
    return svg_doc(view_box, body, f"<defs>{clip}</defs>")


def full_bleed(view_box: str) -> str:
    return svg_doc(view_box, f'<rect width="108" height="108" fill="{INK}"/>{svg_group(pair(mono=False))}')


HINTED = {  # pixel-grid drawings: whole-pixel edges, upright stub, notch on the tear line
    16: {"plate_r": 3.5, "x": 5, "y": 2, "w": 6, "h": 12, "cut": 9, "n": 1.3, "back": (10, 1, 4, 10), "r": 1},
    20: {"plate_r": 4.5, "x": 5, "y": 3, "w": 8, "h": 14, "cut": 10, "n": 1.6, "back": (11, 2, 6, 13), "r": 1.2},
    24: {"plate_r": 5.5, "x": 6, "y": 3, "w": 10, "h": 18, "cut": 13, "n": 1.9, "back": (13, 2, 7, 16), "r": 1.5},
}


def hinted(px: int) -> str:
    s = HINTED[px]
    x, y, w, h, cut, n, r = s["x"], s["y"], s["w"], s["h"], s["cut"], s["n"], s["r"]
    bx, by, bw, bh = s["back"]
    body = (f'<rect width="{px}" height="{px}" rx="{s["plate_r"]}" fill="{INK}"/>'
            f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="{r}" fill="{LEAF}"/>'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{CREAM}"/>'
            f'<path d="M{x},{cut}H{x + w}V{num(y + h - r)}A{r},{r} 0 0,1 {num(x + w - r)},{y + h}H{num(x + r)}'
            f'A{r},{r} 0 0,1 {x},{num(y + h - r)}Z" fill="{CORAL}"/>'
            f'<circle cx="{x}" cy="{cut}" r="{n}" fill="{INK}"/><circle cx="{x + w}" cy="{cut}" r="{n}" fill="{INK}"/>')
    return svg_doc(f"0 0 {px} {px}", body)


# ---- Raster + ICO -----------------------------------------------------------------------
class Chromium:
    def __init__(self, executable: str | None):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(executable_path=executable)
        self._page = self._browser.new_page(device_scale_factor=1)

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()

    def png(self, svg: str, size: int) -> Image.Image:
        data = base64.b64encode(svg.encode()).decode()
        self._page.set_viewport_size({"width": max(size, 16), "height": max(size, 16)})
        self._page.set_content("<body style='margin:0;background:transparent'>"
                               f"<img id=i src='data:image/svg+xml;base64,{data}' width={size} height={size}"
                               " style='display:block'></body>")
        self._page.wait_for_function("document.getElementById('i').complete")
        raw = self._page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
        return Image.open(io.BytesIO(raw)).convert("RGBA")


def ico_bytes(images: list[Image.Image]) -> bytes:
    """32-bit BMP entries up to 128 px for old consumers, PNG for 256 (the Vista+ convention)."""
    entries = []
    for im in images:
        w, h = im.size
        if w >= 256:
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            data = buf.getvalue()
        else:
            header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
            px = im.load()
            xor = bytearray()
            for row in range(h - 1, -1, -1):
                for col in range(w):
                    r, g, b, a = px[col, row]
                    xor += bytes((b, g, r, a))
            stride = ((w + 31) // 32) * 4
            mask = bytearray()
            for row in range(h - 1, -1, -1):
                bits = bytearray(stride)
                for col in range(w):
                    if px[col, row][3] == 0:
                        bits[col // 8] |= 0x80 >> (col % 8)
                mask += bits
            data = header + bytes(xor) + bytes(mask)
        entries.append((w, h, data))
    out = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    blobs = b""
    for w, h, data in entries:
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return out + blobs


ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chromium", help="Chromium/Chrome executable (defaults to Playwright's)")
    args = parser.parse_args()

    res = ROOT / "android/app/src/main/res/drawable"
    (res / "ic_launcher_foreground.xml").write_text(vector(
        "Adaptive launcher foreground: the 票根 pair on a 108 dp canvas (safe zone r 33).",
        vd_group(pair(mono=False))), encoding="utf-8")
    (res / "ic_launcher_monochrome.xml").write_text(vector(
        "Themed-icon layer (Android 13+): the launcher tints this alpha mask; the tear gap replaces colour.",
        vd_group(pair(mono=True))), encoding="utf-8")
    (res / "ic_notification_receipt.xml").write_text(vector(
        "Status-bar icon: one upright stub as an alpha mask (the system tints it).",
        status_paths(), size_dp=24, viewport=24), encoding="utf-8")

    masters = HERE / "masters"
    masters.mkdir(exist_ok=True)
    docs = {
        "ticketbox-icon.svg": plated(),
        "ticketbox-adaptive-full-bleed.svg": full_bleed("0 0 108 108"),
        "ticketbox-monochrome.svg": svg_doc("0 0 108 108", svg_group(pair(mono=True)).replace("#FFFFFF", INK)),
        **{f"ticketbox-icon-{px}px.svg": hinted(px) for px in HINTED},
    }
    for name, text in docs.items():
        (masters / name).write_text(text + "\n", encoding="utf-8")

    chrome = Chromium(args.chromium)
    try:
        ico = [chrome.png(hinted(s) if s in HINTED else plated(holes=s >= 64), s) for s in ICO_SIZES]
        (ROOT / "backend/packaging/ticketbox.ico").write_bytes(ico_bytes(ico))
        brand = ROOT / "backend/app/static/web/product/brand"
        chrome.png(plated(holes=False), 48).save(brand / "favicon-48.png", optimize=True)
        chrome.png(plated(), 512).save(brand / "icon-512.png", optimize=True)
        chrome.png(full_bleed("9 9 90 90"), 512).convert("RGB").save(brand / "icon-maskable-512.png", optimize=True)
        chrome.png(plated(), 256).save(brand / "brand-mark.png", optimize=True)
        chrome.png(plated(plate=INK_LIFT), 256).save(brand / "brand-mark-midnight.png", optimize=True)
    finally:
        chrome.close()


if __name__ == "__main__":
    main()
