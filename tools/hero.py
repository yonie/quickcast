#!/usr/bin/env python3
"""Render the README hero screenshot: the app (in --mock mode) wrapped in a
clean Adwaita-style window frame (titlebar + window controls + drop shadow),
matching the quicksnip/quickcell screenshots.

Usage: python3 tools/hero.py [out.png] [WIDTH] [HEIGHT]
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import quickcast  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "screenshot.png"
W = int(sys.argv[2]) if len(sys.argv) > 2 else 1180
H = int(sys.argv[3]) if len(sys.argv) > 3 else 620

app = quickcast.QuickCast(mock=True)
child = app.window.get_child()
app.window.remove(child)
off = Gtk.OffscreenWindow()
off.add(child)
off.set_size_request(W, H)
off.show_all()

MARGIN, TB, RADIUS = 46, 42, 11


def _round_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def render():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    content = off.get_pixbuf()  # W x H

    cw, ch = W + 2 * MARGIN, H + TB + 2 * MARGIN
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, cw, ch)
    cr = cairo.Context(surf)

    # soft drop shadow (stacked translucent expanding rounded rects)
    for i in range(MARGIN, 0, -1):
        _round_rect(cr, MARGIN - i, MARGIN - i + 7, W + 2 * i, TB + H + 2 * i, RADIUS + i)
        cr.set_source_rgba(0, 0, 0, 0.006)
        cr.fill()

    # window body, clipped to rounded rect
    _round_rect(cr, MARGIN, MARGIN, W, TB + H, RADIUS)
    cr.clip_preserve()
    cr.set_source_rgb(1, 1, 1)
    cr.fill()

    # titlebar
    grad = cairo.LinearGradient(0, MARGIN, 0, MARGIN + TB)
    grad.add_color_stop_rgb(0, 0.925, 0.925, 0.925)
    grad.add_color_stop_rgb(1, 0.902, 0.902, 0.902)
    cr.rectangle(MARGIN, MARGIN, W, TB)
    cr.set_source(grad)
    cr.fill()
    cr.rectangle(MARGIN, MARGIN + TB - 1, W, 1)
    cr.set_source_rgb(0.82, 0.82, 0.82)
    cr.fill()

    # title text (centered)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(14)
    ext = cr.text_extents("QuickCast")
    cr.move_to(MARGIN + W / 2 - ext.width / 2, MARGIN + TB / 2 + ext.height / 2)
    cr.set_source_rgb(0.2, 0.2, 0.2)
    cr.show_text("QuickCast")

    # window controls (minimize / maximize / close) on the right
    cy = MARGIN + TB / 2
    cr.set_line_width(1.4)
    cr.set_source_rgb(0.35, 0.35, 0.35)
    bx = MARGIN + W - 30
    # close ✕
    cr.move_to(bx - 5, cy - 5); cr.line_to(bx + 5, cy + 5)
    cr.move_to(bx + 5, cy - 5); cr.line_to(bx - 5, cy + 5)
    cr.stroke()
    # maximize ▢
    bx -= 34
    cr.rectangle(bx - 5, cy - 5, 10, 10); cr.stroke()
    # minimize _
    bx -= 34
    cr.move_to(bx - 5, cy + 5); cr.line_to(bx + 5, cy + 5); cr.stroke()

    # app content under the titlebar
    Gdk.cairo_set_source_pixbuf(cr, content, MARGIN, MARGIN + TB)
    cr.paint()

    cr.reset_clip()
    # hairline border around the window
    _round_rect(cr, MARGIN + 0.5, MARGIN + 0.5, W - 1, TB + H - 1, RADIUS)
    cr.set_source_rgba(0, 0, 0, 0.12)
    cr.set_line_width(1)
    cr.stroke()

    surf.write_to_png(OUT)
    print(f"[hero] saved {OUT} ({cw}x{ch})", flush=True)
    Gtk.main_quit()
    return False


GLib.timeout_add(6500, render)
Gtk.main()
