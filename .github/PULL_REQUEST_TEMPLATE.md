## What this changes

<!-- What the change does, and why. If it fixes something visible on the wall,
say what the failure looked like. -->

## How it was verified

<!-- Which tests, and anything you checked by hand. Rendering changes need the
editor and the projected output compared against each other. -->

- [x] `pytest` passes
- [x] `xvfb-run -a env QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 pytest` passes (rendering changes)

## Licensing

- [x] Every commit is signed off (`git commit -s`) under the [DCO](../CONTRIBUTING.md#sign-your-work--the-dco)
- [x] New `.py` files carry the `SPDX-License-Identifier: GPL-3.0-only` header
- [x] I have the right to submit this code under GPL-3.0-only, and no part
      of it is copied from a source under incompatible terms
