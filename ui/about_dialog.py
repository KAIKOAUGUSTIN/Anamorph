# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The About box, which exists for a legal reason as much as a friendly one.

The GPL (section 5d) expects an interactive program to carry its Appropriate
Legal Notices. Until now the only statement of licence in the whole project
was a 674-line file nobody opens; someone running a packaged build would have
had no way at all to find out what terms they hold it under.

The text itself lives in `about` so this dialog, the README and any future
installer cannot disagree about it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from about import (
    APP_NAME,
    HOMEPAGE,
    LICENSE_NAME,
    LICENSE_URL,
    TAGLINE,
    VERSION,
    legal_notice,
)


class AboutDialog(QDialog):
    """Name, version, and the terms - the four facts the GPL asks for."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setStyleSheet(
            "color: #00d4aa; font-size: 22px; font-weight: 700; letter-spacing: 2px;"
        )
        layout.addWidget(title)

        version = QLabel(f"Version {VERSION}")
        version.setStyleSheet("color: #a0a0a0;")
        layout.addWidget(version)

        tagline = QLabel(TAGLINE)
        tagline.setWordWrap(True)
        tagline.setStyleSheet("color: #e0e0e0; padding-top: 6px;")
        layout.addWidget(tagline)

        self.notice = QLabel(legal_notice())
        self.notice.setWordWrap(True)
        # The operator may need to paste this into an email to a client's
        # legal department; a label they cannot select is a label they retype.
        self.notice.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notice.setStyleSheet(
            "color: #a0a0a0; background: #202024; border: 1px solid #3a3a3e;"
            " border-radius: 3px; padding: 10px; margin-top: 8px;"
        )
        layout.addWidget(self.notice)

        links = QLabel(
            f'<a style="color:#00d4aa;" href="{LICENSE_URL}">{LICENSE_NAME}</a>'
            f'&nbsp;&nbsp;·&nbsp;&nbsp;'
            f'<a style="color:#00d4aa;" href="{HOMEPAGE}">Source code</a>'
        )
        links.setOpenExternalLinks(True)
        links.setTextFormat(Qt.RichText)
        layout.addWidget(links)

        third_party = QLabel(
            "Built on Qt (PySide6), NumPy, OpenCV, Pillow, PyOpenGL and "
            "mapbox_earcut. See THIRD-PARTY-NOTICES.md for their licences."
        )
        third_party.setWordWrap(True)
        third_party.setStyleSheet("color: #707070; font-size: 11px; padding-top: 4px;")
        layout.addWidget(third_party)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
