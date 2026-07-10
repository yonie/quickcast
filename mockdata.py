"""Deterministic mock backend for QuickCast.

Enabled with `--mock` (or QUICKCAST_MOCK=1). Serves invented libraries and
items with real, rights-free artwork from Lorem Picsum (Unsplash-sourced,
free to use), seeded per item so it is stable across runs and cached to disk
so it works offline after the first fetch. Falls back to procedurally-drawn
art when offline. No real server and no copyrighted content, so the app can
be screenshotted and regression-tested freely.
"""
import hashlib
import io
import os

import cairo
import requests

_CACHE_DIR = os.path.expanduser("~/.cache/quickcast/mock-art")
_OFFLINE = os.environ.get("QUICKCAST_MOCK_OFFLINE") == "1"

# ── Invented, non-copyrighted content ───────────────────────────────
MOVIE_TITLES = [
    "The Silent Harbor", "Neon Skyline", "Autumn Vector", "Paper Kingdoms",
    "Glass Meridian", "The Longest Winter", "Velvet Machine", "Northern Signals",
    "A Quiet Algorithm", "Cinder & Salt", "The Ninth Room", "Hollow Tide",
    "Marigold Country", "Static Bloom", "The Last Ferry", "Copper Sun",
    "Midnight Cartography", "Wren", "The Understudy", "Gravity's Cousin",
    "Saltwater Gospel", "The Paper Moon", "Ember Street", "Low Orbit",
]
SERIES_TITLES = ["Division Nine", "The Greenhouse", "Cold Harbor", "Aftered", "Signal Hill", "Understory"]
ARTIST_NAMES = [
    "Blue Static", "The Harbor Lights", "Marlow", "Cassette Sky", "Ivory Coast Club",
    "Northern Wren", "Paper Tigers", "The Meridians", "Velour", "Slow Channel",
    "Amber Roads", "Glasshouse", "The Undertow", "Kestrel", "Neon Parish",
    "Saltbox", "The Ninth Hour", "Lantern", "Foxglove", "Tidewater",
    "Copperfield", "The Quiet Set", "Marigold", "Ember Choir",
]
GENRES = ["Action", "Comedy", "Drama", "Documentary", "Family", "Sci-Fi", "Thriller", "Music"]
OVERVIEW = (
    "A quietly ambitious story that follows its characters across one turning "
    "point, told with restraint and a good deal of warmth. Placeholder synopsis "
    "for mock mode — no real metadata is shown."
)
LIBRARIES = [
    ("lib-movies", "Movies", "movie"),
    ("lib-series", "Series", "series"),
    ("lib-music", "Music", "artist"),
    ("lib-kids", "Kids", "movie"),
]


def _rand(seed, lo, hi):
    """Deterministic int in [lo, hi] from a string seed."""
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return lo + (h % (hi - lo + 1))


def _ticks(minutes):
    return int(minutes * 60 * 10_000_000)


