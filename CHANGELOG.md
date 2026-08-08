# Changelog

Every release, newest first. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version
numbers follow [Semantic Versioning](https://semver.org/).

Entries are written by hand when a release is cut, and the number is chosen by
hand too. That used to be automated - a script read the commits, asked a model
to classify them, and pushed a tag on every merge to `main`. It worked, and it
was still the wrong trade: a version number is a promise to whoever downloads
the build, and nothing that guesses should be allowed to make one. Cutting a
release is rare enough that doing it deliberately costs almost nothing.

Each bullet is one user-visible outcome, written for someone operating a
projector rather than for someone reading the diff. Sections appear in the
order Keep a Changelog gives them - Added, Changed, Deprecated, Removed, Fixed,
Security - and empty ones are left out.

While the version stays below `1.0.0`, a breaking change raises the minor
number rather than the major one. `1.0.0` is a promise about stability, and it
will be made deliberately rather than reached by accident.

<!-- releases -->

## [0.2.2] - 2026-08-08

### Fixed
- Release notes now keep a blank line between version sections so the file stays readable in a terminal.
- The release process can now be safely re-run after a partial failure without creating duplicate commits or getting stuck.

## [0.2.1] - 2026-08-08

### Fixed
- Release builds now start automatically instead of silently skipping the build process
- The release job now fails loudly instead of reporting success when a pull request cannot be opened
- The release job now warns clearly when a build must be started manually due to missing automation tokens
## [0.2.0] - 2026-08-08

### Added
- Downloadable application bundles for Windows, macOS, and Linux that run without installing Python or dependencies.
- Application window and file icons showing the projection mapping corner-pin concept.
- About box displaying the application's name, version, copyright, and licence information.
- Automatic migration of your unsaved session work to the new Anamorph application data folder when launching the renamed app for the first time.
- README providing first-time setup instructions, including how to bypass unsigned build warnings on each operating system.

### Changed
- Application licence is now strictly GPL-3.0-only.
- macOS builds are restricted to Apple Silicon.
- Unsaved session files are now stored in a folder named Anamorph instead of a generic interpreter folder.

### Fixed
- Video clips no longer close immediately on Windows when checking for idle timeouts.
- Failure annotations in pull requests now correctly point to the exact failing line of code instead of floating at the top of the run.

### Security
- Continuous integration checks now enforce binary-only dependency installations to prevent running untrusted setup scripts.

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
