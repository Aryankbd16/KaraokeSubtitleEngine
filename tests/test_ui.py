import time
from unittest.mock import Mock

import pytest

from app.core import EngineError
from app.jobs import Result
from app.media import MediaInfo

pytest.importorskip("PySide6.QtWidgets")

from PySide6 import QtWidgets  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app import ui  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["kata", "-platform", "offscreen"])


HINDI_TRANSCRIPT = (
    "किसी ने मुझसे पूछा कि हमेशा सच कहते फिरते हो तुम?\n\n"
    "ऐसा भी क्या है इस हंसी के पीछे जिसे हमेशा छुपाए फिरते हो तुम?\n\n"
    "मैंने भी हंस के उसे देखा और कहा, अब इतने दिन हो गए इस हंसी के नकाब को पहना है "
    "कि जनाब अब याद भी नहीं इस हंसी के पीछे क्या है।"
)


@pytest.fixture
def validation_window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path))
    window = ui.MainWindow(ui.Wav2VecAligner(tmp_path), tmp_path / "engine.log")
    window.video = tmp_path / "input.mp4"
    window.video.write_bytes(b"fixture")
    monkeypatch.setattr(ui, "Media", Mock())
    monkeypatch.setattr(window.aligner, "ready", lambda _: True)
    monkeypatch.setattr(window, "start_task", Mock())
    monkeypatch.setattr(ui, "check_language", Mock(wraps=ui.check_language))
    window.show()
    qt_app.processEvents()
    try:
        yield window
    finally:
        window.close()
        qt_app.processEvents()


@pytest.mark.parametrize(("language", "script", "required_script"), [
    ("hi", HINDI_TRANSCRIPT, None),
    ("hi", "नमस्ते दुनिया।", None),
    ("en", "Every word shines.", None),
    ("hi", "Namaste duniya.", "Devanagari"),
    ("hi", "नमस्ते world", "Devanagari"),
    ("en", "नमस्ते दुनिया।", "Latin"),
])
def test_generate_validates_selected_language(validation_window, language, script, required_script):
    window = validation_window
    window.editor.setPlainText(script)
    QTest.keyClick(window.language, Qt.Key.Key_End if language == "hi" else Qt.Key.Key_Home)
    window.generate.click()
    ui.check_language.assert_called_once()
    selected, tokens = ui.check_language.call_args.args
    assert selected == language
    assert [token.text for token in tokens] == script.split()
    if required_script:
        window.start_task.assert_not_called()
        assert window.status.text() == (
            f"Use {required_script} script for this language. "
            "Romanized Hindi and mixed-script alignment are unavailable."
        )
    else:
        window.start_task.assert_called_once()


def test_scrolling_over_language_preserves_selection(validation_window, qt_app):
    window = validation_window
    combo = window.language
    window.editor.setPlainText(HINDI_TRANSCRIPT)
    window.scroll.ensureWidgetVisible(combo)
    qt_app.processEvents()
    combo.showPopup()
    view = combo.view()
    row = combo.model().index(combo.findText("Hindi · देवनागरी"), 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(row).center())
    assert combo.currentData() == "hi"
    bar = window.scroll.verticalScrollBar()
    before = bar.value()
    QTest.wheelEvent(window.windowHandle(), combo.mapTo(window, combo.rect().center()), QPoint(0, 120))
    qt_app.processEvents()
    window.generate.click()
    assert ui.check_language.call_args.args[0] == "hi"
    window.start_task.assert_called_once()
    assert bar.value() < before


def test_script_error_follows_input_changes(validation_window):
    window = validation_window
    window.editor.setPlainText(HINDI_TRANSCRIPT)
    window.generate.click()
    assert "Use Latin script" in window.status.text()
    QTest.keyClick(window.language, Qt.Key.Key_End)
    assert "Use Latin script" not in window.status.text()
    window.generate.click()
    window.start_task.assert_called_once()
    QTest.keyClick(window.language, Qt.Key.Key_Home)
    window.generate.click()
    assert "Use Latin script" in window.status.text()
    window.editor.setPlainText("Every word.")
    assert "Use Latin script" not in window.status.text()
    window.generate.click()
    assert [call.args[0] for call in ui.check_language.call_args_list] == ["en", "hi", "en", "en"]
    assert window.start_task.call_count == 2


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
