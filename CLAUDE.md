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

- `projection_gui.py` - Thin CLI entry point, delegates to `pm.app_main.run()`
- `pm/app_main.py` - Application initialization: QApplication setup, high DPI config, theme application

- `pm/model/` - Data models (dataclasses, no Qt dependency)
  - `project.py` - Project root with CanvasSettings, shape list, media library; emits `changed` signal via QObject inheritance
  - `shapes.py` - PolygonShape (per-edge visibility and bezier controls), CircleShape and MeshShape dataclasses, plus `Mask`; serialized via `shape_to_dict`/`shape_from_dict`
  - `media.py` - MediaRef (image/video) with fit modes, UV transform, and `SourceRect` (which region of the media feeds the surface)
  - `effects.py` - Effects (pulse, strobe, RGB shift) with parameters
  - `commands.py` - Undoable edits as `QUndoCommand`s, plus `EditSession` for turning a drag - of one shape or a whole group - into one step
  - `snapping.py` - Magnetic snap search (vertex, then edge, then grid); pure geometry
  - `output.py` - `Output` (canvas region, keystone, `EdgeBlend`, `ColorCorrection`) and `split_outputs`
  - `project_store.py` - Loads/saves the one session project; migrates the old per-screen workspaces

- `pm/ui/` - Qt6/PySide6 UI components
  - `main_window.py` - Central window with toolbar, splitter layout, menus, and screen selection
  - `canvas_editor.py` - Interactive QGraphicsView for shape editing; vertex handles plus move/rotate/scale gestures
  - `projection_window.py` - Full-screen projection output window
  - `property_panel.py` - Property editing UI for selected shape
  - `object_list.py` - Layer list with visibility, lock and group markers, and Solo
  - `source_region.py` - Draggable rectangle over the media thumbnail, for picking the input region
  - `output_panel.py` - `OutputDialog`: per-projector region, keystone, blend and colour
- `styles.py` - Studio Dark Luxury theme with cyan accents; provides `STUDIO_DARK_QSS` stylesheet and `COLORS` palette for consistent UI styling
- `widgets.py` - Custom keyboard-friendly widgets: `ArrowSlider`, `ArrowSpinBox` for arrow key navigation

- `pm/render/` - Rendering subsystem
  - `gl_renderer.py` - `QOpenGLWidget` renderer with GLSL shaders; uploads media as GL textures and caches them per path
  - `shaders.py` - GLSL sources: shared vertex shader plus texture/solid/stroke fragment shaders
  - `homography.py` - Corner-pin math (numpy only, no Qt/GL), shared by the renderer and the editor preview
  - `fit.py` - `content_rect`: where media sits inside a surface's box. The single source of truth for stretch/contain/cover
  - `test_pattern.py` - Calibration images (grid / checkerboard / borders) drawn with QPainter
  - `mesh.py` - All the CPU-side geometry: earcut triangulation with holes (`triangulate_with_holes`), the Catmull-Rom patch behind `MeshShape` (`tessellate_mesh`/`mesh_outline`), and the cubic-edge sampling behind curved polygons (`bezier_control_points`/`polygon_outline`)

- `pm/media/` - Media handling
  - `video_player.py` - OpenCV-based video playback with threading, looping, and RGB conversion
  - `image_cache.py` - mtime-keyed QImage cache for the editor viewport (paint runs every frame)

- `pm/io/` - Serialization
  - `project_io.py` - JSON save/load with `.pmap.json` extension

### Key Design Patterns

1. **Signal-based Updates**: Project.changed signal propagates to UI components; circular updates prevented by `blockSignals` in zoom controls

2. **Shape Types**: Three shape types supported:
   - `PolygonShape`: Variable points, with per-edge visibility, length and curvature
   - `CircleShape`: Elliptical with control points and anchor system
   - `MeshShape`: A control grid of `(rows + 1) x (cols + 1)` points, row-major

   A polygon with a corner pin describes a *flat* plane seen off-axis. A column, a cylinder, a dome or a hung cloth is curved, and no arrangement of four corners can express that - the surface has to bend *between* its corners. `MeshShape` is that surface.

   The control grid is coarse because it is what a person drags; `tessellate_mesh` (`pm/render/mesh.py`) smooths it into a dense render mesh with a **Catmull-Rom** patch, which passes *through* every control point - what the operator positions is exactly where the surface goes, with curvature filled in between. Neighbour lookup at the boundary clamps rather than wraps (`_clamped`): wrapping would pull the far edge of the surface into the near one.

   UVs come from the parametric grid position, not from canvas coordinates, so media flows *along* the bend; `source_rect` and `MediaTransform` still compose on top in the shader. Per-vertex UVs are honest here only because the patch is subdivided - across a coarse cell the interpolation error would be visible, across a subdivided one it is far below a pixel.

   The editor mirrors it in `canvas_editor._paint_mesh_media`, filling one tessellated triangle at a time. `QTransform.quadToQuad` refuses a triangle with a repeated corner, so `_triangle_transform` solves the 2x3 affine directly from the three point pairs. That pass sets `Antialiasing False`: an antialiased clip edge blends with what is behind it, so every shared triangle edge would show up as a pale hairline and the tessellation would be visible through the media.

   `resize_grid` resamples the *current* patch instead of rebuilding a flat grid, so density can be raised late without losing the bending already done.

