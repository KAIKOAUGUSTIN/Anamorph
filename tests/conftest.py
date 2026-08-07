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


@pytest.fixture(autouse=True)
def _drain_deleted_widgets():
    """Let `deleteLater` actually delete.

    Qt defers those deletions to the event loop, and a test that never runs
    one leaves the widget - and, for a renderer, its GL context - alive until
    the interpreter exits. Hundreds of them piled up over a run and the
    process segfaulted on the way out, after every test had passed.
    """
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()
        app.sendPostedEvents(None, 0)
        app.processEvents()


@pytest.fixture(scope="session", autouse=True)
def _close_widgets_before_the_app_goes():
    """Tear widgets down while there is still a QApplication to do it under."""
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in list(app.topLevelWidgets()):
        widget.close()
        widget.setParent(None)
        widget.deleteLater()
    app.processEvents()
    app.sendPostedEvents(None, 0)
    app.processEvents()
