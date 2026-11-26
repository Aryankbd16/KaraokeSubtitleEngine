@echo off
setlocal
cd /d "%~dp0"
if not defined KARAOKE_FFMPEG for /d %%I in (".tools\ffmpeg-*-essentials_build") do if exist "%%~fI\bin\ffmpeg.exe" set "KARAOKE_FFMPEG=%%~fI\bin\ffmpeg.exe"
if not defined KARAOKE_FFPROBE for /d %%I in (".tools\ffmpeg-*-essentials_build") do if exist "%%~fI\bin\ffprobe.exe" set "KARAOKE_FFPROBE=%%~fI\bin\ffprobe.exe"
if not defined KARAOKE_DATA_DIR if exist ".verified\models\" set "KARAOKE_DATA_DIR=%CD%\.verified"
if exist "dist\KaraokeSubtitleEngine\KaraokeSubtitleEngine.exe" (
    start "" "%CD%\dist\KaraokeSubtitleEngine\KaraokeSubtitleEngine.exe"
    exit /b 0
)
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run Setup Karaoke.cmd first.
    pause
    exit /b 1
)
start "" "%CD%\.venv\Scripts\pythonw.exe" -m app.main
