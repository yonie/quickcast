#!/usr/bin/env python3
"""Single-shot screenshot of the QuickCast home view.

Usage: python3 tools/shot.py <out.png> [delay_ms] [width] [height]
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import quickcast  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "build/quickcast.png"
delay = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1180
H = int(sys.argv[4]) if len(sys.argv) > 4 else 780
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

app = quickcast.QuickCast()
app.window.set_default_size(W, H)
app.window.resize(W, H)
app.window.move(40, 40)


def take():
    gwin = app.window.get_window()
    ok = False
    try:
        xid = gwin.get_xid()
        r = subprocess.run(["import", "-window", str(xid), out], capture_output=True, text=True)
        ok = r.returncode == 0
    except Exception:
        pass
    if not ok:
        try:
            pb = Gdk.pixbuf_get_from_window(gwin, 0, 0, gwin.get_width(), gwin.get_height())
            pb.savev(out, "png", [], [])
            ok = True
        except Exception as e:
            print(f"[shot] gdk grab failed: {e}", flush=True)
    print(f"[shot] {'saved ' + out if ok else 'FAILED'}", flush=True)
    Gtk.main_quit()
    return False


GLib.timeout_add(delay, take)
Gtk.main()
