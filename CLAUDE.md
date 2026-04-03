# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Projection Mapping MVP application built with Python and PySide6. It allows users to create and manipulate shapes (polygons and circles) for projection onto surfaces, with media mapping support (images/videos), effects (pulse, strobe, RGB shift), and multi-screen projection output.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python projection_gui.py
```

## Architecture

### Module Structure

- `pm/model/` - Data models (dataclasses, no Qt dependency)
  - `project.py` - Project root with CanvasSettings, shape list, media library; emits `changed` signal via QObject inheritance
  - `shapes.py` - PolygonShape and CircleShape dataclasses with serialization via `shape_to_dict`/`shape_from_dict`
  - `media.py` - MediaRef (image/video) with fit modes (stretch/contain/cover) and UV transform
  - `effects.py` - Effects (pulse, strobe, RGB shift) with parameters

- `pm/ui/` - Qt6/PySide6 UI components
  - `main_window.py` - Central window with toolbar, splitter layout, menus, and screen selection
  - `canvas_editor.py` - Interactive QGraphicsView for shape editing with modes: points, scale, rotate
  - `projection_window.py` - Full-screen projection output window
  - `property_panel.py` - Property editing UI for selected shape
  - `object_list.py` - Layer list widget showing shapes
- `styles.py` - Studio Dark Luxury theme with cyan accents; provides `STUDIO_DARK_QSS` stylesheet and `COLORS` palette for consistent UI styling

- `pm/render/` - Rendering subsystem
  - `gl_renderer.py` - QWidget-based renderer using QPainter (not raw OpenGL), handles media texture mapping via affine triangle transforms
  - `mesh.py` - Triangulation using mapbox_earcut for polygon mesh generation

- `pm/media/` - Media handling
  - `video_player.py` - OpenCV-based video playback with threading, looping, and RGB conversion

- `pm/io/` - Serialization
  - `project_io.py` - JSON save/load with `.pmap.json` extension

### Key Design Patterns

1. **Signal-based Updates**: Project.changed signal propagates to UI components; circular updates prevented by `blockSignals` in zoom controls

2. **Shape Types**: Two shape types supported:
   - `PolygonShape`: Variable points with per-edge visibility control
   - `CircleShape`: Elliptical with control points and anchor system

3. **Media Mapping**: Achieved via per-triangle affine transformation computed by `_affine_from_triangles` in `gl_renderer.py`. UV coordinates computed based on fit mode.

4. **Multi-screen**: Projection can target specific displays via `QGuiApplication.screens()`; canvas resolution auto-adjusts to selected screen

5. **Editing Modes**: Canvas has three edit modes affecting mouse interaction:
   - `points`: Drag individual vertices
   - `scale`: Scale from center or edges
   - `rotate`: Rotate around center

### File Format

Projects saved as JSON with `.pmap.json` extension containing:
- Canvas dimensions and background color
- Shapes array with full state (points, colors, media, effects)
- Media library paths
- UI state (last projection screen, test mode)

### Threading Notes

VideoPlayer uses daemon thread with lock-protected frame access. Main thread (GLRenderer) retrieves frames via `get_frame()`. Cleanup handled in renderer's `cleanup()` method.
