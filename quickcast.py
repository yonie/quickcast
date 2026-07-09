#!/usr/bin/env python3
import os
import sys
import threading
import time

import gi
import pychromecast
import requests

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

VERSION = "0.3.0"
APP_NAME = "QuickCast"

# Accent color
ACCENT = "#5B7CFA"

CSS = """
/* QuickCast — minimal, theme-adaptive. Trust the native GNOME theme;
   style structure with named theme colors so it follows the user's
   light/dark preference instead of imposing our own. */

/* ── Section + page headers ─────────────────────────── */
.section-header { font-size: 15px; font-weight: 800; padding: 16px 18px 6px 18px; }
.page-title { font-size: 22px; font-weight: 800; padding: 4px 18px 0 18px; }
.page-sub { color: @insensitive_fg_color; font-size: 12px; padding: 0 18px 6px 18px; }
.dim { color: @insensitive_fg_color; font-size: 12px; }
.status-label { color: @insensitive_fg_color; font-size: 12px; }

/* ── Cards (continue watching + library/content tiles) ─ */
.card {
    border: 1px solid @borders;
    border-radius: 10px;
    background-color: alpha(@theme_base_color, 0.5);
    transition: all 140ms ease;
}
.card:hover {
    background-color: alpha(@theme_fg_color, 0.07);
    border-color: alpha(@theme_fg_color, 0.28);
}
.poster { background-color: alpha(@theme_fg_color, 0.10); border-radius: 10px 10px 0 0; }
.card-title { font-size: 12px; font-weight: 600; padding: 7px 10px 1px 10px; }
.card-sub { color: @insensitive_fg_color; font-size: 11px; padding: 0 10px 8px 10px; }
.cw-progress { background-color: @theme_selected_bg_color; min-height: 3px; border-radius: 0; }

/* ── Loading / placeholder ──────────────────────────── */
.loading-label { color: @insensitive_fg_color; font-size: 13px; }
.placeholder { color: @insensitive_fg_color; font-size: 15px; }
.placeholder-icon { font-size: 46px; color: alpha(@theme_fg_color, 0.18); margin-bottom: 8px; }
.skeleton {
    border: 1px solid @borders;
    border-radius: 10px;
    background-color: alpha(@theme_fg_color, 0.06);
}

/* ── Detail page ────────────────────────────────────── */
.detail-backdrop { background-color: #000000; }
.detail-title { font-size: 26px; font-weight: 800; }
.detail-meta { color: @insensitive_fg_color; font-size: 13px; font-weight: 600; }
.detail-overview { font-size: 14px; }
.chip {
    background-color: alpha(@theme_fg_color, 0.08);
    border: 1px solid @borders;
    border-radius: 13px;
    padding: 3px 11px;
    font-size: 11px;
    font-weight: 600;
}
.detail-cast-btn { padding: 10px 28px; font-size: 15px; font-weight: 700; }

/* ── Now playing bar ────────────────────────────────── */
.now-playing { border-top: 1px solid @borders; padding: 8px 16px; }
.now-playing .title { font-size: 13px; font-weight: 700; }
.now-playing .subtitle { color: @insensitive_fg_color; font-size: 11px; }
.now-playing progressbar { min-height: 4px; }
.now-playing progressbar progress { background-color: @theme_selected_bg_color; border-radius: 2px; }

/* ── Toast ──────────────────────────────────────────── */
.toast {
    background-color: rgba(0,0,0,0.82);
    color: #ffffff;
    padding: 11px 24px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
}
.toast.error { background-color: rgba(150,40,32,0.92); }

/* ── Cast picker rows ───────────────────────────────── */
.cast-row {
    border: 1px solid @borders;
    border-radius: 10px;
    padding: 12px 14px;
    margin: 3px 0;
    transition: all 140ms ease;
}
.cast-row:hover { background-color: alpha(@theme_fg_color, 0.07); border-color: @theme_selected_bg_color; }
.cast-device-name { font-size: 14px; font-weight: 700; }
.cast-device-type { color: @insensitive_fg_color; font-size: 11px; }
.qc-code { font-size: 34px; font-weight: 800; color: @theme_selected_bg_color; padding: 6px; }
"""


class ImageCache:
    """Simple in-memory image cache keyed by (item_id, size)."""
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, item_id, size):
        with self._lock:
            return self._cache.get((item_id, size))

    def put(self, item_id, size, data):
        with self._lock:
            self._cache[(item_id, size)] = data


def log(msg):
    print(f"[QuickCast] {msg}", flush=True)


