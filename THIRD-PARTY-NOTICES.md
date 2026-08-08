# Third-party notices

Anamorph is licensed under the GNU General Public License, version 3.
It depends on the following components, which carry their own licences and
remain the property of their respective authors.

The licences below were read from the package metadata of the versions this
project is developed against. When a build is packaged for distribution, this
file - and each dependency's own licence text - must ship with it.

| Component | Version | Licence | Notes |
|---|---|---|---|
| [PySide6-Essentials / Qt](https://www.qt.io/qt-for-python) | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Used under the **LGPL-3.0** option. See below. Essentials only - the Addons wheel is never imported and never shipped. |
| [shiboken6](https://www.qt.io/qt-for-python) | 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | Binding runtime for PySide6; same terms. |
| [NumPy](https://numpy.org/) | 2.5.1 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | |
| [OpenCV (opencv-python-headless)](https://opencv.org/) | 4.9+ | Apache-2.0 | Headless build - no GUI toolkit. See the note on bundled codecs. |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU (HPND) | |
| [PyOpenGL](https://pyopengl.sourceforge.net/) | 3.1.10 | BSD-3-Clause | |
| [mapbox_earcut](https://github.com/skogler/mapbox_earcut_python) | 2.0.0 | ISC | Polygon triangulation, including holes. |

## Compatibility with the GPL-3.0

All of the above are compatible with GPL-3.0-only:

- **Qt / PySide6** is taken under its **LGPL-3.0** option. LGPL-3.0 permits
  conveying the combined work under the GPL-3.0, which is what this project
  does. The GPL-2.0-only option in Qt's triple licence is *not* usable here -
  GPL-2.0-only and GPL-3.0 are incompatible - and nothing in this project
  relies on it.
- **Apache-2.0** (OpenCV) is compatible with GPL **version 3**, and is *not*
  compatible with GPL version 2. This is one concrete reason the project is
  licensed under v3 rather than v2: the choice is load-bearing, not cosmetic.
- BSD-3-Clause, MIT, MIT-CMU, ISC, Zlib, 0BSD and CC0-1.0 are permissive and
  impose no conditions the GPL conflicts with.

## Obligations when distributing a build

Running from source, as the project does today, puts almost nothing on you
beyond keeping this file accurate. **Shipping a packaged binary is different**,
and the requirements below become live the moment an installer exists:

1. **Qt under the LGPL-3.0** requires that the recipient be able to replace the
   Qt libraries with a modified version. In practice that means linking Qt
   dynamically - a frozen binary with Qt statically linked in and no way to
   relink does not satisfy it. Because Anamorph's own source is offered under
   the GPL anyway, the "recombining" condition is otherwise straightforward.
2. **Notice and licence text.** The build must state that it uses Qt under the
   LGPL-3.0 and include the LGPL-3.0 text, along with the licence texts of the
   other components above. The About box states the terms; the installer has
   to carry the texts.
3. **Bundled codecs.** The `opencv-python` wheels ship pre-built binaries that
   may include FFmpeg and other third-party codec libraries under their own
   terms, which are not the same as OpenCV's Apache-2.0. Before publishing a
   binary, check what the wheel in use actually bundles and add it here - this
   is the item most likely to be missed, because it is invisible from the
   source tree.

None of this blocks development. It is written down now so that packaging
(currently deferred) starts from a list rather than from a memory.