class MockData:
    # ── artwork ─────────────────────────────────────────────────────
    def _aspect(self, item_id):
        if item_id.startswith("lib-") or "-e" in item_id:   # library banner / episode
            return (16, 9)
        if item_id.startswith("artist-") or "-al" in item_id or "-tr" in item_id:
            return (1, 1)            # music: square
        return (2, 3)                # movie / series / season poster

    def image(self, item_id, size=300):
        aw, ah = self._aspect(item_id)
        scale = size / max(aw, ah)
        w, h = max(1, int(aw * scale)), max(1, int(ah * scale))
        return self._photo(item_id, w, h) or self._draw(item_id, w, h, self._label(item_id))

    def backdrop(self, item_id, size=1280):
        w, h = size, int(size * 9 / 16)
        return self._photo(item_id + "-bd", w, h) or self._draw(item_id + "-bd", w, h, "", band=False)

    def _photo(self, seed, w, h):
        """Real rights-free photo from Lorem Picsum, seeded + disk-cached.
        Returns image bytes, or None to fall back to procedural art."""
        if _OFFLINE:
            return None
        key = hashlib.md5(f"{seed}-{w}x{h}".encode()).hexdigest()
        path = os.path.join(_CACHE_DIR, f"{key}.jpg")
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
        except OSError:
            pass
        try:
            url = f"https://picsum.photos/seed/{key}/{w}/{h}"
            resp = requests.get(url, timeout=6)
            resp.raise_for_status()
            data = resp.content
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            return data
        except Exception:
            return None  # offline / blocked → procedural fallback

    def _label(self, item_id):
        name = self.item(item_id).get("Name", "?")
        parts = [p for p in name.replace("&", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return name[:2].upper()

    def _draw(self, seed, w, h, label, band=True):
        d = hashlib.md5(seed.encode()).digest()
        r, g, b = d[0] / 255, d[1] / 255, d[2] / 255
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        # diagonal-ish two-tone background
        grad = cairo.LinearGradient(0, 0, w, h)
        grad.add_color_stop_rgb(0, r * 0.45, g * 0.45, b * 0.5)
        grad.add_color_stop_rgb(1, r * 0.8, g * 0.8, b * 0.85)
        cr.set_source(grad)
        cr.paint()
        if band:
            cr.set_source_rgba(1, 1, 1, 0.08)
            cr.rectangle(0, h * 0.62, w, h * 0.06)
            cr.fill()
        if label:
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            fs = min(w, h) * 0.42
            cr.set_font_size(fs)
            ext = cr.text_extents(label)
            cr.move_to(w / 2 - ext.width / 2 - ext.x_bearing, h / 2 - ext.height / 2 - ext.y_bearing)
            cr.set_source_rgba(1, 1, 1, 0.92)
            cr.show_text(label)
        buf = io.BytesIO()
        surf.write_to_png(buf)
        return buf.getvalue()

    # ── structure ───────────────────────────────────────────────────
    def views(self):
        return [{"Id": lid, "Name": name, "Type": "CollectionFolder"} for lid, name, _ in LIBRARIES]

    def _movie(self, n, kids=False):
        seed = f"movie-{n}"
        title = MOVIE_TITLES[n % len(MOVIE_TITLES)]
        year = _rand(seed + "y", 1968, 2024)
        return {
            "Id": ("kid-" if kids else "") + seed, "Name": title, "Type": "Movie",
            "ProductionYear": year,
            "CommunityRating": round(4 + _rand(seed + "r", 0, 55) / 10, 1),
            "OfficialRating": ["G", "PG", "PG-13", "R"][_rand(seed + "o", 0, 3)],
            "RunTimeTicks": _ticks(_rand(seed + "t", 82, 158)),
            "Genres": [GENRES[_rand(seed + "g", 0, len(GENRES) - 1)],
                       GENRES[_rand(seed + "g2", 0, len(GENRES) - 1)]],
            "Overview": OVERVIEW,
            "UserData": {"PlaybackPositionTicks": 0},
        }

    def _series(self, n):
        seed = f"series-{n}"
        return {"Id": seed, "Name": SERIES_TITLES[n % len(SERIES_TITLES)], "Type": "Series",
                "ProductionYear": _rand(seed + "y", 2012, 2024),
                "ChildCount": _rand(seed + "c", 2, 4),
                "CommunityRating": round(6 + _rand(seed + "r", 0, 35) / 10, 1),
                "Genres": ["Drama"], "Overview": OVERVIEW}

    def _artist(self, n):
        seed = f"artist-{n}"
        return {"Id": seed, "Name": ARTIST_NAMES[n % len(ARTIST_NAMES)], "Type": "MusicArtist"}

    def items(self, parent_id, sort_by="SortName", sort_order="Ascending", genre=None, decade=None):
        out = []
        if parent_id in ("lib-movies", "lib-kids"):
            kids = parent_id == "lib-kids"
            count = 12 if kids else len(MOVIE_TITLES)
            out = [self._movie(i, kids) for i in range(count)]
        elif parent_id == "lib-series":
            out = [self._series(i) for i in range(len(SERIES_TITLES))]
        elif parent_id == "lib-music":
            out = [self._artist(i) for i in range(len(ARTIST_NAMES))]
        elif parent_id.startswith("series-") and "-s" not in parent_id:
            seasons = _rand(parent_id + "c", 2, 4)
            out = [{"Id": f"{parent_id}-s{s}", "Name": f"Season {s}", "Type": "Season",
                    "ProductionYear": 2015 + s} for s in range(1, seasons + 1)]
        elif "-s" in parent_id and "-e" not in parent_id:
            eps = _rand(parent_id + "e", 5, 9)
            s = parent_id.split("-s")[-1]
            out = [{"Id": f"{parent_id}-e{e}", "Name": f"Episode {e}", "Type": "Episode",
                    "ParentIndexNumber": int(s), "IndexNumber": e,
                    "RunTimeTicks": _ticks(_rand(f'{parent_id}e{e}', 42, 58)),
                    "Overview": OVERVIEW, "UserData": {"PlaybackPositionTicks": 0}} for e in range(1, eps + 1)]
        elif parent_id.startswith("artist-") and "-al" not in parent_id:
            albums = _rand(parent_id + "a", 2, 5)
            out = [{"Id": f"{parent_id}-al{a}", "Name": f"Album {a}", "Type": "MusicAlbum",
                    "AlbumArtist": self._artist(int(parent_id.split("-")[1])).get("Name"),
                    "ProductionYear": _rand(f'{parent_id}al{a}', 1998, 2024)} for a in range(1, albums + 1)]
        elif "-al" in parent_id:
            tracks = _rand(parent_id + "t", 6, 12)
            out = [{"Id": f"{parent_id}-tr{t}", "Name": f"Track {t}", "Type": "Audio",
                    "IndexNumber": t, "RunTimeTicks": _ticks(_rand(f'{parent_id}tr{t}', 2, 6))}
                   for t in range(1, tracks + 1)]

        if genre:
            out = [x for x in out if genre in (x.get("Genres") or [])]
        if decade is not None:
            lo, hi = (1900, 1949) if decade == 0 else (decade, decade + 9)
            out = [x for x in out if x.get("ProductionYear") and lo <= x["ProductionYear"] <= hi]

        reverse = sort_order == "Descending"
        if "ProductionYear" in sort_by:
            out.sort(key=lambda x: x.get("ProductionYear") or 0, reverse=reverse)
        elif "CommunityRating" in sort_by:
            out.sort(key=lambda x: x.get("CommunityRating") or 0, reverse=reverse)
        elif "DateCreated" in sort_by:
            out.sort(key=lambda x: _rand(x["Id"] + "dc", 0, 9999), reverse=reverse)
        elif sort_by == "Random":
            out.sort(key=lambda x: _rand(x["Id"] + "rnd", 0, 9999))
        else:
            out.sort(key=lambda x: x.get("Name", ""), reverse=reverse)
        return out

    def resume(self):
        items = []
        for i in (2, 5, 9, 14):
            m = self._movie(i)
            m["UserData"] = {"PlaybackPositionTicks": _ticks(_rand(m["Id"] + "p", 12, 70)),
                             "PlayedPercentage": _rand(m["Id"] + "pp", 15, 80)}
            items.append(m)
        ep = self.item("series-0-s1-e2")
        ep["UserData"] = {"PlayedPercentage": 45}
        items.append(ep)
        return items

    def genres(self, parent_id):
        if parent_id in ("lib-movies", "lib-kids"):
            return GENRES
        return []

    def search(self, term):
        term = term.lower()
        hits = []
        for i in range(len(MOVIE_TITLES)):
            if term in MOVIE_TITLES[i].lower():
                hits.append(self._movie(i))
        for i in range(len(ARTIST_NAMES)):
            if term in ARTIST_NAMES[i].lower():
                hits.append(self._artist(i))
        for i in range(len(SERIES_TITLES)):
            if term in SERIES_TITLES[i].lower():
                hits.append(self._series(i))
        return hits

    def item(self, item_id):
        """Reconstruct a full item (with MediaSources) from its id."""
        if item_id.startswith(("movie-", "kid-movie-")):
            n = int(item_id.split("movie-")[-1])
            it = self._movie(n, item_id.startswith("kid-"))
        elif "-e" in item_id:
            s = int(item_id.split("-s")[1].split("-e")[0])
            e = int(item_id.split("-e")[1])
            it = {"Id": item_id, "Name": f"Episode {e}", "Type": "Episode",
                  "ParentIndexNumber": s, "IndexNumber": e, "ProductionYear": 2015 + s,
                  "RunTimeTicks": _ticks(_rand(item_id, 42, 58)), "Overview": OVERVIEW,
                  "Genres": ["Drama"], "UserData": {"PlaybackPositionTicks": 0}}
        elif item_id.startswith("series-") and "-s" not in item_id:
            it = self._series(int(item_id.split("-")[1]))
        elif "-al" in item_id and "-tr" not in item_id:
            it = {"Id": item_id, "Name": "Album", "Type": "MusicAlbum",
                  "ProductionYear": _rand(item_id, 1998, 2024), "Genres": ["Music"], "Overview": OVERVIEW}
        elif item_id.startswith("artist-"):
            it = self._artist(int(item_id.split("-")[1]))
        else:
            it = {"Id": item_id, "Name": "Item", "Type": "Video"}
        # attach a plausible media source
        it.setdefault("Genres", [])
        it["MediaSources"] = [{
            "Container": ["mkv", "mp4"][_rand(item_id + "c", 0, 1)],
            "Bitrate": _rand(item_id + "b", 3, 18) * 1_000_000,
            "Size": _rand(item_id + "s", 700, 14000) * 1_000_000,
            "MediaStreams": [
                {"Type": "Video", "Codec": ["h264", "hevc"][_rand(item_id + "vc", 0, 1)],
                 "Height": [480, 720, 1080, 2160][_rand(item_id + "res", 0, 3)]},
                {"Type": "Audio", "Codec": ["aac", "ac3", "eac3"][_rand(item_id + "ac", 0, 2)],
                 "Channels": [2, 6, 8][_rand(item_id + "ch", 0, 2)]},
            ],
        }]
        return it
