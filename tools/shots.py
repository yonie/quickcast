#!/usr/bin/env python3
"""Regression screenshot set for QuickCast.

Drives one app instance through its key states, capturing each to <outdir>.
Uses a real Jellyfin connection from ~/.config/quickcast.conf.

Usage: python3 tools/shots.py <outdir> [WIDTH] [HEIGHT]

Captures via ImageMagick `import -window <xid>` on X11, falling back to
Gdk.pixbuf_get_from_window (works under Wayland).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import quickcast  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "build/screenshots"
W = int(sys.argv[2]) if len(sys.argv) > 2 else 1180
H = int(sys.argv[3]) if len(sys.argv) > 3 else 780
os.makedirs(OUT, exist_ok=True)

app = quickcast.QuickCast(mock=True)  # deterministic, copyright-free data

# Reparent the UI into an OffscreenWindow: renders to a buffer independent of
# the compositor, so captures are reliable even when nothing is visible on
# screen (Wayland throttles frames for hidden windows -> stale grabs).
_child = app.window.get_child()
app.window.remove(_child)
_off = Gtk.OffscreenWindow()
_off.add(_child)
_off.set_size_request(W, H)
_off.show_all()


def capture(name):
    path = os.path.join(OUT, name + ".png")
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    pb = _off.get_pixbuf()
    if pb is None:
        print(f"[shots] {name}: FAIL (no pixbuf)", flush=True)
        return
    pb.savev(path, "png", [], [])
    print(f"[shots] {name}: ok {pb.get_width()}x{pb.get_height()}", flush=True)


def _view(name):
    views = app.fetch_user_views()
    return next((v for v in views if v.get("Name") == name), views[0] if views else None)


def enter_library(name):
    v = _view(name)
    if v:
        app.on_item_click(v)


def open_first(kind, library):
    v = _view(library)
    if not v:
        return
    items = app.fetch_items(v["Id"])
    it = next((x for x in items if x.get("Type") == kind), items[0] if items else None)
    if it:
        app.on_item_click(it)


# name, action or None, wait_ms before capture
STAGES = [
    ("01-home", None, 7000),
    ("02-library-grid", lambda: enter_library("Movies"), 6000),
    ("03-loading", lambda: app.show_loading_state("Loading…"), 500),
    ("04-sorted-year", lambda: app.sort_combo.set_active(quickcast.QuickCast.SORT_OPTIONS.index("Year")), 5000),
    ("05-music-grid", lambda: (app.on_home(None), enter_library("Music")), 6000),
    ("06-series-lib", lambda: (app.on_home(None), enter_library("Series")), 6000),
    ("07-series-drill", lambda: open_first("Series", "Series"), 6000),
    ("08-search", lambda: app.search_entry.set_text("the"), 5000),
    ("09-detail", lambda: open_first("Movie", "Movies"), 6500),
]

_idx = [0]


def run_stage():
    if _idx[0] >= len(STAGES):
        Gtk.main_quit()
        return False
    name, action, wait = STAGES[_idx[0]]
    if action:
        try:
            action()
        except Exception as e:
            print(f"[shots] {name} action error: {e}", flush=True)
    GLib.timeout_add(wait, lambda: _cap_advance(name))
    return False


def _cap_advance(name):
    capture(name)
    _idx[0] += 1
    run_stage()
    return False


GLib.timeout_add(200, run_stage)
Gtk.main()
