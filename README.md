# Anamorph

[![Licence: GPL v3+](https://img.shields.io/badge/licence-GPL--3.0--or--later-blue.svg)](LICENSE)

Projection mapping: take a video or an image, cut it into surfaces, and land
each surface exactly on the thing you are projecting onto — a wall, a column,
a set piece, a shop window.

One canvas, any number of projectors. Each projector shows its own region of
that canvas, through its own keystone, edge blend and colour correction, so
two of them can overlap and disappear into each other rather than being two
separate artworks that happen to be pointed at the same building.

---

## Installing

You need **Python 3.12 or newer**. (`numpy` has no build below that.)

```bash
git clone https://github.com/KAIKOAUGUSTIN/Anamorph.git
cd Anamorph

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python projection_gui.py
```

There is no installer yet — this runs from source.

---

## Your first surface, in five minutes

1. **Plug the projector in** and let the desktop see it as a second display.
2. **Open the Outputs dialog** (`Outputs...` in the toolbar). Pick your
   projector under **Screen**. The canvas takes that projector's resolution
   automatically the first time — leave it alone unless you know you want
   something else.
3. **Turn on Test Mode** and press **Project**. A calibration grid appears on
   the wall. Focus the projector and square it up physically as far as it will
   go; correct the rest with **Keystone** in the Outputs dialog. Physical
   first, always — keystone throws away pixels.
4. **Turn Test Mode off.** Click **Polygon** in the toolbar and click on the
   canvas. A quad appears.
5. **Load media**: with the surface selected, `Image` or `Video` in the
   properties panel on the right.
6. **Drag the corners onto the thing you are projecting onto.** Click the
   surface once to select it (you get the white box grips); click it *again*
   to switch to its own corner points, and drag those. The projection follows
   live.
7. **Save** with `Ctrl+S`.

That is the whole loop. Everything else is refinement.

---

## The parts

### Surfaces

- **Polygon** — any number of corners. Each edge can be hidden, shortened, or
  curved (`Alt` + double-click an edge). This is the workhorse.
- **Circle** — an ellipse, dragged by four axis handles.
- **Mesh** — a grid of control points that bends *between* its corners. For
  columns, cylinders, domes, hanging cloth: anything four corners cannot
  describe.

You can change a surface's type later without losing its media or its name.

**Masks** cut holes in a surface — a window, a doorway, a pillar standing in
front of the wall. `Ctrl+M`, then drag the red corners.

**Groups** make several surfaces move as one (`Ctrl+G`). Useful for a window
frame made of four panels, or a row of identical columns.

### Fitting media to a surface

The **Fit** setting decides how the image lands:

| Mode | What it does |
|---|---|
| Stretch | Fills the surface, ignoring aspect ratio |
| Contain | Fits inside, letterboxed |
| Cover | Fills and crops |
| **Corner pin** | Maps the image onto the four corners with real perspective |

**Corner pin is the one that matters** for projection mapping. It is what
makes an image sit flat on a wall you are looking at from an angle. It is the
default the first time you drop media on a quad.

**Source region** picks *which part* of the media feeds this surface —
"this wall shows the left third of the video". One clip can drive six
surfaces, each taking a different slice, without six copies of the file.

### Playing

The whole show runs off one clock. `Space` plays and pauses everything; the
toolbar shows the position and a rate for the show as a whole.

Each surface has its own **Playback** settings — loop, speed, and an offset
that says where show-time zero lands in that clip. Two surfaces with the same
file and the same settings share one decoder, which is what keeps them
frame-accurate against each other.

**Blend** decides how a surface composites over what is under it. `Add` and
`Screen` are how projected light actually behaves: two beams on the same wall
sum, they do not replace one another. Stacking two surfaces with `Add` is
also how you layer for now.

### Multiple projectors

In the Outputs dialog, each projector gets:

- **Canvas region** — which part of the shared canvas it covers. Two
  projectors overlap here.
- **Keystone** — four corners, for squaring the projector against the surface.
- **Edge blend** — a ramp on the edges that meet a neighbour, so the seam
  disappears. Tune the curve by eye until the overlap stops showing as a
  bright or dark band.
- **Colour** — projectors never match out of the box.

**Tile** sets up N projectors side by side, already overlapping, with matching
blend ramps. It is the fastest way to start a two-projector rig.

**Preview** shows what one projector sees — region, keystone, blend, colour —
without turning the projector on.

---

## When something goes wrong

**Blackout (`B`)** kills every projector instantly. This is the panic button.
It is not pause — pausing leaves the last frame on the wall. The editor keeps
working, and draws a red frame around the canvas so you know the projectors
are dark.

**A surface is hatched red** — its media file is not where the project expects
it. The toolbar shows how many are missing; click it to relink. Relinking
works by folder, so pointing at one file's new home finds its neighbours too.

**A warning appears in the toolbar** — something failed that was not fatal: a
codec this build cannot open, a file that would not parse. Click it for the
list.

**Nothing on the wall at all** — check, in order: is Blackout on, is
**Project** on, does the output have a **Screen** assigned, is it **Enabled**.

**The projection looks softer than it should** — the canvas is probably
smaller than the projector. Check the resolution in the Outputs dialog and use
**Match to screen**.

---

## Files

Projects are `.pmap.json`. Media paths are stored **relative to the project
file** when the media lives near it, so you can copy the whole show folder to
the machine driving the projectors and it still opens. Keep media in a folder
beside the project and this works by itself.

Saving keeps the previous version as `.bak`, and writes atomically — a crash
mid-save cannot destroy the good file.

Work is autosaved to a session copy every 20 seconds. If the app dies, it
comes back with the unsaved work still there and tells you so. That copy is
*not* your file: you still have to save.

---

## Keyboard and mouse

`F1` opens the full sheet in the app. The essentials:

| | |
|---|---|
| Click | Select a surface |
| Click again | Swap between the box grips and the surface's own points |
| `Ctrl` + click | Add a surface to the selection |
| Drag the body | Move. `Shift` locks to one axis |
| `Alt` + drag | Rotate. `Shift` snaps to 15° |
| `Ctrl` + drag | Scale |
| Double-click an edge | Insert a vertex |
| `Alt` + double-click an edge | Curve it, or straighten it |
| `Space` | Play / pause the show |
| `B` | Blackout |
| `Ctrl+D` / `Ctrl+M` / `Ctrl+G` | Duplicate / mask / group |
| `Ctrl+Z` | Undo — everything that changes the artwork is undoable |

---

## Supported media

- **Images** — PNG, JPG, JPEG, BMP
- **Video** — MP4, MOV, AVI, MKV
- **Live** — any capture device OpenCV can open, by index

No audio yet.

---

## Running the tests

```bash
pytest
```

The rendering tests need a real OpenGL context and skip without one. To run
them for real:

```bash
xvfb-run -a env QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 pytest
```

`CLAUDE.md` documents the internals and the reasoning behind them — read that
before changing anything, not this file.

---

## Licence

Anamorph is free software: you can redistribute it and modify it under the
terms of the **GNU General Public License, version 3 or later**, as published
by the Free Software Foundation. The full text is in [LICENSE](LICENSE).

It is distributed in the hope that it will be useful, but **WITHOUT ANY
WARRANTY** — without even the implied warranty of merchantability or fitness
for a particular purpose.

In practice, what this means for you:

- **Use it for anything**, including paid commercial shows. Using the program
  puts no obligation on you at all.
- **If you distribute it** — modified or not, free or sold — you have to pass
  on the source under the same licence, and keep the notices intact.
- **Your shows are yours.** The licence covers this program's code, not the
  `.pmap.json` files you make with it or the media you project.

Third-party components and their licences are listed in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Contributing

Contributions come in under the same GPL-3.0-or-later, certified with a
[Developer Certificate of Origin](CONTRIBUTING.md) sign-off (`git commit -s`).
You keep the copyright on what you write — nothing is assigned to anyone, and
as a result **this project cannot be relicensed or closed** without every
contributor agreeing. That is the intent, and the DCO is what makes it
structural rather than a promise.

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## What is not here yet

Being straight about it: **audio**, **NDI / Spout / Syphon**, **scenes and
cues**, **MIDI / OSC / DMX**, **mesh warp on the output stage** (projectors get
four-corner keystone only), and **multiple media layers inside one surface**.

There is also no packaged build — it runs from source.
