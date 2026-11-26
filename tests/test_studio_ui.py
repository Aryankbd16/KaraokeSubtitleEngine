import time

from PySide6.QtWidgets import QApplication

from app.core import EngineError
from app.presets import DEFAULT, PresetStore
from app.studio import StudioDialog


def wait_until(app, condition):
    deadline = time.monotonic() + 12
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.015)
    assert condition()


def test_dialog_preview_and_recovery(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication(["studio", "-platform", "offscreen"])
    from app.media import Media
    import pytest
    try:
        Media()
    except EngineError as exc:
        pytest.skip(str(exc))
    store = PresetStore(tmp_path / "presets.json")
    dialog = StudioDialog(store, DEFAULT, store.current, None, None, "")
    dialog.show()
    try:
        dialog.presets.setCurrentText("Poetry / Shayari")
        assert dialog.fields["hi_weight"].count() == 1
        dialog.fields["hi_italic"].setChecked(True)
        dialog.fields["size"].setValue(76)
        wait_until(app, lambda: not dialog.preview.original.isNull())
        image = dialog.preview.original.cacheKey()

        def fail(*_):
            raise EngineError("Fixture decoder failure")
        monkeypatch.setattr("app.preview.render_frame", fail)
        dialog.fields["hindi_font"].setCurrentText("Mukta")
        assert not dialog.fields["hi_italic"].isEnabled() and not dialog.style.hi_italic
        assert dialog.fields["hi_weight"].count() == 4
        wait_until(app, lambda: "Fixture decoder failure" in dialog.preview.status.text())
        assert dialog.preview.original.cacheKey() == image
        dialog.manage("restore")
        assert dialog.style.size == 60
        dialog.apply()
        assert PresetStore(store.path).selected == "Poetry / Shayari"
    finally:
        if dialog.isVisible():
            dialog.reject()

