# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

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

AUTHOR = "Kaio Augusto"
COPYRIGHT_YEARS = "2026"
COPYRIGHT = f"Copyright (C) {COPYRIGHT_YEARS} {AUTHOR}"

# The SPDX identifier is the machine-readable half: compliance scanners look
# for exactly this string. "or-later" is the choice - the project can follow a
# future GPL rather than being frozen at version 3.
LICENSE_ID = "GPL-3.0-or-later"
LICENSE_NAME = "GNU General Public License, version 3 or later"
LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"

HOMEPAGE = "https://github.com/KAIKOAUGUSTIN/Anamorph"

TAGLINE = "Projection mapping: one canvas, any number of projectors."

WARRANTY = (
    "This program comes with ABSOLUTELY NO WARRANTY, to the extent permitted "
    "by applicable law."
)

REDISTRIBUTION = (
    "This is free software, and you are welcome to redistribute it under the "
    "conditions of the GNU General Public License, version 3 or later."
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
