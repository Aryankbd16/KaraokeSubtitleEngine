@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchaudio==2.8.0
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
where ffmpeg >nul 2>&1
if errorlevel 1 if not defined KARAOKE_FFMPEG echo Install FFmpeg with: winget install --id Gyan.FFmpeg -e
where ffprobe >nul 2>&1
if errorlevel 1 if not defined KARAOKE_FFPROBE echo Open a new window after installing FFmpeg so FFprobe is available.
echo Setup complete. Open Launch Karaoke.cmd.
pause
exit /b 0
:error
echo Setup failed. Install 64-bit Python 3.12 from python.org with the Python launcher, then check the error above.
pause
exit /b 1
