# Contributing to Anamorph

Anamorph is free software under the **GNU General Public License, version 3 or
later**. Contributions come in under those same terms, and stay there - this
project is not going to be closed later, and the contribution process is built
on that promise rather than on a document that reserves the right to break it.

## Sign your work - the DCO

Anamorph uses the [Developer Certificate of Origin](https://developercertificate.org/)
(DCO) rather than a Contributor Licence Agreement.

The difference matters, so it is worth stating plainly:

- **You keep the copyright on what you write.** Nothing is assigned or
  transferred to anyone.
- **Your contribution is licensed under GPL-3.0-only**, the same licence as
  the rest of the project.
- Because no one holds a broad licence over your work, **the project cannot be
  relicensed or made proprietary** without asking every contributor. The DCO is
  what makes that guarantee structural instead of a promise in a README.

What the DCO asks of you is one thing: certify that you have the right to
submit the code. You do that by adding a `Signed-off-by` line to each commit:

```bash
git commit -s -m "Your commit message"
```

which appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

Use your real name and an address that reaches you. The name must match the
commit author. If you forget on the last commit:

```bash
git commit --amend -s --no-edit
```

and for a whole branch:

```bash
git rebase --signoff dev
```

By signing off you agree to the following, which is the DCO version 1.1
verbatim:

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

Note point (d): your name and email address become part of the public git
history, permanently.

**Do not submit code you do not have the right to submit.** Code from another
project under an incompatible licence, code owned by an employer who has not
agreed, or code produced from a source you cannot account for - all of it
puts the whole project at risk, and unwinding it later means deleting
functionality other people have come to rely on.

## Licence headers

Every `.py` file carries this header, and a test fails if one does not:

```python
# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only
```

New files need it too. If a contribution is substantial enough that you want
your own copyright line on the files you touched, add it below the existing
one - you keep the copyright on your work either way, whether or not the line
is there.

## Which branch

Two long-lived branches, and neither is written to directly.

- **`dev`** is where work integrates. It is the default branch and the target
  for every pull request.
- **`main`** is what has been released. Nothing reaches it except a merge from
  `dev` when a version goes out.

So the loop is: branch off `dev`, open a pull request back into `dev`, and
releases travel `dev` → `main`.

```bash
git switch dev && git pull
git switch -c feature/curved-masks
```

Name it `feature/<what>` or `fix/<what>`. **Not `dev/<what>`** - that one
looks tidy and breaks every clone. Git stores refs as files and directories,
so `refs/heads/dev` is a file while `refs/heads/dev/anything` needs `dev` to
be a directory. GitHub will happily create both on the server, and then every
`git fetch` fails with `cannot lock ref 'refs/remotes/origin/dev'`. The
convention is not cosmetic; it is the only one that coexists with a branch
called `dev`.

## Before you open a pull request

```bash
pytest
```

637 tests, all offscreen. The rendering tests need a real OpenGL context and
skip without one; to run those for real:

```bash
xvfb-run -a env QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 pytest
```

CI runs the suite once per operating system and once more for the rendering
tests. A failure is annotated on the diff - file, test, line and the
assertion - and listed in the job summary, so a red run does not mean
scrolling a log. It fails if the rendering tests *skip*: a skipped pixel
suite is a green tick that proves nothing.

A few things this codebase cares about, which will come up in review:

- **Anything that mutates a shape goes through a command** (`model/commands.py`),
  or it is silently un-undoable.
- **The editor and the projector must agree.** A preview that composites
  differently from the output is the failure this project has spent the most
  effort on. If you change how something renders, change both sides.
- **Comments explain why, not what.** The reasoning in `CLAUDE.md` is the
  house style - read it before changing anything.

## Reporting problems

Open an issue with what you did, what happened, and what you expected. For
anything visual, a screenshot of the editor next to a photo of the wall is
worth more than a paragraph.
