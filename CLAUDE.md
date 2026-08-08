# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Projection Mapping MVP application built with Python and PySide6. It allows users to create and manipulate shapes (polygons and circles) for projection onto surfaces, with media mapping support (images/videos), effects (pulse, strobe, RGB shift), and multi-screen projection output.

## Running the Application

Requires **Python 3.12+** - `numpy>=2.5.1` in requirements.txt has no build for older interpreters.

```bash
# Install dependencies
pip install -r requirements.txt

# On Windows, activate virtual environment first:
.venv\Scripts\activate

# Run the application
python projection_gui.py
```

## Architecture

### Module Structure

- `projection_gui.py` - Thin CLI entry point, delegates to `app_main.run()`
- `app_main.py` - Application initialization: QApplication setup, high DPI config, theme application
- `about.py` - Name, version, copyright, licence and `PACKAGES` (the app's own top-level modules) in one place, with no Qt import - read by the About box, and by packaging later
- `app_paths.py` - Where the session copy lives, and carrying it across when the app's name moves `AppDataLocation`

- `model/` - Data models (dataclasses, no Qt dependency)
  - `project.py` - Project root with CanvasSettings, shape list, media library; emits `changed` signal via QObject inheritance
  - `shapes.py` - PolygonShape (per-edge visibility and bezier controls), CircleShape and MeshShape dataclasses, plus `Mask`; serialized via `shape_to_dict`/`shape_from_dict`
  - `media.py` - MediaRef (image/video) with fit modes, UV transform, and `SourceRect` (which region of the media feeds the surface)
  - `effects.py` - Effects (pulse, strobe, RGB shift) with parameters
  - `commands.py` - Undoable edits as `QUndoCommand`s, plus `EditSession` for turning a drag - of one shape or a whole group - into one step
  - `transport.py` - The show clock: play/pause/seek/rate for the whole project
  - `snapping.py` - Magnetic snap search (vertex, then edge, then grid); pure geometry
  - `output.py` - `Output` (canvas region, keystone, `EdgeBlend`, `ColorCorrection`) and `split_outputs`
  - `project_store.py` - Loads/saves the one session project; migrates the old per-screen workspaces

- `ui/` - Qt6/PySide6 UI components
  - `main_window.py` - Central window with toolbar, splitter layout, menus, and screen selection
  - `canvas_editor.py` - Interactive QGraphicsView for shape editing; vertex handles plus move/rotate/scale gestures
  - `projection_window.py` - Full-screen projection output window
  - `property_panel.py` - Property editing UI for selected shape
  - `object_list.py` - Layer list with visibility, lock and group markers, and Solo
  - `source_region.py` - Draggable rectangle over the media thumbnail, for picking the input region
  - `output_panel.py` - `OutputDialog`: per-projector region, keystone, blend, colour and the canvas resolution
  - `about_dialog.py` - The About box: the notices GPL-3 asks an interactive program to display
  - `help_dialog.py` - The shortcut sheet, non-modal so it can stay open. `tests/test_problems.py` checks every key it names is actually bound - a manual that lies is worse than none
  - `problem_log.py` - A logging handler that puts warnings and errors where the operator can see them
  - `transport_bar.py` - Play/pause, restart and rate, in the toolbar
  - `relink_dialog.py` - Point the project at media that has moved, by folder
  - `output_preview.py` - Live view of one projector's frame, through its own calibration
- `styles.py` - Studio Dark Luxury theme with cyan accents; provides `STUDIO_DARK_QSS` stylesheet and `COLORS` palette for consistent UI styling
- `widgets.py` - Keyboard-friendly widgets: `ArrowSlider`/`ArrowSpinBox` for arrow-key navigation, and a `NoScrollMixin` so the wheel cannot edit a field it merely rolled past

- `render/` - Rendering subsystem
  - `gl_renderer.py` - `QOpenGLWidget` renderer with GLSL shaders; uploads media as GL textures and caches them per path
  - `shaders.py` - GLSL sources: shared vertex shader plus texture/solid/stroke fragment shaders
  - `homography.py` - Corner-pin math (numpy only, no Qt/GL), shared by the renderer and the editor preview
  - `geometry_cache.py` - Triangles, rebuilt only when a shape's geometry signature changes
  - `fit.py` - `content_rect`: where media sits inside a surface's box. The single source of truth for stretch/contain/cover
  - `test_pattern.py` - Calibration images (grid / checkerboard / borders) drawn with QPainter
  - `mesh.py` - All the CPU-side geometry: earcut triangulation with holes (`triangulate_with_holes`), the Catmull-Rom patch behind `MeshShape` (`tessellate_mesh`/`mesh_outline`), and the cubic-edge sampling behind curved polygons (`bezier_control_points`/`polygon_outline`)

- `media/` - Media handling
  - `availability.py` - Which media the project can actually find, cached briefly
  - `clip_pool.py` - Every open decoder, shared and keyed by what it is playing; the show clock drives them
  - `image_cache.py` - mtime-keyed QImage cache for the editor viewport (paint runs every frame)

- `fileio/` - Serialization
  - `project_io.py` - JSON save/load with `.pmap.json` extension; atomic write, `.bak` of the previous version
  - `media_paths.py` - Media paths relative to the project file, so a show folder can be moved

### Layout

The modules sit at the repository root - `model/`, `ui/`, `render/`, `media/`,
`fileio/` - rather than under a `pm/` package.

`fileio/` is not called `io/` for a hard reason, not a stylistic one: a
top-level `io` package is **unimportable**. CPython imports the standard
library's `io` during interpreter startup, so it is already in `sys.modules`
before any path of ours is consulted, and `from io.project_io import ...`
fails with "'io' is not a package". Renaming it back would break the app at
import time.

`pytest.ini` sets `pythonpath = .` because the repository is not installed as
a package, so the root has to be on `sys.path` for any of these to import.

### Key Design Patterns

1. **Signal-based Updates**: Project.changed signal propagates to UI components; circular updates prevented by `blockSignals` in zoom controls

2. **Shape Types**: Three shape types supported:
   - `PolygonShape`: Variable points, with per-edge visibility, length and curvature
   - `CircleShape`: Elliptical with control points and anchor system
   - `MeshShape`: A control grid of `(rows + 1) x (cols + 1)` points, row-major

   A polygon with a corner pin describes a *flat* plane seen off-axis. A column, a cylinder, a dome or a hung cloth is curved, and no arrangement of four corners can express that - the surface has to bend *between* its corners. `MeshShape` is that surface.

   The control grid is coarse because it is what a person drags; `tessellate_mesh` (`render/mesh.py`) smooths it into a dense render mesh with a **Catmull-Rom** patch, which passes *through* every control point - what the operator positions is exactly where the surface goes, with curvature filled in between. Neighbour lookup at the boundary clamps rather than wraps (`_clamped`): wrapping would pull the far edge of the surface into the near one.

   UVs come from the parametric grid position, not from canvas coordinates, so media flows *along* the bend; `source_rect` and `MediaTransform` still compose on top in the shader. Per-vertex UVs are honest here only because the patch is subdivided - across a coarse cell the interpolation error would be visible, across a subdivided one it is far below a pixel.

   The editor mirrors it in `canvas_editor._paint_mesh_media`, filling one tessellated triangle at a time. `QTransform.quadToQuad` refuses a triangle with a repeated corner, so `_triangle_transform` solves the 2x3 affine directly from the three point pairs. That pass sets `Antialiasing False`: an antialiased clip edge blends with what is behind it, so every shared triangle edge would show up as a pale hairline and the tessellation would be visible through the media.

   `resize_grid` resamples the *current* patch instead of rebuilding a flat grid, so density can be raised late without losing the bending already done.

3. **Media Mapping**: UVs come from the shape's fit mode (`stretch`/`contain`/`cover`), computed per vertex in `_compute_fit_uvs`.

   The `warp` fit mode - shown in the UI as **Corner pin** - is different and is the mode that matters for projection mapping. A four-point polygon gets a homography from `canvas_to_uv_matrix` (`render/homography.py`), uploaded as the `u_uv_matrix` uniform and divided **per fragment** in `FRAGMENT_SHADER_TEXTURE`. Interpolating UVs per vertex instead would bend the image along the triangulation diagonal, which is the classic broken-mapping artifact. Per-vertex UVs are still uploaded as a fallback for degenerate quads.

   The editor mirrors this with `QTransform.quadToQuad` in `canvas_editor._paint_media`, so the canvas preview and the projected output agree. Corner-to-UV pairing is by proximity to the bounding box (`corner_uv_assignment`), not vertex index, so the media stays put while a corner is dragged.

4. **One canvas, many projectors**: A `Project` has one canvas and a list of `Output`s. Each output is one projector's view of *part* of that canvas, carrying its own keystone, edge blend and colour. Screens used to own a whole `Project` each, which made two projectors two separate artworks and left soft-edge with nothing to blend.

   Rendering is two passes (`GLRenderer.paintGL`): the canvas is composited into a framebuffer once, then each output draws that texture through its corrections. Doing it per shape would be wrong, not just slower - a blend ramp must attenuate the *finished* image, or two surfaces overlapping inside the strip each get darkened and the seam turns into a dark patch.

   The blend ramp is an S-curve, not `pow(t, k)`. Facing projectors see `t` and `1-t`, and only the S-curve sums to exactly 1 for any exponent; anything else leaves a bright or dark band down the seam. The exponent stays adjustable because projectors are not linear.

   The canvas pass inverts Y into the framebuffer, so the output pass samples `1 - v`. Without that the projection comes out vertically mirrored - invisible on a symmetric test pattern.

5. **Gestures, not modes**: There is no Points/Scale/Rotate mode any more - a trip to the toolbar mid-show is a trip nobody has time for. The body of the shape carries the transforms:
   - Drag the body: move. `Shift` locks to one axis
   - `Alt` + drag: rotate about the shape's centre. `Shift` snaps to 15 degree steps
   - `Ctrl` + drag: scale from that centre
   - Drag a vertex: reshape that corner. `Alt` still bypasses snapping there

   All three run through `CanvasEditor._update_body_drag` rather than Qt's `ItemIsMovable`, which is what lets `Shift` mean "constrain" instead of "move this time".

   A selected shape also gets a dashed bounding box with four `TransformHandle` grips at its corners and a rotate grip above it. They force their own gesture and drive the same `_apply_body_scale`/`_apply_body_rotate` - there is one implementation of each transform, not two. They exist for discoverability: a modifier with no visible affordance is a feature only the manual can tell you about.

   **Two handle sets, never both at once.** The corner grips land exactly on a quad's corner vertices, so showing both makes one of them unreachable. Selection opens in *transform* mode (grips only); clicking the already-selected shape again switches to *point* mode (vertices, curve controls, mask corners) and back. `_handles_visible_for` is the single rule, and it also honours `locked` - the shape refused to move all along, but its handles stayed live, so a calibrated surface could still be reshaped corner by corner.

   A click on a handle is never a click on the body. `_body_item_at` returns None for every handle type; without that, handles parented to a shape item (curve and mask controls) resolved to their parent, the view started a body gesture and swallowed every move event the handle needed. And the view's press handler *returns* instead of falling through to `QGraphicsView`, which would otherwise select the item under the cursor and clear everything else - the reason a Ctrl-built selection, and a group, used to flicker and collapse the moment it was clicked. Clicking empty canvas clears the selection; *dragging* empty canvas pans and keeps it.

6. **Undo**: Commands are snapshot-based (`model/commands.py`), storing a shape's serialised state before and after an edit and swapping them - shapes are mutated in place during a drag, so there is no inverse to replay. `EditSession` snapshots on mouse press and pushes on release, making a drag one undo step; `ShapeEditCommand.mergeWith` collapses same-labelled edits to the same shape within a short window, which is what keeps a slider drag from filling the stack.

   Anything that mutates a shape must go through a command, or it will be silently un-undoable. In the property panel that means calling `self._commit("Label")` instead of emitting `shape_changed` directly.

   **A command replaces the shape object, it does not mutate it.** `_restore` swaps a freshly deserialised shape into the project list, so anything holding the old reference is left with an orphan: it keeps painting the state that was just undone, and edits written to it never reach the project. Every holder must re-point after a change - `CanvasEditor._update_item` reassigns `item.model`, and `PropertyPanel._commit`/`refresh_geometry` re-read `_shape` by id. A new widget that caches a shape has to do the same.

7. **Curved edges**: Each `EdgeVisibility` carries a cubic's two control points in **edge-local** `(t, n)` units - `t` along the chord from this vertex to the next, `n` perpendicular, both scaled by the chord's length. Move, rotate or scale the polygon and the curvature comes along for free; absolute control points would have to be transformed at every one of those sites, and would be missed at one.

   Straight is the *default value*, not a branch: the controls sit at `1/3` and `2/3` of the chord with no offset, which reproduces the segment exactly. `PolygonShape.curve_pairs()` returns None when nothing is curved, so an all-straight polygon keeps the cheap path through triangulation, stroking and hit testing - and `shape_to_dict` writes no curve keys, leaving old files unchanged.

   `PolygonShape.bow_edge` picks the sign of the first bow from the polygon's winding (`signed_area`), because the edge frame's normal points inward for one winding and outward for the other, and the first click on "Curve" should give an arch rather than a dent.

   The renderer tessellates `shape.outline()`; the editor draws Qt cubics via `polygon_path`, so the preview is the same curve rather than an approximation of it. Corner pin still builds its homography from the four *anchors* (`_warp_matrix` reads `shape.points`, never the outline) and the clip is forced on for curved shapes, so a bulge past a corner reads outside the media instead of smearing its edge texel.

   Edges are curved with Alt+double-click on the canvas or the per-edge Curve box in the panel; the amber `CurveHandle`s appear only for edges that are curved, and deliberately do not snap.

8. **Masks**: `shape.masks` is a list of `Mask` rings - the regions a surface must *not* project into. A wall has windows; a stage has a pillar in front of it. Turning the stroke off does not help, because the fill is what lands on the glass, so a mask removes the region from the geometry instead.

   Points are in canvas coordinates like the surface's own, so the body gestures carry them (`_apply_to_masks` runs the same point transform the gesture applies to the outline) and `duplicate_shape` nudges them. Parenting them to the shape would have been the other option; it would need a local frame that a corner-pinned quad does not have.

   The renderer cuts them with `triangulate_with_holes` - earcut takes ring end-indices, and the holes' corners become real vertices of the result, so the caller uses the combined point list the indices refer to. A circle with masks goes through `circle_ring` rather than the centre fan: a hole has to be cut out of a *simple* boundary. The editor gets the same result for free by adding each ring as a closed subpath under `Qt.OddEvenFill`, which serves as the fill and as the media's clip at once.

   `MeshShape` has no `masks` field at all, deliberately: a mesh's UVs come from its grid position, and re-triangulating the boundary to cut a hole throws that parametrisation away - the one thing a mesh exists for. Masking a bent surface needs its own answer.

9. **Groups**: `shape.group_id` ties surfaces together. A window frame is four panels; a colonnade is a dozen identical columns - once they sit right relative to each other, nudging the arrangement has to move all of them.

   A group is that promise and nothing more: there is no container object and no coordinate space of its own. Members stay independent shapes with their own vertices, media and masks, and dragging a *vertex* still edits only that shape. What is shared is the body gesture - `_drag_members` returns the group (or, for loose shapes, the current multi-selection), and every member is transformed about the group's shared pivot (`_members_centre`). Rotating about each member's own centre would spin the parts in place and leave the arrangement untouched, which is not what "rotate the group" means to anyone.

   Because a gesture now touches N shapes, `EditSession` snapshots many (`begin_many`) and commits a `ShapesEditCommand` - a single entry, not a macro, since a macro is N entries the user can only step over together and `mergeWith` cannot see inside one. A single-shape edit still goes through `ShapeEditCommand` so slider merging is unchanged. A locked member stays put while the rest of the group moves, which is what locking one surface after calibrating it is for.

   Selecting one member selects the whole group, and the bounding box spans it: a group that looked like a single shape until something moved unexpectedly would be worse than no group at all. `Ctrl`+click adds a loose shape to the selection; the layer list numbers each group so membership is legible when a facade has four of them.

10. **Snapping**: `find_snap` (`model/snapping.py`) prefers a vertex, then an edge, then the grid. Mesh control points pass `grid=False`: the grid is a placement aid for whole surfaces, and on a bend it quantises the one thing a mesh exists to express. The dragged shape is excluded from its own candidates - its adjacent edges are zero pixels away and would pin the vertex in place. The threshold is in screen pixels, divided by the zoom before use, so the magnet feels constant to the hand.

11. **Input space**: `MediaRef.source_rect` (a `SourceRect`) says *which part* of the media feeds a surface, independent of where that surface sits. One clip can drive six surfaces, each taking a different region. It is applied last in the UV chain - after fit, corner pin and `MediaTransform` - in `FRAGMENT_SHADER_TEXTURE`, and mirrored in `canvas_editor._paint_media`. Aspect ratio and pixel offsets are measured against the *region*, not the whole file.

   Axis-aligned on purpose: a free quad here would be a second homography stacked on the corner pin, and the real need ("this wall shows the left third") is a rectangle.

### Errors the operator can see

Everything non-fatal used to end at `logger.warning`, in a console nobody
watches during a show. `ProblemLog` is a **logging handler**, not a rewrite of
every call site: those calls are already in the right places and already say
the right thing, and what was missing was somewhere for them to arrive.
Anything this app logs at WARNING or above shows up in the toolbar and in a
dialog - which also means a failure added later is visible without anyone
remembering to wire it.

The handler sits on the **root** logger. It used to sit on `pm`, which was
the one ancestor every module in the app shared; flattening the layout took
that ancestor away, so `about.PACKAGES` lists the app's own top-level modules
and the handler drops everything else - a decoding library complaining about
a colour profile is not something anyone can act on mid-show. A module left
off that list fails *silently*: its warnings are logged and never shown, which
is exactly what happened to `app_paths` the day it was written.
`tests/test_problems.py` now walks the tracked files and fails if any
top-level module is missing from it.

Two things stay modal, because they block rather than inform: a save that did
not happen, and a project that would not open. Everything else is a status
message plus a line in the list.

### Blackout, and missing media

`Project.blackout` is the panic button and short-circuits `paintGL` before
anything else runs - not the canvas, not the test pattern, not a half-finished
edit can reach the wall. It is deliberately **not** `pause`: pausing leaves the
last frame up, and what you need when something goes wrong is darkness. It is
also deliberately not serialised, and does not dirty the project: a show that
opens black sends the operator hunting for why nothing is on the wall.

The editor keeps working during a blackout, so it draws a red frame around the
canvas to say the projectors are dark.

A missing file used to be silent - the surface simply came up empty, which in
a dark room reads as "I mapped it wrong" rather than "the drive is not
plugged in". `media/availability.py` answers the question with a one-second
cache, because it is asked once per layer-list repaint and a `stat` per surface
has no business in the frame budget. Broken surfaces are hatched in red on the
canvas, marked in the layer list, and counted in the toolbar; the count opens
`RelinkDialog`, which relinks **by folder** - media moves by the folder, so
pointing at one file's new home is taken as an offer to find its neighbours.

### Media playback

Clips do not run on their own clocks. `Project.transport` (`model/transport.py`)
is monotonic wall time scaled by `speed`, and every decoder reads its position
from there. That is what makes one button stop the whole show, and what makes a
stalled file unable to drag the rest of it back.

**Sharing is how synchronisation is spelled.** `ClipPool` keys a decoder on
`clip_key(media)` - the path plus the playback settings - so two surfaces
showing the same file the same way share one decoder and cannot drift from each
other. Different settings get their own decoder, which is the only honest answer
when one is at half speed. The pool is process-wide, so the editor, the output
preview and every projection window decode a clip once between them; that is
what finally made video previewable in the editor.

`MediaRef.playback` (`Playback`) belongs to the *surface*, not the file: `loop`,
`speed`, `start` (where show-time zero lands in the clip - negative delays it)
and `hold_last`. Holding the last frame is the default because going black
mid-show is a failure the audience sees.

The decode thread never seeks unless the show clock has moved somewhere it
cannot reach by reading forward - seeking a compressed video is expensive and
inexact, so playing forward at normal speed never does it. When the show is
paused or running slow, the thread waits instead of decoding frames that will
be thrown away.

`kind` is `image`, `video` or `camera`; a camera carries its device index in
`path` and has no timeline, so the transport does not apply to it.

### Blend modes

`blend_mode` has been on the model and in the file format since the beginning
and the renderer never read it - every surface composited as `normal`. It is
`glBlendFunc` per shape now (`GLRenderer.BLEND_MODES`), reset to normal
afterwards so it cannot leak into the next surface or the output pass.

Add and screen are how projected light actually behaves: two beams on the same
wall sum, they do not replace one another. Multiply is a gel. The editor
mirrors all four with `QPainter` composition modes (`canvas_editor.apply_blend_mode`),
because a preview that composites differently from the projector is the failure
this codebase has spent the most effort on.

Stacking two surfaces with `add` is also the answer to "one media layer per
surface" for now: there is no multi-layer compositing inside a single surface.

### Files, autosave and recovery

`.pmap.json` stores media paths **relative to itself** (`fileio/media_paths.py`)
when the media is within a few hops of the project - the case where the folder
travels as one piece. Anything further away keeps its absolute path, because a
media server is not part of the show. Only the file is relative: the in-memory
model always holds absolute paths, since the image cache and the video decoder
open them directly.

Saving writes to a temp file and renames it into place, after copying the
previous version to `.bak`. A crash mid-write cannot leave a half-written
project where the good one used to be.

The session copy in app data is the crash net. `MainWindow` autosaves it every
20 seconds while the project is dirty, with `mark_saved=False` - the work is
safe from a crash but it has *not* reached the operator's file, and clearing
the dirty flag would stop the close prompt from ever asking again. The session
carries a `_session` block (`source_path`, `dirty`) that a `.pmap.json` must
never contain: a project recording its own path breaks the moment it is moved.
On restore, a session that was dirty comes back dirty and the window says so.

### Performance

The renderer repaints on a 16ms timer whether anything moved or not, and it
used to rebuild every surface's triangles each time: 50 surfaces cost 60ms of
Python per frame - 16fps before the GPU saw a vertex. Two fixes, both in place:

- `tessellate_mesh` is vectorised with numpy. The Catmull-Rom patch was a
  Python triple loop at ~5ms *per mesh*, and it was called twice per mesh per
  frame because UVs were requested separately.
- `GeometryCache` keys triangles on a **signature** of the shape's geometry,
  not on object identity - undo replaces a shape rather than mutating it, so
  identity says "new" for something bit-for-bit unchanged, while a dragged
  corner mutates in place without changing identity at all. Colour, opacity
  and effects are absent from the signature: they change constantly during a
  show and none of them moves a vertex.

200 surfaces went from 253ms to 0.43ms per idle frame, and 1.2ms while a mesh
is being dragged. `tests/test_performance.py` guards both with loose budgets.

### Canvas resolution

`CanvasSettings` starts at 1280x720 and knows it (`is_default()`). Everything -
the test pattern included - is composited at the canvas resolution before the
output pass resamples it onto each projector, so leaving the placeholder in
place while the projector reports 1920x1080 throws away detail nothing
downstream can put back. The outputs dialog adopts a screen's resolution the
first time an output is aimed at one, and never touches a size the operator has
already set. It can also be typed, or matched to the selected projector.

### Naming

New surfaces are called `Polygon`, `Circle`, `Mesh` (`DEFAULT_*_NAME` in
`model/shapes.py`). They used to be Portuguese in an English interface,
which reads as a bug rather than a choice. Existing projects are unaffected -
a shape's name travels with the shape.

### Licensing

**GPL-3.0-or-later**, and the repository is built so it stays that way without
anyone having to remember.

`about.py` is the single source: name, version, copyright, the SPDX
identifier and the four facts GPL-3 section 0 calls "Appropriate Legal
Notices". The About box, the README and any future installer read from there
rather than each carrying their own copy to drift out of sync. It has no Qt
import, so packaging and a future CLI can use it too.

Every `.py` carries a four-line SPDX header. That is not decoration: a file
copied out of this repository on its own used to arrive with no terms at all,
and the LICENSE file does not travel into a frozen binary either - which is
why the About box exists at all.

`tests/test_licensing.py` is what makes it durable. It parametrises over
`git ls-files '*.py'`, so a new file without a header fails immediately, and
it fails if a dependency is added to `requirements.txt` without an entry in
`THIRD-PARTY-NOTICES.md` - the omission that is invisible until the day
someone ships a build. Both were verified to fail when their subject is
removed.

Contributions come in under the **DCO**, not a CLA (`CONTRIBUTING.md` quotes
version 1.1 in full). That is a deliberate one-way door: contributors keep
their copyright, so nobody - including the owner - can relicense the project
without asking all of them. It is the mechanism that makes "this will stay
free" structural rather than a promise.

### The session directory, and the app's name

`app_main` sets `setApplicationName`/`setOrganizationName`, which is what
makes the session copy land in a folder called Anamorph rather than one named
after whichever interpreter launched it.

`QStandardPaths` derives `AppDataLocation` from exactly those two, so setting
them **moves** the session directory - and the session copy is the only place
an hour of unsaved work exists. A release that silently relocated it would
empty the crash net exactly once, at the one moment it matters.

So `app_paths.py` performs the move rather than allowing it. `app_main` calls
`remember_legacy_app_data()` *before* renaming anything, because afterwards
the old location is no longer computable - it depended on the executable's
name, which differs between running from source and running a build. The
first `workspace_base_path()` under the new name copies the previous session
across. Copy, not move: an operator who goes back to an older build still
finds their session where they left it, and nothing already in the new
location is overwritten, so a second run cannot drag a stale session back
over a newer one.

### File Format

Projects saved as JSON with `.pmap.json` extension containing:
- Canvas dimensions and background color
- Shapes array with full state (points, colors, media, effects); a mesh also stores `rows`/`cols`, a curved edge stores `curve1`/`curve2`, a masked surface stores `masks`, and a grouped one stores `group_id`
- Media library paths
- `outputs`: one entry per projector (region, keystone corners, blend, colour)
- UI state (`last_projection_screen_id`, `test_mode`, `test_pattern`)

`media.source_rect` is absent from files written before input space existed; that
reads back as the full frame, so old projects open unchanged. Likewise a file
with no `outputs` gets one full-frame output aimed at `last_projection_screen_id`.

The old per-screen `*.workspace.json` files are folded into a single project on
first run by `ProjectStore._migrate_legacy_workspaces`: the workspace with the
most shapes becomes the artwork, every screen that had one becomes an output,
and the originals are left on disk so a bad merge is recoverable by hand.

`Project.dirty` is set by `touch()` and cleared by `mark_saved()`, which every
save and load path calls. It is what the unsaved-changes prompt reads - do not
go back to inferring it from whether the project has a path.

### Threading Notes

VideoPlayer uses daemon thread with lock-protected frame access. Main thread (GLRenderer) retrieves frames via `get_frame()`. Cleanup handled in renderer's `cleanup()` method.

## User Interface

### Toolbar Actions
- **Polygon/Circle/Mesh** - Add new shapes. Mesh is the bendable one: a control grid for columns, cylinders and domes
- **Duplicate** - Copy the selected surface with an offset (`Ctrl+D`)
- **Mask** - Cut a hole in the selected surface for a window, doorway or pillar (`Ctrl+M`)
- **Group / Ungroup** - Make the selected surfaces move as one (`Ctrl+G`, `Ctrl+Shift+G`)
- **Snap** - Magnetic snapping of dragged vertices to other surfaces
- **Project** - Toggle fullscreen projection to selected screen
- **Test Mode** + pattern dropdown - Replace the output with a calibration pattern
- **Blackout** - Kill every projector at once, without stopping the show (`B`)
- **Help** - Every gesture and shortcut on one sheet (`F1`). The Help *menu* also has About, which is where the program states its licence
- **Preview** - Watch one projector's frame - region, keystone, blend, colour - without projecting
- **Outputs...** - Per-projector calibration: canvas region, keystone, edge blend, colour. `Tile` lays out N projectors pre-overlapped with matching ramps

### Keyboard Shortcuts
- `Ctrl+Z` / `Ctrl+Shift+Z` (or `Ctrl+Y`) - Undo / redo
- Arrow keys - Nudge the selected shape by 1 unit, or the last-touched vertex
- `Shift` + arrows - Nudge by 10
- `Alt` / `Ctrl` + drag - Rotate / scale the shape (see Gestures above)
- `Alt` while dragging a vertex - Bypass snapping for that drag
- `Ctrl+D` - Duplicate the selected shape
- `Ctrl+M` - Cut a mask (a hole) in the selected surface
- `Ctrl+G` / `Ctrl+Shift+G` - Group / ungroup the selected surfaces
- `Ctrl` + click - Add a surface to the selection
- Double-click an edge - Insert a vertex there
- `Alt` + double-click an edge - Curve it, or straighten it again
- `Delete` / `Backspace` - Remove selected shape
- Click a selected shape again - Swap between the transform grips and its own points
- `Escape` - Close fullscreen projection window
- `Space` - Play or pause the whole show
- `B` - Blackout: kill every projector at once
- `F1` - Keyboard and mouse reference

### Supported Media Formats
- **Images:** PNG, JPG, JPEG, BMP
- **Videos:** MP4, MOV, AVI, MKV
- **Live:** any capture device OpenCV can open, by index

## Testing

```bash
pytest
```

`tests/conftest.py` forces `QT_QPA_PLATFORM=offscreen`, so the Qt tests need no display.

- `tests/test_homography.py` - corner-pin math, pure numpy
- `tests/test_snapping.py` - snap priority and the canvas wiring around it
- `tests/test_undo.py` - command round trips, gesture merging, drag-to-one-step, and that undo reaches the canvas item and the panel rather than an orphan
- `tests/test_precision.py` - keyboard nudge and typed coordinates
- `tests/test_corner_pin_ui.py` - fit mode persistence, corner-pin defaults, handle highlighting
- `tests/test_test_pattern.py` - calibration pattern rendering and persistence
- `tests/test_fit.py` - `content_rect` for every mode, including degenerate boxes
- `tests/test_gestures.py` - move/rotate/scale gestures, duplicate, solo
- `tests/test_source_region.py` - input space value type, persistence, panel wiring
- `tests/test_project_integrity.py` - discard prompts, workspace registration, undoable visibility
- `tests/test_video_player.py` - playback pacing and shutdown (writes a real clip via OpenCV)
- `tests/test_outputs.py` - blend-curve complementarity, tiling, clamping, output persistence
- `tests/test_project_store.py` - session round trip and legacy workspace migration
- `tests/test_output_ui.py` - the outputs dialog and one projection window per enabled output
- `tests/test_mesh.py` - patch interpolation, UVs following the bend, density resampling, mesh handles and gestures
- `tests/test_bezier_edges.py` - edge-local controls, the straight-by-default invariant, outward bowing, curve handles and hit testing
- `tests/test_masks.py` - holes cut from the triangulated area, the odd-even preview, masks following the shape, persistence
- `tests/test_groups.py` - group selection, the shared pivot, one undo step for a group gesture, locked members
- `tests/test_bugfixes.py` - regressions found by using the app: the missing circle wedge, handles that could not be dragged, selections that collapsed, the two handle sets, type conversion, canvas resolution

- `tests/test_project_files.py` - relative media paths, backups, atomic writes, session recovery, the output preview
- `tests/test_performance.py` - the geometry cache's hit/miss behaviour and per-frame budgets
- `tests/test_playback.py` - the show clock, decoder sharing, loop/offset/rate, the transport bar
- `tests/test_showtime.py` - blackout, missing-media detection, relinking, the undo gaps
- `tests/test_problems.py` - the problem log, the real call sites reaching it, and that the help sheet's keys are bound
- `tests/test_ci_report.py` - the failure reporter itself: that it finds the failing line rather than the `def`, and says something when pytest died before writing a report
- `tests/test_app_paths.py` - the session surviving the rename: carried across, original left alone, current work never overwritten
- `tests/test_licensing.py` - the SPDX header on every tracked `.py`, a notice for every dependency, the DCO quoted in full, and the About box carrying the notices the GPL asks for
- `tests/test_render_gl.py` - **pixels**: what actually lands on the projector

`test_render_gl.py` needs a real GL context, which the `offscreen` platform
cannot give, so it skips by default and runs for real under:

```bash
xvfb-run -a env QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 pytest
```

It covers the failures that live in the gap between the numbers and the frame:
the canvas Y flip, stroke width, a mask cut out of the geometry but not the
image, a circle that does not close, `contain` smearing instead of
letterboxing, the output pass (region crop, blend ramp, colour), the four
blend modes and the blackout. Each one was verified to fail when its fix is
reverted.

CI runs **one job per operating system**, not per test file. Splitting by
file briefly gave 25 jobs, and that does not survive a second platform - 25
suites times three systems is 75 jobs for one push. It was also the weaker
signal: a job named `masks` tells you the area, while an annotation tells you
the file, the test, the line and the assertion, on the diff itself.

`.github/scripts/test_report.py` turns pytest's JUnit report into `::error`
annotations plus a table in the job summary. Neither needs write permission
on the repository, which is why it is not a PR comment: on a pull request
from a fork the token is read-only, so a commenting bot fails precisely on
outside contributions. The annotation's line comes from the *last frame of
the traceback*, not from the testcase's `file`/`line` attributes - those
point at the `def`, which can be far from the assertion that failed. The
attributes are the fallback, and `pytest.ini` sets `junit_family = xunit1`
because the default `xunit2` drops them entirely.

The matrix carries `ubuntu-latest`, `windows-latest` and `macos-latest`, and
`fail-fast: false` is what makes "does this break on Windows only?"
answerable. It did, on the first run: `reap_idle` compared `idle_for() >
timeout`, and `time.monotonic()` ticks about every 15ms on Windows against
nanoseconds elsewhere, so a decoder opened and reaped in the same breath aged
exactly 0.0 there and the reap was refused. macOS and Linux had agreed with
each other for months about a boundary that was wrong.

The lesson is in how it was fixed, not what it was: the guard tests
(`test_a_clip_idle_for_exactly_the_timeout_is_reaped`) name the idle time
through a stand-in instead of racing a real clock. A test built on elapsed
time cannot state where a boundary is - it can only report where this
machine's clock happened to land - which is why the off-by-one survived until
a runner with a coarse clock looked at it.

The annotation path is normalised through `_repo_path` for the same reason.
The Windows runner writes `tests\test_playback.py` in the traceback, and
GitHub does not reject a backslash path - it silently fails to match it, so
the annotation detaches from the file and floats at the top of the run. A
reporter that quietly stops pointing anywhere is worse than none, since the
step still passes.

Two more jobs: a step inside the matrix job runs one suite *by path*, because
that is a different `sys.path` setup from bare `pytest` and the suite once
passed one way while failing to import the other; and `render_gl (OpenGL)`
runs under xvfb+Mesa and fails if those tests *skip* - a skipped pixel suite
is a green tick that proves nothing. The shared install lives in
`.github/actions/setup`, and skips its apt steps off Linux.

`pytest.ini` sets `pythonpath = .`, because the repo is not installed as a
package and its modules are therefore only importable when the repo root is on
`sys.path`. Pytest puts it there when invoked with no path argument and *not*
when invoked as `pytest tests/test_x.py`, so the suite used to pass one way
and fail to import the other. The two CI jobs now use both invocation forms
between them, which keeps that from coming back quietly.

`tests/conftest.py` drains Qt's deferred deletions after every test and closes
the remaining widgets before the QApplication goes away. Without it hundreds of
never-deleted widgets - some holding GL contexts - piled up and the process
segfaulted on the way out, *after* every test had passed.

## Notes

- **Canvas Y is inverted in the vertex shader.** Canvas coordinates grow downward to match the editor; NDC grows upward. Removing that inversion mirrors the projection against what the user is editing.
- Media fit modes serialize as `stretch`/`contain`/`cover`/`warp`. The combo box shows friendlier labels and keeps the serialized value in `userData` - do not switch back to reading `currentText()`, it would break existing `.pmap.json` files.
- A dirty project prompts before New/Open/Quit. Tests that close a `MainWindow` must call `project.mark_saved()` first, or the modal blocks with nobody to answer it.
- `MainWindow` restores the last session from the platform's app data directory on construction and writes it back on close. `tests/conftest.py` wipes that directory **per test** - the leak happens inside a single run, not just between runs.
- `_sync_projection_windows` only opens anything while `_projecting` is set. Editing outputs with the show stopped must not start it.
- `MediaTransform` offsets are in **source pixels** (matching the property panel's range and step); the renderer converts them to UV units against the media size, and rotation is degrees about the media centre.
- Widgets added to a layout at runtime need `setParent(None)` before `deleteLater()`, and the panel needs `updateGeometry()` afterwards. Without the first, stale rows keep painting where they were; without the second, the enclosing scroll area keeps the old height and clips them.
