import time

import pytest

from app.core import EngineError
from app.jobs import Result
from app.media import MediaInfo

pytest.importorskip("PySide6.QtWidgets")

from PySide6 import QtWidgets  # noqa: E402

from app import ui  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["kata", "-platform", "offscreen"])


def while_working(window):
    deadline = time.monotonic() + 5
    while window.thread is not None and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.015)
    assert window.thread is None


def test_workflow(qt_app, tmp_path, monkeypatch):
    source = tmp_path / "Filename नाम.mp4"
    source.write_bytes(b"fixture")
    result = Result(tmp_path / "export.mp4", tmp_path / "export.alignment.json", None, ())
    progress = []

    class FakeMedia:
        def probe(self, path, cancel):
            if path == source:
                return MediaInfo(1, 1, 1, 640, 360, 25, "h264", "aac", 48000, 2)
            raise EngineError("Unsupported media fixture.")

    class LocalModel:
        cache = tmp_path

        def ready(self, language):
            return True

    class FakeJob:
        def __init__(self, aligner):
            assert isinstance(aligner, LocalModel)

        def run(self, project, cancel, update):
            assert project.video == source and project.script == "Every word."
            update(50, "Controlled progress")
            update(100, "Output verified")
            return result

    monkeypatch.setattr(ui, "Media", FakeMedia)
    monkeypatch.setattr(ui, "Job", FakeJob)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_: (str(source), ""))
    window = ui.MainWindow(LocalModel(), tmp_path / "engine.log")
    window.show()
    window.progress_bar.valueChanged.connect(progress.append)
    try:
        window.generate.click()
        assert "Choose a video" in window.status.text()
        window.choose_media(False)
        while_working(window)
        assert window.video == source
        assert "640 × 360" in window.video_label.text()
        window.generate.click()
        assert "Enter a script" in window.status.text()
        window.editor.setPlainText("Every word.")
        assert "2 words" in window.counter.text()
        window.generate.click()
        assert not window.generate.isEnabled()
        while_working(window)
        assert 50 in progress and 100 in progress
        assert window.output == result and window.output_controls.isEnabled()
        assert str(result.video) in window.output_label.text()
        window.reset()
        assert not window.editor.toPlainText() and window.video is None
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                            lambda *_: (str(tmp_path / "missing.mp4"), ""))
        window.choose_media(False)
        while_working(window)
        assert "Cannot read" in window.status.text()
    finally:
        window.close()
        qt_app.processEvents()


def test_cancel_is_handled_on_worker_thread(qt_app, tmp_path):
    window = ui.MainWindow(ui.Wav2VecAligner(tmp_path), tmp_path / "engine.log")

    def cancellable(cancel, update):
        update(25, "Working")
        cancel.event.wait(3)
        cancel.check()

    window.start_task(cancellable, lambda _: pytest.fail("Cancelled task succeeded"),
                      "Starting", True)
    window.cancel_button.click()
    while_working(window)
    assert window.status.text() == "Processing cancelled."
    assert window.generate.isEnabled()
    window.close()
    qt_app.processEvents()
