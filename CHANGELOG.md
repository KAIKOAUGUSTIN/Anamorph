# Changelog

Every release, newest first. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version
numbers follow [Semantic Versioning](https://semver.org/).

Entries are written by `.github/scripts/next_release.py` when a change reaches
`main`, so the shape is the same in every release rather than depending on who
cut it. What decides the number is the marker in the commits: `feat:` for a
new capability, `fix:` for a repair, and `!` or a `BREAKING CHANGE:` trailer
when something that used to work stops working. Where nobody said, a model
reads the commits and proposes, and its reasoning is printed in the job that
made the call.

While the version stays below `1.0.0`, a breaking change raises the minor
number rather than the major one. `1.0.0` is a promise about stability, and it
will be made deliberately rather than reached by accident.

<!-- releases -->

## [0.1.0] - 2026-08-08

The first tagged build, and the first one anyone can run without installing
Python.

### Added
- Surfaces: polygons with curved edges, ellipses, and a bendable control mesh
  for columns, cylinders and domes.
- Corner pin, computed per fragment, so media lands square on an off-axis wall
  instead of bending along a triangulation seam.
- One canvas, any number of projectors. Each carries its own region, keystone,
  edge blend and colour correction, so two of them overlap into one image.
- Masks: holes cut from a surface for a window, a doorway or a pillar.
- Groups, so a facade's panels move as one arrangement.
- Media playback on a single show clock, with one decoder shared between every
  surface playing the same file the same way.
- Blackout on `B`: every projector dark at once, without stopping the show.
- Test patterns, an output preview, and a relink dialog for media that moved.
- Packaged builds for Linux, Windows and macOS, with the licence texts inside.

### Fixed
- Editor and projector agree: fit modes, stroke width, masks and blend modes
  now composite the same way on both sides.
- `contain` letterboxes instead of smearing the media's edge pixels.
- A circle closes all the way round on the output.
- Idle decoders are reaped on Windows, where the clock ticks coarsely enough
  that the old comparison never fired.