class QuickCast:
    def __init__(self):
        log("Starting QuickCast")
        self.img_cache = ImageCache()

        self.window = Gtk.Window(title=APP_NAME)
        self.window.set_default_size(1100, 750)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        style_ctx = Gtk.StyleContext()
        style_ctx.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.window.connect("destroy", Gtk.main_quit)
        self.window.connect("key-press-event", self.on_key_press)

        # State
        self.server_url = None
        self.api_key = None
        self.user_id = None
        self.chromecast = None
        self.browsing_path = []
        self._qc_polling = False
        self._qc_secret = None
        self._toast_timer_id = None
        self._progress_timer_id = None
        self._detail_current_item = None

        # Build UI
        self._build_toolbar()
        self._build_content()
        self._build_now_playing()
        self._assemble()

        self.window.show_all()
        log("Window shown")

        self.load_config()
        log(f"Config: server={self.server_url}, key={'set' if self.api_key else 'none'}, user={'set' if self.user_id else 'none'}")

        if not self.server_url:
            self.show_placeholder("Connect to your Jellyfin server to get started", "🔌")
        else:
            self.on_refresh(None)

    # ── Toolbar ─────────────────────────────────────────
    def _build_toolbar(self):
        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.toolbar.get_style_context().add_class("toolbar")

        def make_btn(label, callback, css_class=None):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", callback)
            if css_class:
                btn.get_style_context().add_class(css_class)
            return btn

        self.server_btn = make_btn("Server", self.show_server_config)
        self.refresh_btn = make_btn("Refresh", self.on_refresh)
        self.cast_btn = make_btn("Cast", self.show_cast_devices)
        self.stop_btn = make_btn("Stop", self.on_stop_cast)
        self.back_btn = make_btn("Back", self.on_back)
        self.home_btn = make_btn("Home", self.on_home)
        self.help_btn = make_btn("About", self.show_help)

        self.status_label = Gtk.Label(label="")
        self.status_label.get_style_context().add_class("status-label")
        self.status_label.set_halign(Gtk.Align.END)
        self.status_label.set_margin_start(16)

        def sep():
            return Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)

        for btn in [self.server_btn, self.refresh_btn, sep(), self.cast_btn, self.stop_btn, sep(),
                     self.back_btn, self.home_btn, sep(), self.help_btn]:
            self.toolbar.pack_start(btn, False, False, 0)
        self.toolbar.pack_end(self.status_label, False, False, 8)

    # ── Content area ────────────────────────────────────
    def _build_content(self):
        # Main scrollable
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.get_style_context().add_class("content")

        # We use a single content_box that we swap between browse view and detail view
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # --- Browse layout (home + folder browsing) ---
        self.browse_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Continue Watching
        self.cw_header = Gtk.Label(label="Continue Watching")
        self.cw_header.get_style_context().add_class("section-header")
        self.cw_header.set_halign(Gtk.Align.START)
        self.cw_header.set_no_show_all(True)

        self.cw_scroll = Gtk.ScrolledWindow()
        self.cw_scroll.get_style_context().add_class("cw-scrolled")
        self.cw_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.cw_scroll.set_no_show_all(True)

        self.cw_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.cw_box.set_margin_start(20)
        self.cw_box.set_margin_end(20)
        self.cw_box.set_margin_top(4)
        self.cw_box.set_margin_bottom(8)
        self.cw_scroll.add(self.cw_box)

        self.cw_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.cw_separator.set_no_show_all(True)
        self.cw_separator.set_margin_top(8)
        self.cw_separator.set_margin_start(20)
        self.cw_separator.set_margin_end(20)

        # Libraries grid
        self.lib_header = Gtk.Label(label="Libraries")
        self.lib_header.get_style_context().add_class("section-header")
        self.lib_header.set_halign(Gtk.Align.START)
        self.lib_header.set_no_show_all(True)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(8)
        self.flowbox.set_min_children_per_line(3)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_column_spacing(16)
        self.flowbox.set_row_spacing(16)
        self.flowbox.set_margin_start(20)
        self.flowbox.set_margin_end(20)
        self.flowbox.set_margin_top(4)
        self.flowbox.set_margin_bottom(28)

        self.browse_box.pack_start(self.cw_header, False, False, 0)
        self.browse_box.pack_start(self.cw_scroll, False, False, 0)
        self.browse_box.pack_start(self.cw_separator, False, False, 0)
        self.browse_box.pack_start(self.lib_header, False, False, 0)
        self.browse_box.pack_start(self.flowbox, True, True, 0)

        # --- Detail layout (hidden by default) ---
        self.detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.detail_box.set_no_show_all(True)

        # --- Loading / placeholder overlay (shown on top) ---
        self.loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.loading_box.get_style_context().add_class("loading-box")
        self.loading_box.set_valign(Gtk.Align.CENTER)
        self.loading_box.set_halign(Gtk.Align.CENTER)
        self.loading_box.set_no_show_all(True)
        self.loading_spinner = Gtk.Spinner()
        self.loading_spinner.start()
        self.loading_label = Gtk.Label(label="Loading...")
        self.loading_label.get_style_context().add_class("loading-label")
        self.loading_box.pack_start(self.loading_spinner, False, False, 0)
        self.loading_box.pack_start(self.loading_label, False, False, 0)

        self.content_box.pack_start(self.browse_box, True, True, 0)
        self.content_box.pack_start(self.detail_box, True, True, 0)
        self.content_box.pack_start(self.loading_box, True, True, 0)

        self.scrolled_window.add(self.content_box)

    # ── Now playing bar ─────────────────────────────────
    def _build_now_playing(self):
        self.np_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.np_box.get_style_context().add_class("now-playing")

        self.np_thumbnail = Gtk.Image()
        self.np_thumbnail.set_size_request(48, 48)

        self.np_title = Gtk.Label(label="Nothing casting")
        self.np_title.get_style_context().add_class("title")
        self.np_title.set_halign(Gtk.Align.START)
        self.np_title.set_ellipsize(Pango.EllipsizeMode.END)

        self.np_subtitle = Gtk.Label(label="")
        self.np_subtitle.get_style_context().add_class("subtitle")
        self.np_subtitle.set_halign(Gtk.Align.START)

        self.np_progress = Gtk.ProgressBar()
        self.np_progress.set_fraction(0.0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.pack_start(self.np_title, False, False, 0)
        title_box.pack_start(self.np_subtitle, False, False, 0)
        title_box.set_margin_start(14)
        title_box.set_valign(Gtk.Align.CENTER)

        self.np_time_label = Gtk.Label(label="0:00 / 0:00")
        self.np_time_label.get_style_context().add_class("subtitle")
        self.np_time_label.set_margin_end(16)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        controls.set_valign(Gtk.Align.CENTER)
        controls.set_margin_end(20)

        def ctrl_btn(label, callback):
            b = Gtk.Button(label=label)
            b.connect("clicked", callback)
            return b

        self.np_back_btn = ctrl_btn("⏪", self.on_seek_back)
        self.np_play_btn = ctrl_btn("▶", self.on_play_pause)
        self.np_fwd_btn = ctrl_btn("⏩", self.on_seek_fwd)

        controls.pack_start(self.np_back_btn, False, False, 0)
        controls.pack_start(self.np_play_btn, False, False, 0)
        controls.pack_start(self.np_fwd_btn, False, False, 0)

        prog_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        prog_col.pack_start(title_box, False, False, 0)
        prog_col.pack_start(self.np_progress, False, False, 0)
        prog_col.set_valign(Gtk.Align.CENTER)

        self.np_box.pack_start(self.np_thumbnail, False, False, 0)
        self.np_box.pack_start(prog_col, True, True, 0)
        self.np_box.pack_start(self.np_time_label, False, False, 0)
        self.np_box.pack_start(controls, False, False, 0)

    def _assemble(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.pack_start(self.toolbar, False, False, 0)
        main_box.pack_start(self.scrolled_window, True, True, 0)
        main_box.pack_start(self.np_box, False, False, 0)

        self.toast_label = Gtk.Label(label="")
        self.toast_label.get_style_context().add_class("toast")
        self.toast_label.set_halign(Gtk.Align.CENTER)
        self.toast_label.set_valign(Gtk.Align.START)
        self.toast_label.set_margin_top(24)
        self.toast_label.set_no_show_all(True)

        self.overlay = Gtk.Overlay()
        self.overlay.add_overlay(self.toast_label)
        self.overlay.add(main_box)
        self.window.add(self.overlay)

    # ── Config ──────────────────────────────────────────
    def get_config_path(self):
        return os.path.expanduser("~/.config/quickcast.conf")

    def load_config(self):
        path = self.get_config_path()
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    if "=" in line:
                        key, val = line.strip().split("=", 1)
                        if key == "server_url":
                            self.server_url = val
                        elif key == "api_key":
                            self.api_key = val
                        elif key == "user_id":
                            self.user_id = val
            self.update_status()

    def save_config(self):
        path = self.get_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"server_url={self.server_url or ''}\n")
            f.write(f"api_key={self.api_key or ''}\n")
            f.write(f"user_id={self.user_id or ''}\n")

    def update_status(self):
        server = "●" if self.server_url else "○"
        cast = "●" if self.chromecast else "○"
        self.status_label.set_markup(
            f"<span foreground='{'#5B7CFA' if self.server_url else '#ccc'}'>{server}</span> Server"
            f"   "
            f"<span foreground='{'#5B7CFA' if self.chromecast else '#ccc'}'>{cast}</span> Cast"
        )

    def _auth_header(self):
        return {
            "X-Emby-Authorization": f'MediaBrowser Client="QuickCast", Device="Linux", DeviceId="quickcast-1", Version="{VERSION}"'
        }

    # ── Toast ───────────────────────────────────────────
    def show_toast(self, message):
        log(f"Toast: {message}")
        if self._toast_timer_id is not None:
            GLib.source_remove(self._toast_timer_id)
        self.toast_label.set_text(message)
        self.toast_label.show()
        self._toast_timer_id = GLib.timeout_add(2800, self.hide_toast)

    def hide_toast(self):
        self._toast_timer_id = None
        self.toast_label.hide()
        return False

    # ── View switching ──────────────────────────────────
    def show_browse(self):
        self.browse_box.show()
        self.detail_box.hide()
        self.loading_box.hide()

    def show_detail_view(self):
        self.browse_box.hide()
        self.detail_box.show()
        self.loading_box.hide()

    def show_loading_state(self, text="Loading..."):
        self.browse_box.hide()
        self.detail_box.hide()
        self.loading_label.set_text(text)
        self.loading_spinner.start()
        self.loading_box.show()

    def show_placeholder(self, text, icon="📭"):
        for child in self.cw_box.get_children():
            self.cw_box.remove(child)
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        self.cw_header.hide()
        self.cw_scroll.hide()
        self.cw_separator.hide()
        self.lib_header.hide()

        icon_label = Gtk.Label(label=icon)
        icon_label.get_style_context().add_class("placeholder-icon")
        icon_label.set_halign(Gtk.Align.CENTER)

        text_label = Gtk.Label(label=text)
        text_label.get_style_context().add_class("placeholder")
        text_label.set_halign(Gtk.Align.CENTER)

        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wrap.pack_start(icon_label, False, False, 0)
        wrap.pack_start(text_label, False, False, 0)
        wrap.set_halign(Gtk.Align.CENTER)
        wrap.set_valign(Gtk.Align.CENTER)
        wrap.set_margin_top(120)
        wrap.set_margin_bottom(120)

        self.flowbox.add(wrap)
        self.show_browse()
        self.flowbox.show_all()

    # ── Jellyfin API ────────────────────────────────────
    def jf_request(self, endpoint, params=None):
        if not self.server_url:
            return None
        url = f"{self.server_url.rstrip('/')}{endpoint}"
        headers = {}
        if self.api_key:
            headers["X-Emby-Token"] = self.api_key
        log(f"GET {url}")
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            log(f"  → {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            log(f"  → HTTP {e.response.status_code}: {e.response.text[:200]}")
            GLib.idle_add(self.show_toast, f"API error: {e.response.status_code}")
            return None
        except Exception as e:
            log(f"  → Error: {e}")
            GLib.idle_add(self.show_toast, f"Network error: {e}")
            return None

    def fetch_user_views(self):
        if not self.user_id:
            data = self.jf_request("/Users")
            if data and len(data) > 0:
                self.user_id = data[0]["Id"]
                self.save_config()
            else:
                return []
        data = self.jf_request(f"/Users/{self.user_id}/Views")
        return data.get("Items", []) if data else []

    def fetch_items(self, parent_id):
        data = self.jf_request(
            f"/Users/{self.user_id}/Items",
            params={"ParentId": parent_id, "Recursive": False, "SortBy": "SortName"},
        )
        return data.get("Items", []) if data else []

    def fetch_resume(self):
        data = self.jf_request(f"/Users/{self.user_id}/Items/Resume", params={"Limit": 20})
        return data.get("Items", []) if data else []

    def fetch_item(self, item_id):
        return self.jf_request(f"/Users/{self.user_id}/Items/{item_id}")

    def fetch_image(self, item_id, size=300):
        if not self.server_url:
            return None
        cached = self.img_cache.get(item_id, size)
        if cached:
            return cached
        params = {"maxWidth": size, "maxHeight": size, "quality": 85}
        url = f"{self.server_url.rstrip('/')}/Items/{item_id}/Images/Primary"
        headers = {}
        if self.api_key:
            headers["X-Emby-Token"] = self.api_key
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.content
            self.img_cache.put(item_id, size, data)
            return data
        except Exception:
            return None

    def fetch_backdrop(self, item_id, size=1280):
        if not self.server_url:
            return None
        url = f"{self.server_url.rstrip('/')}/Items/{item_id}/Images/Backdrop"
        headers = {}
        if self.api_key:
            headers["X-Emby-Token"] = self.api_key
        params = {"maxWidth": size, "quality": 80}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    # ── Browsing ────────────────────────────────────────
    def on_refresh(self, widget):
        log("Refresh")
        if not self.server_url:
            self.show_placeholder("Connect to your Jellyfin server to get started", "🔌")
            return
        self.browsing_path = []
        self.show_loading_state("Loading your library...")
        threading.Thread(target=self._load_home, daemon=True).start()

    def on_home(self, widget):
        self.on_refresh(None)

    def on_back(self, widget):
        if self.detail_box.get_visible():
            # From detail → back to browse
            self.show_browse()
            return
        if len(self.browsing_path) > 1:
            self.browsing_path.pop()
            parent_id = self.browsing_path[-1]
            self.show_loading_state("Loading...")
            threading.Thread(target=self._load_items, args=(parent_id,), daemon=True).start()
        else:
            self.on_refresh(None)

    def _load_home(self):
        views = self.fetch_user_views()
        resume = self.fetch_resume()
        GLib.idle_add(self._render_home, views, resume)

    def _render_home(self, views, resume_items):
        for child in self.cw_box.get_children():
            self.cw_box.remove(child)
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

        if resume_items:
            self.cw_header.show()
            self.cw_scroll.show()
            self.cw_separator.show()
            for item in resume_items[:20]:
                self.add_cw_card(item)
            self.cw_box.show_all()
        else:
            self.cw_header.hide()
            self.cw_scroll.hide()
            self.cw_separator.hide()

        if views:
            self.lib_header.show()
            for view in views:
                self.add_lib_card(view)
            self.flowbox.show_all()
        else:
            self.lib_header.hide()

        self.show_browse()
        log(f"Home rendered: {len(resume_items)} resume, {len(views)} views")

    def _load_items(self, parent_id):
        items = self.fetch_items(parent_id)
        GLib.idle_add(self._render_items, items)

    def _render_items(self, items):
        for child in self.cw_box.get_children():
            self.cw_box.remove(child)
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

        self.cw_header.hide()
        self.cw_scroll.hide()
        self.cw_separator.hide()
        self.lib_header.hide()

        if not items:
            self.show_placeholder("No items found", "📂")
            return

        for item in items:
            self.add_lib_card(item)

        self.show_browse()
        self.flowbox.show_all()
        log(f"Rendered {len(items)} items")

    # ── Image helpers ───────────────────────────────────
    def _load_pixbuf_aspect(self, item_id, target_w, target_h):
        img_data = self.fetch_image(item_id, size=max(target_w, target_h))
        if not img_data:
            return None
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(img_data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if not pixbuf:
                return None
            orig_w = pixbuf.get_width()
            orig_h = pixbuf.get_height()
            if orig_w <= 0 or orig_h <= 0:
                return None
            scale = min(target_w / orig_w, target_h / orig_h)
            new_w = max(1, int(orig_w * scale))
            new_h = max(1, int(orig_h * scale))
            return pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            return None

    # ── Continue Watching card ──────────────────────────
    def add_cw_card(self, item):
        item_id = item.get("Id")
        name = item.get("Name", "Unknown")
        played_pct = item.get("UserData", {}).get("PlayedPercentage", 0)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.get_style_context().add_class("card")

        # Image wrapper (landscape 16:9, 260x146)
        img_w, img_h = 260, 146
        img_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        img_wrap.get_style_context().add_class("poster")
        img_wrap.set_size_request(img_w, img_h)

        image = Gtk.Image()
        image.set_size_request(img_w, img_h)

        pixbuf = self._load_pixbuf_aspect(item_id, img_w, img_h)
        if pixbuf:
            image.set_from_pixbuf(pixbuf)
        else:
            image.set_from_icon_name("video-display", Gtk.IconSize.DIALOG)

        img_wrap.pack_start(image, True, True, 0)

        # Progress bar at bottom of image
        if played_pct > 0:
            progress = Gtk.ProgressBar()
            progress.get_style_context().add_class("cw-progress")
            progress.set_fraction(played_pct / 100.0)
            img_wrap.pack_end(progress, False, False, 0)

        title_label = Gtk.Label(label=name)
        title_label.get_style_context().add_class("card-title")
        title_label.set_max_width_chars(30)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_halign(Gtk.Align.START)

        card.pack_start(img_wrap, False, False, 0)
        card.pack_start(title_label, False, False, 0)

        event_box = Gtk.EventBox()
        event_box.add(card)
        event_box.connect("button-press-event", lambda w, e, it=item: self.on_item_click(it))
        event_box.set_tooltip_text(name)

        self.cw_box.pack_start(event_box, False, False, 0)

    # ── Library / folder tile ───────────────────────────
    def add_lib_card(self, item):
        item_id = item.get("Id")
        name = item.get("Name", "Unknown")
        item_type = item.get("Type", "")

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.get_style_context().add_class("card")

        img_w, img_h = 170, 255
        img_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        img_wrap.get_style_context().add_class("poster")
        img_wrap.set_size_request(img_w, img_h)

        image = Gtk.Image()
        image.set_size_request(img_w, img_h)

        pixbuf = self._load_pixbuf_aspect(item_id, img_w, img_h)
        if pixbuf:
            image.set_from_pixbuf(pixbuf)
        else:
            icon = "folder-music" if "Music" in item_type else "folder"
            image.set_from_icon_name(icon, Gtk.IconSize.DIALOG)

        img_wrap.pack_start(image, True, True, 0)

        title_label = Gtk.Label(label=name)
        title_label.get_style_context().add_class("card-title")
        title_label.set_max_width_chars(24)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_halign(Gtk.Align.START)

        card.pack_start(img_wrap, False, False, 0)
        card.pack_start(title_label, False, False, 0)

        event_box = Gtk.EventBox()
        event_box.add(card)
        event_box.connect("button-press-event", lambda w, e, it=item: self.on_item_click(it))
        event_box.set_tooltip_text(name)

        self.flowbox.add(event_box)

    # ── Item click → folder browse or detail page ──────
    def on_item_click(self, item):
        item_type = item.get("Type", "")
        name = item.get("Name", "Unknown")
        is_folder = item_type in ("CollectionFolder", "Folder", "MusicAlbum", "Season", "Series", "BoxSet", "MusicArtist")
        log(f"Click: {name} (type={item_type}, folder={is_folder})")

        if is_folder:
            parent_id = item["Id"]
            self.browsing_path.append(parent_id)
            self.show_loading_state("Loading...")
            threading.Thread(target=self._load_items, args=(parent_id,), daemon=True).start()
        else:
            self.show_loading_state("Loading details...")
            threading.Thread(target=self._load_detail, args=(item,), daemon=True).start()

    # ── Detail page ─────────────────────────────────────
    def _load_detail(self, item):
        item_id = item.get("Id")
        full_item = self.fetch_item(item_id)
        if not full_item:
            full_item = item
        backdrop = self.fetch_backdrop(item_id, size=1280)
        poster = self._load_pixbuf_aspect(item_id, 200, 300)
        GLib.idle_add(self._render_detail, full_item, backdrop, poster)

    def _render_detail(self, item, backdrop_bytes, poster_pixbuf):
        self._detail_current_item = item
        item_id = item.get("Id")
        name = item.get("Name", "Unknown")
        overview = item.get("Overview", "")
        year = item.get("ProductionYear", "")
        runtime = item.get("RunTimeTicks", 0)
        community_rating = item.get("CommunityRating")
        official_rating = item.get("OfficialRating", "")
        genres = item.get("Genres", [])

        for child in self.detail_box.get_children():
            self.detail_box.remove(child)

        # Backdrop area (height ~280)
        backdrop_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        backdrop_wrap.get_style_context().add_class("detail-backdrop")
        backdrop_wrap.set_size_request(-1, 280)

        backdrop_image = Gtk.Image()
        backdrop_image.set_size_request(-1, 280)

        if backdrop_bytes:
            try:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(backdrop_bytes)
                loader.close()
                pb = loader.get_pixbuf()
                if pb:
                    win_w = self.window.get_size()[0]
                    new_h = 280
                    new_w = int(pb.get_width() * new_h / pb.get_height())
                    scaled = pb.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
                    backdrop_image.set_from_pixbuf(scaled)
            except Exception:
                pass

        if not backdrop_image.get_pixbuf():
            backdrop_image.set_from_icon_name("video-display", Gtk.IconSize.DIALOG)

        # Back button overlay
        back_btn = Gtk.Button(label="← Back")
        back_btn.get_style_context().add_class("detail-back-btn")
        back_btn.connect("clicked", lambda w: self.on_back(None))
        back_btn.set_halign(Gtk.Align.START)
        back_btn.set_valign(Gtk.Align.START)
        back_btn.set_margin_start(16)
        back_btn.set_margin_top(16)

        backdrop_overlay = Gtk.Overlay()
        backdrop_overlay.add(backdrop_image)
        backdrop_overlay.add_overlay(back_btn)

        backdrop_wrap.pack_start(backdrop_overlay, True, True, 0)

        # Info section
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        info_box.get_style_context().add_class("detail-info")

        # Poster + title row
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)

        poster_img = Gtk.Image()
        poster_img.set_size_request(140, 210)
        if poster_pixbuf:
            new_w = 140
            new_h = int(poster_pixbuf.get_height() * new_w / poster_pixbuf.get_width()) if poster_pixbuf.get_width() > 0 else 210
            scaled = poster_pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
            poster_img.set_from_pixbuf(scaled)
        else:
            poster_img.set_from_icon_name("video-display", Gtk.IconSize.DIALOG)

        poster_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        poster_wrap.pack_start(poster_img, False, False, 0)

        # Right side: title, meta, overview, cast button
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        title_label = Gtk.Label(label=name)
        title_label.get_style_context().add_class("detail-title")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_line_wrap(True)
        title_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title_label.set_max_width_chars(60)

        # Meta line: year • runtime • rating • genres
        meta_parts = []
        if year:
            meta_parts.append(str(year))
        if runtime:
            ticks_per_sec = 10000000
            mins = int(runtime / ticks_per_sec / 60)
            if mins > 60:
                meta_parts.append(f"{mins // 60}h {mins % 60}m")
            else:
                meta_parts.append(f"{mins}m")
        if official_rating:
            meta_parts.append(official_rating)
        if community_rating:
            meta_parts.append(f"★ {community_rating:.1f}")
        if genres:
            meta_parts.append(" · ".join(genres[:3]))

        meta_label = Gtk.Label(label="  ·  ".join(meta_parts))
        meta_label.get_style_context().add_class("detail-meta")
        meta_label.set_halign(Gtk.Align.START)

        # Overview
        overview_label = Gtk.Label(label=overview[:600] + ("..." if len(overview) > 600 else "") if overview else "No description available.")
        overview_label.get_style_context().add_class("detail-overview")
        overview_label.set_halign(Gtk.Align.START)
        overview_label.set_line_wrap(True)
        overview_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        overview_label.set_max_width_chars(80)
        overview_label.set_justify(Gtk.Justification.LEFT)
        overview_label.set_xalign(0)

        # Cast button
        cast_btn = Gtk.Button(label="▶  Cast to TV")
        cast_btn.get_style_context().add_class("detail-cast-btn")
        cast_btn.connect("clicked", lambda w: self.cast_item(self._detail_current_item))
        cast_btn.set_halign(Gtk.Align.START)
        cast_btn.set_margin_top(12)

        if not self.chromecast:
            cast_btn.set_label("📺  Select a Chromecast first")
            cast_btn.set_sensitive(False)

        right_col.pack_start(title_label, False, False, 0)
        right_col.pack_start(meta_label, False, False, 0)
        right_col.pack_start(overview_label, False, False, 0)
        right_col.pack_start(cast_btn, False, False, 0)

        top_row.pack_start(poster_wrap, False, False, 0)
        top_row.pack_start(right_col, True, True, 0)

        info_box.pack_start(top_row, False, False, 0)

        self.detail_box.pack_start(backdrop_wrap, False, False, 0)
        self.detail_box.pack_start(info_box, True, True, 0)
        self.detail_box.show_all()

        self.show_detail_view()
        log(f"Detail rendered: {name}")

    # ── Casting ─────────────────────────────────────────
    def cast_item(self, item):
        if not self.chromecast:
            self.show_toast("Select a Chromecast first (Cast button in toolbar)")
            return

        item_id = item.get("Id")
        name = item.get("Name", "Unknown")
        log(f"Casting: {name}")

        self.show_toast(f"🎬 {name}")
        threading.Thread(target=self._cast_media, args=(item_id, name), daemon=True).start()

    def _cast_media(self, item_id, name):
        try:
            mc = self.chromecast.media_controller
            item_info = self.fetch_item(item_id)

            mime = "video/mp4"
            if item_info:
                containers = item_info.get("Container", "mp4").lower()
                if "mkv" in containers:
                    mime = "video/x-matroska"
                elif "webm" in containers:
                    mime = "video/webm"
                elif "ts" in containers or "m2ts" in containers:
                    mime = "video/mp2t"
                elif "mp3" in containers:
                    mime = "audio/mpeg"
                elif "flac" in containers:
                    mime = "audio/flac"
                elif "wav" in containers:
                    mime = "audio/wav"

            stream_url = f"{self.server_url.rstrip('/')}/Videos/{item_id}/stream?static=true&api_key={self.api_key}"
            log(f"Stream: {stream_url[:80]}... mime={mime}")

            mc.play_media(stream_url, content_type=mime, title=name)
            GLib.idle_add(self._update_now_playing, name, item_id)
        except Exception as e:
            log(f"Cast error: {e}")
            GLib.idle_add(self.show_toast, f"Cast error: {e}")

    def _update_now_playing(self, title, item_id):
        log(f"Now playing: {title}")
        self.np_title.set_text(title)
        self.np_play_btn.set_label("⏸")
        threading.Thread(target=self._fetch_np_thumbnail, args=(item_id,), daemon=True).start()

        if self._progress_timer_id:
            GLib.source_remove(self._progress_timer_id)
        self._progress_timer_id = GLib.timeout_add(1000, self._poll_progress)

    def _fetch_np_thumbnail(self, item_id):
        img_data = self.fetch_image(item_id, size=120)
        if img_data:
            try:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(img_data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                if pixbuf:
                    orig_w = pixbuf.get_width()
                    orig_h = pixbuf.get_height()
                    if orig_w > 0 and orig_h > 0:
                        scale = min(48 / orig_w, 48 / orig_h)
                        new_w = max(1, int(orig_w * scale))
                        new_h = max(1, int(orig_h * scale))
                        scaled = pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)
                        GLib.idle_add(self.np_thumbnail.set_from_pixbuf, scaled)
            except Exception:
                pass

    def _format_time(self, seconds):
        if not seconds:
            return "0:00"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        hours = int(mins // 60)
        if hours > 0:
            return f"{hours}:{mins % 60:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    def _poll_progress(self):
        if not self.chromecast or not self.chromecast.media_controller.is_active:
            return False
        try:
            status = self.chromecast.media_controller.status
            if status and status.duration:
                fraction = (status.current_time or 0) / status.duration
                time_str = f"{self._format_time(status.current_time)} / {self._format_time(status.duration)}"
                GLib.idle_add(self.np_progress.set_fraction, fraction)
                GLib.idle_add(self.np_time_label.set_text, time_str)

                state = status.player_state
                if state == "PLAYING":
                    GLib.idle_add(self.np_play_btn.set_label, "⏸")
                elif state == "PAUSED":
                    GLib.idle_add(self.np_play_btn.set_label, "▶")
        except Exception:
            pass
        return True

    def on_play_pause(self, widget):
        if not self.chromecast or not self.chromecast.media_controller.is_active:
            return
        mc = self.chromecast.media_controller
        if mc.status and mc.status.player_state == "PLAYING":
            mc.pause()
            self.np_play_btn.set_label("▶")
            self.show_toast("Paused")
        else:
            mc.play()
            self.np_play_btn.set_label("⏸")
            self.show_toast("Playing")

    def on_seek_fwd(self, widget):
        if not self.chromecast or not self.chromecast.media_controller.is_active:
            return
        mc = self.chromecast.media_controller
        if mc.status and mc.status.current_time is not None:
            mc.seek(min(mc.status.current_time + 30, mc.status.duration or 0))
            self.show_toast("+30s")

    def on_seek_back(self, widget):
        if not self.chromecast or not self.chromecast.media_controller.is_active:
            return
        mc = self.chromecast.media_controller
        if mc.status and mc.status.current_time is not None:
            mc.seek(max(0, mc.status.current_time - 30))
            self.show_toast("-30s")

    def on_stop_cast(self, widget):
        if not self.chromecast:
            return
        self.chromecast.media_controller.stop()
        self.np_title.set_text("Nothing casting")
        self.np_subtitle.set_text("")
        self.np_progress.set_fraction(0.0)
        self.np_time_label.set_text("0:00 / 0:00")
        self.np_thumbnail.clear()
        self.np_play_btn.set_label("▶")
        if self._progress_timer_id:
            GLib.source_remove(self._progress_timer_id)
            self._progress_timer_id = None
        self.show_toast("Stopped")

    # ── Cast picker ─────────────────────────────────────
    def show_cast_devices(self, widget):
        dialog = Gtk.Dialog(title="Select Chromecast", parent=self.window, flags=0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.set_default_size(380, 300)

        spinner = Gtk.Spinner()
        spinner.start()
        loading = Gtk.Label(label="Scanning for devices...")
        loading.get_style_context().add_class("loading-label")
        loading.set_margin_top(40)
        loading.set_margin_bottom(40)

        load_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        load_box.set_halign(Gtk.Align.CENTER)
        load_box.pack_start(spinner, False, False, 0)
        load_box.pack_start(loading, False, False, 0)

        box = dialog.get_content_area()
        box.add(load_box)
        dialog.show_all()

        def on_found(chromecasts):
            for child in box.get_children():
                box.remove(child)

            if not chromecasts:
                lbl = Gtk.Label(label="No devices found")
                lbl.get_style_context().add_class("placeholder")
                lbl.set_margin_top(40)
                lbl.set_margin_bottom(40)
                box.add(lbl)
                dialog.show_all()
                return

            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            container.set_margin_top(12)
            container.set_margin_bottom(12)
            container.set_margin_start(12)
            container.set_margin_end(12)

            for cc in chromecasts:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row.get_style_context().add_class("cast-row")

                icon = Gtk.Label(label="📺")
                icon.set_halign(Gtk.Align.START)

                name_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                name_label = Gtk.Label(label=cc.name)
                name_label.get_style_context().add_class("cast-device-name")
                name_label.set_halign(Gtk.Align.START)

                type_label = Gtk.Label(label=cc.cast_type.capitalize() if hasattr(cc, 'cast_type') else "Chromecast")
                type_label.get_style_context().add_class("cast-device-type")
                type_label.set_halign(Gtk.Align.START)

                name_col.pack_start(name_label, False, False, 0)
                name_col.pack_start(type_label, False, False, 0)

                btn = Gtk.Button(label="Connect")
                btn.get_style_context().add_class("cast-connect-btn")
                btn.connect("clicked", lambda w, c=cc: self._select_chromecast(c, dialog))

                row.pack_start(icon, False, False, 0)
                row.pack_start(name_col, True, True, 0)
                row.pack_start(btn, False, False, 0)

                container.add(row)

            box.add(container)
            dialog.show_all()

        def scan():
            chromecasts, browser = pychromecast.get_chromecasts()
            log(f"Found {len(chromecasts)} devices")
            GLib.idle_add(on_found, chromecasts)

        threading.Thread(target=scan, daemon=True).start()
        dialog.run()
        dialog.destroy()

    def _select_chromecast(self, cc, dialog):
        log(f"Selected: {cc.name}")
        cc.wait()
        self.chromecast = cc
        self.update_status()
        self.show_toast(f"Connected to {cc.name}")
        dialog.response(Gtk.ResponseType.CANCEL)

        # If detail page is visible, refresh cast button
        if self.detail_box.get_visible() and self._detail_current_item:
            GLib.idle_add(self._refresh_detail_cast_button)

    def _refresh_detail_cast_button(self):
        for child in self.detail_box.get_children():
            for sub in child.get_children():
                if isinstance(sub, Gtk.Box):
                    for w in sub.get_children():
                        if isinstance(w, Gtk.Box):
                            for ww in w.get_children():
                                if isinstance(ww, Gtk.Box):
                                    for www in ww.get_children():
                                        if isinstance(www, Gtk.Button) and www.get_style_context().has_class("detail-cast-btn"):
                                            if self.chromecast:
                                                www.set_label("▶  Cast to TV")
                                                www.set_sensitive(True)

    # ── Server config / Quick Connect ───────────────────
    def show_server_config(self, widget):
        dialog = Gtk.Dialog(title="Connect to Jellyfin", parent=self.window, flags=0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.set_default_size(460, 380)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        step1 = Gtk.Label(label="<b>Server URL</b>")
        step1.set_use_markup(True)
        step1.set_halign(Gtk.Align.START)
        content.pack_start(step1, False, False, 0)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("https://jellyfin.example.com")
        if self.server_url:
            url_entry.set_text(self.server_url)
        content.pack_start(url_entry, False, False, 0)

        step2 = Gtk.Label(label="<b>Quick Connect</b>")
        step2.set_use_markup(True)
        step2.set_halign(Gtk.Align.START)
        step2.set_margin_top(8)
        content.pack_start(step2, False, False, 0)

        qc_btn = Gtk.Button(label="Start Quick Connect")
        qc_btn.get_style_context().add_class("suggested")
        content.pack_start(qc_btn, False, False, 0)

        qc_code_label = Gtk.Label(label="")
        qc_code_label.set_halign(Gtk.Align.CENTER)

        qc_status_label = Gtk.Label(label="")
        qc_status_label.set_halign(Gtk.Align.CENTER)

        spinner = Gtk.Spinner()

        content.pack_start(qc_code_label, False, False, 0)
        content.pack_start(qc_status_label, False, False, 0)
        content.pack_start(spinner, False, False, 0)

        box = dialog.get_content_area()
        box.add(content)
        dialog.show_all()

        qc_code_label.hide()
        qc_status_label.hide()
        spinner.hide()

        def on_qc_click(btn):
            url = url_entry.get_text().strip()
            if not url:
                qc_status_label.set_text("Enter a server URL first")
                qc_status_label.show()
                return

            self.server_url = url
            log(f"Quick Connect for {url}")
            qc_btn.set_sensitive(False)
            url_entry.set_sensitive(False)
            spinner.start()
            spinner.show()
            qc_status_label.set_text("Initiating...")
            qc_status_label.show()
            threading.Thread(target=_qc_flow, daemon=True).start()

        def _qc_flow():
            try:
                resp = requests.get(f"{self.server_url.rstrip('/')}/QuickConnect/Enabled", timeout=10)
                if not resp.json():
                    GLib.idle_add(_qc_fail, "Quick Connect not enabled on this server")
                    return
            except Exception as e:
                GLib.idle_add(_qc_fail, f"Cannot reach server: {e}")
                return

            try:
                resp = requests.get(
                    f"{self.server_url.rstrip('/')}/QuickConnect/Initiate",
                    headers=self._auth_header(), timeout=10,
                )
                data = resp.json()
                code = data["Code"]
                self._qc_secret = data["Secret"]
                log(f"QC code: {code}")
                GLib.idle_add(_qc_show_code, code)
            except Exception as e:
                GLib.idle_add(_qc_fail, f"Initiate failed: {e}")
                return

            self._qc_polling = True
            for i in range(60):
                if not self._qc_polling:
                    return
                try:
                    resp = requests.get(
                        f"{self.server_url.rstrip('/')}/QuickConnect/Connect",
                        params={"Secret": self._qc_secret}, timeout=10,
                    )
                    data = resp.json()
                    if data.get("Authenticated"):
                        log("QC authorized!")
                        GLib.idle_add(_qc_authenticate)
                        return
                except Exception:
                    pass
                time.sleep(1)

            if self._qc_polling:
                GLib.idle_add(_qc_fail, "Timed out (60s)")

        def _qc_show_code(code):
            spinner.stop()
            spinner.hide()
            qc_btn.hide()
            qc_code_label.set_markup(f'<span class="qc-code">{code}</span>')
            qc_code_label.get_style_context().add_class("qc-code")
            qc_code_label.show()
            qc_status_label.set_text("Enter this code in Jellyfin:\nSettings → Quick Connect")
            qc_status_label.show()
            spinner.start()
            spinner.show()

        def _qc_fail(msg):
            log(f"QC failed: {msg}")
            spinner.stop()
            spinner.hide()
            qc_btn.set_sensitive(True)
            url_entry.set_sensitive(True)
            qc_status_label.set_text(str(msg))
            qc_status_label.show()
            qc_code_label.hide()
            self._qc_polling = False

        def _qc_authenticate():
            self._qc_polling = False
            log("Authenticating with QC secret")
            try:
                resp = requests.post(
                    f"{self.server_url.rstrip('/')}/Users/AuthenticateWithQuickConnect",
                    headers={**self._auth_header(), "Content-Type": "application/json"},
                    json={"Secret": self._qc_secret}, timeout=10,
                )
                data = resp.json()
                self.api_key = data["AccessToken"]
                self.user_id = data["User"]["Id"]
                username = data["User"]["Name"]
                log(f"Authenticated as {username}")

                self.save_config()
                self.update_status()

                spinner.stop()
                spinner.hide()
                qc_code_label.set_markup(
                    f'<span foreground="#4CAF50" size="large" weight="bold">✓ Connected as {username}</span>'
                )
                qc_status_label.set_text("Loading library...")

                GLib.timeout_add(1000, lambda: (dialog.destroy(), self.on_refresh(None))[0])
            except Exception as e:
                _qc_fail(f"Auth failed: {e}")

        qc_btn.connect("clicked", on_qc_click)
        dialog.run()
        self._qc_polling = False
        dialog.destroy()

    # ── Help ────────────────────────────────────────────
    def show_help(self, widget):
        dialog = Gtk.Dialog(title=f"About {APP_NAME}", parent=self.window, flags=0)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)

        text = Gtk.Label(
            label=f"""<b>{APP_NAME} v{VERSION}</b>

A minimal Jellyfin remote with Chromecast support.

<b>How to use:</b>
1. Server → Quick Connect to your Jellyfin
2. Cast → select your Chromecast
3. Click media to see details
4. Cast from detail page
5. Bottom bar controls playback

<b>Shortcuts:</b>
• F5 — Refresh
• ESC — Go back"""
        )
        text.set_use_markup(True)
        text.set_margin_start(24)
        text.set_margin_end(24)
        text.set_margin_top(24)
        text.set_margin_bottom(24)

        box = dialog.get_content_area()
        box.add(text)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    # ── Keyboard ────────────────────────────────────────
    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_F5:
            self.on_refresh(None)
            return True
        elif event.keyval == Gdk.KEY_Escape:
            self.on_back(None)
            return True
        return False


def main():
    log("main()")
    app = QuickCast()
    Gtk.main()
    log("exit")


if __name__ == "__main__":
    main()