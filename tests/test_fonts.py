import pytest
from PySide6.QtGui import QRawFont, QFont
from PySide6.QtWidgets import QApplication

from app.core import EngineError
from app.font_library import FONT_DIR, all_faces, resolve, stage_fonts


def test_font_metadata_coverage_and_licenses(tmp_path):
    app = QApplication.instance() or QApplication(["fonts", "-platform", "offscreen"])
    assert app
    stage_fonts(tmp_path)
    for face in all_faces():
        path = face.path()
        font = QRawFont(str(path), 32, QFont.HintingPreference.PreferNoHinting)
        assert font.isValid()
        assert face.family in font.familyName()
        assert font.weight() == face.weight
        assert bool(font.style() != QFont.Style.StyleNormal) == face.italic
        if face.family != "Noto Sans":
            assert all(font.supportsCharacter(ord(c)) for c in "ज़िंदगीआँखविसर्गः१२३")
        assert (tmp_path / "fonts" / face.filename).is_file()
        assert "SIL OPEN FONT LICENSE" in (path.parent / "OFL.txt").read_text(encoding="utf-8")
        assert face.family in (FONT_DIR / "README.md").read_text(encoding="utf-8")


def test_face_resolution(tmp_path):
    assert resolve("Mukta", 580, True).weight == 600
    assert not resolve("Mukta", 580, True).italic
    face = resolve("Tiro Devanagari Hindi", 700, True)
    assert face.weight == 400 and face.italic
    with pytest.raises(EngineError, match="Missing bundled font"):
        face.path(tmp_path)
