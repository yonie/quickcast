# QuickCast

A minimal GNOME/Linux remote for Jellyfin with Chromecast support. Browse your
libraries, sort and search, then throw anything on the TV. Part of the `quick*`
family (quicksnip, quickcell): looks devilishly simple, trusts the native GNOME
theme, stays out of your way.

## Features

- **Browse** every Jellyfin library with artwork that loads asynchronously
  (grids appear instantly, posters fill in). Cards adapt to the content:
  portrait for movies/series, square for albums and artists, landscape for
  episodes and libraries, each with a subtitle (year, artist, `S2 · E4`).
- **Sort** by name, year, recently added, rating, or random.
- **Search** the whole library as you type.
- **Detail pages** with backdrop, poster, overview and pro-user media info
  (container, resolution, codecs, bitrate, file size).
- **Continue Watching** row on the home screen.
- **Cast** to any Chromecast; the now-playing bar reflects what the device is
  doing, including casts started elsewhere.
- Follows your **light/dark GNOME theme** (no imposed colors).

## Install

```bash
pip install -r requirements.txt   # PyGObject, pychromecast, requests
```

Requires GTK 3 with PyGObject (system package `python3-gobject` / `pygobject3`).

## Run

```bash
python3 quickcast.py
```

First run: **🖥️ Server → Start Quick Connect**, enter your Jellyfin URL, and
approve the code in Jellyfin (Settings → Quick Connect). Config is stored in
`~/.config/quickcast.conf`.

## Shortcuts

| Key | Action |
|-----|--------|
| Ctrl+F or `/` | Search |
| F5 or Ctrl+R | Home / refresh |
| Esc | Back (or clear search) |
| Space | Play / pause (while casting) |

## Mock mode

Run with invented libraries and procedurally-drawn placeholder artwork (no
server, no network, no copyrighted content) — handy for screenshots, demos and
regression tests:

```bash
python3 quickcast.py --mock       # or QUICKCAST_MOCK=1 python3 quickcast.py
```

Mock data is deterministic (derived from item ids), so screenshots are stable
across runs. Implemented in `mockdata.py`.

## Screenshots (development)

`tools/shots.py` drives the app through its key states and writes one PNG each
(it uses mock mode, so the set is deterministic and copyright-free).
Run it under a virtual framebuffer for deterministic, occlusion-independent
captures (Wayland throttles frames for hidden windows):

```bash
xvfb-run -a --server-args="-screen 0 1220x840x24" \
  python3 tools/shots.py build/screenshots
```

`tools/shot.py` grabs a single home-view screenshot the same way.

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
