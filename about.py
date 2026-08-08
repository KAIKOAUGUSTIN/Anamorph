# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Who this program is, and under what terms.

The GPL asks an interactive program to show its "Appropriate Legal Notices"
(section 0): a copyright notice, that there is no warranty, that the work may
be conveyed under this License, and how to read the License itself. That is
four facts, and they belong in one place rather than scattered across a
dialog, a README and a packaging script that will drift apart.

Deliberately free of Qt, so the packaging step and any future CLI can read the
same values the About box shows.
"""

from __future__ import annotations

APP_NAME = "Anamorph"
VERSION = "0.1.0"

# QStandardPaths builds AppDataLocation out of these two, which is why they
# are set at all: without them the session copy lands in a folder named after
# whatever interpreter or executable happened to launch the app.
ORGANIZATION = APP_NAME

AUTHOR = "Kaio Augusto"
COPYRIGHT_YEARS = "2026"
COPYRIGHT = f"Copyright (C) {COPYRIGHT_YEARS} {AUTHOR}"

# The SPDX identifier is the machine-readable half: compliance scanners look
# for exactly this string. "only" is the choice, and it is deliberate: the
# terms this project ships under are the ones its author read, not whatever a
# future GPL turns out to say. The cost is symmetrical to the DCO's - with no
# copyright assignment, moving to a later GPL would mean asking every
# contributor, so in practice version 3 is where this stays.
LICENSE_ID = "GPL-3.0-only"
LICENSE_NAME = "GNU General Public License, version 3"
LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"

HOMEPAGE = "https://github.com/KAIKOAUGUSTIN/Anamorph"

TAGLINE = "Projection mapping: one canvas, any number of projectors."

# The application's own top-level modules.
#
# These used to live under a single `pm` package, which gave every logger in
# the app a shared ancestor - `logging.getLogger("pm")` caught all of it and
# nothing else. Flattening the layout took that ancestor away, so the problem
# log listens on the *root* logger and uses this list to tell the app's own
# warnings apart from a dependency's. A new top-level module has to be added
# here or its failures will not reach the operator.
PACKAGES = (
    "about",
    "app_main",
    "app_paths",
    "fileio",
    "media",
    "model",
    "projection_gui",
    "render",
    "ui",
)

WARRANTY = (
    "This program comes with ABSOLUTELY NO WARRANTY, to the extent permitted "
    "by applicable law."
)

REDISTRIBUTION = (
    "This is free software, and you are welcome to redistribute it under the "
    "conditions of the GNU General Public License, version 3."
)


def legal_notice() -> str:
    """The four facts the GPL asks an interactive program to display."""
    return (
        f"{COPYRIGHT}\n\n"
        f"{WARRANTY}\n\n"
        f"{REDISTRIBUTION}\n\n"
        f"The full licence text ships with this program as LICENSE, and is at\n"
        f"{LICENSE_URL}"
    )
