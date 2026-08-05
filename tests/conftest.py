import os

# Qt has to pick a platform before QApplication is constructed, and test
# machines have no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil

import pytest


@pytest.fixture(scope="session", autouse=True)
def _use_qt_test_paths():
    """Keep the persisted session out of the user's real app data."""
    from PySide6.QtCore import QStandardPaths

    QStandardPaths.setTestModeEnabled(True)
    yield


@pytest.fixture(autouse=True)
def _clean_session_file():
    """Every test starts from an empty session.

    MainWindow restores the last session on construction and writes it back on
    close, so without this each test inherits the previous one's shapes and
    starts failing for reasons that have nothing to do with the code under
    test. Per test, not per run: the leak happens inside a single run too.
    """
    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if base:
        shutil.rmtree(f"{base}/ProjectionMapper", ignore_errors=True)
    yield


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
