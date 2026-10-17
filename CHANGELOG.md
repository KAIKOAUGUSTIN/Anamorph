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

## [0.2.3] - 2026-10-17

### Changed
- chore(deps)(deps): update pyside6-essentials requirement
- Add test and release badges to README
- Add test and release badges to README
- Merge branch 'main' into the release branch
- Do not cut a release when only CI changed
- Do not cut a release when only CI changed
- Merge branch 'main' into feature/resumable-release
- Keep a blank line between changelog entries
- Keep a blank line between changelog entries
- Make the release job survive being re-run
- Make the release job survive being re-run
- Merge branch 'dev' into the release branch
- Stop the release job reporting success for work that did not happen
- Stop the release job reporting success for work that did not happen
- Serialise the version job, so two merges cannot race for one number
- Serialise the version job, so two merges cannot race for one number
- Let the release tag itself without punching through branch protection
- Let the release tag itself without punching through branch protection
- Let the release script be tried before it is trusted
- Let the release script be tried before it is trusted
- Decide the version on merge, and write the changelog the same way every time
- Decide the version on merge, and write the changelog the same way every time
- GPL-3.0-only, an icon, and a README that points at the download
- GPL-3.0-only, an icon, and a README that points at the download
- chore(deps)(deps): update opencv-python-headless requirement
- chore(deps)(deps): update opencv-python-headless requirement
- Check the bundle starts in a way macOS can run
- Check the bundle starts in a way macOS can run
- Package it: a bundle someone can download, and still relink Qt in
- Package it: a bundle someone can download, and still relink Qt in
- Take the four SonarQube findings that were real
- Take the four SonarQube findings that were real
- Potential fix for code scanning alert no. 1: Workflow does not contain permissions
- Potential fix for code scanning alert no. 1: Workflow does not contain permissions
- Potential fix for code scanning alert no. 2: Workflow does not contain permissions
- Potential fix for code scanning alert no. 2: Workflow does not contain permissions
- Write down the branching model, and let CI see the integration branch
- Write down the branching model, and let CI see the integration branch
- Fix the two failures the Windows runner found on its first run
- Fix the two failures the Windows runner found on its first run
- Add Windows and macOS to CI test matrix
- Update PULL_REQUEST_TEMPLATE.md
- one job per platform, and annotate the failure instead of naming a job
- Flatten the layout, name the app, and split CI one job per suite
- Nail the licence down: SPDX headers, an About box, and the DCO
- Hand it to someone else: a README, one language, and errors you can see
- Make `pm` importable however pytest is invoked
- blackout, missing media, relinking, and pixel tests in CI
- Media playback: a show clock, shared decoders and real blend modes
- portable projects, crash recovery, output preview, real render tests
- Fix fourteen bugs found using the app
- Group surfaces so they move as one
- Per-surface masks: the regions a projector must not light
- Bezier edges: polygons with sides that curve
- Deformation mesh: surfaces that bend between their corners
- Retire per-screen workspaces; add the outputs dialog
- One canvas, many projectors: keystone, colour and edge blending
- Give the scale and rotate gestures something to look at
- Delete the handle machinery the gesture rewrite orphaned
- Separate input space from output space
- Retire the edit modes: drag to move, Alt to rotate, Ctrl to scale
- Stop losing work: confirm discards, register opened projects, fix playback
- Make the editor and the projector agree on how media is fitted
- Add GNU GPL v3 license file
- Undo/redo, vertex snapping, typed coordinates, real test patterns
- Corner pin: perspective-correct media warp, plus render-path fixes
- chore(deps)(deps): update pyopengl requirement from >=3.1 to >=3.1.10
- chore(deps)(deps): update mapbox-earcut requirement
- chore(deps)(deps): update numpy requirement from >=1.26 to >=2.5.1
- chore(deps)(deps): update pillow requirement from >=10.0 to >=12.3.0
- chore(deps)(deps): update pyside6 requirement from >=6.6 to >=6.11.1
- Set up Dependabot for Python package updates
- fix sonarqube suggestions
- fix duplicated code
- fix sonarqube suggestions
- Add multi-screen workspace support and OpenGL renderer
- claude.md
- claude.md update
- UI improvements
- Projection Mapping Files

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