3. **Media Mapping**: UVs come from the shape's fit mode (`stretch`/`contain`/`cover`), computed per vertex in `_compute_fit_uvs`.

   The `warp` fit mode - shown in the UI as **Corner pin** - is different and is the mode that matters for projection mapping. A four-point polygon gets a homography from `canvas_to_uv_matrix` (`pm/render/homography.py`), uploaded as the `u_uv_matrix` uniform and divided **per fragment** in `FRAGMENT_SHADER_TEXTURE`. Interpolating UVs per vertex instead would bend the image along the triangulation diagonal, which is the classic broken-mapping artifact. Per-vertex UVs are still uploaded as a fallback for degenerate quads.

   The editor mirrors this with `QTransform.quadToQuad` in `canvas_editor._paint_media`, so the canvas preview and the projected output agree. Corner-to-UV pairing is by proximity to the bounding box (`corner_uv_assignment`), not vertex index, so the media stays put while a corner is dragged.

4. **One canvas, many projectors**: A `Project` has one canvas and a list of `Output`s. Each output is one projector's view of *part* of that canvas, carrying its own keystone, edge blend and colour. Screens used to own a whole `Project` each, which made two projectors two separate artworks and left soft-edge with nothing to blend.

   Rendering is two passes (`GLRenderer.paintGL`): the canvas is composited into a framebuffer once, then each output draws that texture through its corrections. Doing it per shape would be wrong, not just slower - a blend ramp must attenuate the *finished* image, or two surfaces overlapping inside the strip each get darkened and the seam turns into a dark patch.

   The blend ramp is an S-curve, not `pow(t, k)`. Facing projectors see `t` and `1-t`, and only the S-curve sums to exactly 1 for any exponent; anything else leaves a bright or dark band down the seam. The exponent stays adjustable because projectors are not linear.

   The canvas pass inverts Y into the framebuffer, so the output pass samples `1 - v`. Without that the projection comes out vertically mirrored - invisible on a symmetric test pattern.

5. **Gestures, not modes**: There is no Points/Scale/Rotate mode any more - a trip to the toolbar mid-show is a trip nobody has time for. Vertices are always on show for the selected shape, and the body of the shape carries the transforms:
   - Drag the body: move. `Shift` locks to one axis
   - `Alt` + drag: rotate about the shape's centre. `Shift` snaps to 15 degree steps
   - `Ctrl` + drag: scale from that centre
   - Drag a vertex: reshape that corner. `Alt` still bypasses snapping there

   All three run through `CanvasEditor._update_body_drag` rather than Qt's `ItemIsMovable`, which is what lets `Shift` mean "constrain" instead of "move this time".

   A selected shape also gets a dashed bounding box with four `TransformHandle` grips at its corners and a rotate grip above it. They force their own gesture and drive the same `_apply_body_scale`/`_apply_body_rotate` - there is one implementation of each transform, not two. They exist for discoverability: a modifier with no visible affordance is a feature only the manual can tell you about.

6. **Undo**: Commands are snapshot-based (`pm/model/commands.py`), storing a shape's serialised state before and after an edit and swapping them - shapes are mutated in place during a drag, so there is no inverse to replay. `EditSession` snapshots on mouse press and pushes on release, making a drag one undo step; `ShapeEditCommand.mergeWith` collapses same-labelled edits to the same shape within a short window, which is what keeps a slider drag from filling the stack.

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

10. **Snapping**: `find_snap` (`pm/model/snapping.py`) prefers a vertex, then an edge, then the grid. The dragged shape is excluded from its own candidates - its adjacent edges are zero pixels away and would pin the vertex in place. The threshold is in screen pixels, divided by the zoom before use, so the magnet feels constant to the hand.

11. **Input space**: `MediaRef.source_rect` (a `SourceRect`) says *which part* of the media feeds a surface, independent of where that surface sits. One clip can drive six surfaces, each taking a different region. It is applied last in the UV chain - after fit, corner pin and `MediaTransform` - in `FRAGMENT_SHADER_TEXTURE`, and mirrored in `canvas_editor._paint_media`. Aspect ratio and pixel offsets are measured against the *region*, not the whole file.

   Axis-aligned on purpose: a free quad here would be a second homography stacked on the corner pin, and the real need ("this wall shows the left third") is a rectangle.

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
- `Escape` - Close fullscreen projection window

### Supported Media Formats
- **Images:** PNG, JPG, JPEG, BMP
- **Videos:** MP4, MOV, AVI, MKV

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

Rendering itself is not covered by the suite: `QOpenGLWidget` refuses to create a
context on the `offscreen` platform. To check the actual output, run under a real
platform (`xvfb-run -a env QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 ...`) and
compare `GLRenderer.grabFramebuffer()` against the editor preview.

## Notes

- **Canvas Y is inverted in the vertex shader.** Canvas coordinates grow downward to match the editor; NDC grows upward. Removing that inversion mirrors the projection against what the user is editing.
- Media fit modes serialize as `stretch`/`contain`/`cover`/`warp`. The combo box shows friendlier labels and keeps the serialized value in `userData` - do not switch back to reading `currentText()`, it would break existing `.pmap.json` files.
- A dirty project prompts before New/Open/Quit. Tests that close a `MainWindow` must call `project.mark_saved()` first, or the modal blocks with nobody to answer it.
- `MainWindow` restores the last session from the platform's app data directory on construction and writes it back on close. `tests/conftest.py` wipes that directory **per test** - the leak happens inside a single run, not just between runs.
- `_sync_projection_windows` only opens anything while `_projecting` is set. Editing outputs with the show stopped must not start it.
- `MediaTransform` offsets are in **source pixels** (matching the property panel's range and step); the renderer converts them to UV units against the media size, and rotation is degrees about the media centre.
- Widgets added to a layout at runtime need `setParent(None)` before `deleteLater()`, and the panel needs `updateGeometry()` afterwards. Without the first, stale rows keep painting where they were; without the second, the enclosing scroll area keeps the old height and clips them.
