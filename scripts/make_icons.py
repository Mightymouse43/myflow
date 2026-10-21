"""Draw the MyFlow mark as the app icon and the menu bar glyphs. No paid tools.

Marks (pick with --mark; see DEFAULT_MARK):
  caret    a text cursor with two sound ripples arriving at it: voice becoming text
  bubble   a speech bubble with an M knocked out of it
  ribbon   the letter M as one thick stroke with rounded joints

`--sheet PATH` renders every candidate side by side at menu bar and app icon sizes.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

import AppKit

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "voz" / "assets"
DEFAULT_MARK = "caret"

PNG = AppKit.NSBitmapImageFileTypePNG
SRC_OVER = AppKit.NSCompositingOperationSourceOver
DEST_IN = AppKit.NSCompositingOperationDestinationIn
DEST_OUT = AppKit.NSCompositingOperationDestinationOut


def _rgb(hexstr: str, alpha: float = 1.0):
    r, g, b = (int(hexstr[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


class Canvas:
    """A transparent RGBA bitmap that is the current drawing context inside a `with` block."""

    def __init__(self, w: int, h: int):
        self.rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, w, h, 8, 4, True, False, AppKit.NSCalibratedRGBColorSpace, 0, 0)
        self.w, self.h = w, h

    def __enter__(self):
        AppKit.NSGraphicsContext.saveGraphicsState()
        ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(self.rep)
        AppKit.NSGraphicsContext.setCurrentContext_(ctx)
        ctx.setShouldAntialias_(True)
        return self

    def __exit__(self, *exc):
        AppKit.NSGraphicsContext.restoreGraphicsState()

    def image(self):
        img = AppKit.NSImage.alloc().initWithSize_((self.w, self.h))
        img.addRepresentation_(self.rep)
        return img

    def write(self, path: Path):
        self.rep.representationUsingType_properties_(PNG, None).writeToFile_atomically_(str(path), True)


def _stroke_path(width: float):
    p = AppKit.NSBezierPath.bezierPath()
    p.setLineWidth_(width)
    p.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    p.setLineJoinStyle_(AppKit.NSLineJoinStyleRound)
    return p


def _polyline(points, width: float):
    p = _stroke_path(width)
    p.moveToPoint_(points[0])
    for pt in points[1:]:
        p.lineToPoint_(pt)
    return p


def _arc(center, r: float, a0: float, a1: float, width: float):
    p = _stroke_path(width)
    cx, cy = center
    p.moveToPoint_((cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))))
    p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(center, r, a0, a1, False)
    return p


# ---- the marks: each draws in black inside the square (x, y, s) ----------------------------------

def draw_caret(x: float, y: float, s: float):
    """I-beam cursor on the right, two sound ripples travelling toward it from the left."""
    t = s * 0.12
    cx = x + s * 0.76
    top, bot = y + s * 0.92, y + s * 0.08
    mid = (top + bot) / 2
    _polyline([(cx, bot), (cx, top)], t).stroke()
    for yy in (top, bot):
        _polyline([(cx - s * 0.16, yy), (cx + s * 0.16, yy)], t).stroke()
    src = (x + s * 0.02, mid)
    for r in (s * 0.20, s * 0.40):
        _arc(src, r, -42, 42, t).stroke()


def draw_bubble(x: float, y: float, s: float):
    """Rounded speech bubble, tail bottom-left, with an M knocked out of it."""
    body = ((x + s * 0.02, y + s * 0.22), (s * 0.96, s * 0.74))
    AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body, s * 0.24, s * 0.24).fill()
    tail = AppKit.NSBezierPath.bezierPath()
    tail.moveToPoint_((x + s * 0.16, y + s * 0.30))
    tail.lineToPoint_((x + s * 0.10, y + s * 0.02))
    tail.lineToPoint_((x + s * 0.40, y + s * 0.26))
    tail.closePath()
    tail.fill()
    cx, cy = x + s * 0.50, y + s * 0.59
    w, h = s * 0.50, s * 0.36
    ctx = AppKit.NSGraphicsContext.currentContext()
    ctx.setCompositingOperation_(DEST_OUT)
    _polyline([(cx - w / 2, cy - h / 2), (cx - w / 2, cy + h / 2), (cx, cy - h * 0.15),
               (cx + w / 2, cy + h / 2), (cx + w / 2, cy - h / 2)], s * 0.10).stroke()
    ctx.setCompositingOperation_(SRC_OVER)


def draw_ribbon(x: float, y: float, s: float):
    """The letter M as one continuous thick stroke."""
    _polyline([(x + s * 0.10, y + s * 0.14), (x + s * 0.19, y + s * 0.86), (x + s * 0.50, y + s * 0.36),
               (x + s * 0.81, y + s * 0.86), (x + s * 0.90, y + s * 0.14)], s * 0.17).stroke()


MARKS = {"caret": draw_caret, "bubble": draw_bubble, "ribbon": draw_ribbon}


def mark_image(name: str, px: int, scale: float = 1.0):
    """The mark in solid black on a transparent px by px square; `scale` is the share of the square it fills."""
    with Canvas(px, px) as c:
        _rgb("#000000").setFill()
        _rgb("#000000").setStroke()
        s = px * scale
        MARKS[name]((px - s) / 2, (px - s) / 2, s)
        return c.image()


def tinted(name: str, px: int, scale: float, color=None, gradient=None):
    """The mark filled with a flat colour or a vertical gradient (bottom colour first)."""
    with Canvas(px, px) as c:
        if gradient is not None:
            AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(*gradient).drawInRect_angle_(((0, 0), (px, px)), 90)
        else:
            color.setFill()
            AppKit.NSBezierPath.fillRect_(((0, 0), (px, px)))
        mark_image(name, px, scale).drawInRect_fromRect_operation_fraction_(((0, 0), (px, px)), AppKit.NSZeroRect, DEST_IN, 1.0)
        return c.image()


def _draw(img, x: float, y: float, w: float, h: float):
    img.drawInRect_fromRect_operation_fraction_(((x, y), (w, h)), AppKit.NSZeroRect, SRC_OVER, 1.0)


def app_icon(name: str, px: int, path: Path | None = None):
    with Canvas(px, px) as c:
        s = px
        tile = s * 0.80                      # macOS icon grid: tile fills ~80% with ~22% corner radius
        inset = (s - tile) / 2
        tile_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((inset, inset), (tile, tile)), tile * 0.225, tile * 0.225)
        AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(_rgb("#0B1020"), _rgb("#1E2A44")).drawInBezierPath_angle_(tile_path, 90)
        hl = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((inset + tile * 0.04, inset + tile * 0.04), (tile * 0.92, tile * 0.92)), tile * 0.20, tile * 0.20)
        hl.setLineWidth_(max(1.0, s * 0.004))
        _rgb("#FFFFFF", 0.07).setStroke()
        hl.stroke()
        glyph = tile * 0.60
        _draw(tinted(name, int(glyph) or 1, 1.0, gradient=(_rgb("#2EE6C5"), _rgb("#B9FF66"))),
              inset + (tile - glyph) / 2, inset + (tile - glyph) / 2, glyph, glyph)
        if path is not None:
            c.write(path)
        return c.image()


def menubar_glyph(name: str, px: int, path: Path, color):
    with Canvas(px, px) as c:
        _draw(tinted(name, px, 0.86, color=color), 0, 0, px, px)
        c.write(path)


def _label(text: str, x: float, y: float, color, size: float = 13.0):
    attrs = {AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(size), AppKit.NSForegroundColorAttributeName: color}
    AppKit.NSString.stringWithString_(text).drawAtPoint_withAttributes_((x, y), attrs)


def preview(name: str, path: Path):
    """The chosen glyph on a dark and a light menu bar, the three states, and the app icon."""
    w, h = 900, 300
    with Canvas(w, h) as c:
        _rgb("#1C1C1E").setFill(); AppKit.NSBezierPath.fillRect_(((0, 0), (300, h)))
        _rgb("#F2F2F7").setFill(); AppKit.NSBezierPath.fillRect_(((300, 0), (300, h)))
        _rgb("#2A2A2E").setFill(); AppKit.NSBezierPath.fillRect_(((600, 0), (300, h)))
        for x, col in ((150, _rgb("#FFFFFF")), (450, _rgb("#000000"))):
            _draw(tinted(name, 160, 0.86, color=col), x - 40, h / 2 - 10, 80, 80)
        for x, col in ((95, _rgb("#FF4D4D")), (150, _rgb("#FFC53D")), (205, _rgb("#FFFFFF"))):
            _draw(tinted(name, 80, 0.86, color=col), x - 18, 44, 36, 36)
        _draw(app_icon(name, 512), 622, 22, 256, 256)
        c.write(path)


def sheet(path: Path):
    """Every candidate: real menu bar size (22 px bar, 18 px glyph) and 2x, on dark and light, plus the app icon."""
    rows, row_h, w = list(MARKS), 150, 1000
    h = row_h * len(rows) + 40
    with Canvas(w, h) as c:
        _rgb("#3A3A3C").setFill(); AppKit.NSBezierPath.fillRect_(((0, 0), (w, h)))
        for i, name in enumerate(rows):
            y0 = h - 40 - (i + 1) * row_h
            _label(name, 20, y0 + row_h - 28, _rgb("#FFFFFF"), 15)
            # real-size menu bar strips: dark and light, 22 px tall, glyph 18 px, next to the "MyFlow" title
            for sx, bar, fg in ((20, "#1C1C1E", "#FFFFFF"), (20, "#E9E9EE", "#000000")):
                by = y0 + (72 if bar == "#1C1C1E" else 40)
                _rgb(bar).setFill(); AppKit.NSBezierPath.fillRect_(((sx, by), (170, 22)))
                _draw(tinted(name, 72, 0.86, color=_rgb(fg)), sx + 8, by + 2, 18, 18)
                _label("MyFlow", sx + 32, by + 3, _rgb(fg), 13)
                _rgb(bar).setFill(); AppKit.NSBezierPath.fillRect_(((sx + 200, by - 11), (120, 44)))
                _draw(tinted(name, 144, 0.86, color=_rgb(fg)), sx + 216, by - 7, 36, 36)
                _label("MyFlow", sx + 264, by + 1, _rgb(fg), 15)
            for j, col in enumerate(("#FF4D4D", "#FFC53D")):
                _draw(tinted(name, 72, 0.86, color=_rgb(col)), 380 + j * 30, y0 + 74, 18, 18)
            _draw(app_icon(name, 256), 470, y0 + 8, 128, 128)
            _draw(app_icon(name, 128), 620, y0 + 40, 64, 64)
            _draw(app_icon(name, 64), 700, y0 + 56, 32, 32)
            _draw(app_icon(name, 32), 750, y0 + 64, 16, 16)
        _label("Wispr Flow's mark is five vertical bars. None of these use bars.", 20, 10, _rgb("#C7C7CC"), 12)
        c.write(path)


def build(name: str) -> None:
    ASSETS.mkdir(exist_ok=True)
    iconset = ROOT / "launcher" / "AppIcon.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()
    for pt in (16, 32, 128, 256, 512):
        app_icon(name, pt, iconset / f"icon_{pt}x{pt}.png")
        app_icon(name, pt * 2, iconset / f"icon_{pt}x{pt}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ROOT / "launcher" / "AppIcon.icns")], check=True)
    app_icon(name, 512, ASSETS / "preview-appicon.png")
    menubar_glyph(name, 80, ASSETS / "menubar-idle.png", _rgb("#000000"))        # template: macOS recolours it
    menubar_glyph(name, 80, ASSETS / "menubar-listening.png", _rgb("#FF4D4D"))
    menubar_glyph(name, 80, ASSETS / "menubar-thinking.png", _rgb("#FFC53D"))
    preview(name, ASSETS / "preview.png")
    print("wrote", name, "mark:", ROOT / "launcher" / "AppIcon.icns", "and", sorted(p.name for p in ASSETS.iterdir()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mark", choices=sorted(MARKS), default=DEFAULT_MARK)
    ap.add_argument("--sheet", type=Path, help="only render the candidates sheet to this PNG")
    args = ap.parse_args()
    if args.sheet:
        sheet(args.sheet)
        print("wrote", args.sheet)
        return 0
    build(args.mark)
    return 0


if __name__ == "__main__":
    sys.exit(main())
