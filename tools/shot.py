#!/usr/bin/env python3
"""Single-shot screenshot of the QuickCast home view.

Usage: python3 tools/shot.py <out.png> [delay_ms] [width] [height]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import quickcast  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "build/quickcast.png"
delay = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1180
H = int(sys.argv[4]) if len(sys.argv) > 4 else 780
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

app = quickcast.QuickCast(mock=True)  # deterministic, copyright-free data

_child = app.window.get_child()
app.window.remove(_child)
_off = Gtk.OffscreenWindow()
_off.add(_child)
_off.set_size_request(W, H)
_off.show_all()


def take():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    pb = _off.get_pixbuf()
    if pb is not None:
        pb.savev(out, "png", [], [])
        print(f"[shot] saved {out}", flush=True)
    else:
        print("[shot] FAILED (no pixbuf)", flush=True)
    Gtk.main_quit()
    return False


GLib.timeout_add(delay, take)
Gtk.main()
