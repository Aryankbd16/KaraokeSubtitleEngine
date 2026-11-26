$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed `
        --name KaraokeSubtitleEngine --paths . --add-data 'app/fonts:app/fonts' `
        --collect-submodules transformers.models.wav2vec2 --exclude-module tkinter `
        --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineCore `
        --exclude-module pandas --exclude-module matplotlib scripts/desktop_entry.py
    if ($LASTEXITCODE) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
    $bundle = Join-Path $PWD 'dist/KaraokeSubtitleEngine'
    # Qt uses Windows' ICU. A private ICU found on the build host may shadow
    # the Windows DLL with an incompatible export table.
    foreach ($name in @('icuuc.dll', 'icuin.dll')) {
        $collected = Join-Path $bundle "_internal/$name"
        if (Test-Path -LiteralPath $collected) { Remove-Item -LiteralPath $collected }
    }
    foreach ($name in @('ffmpeg', 'ffprobe')) {
        $tool = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue
        if ($tool) { Write-Host "$name available on PATH. The package uses the installed copy." }
    }
    $app = Join-Path $bundle 'KaraokeSubtitleEngine.exe'
    $process = Start-Process -FilePath $app -ArgumentList '--smoke' -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(60000)) {
        $process.Kill()
        throw "The packaged app did not exit its startup smoke test within 60 seconds."
    }
    if ($process.ExitCode) { throw "Packaged app failed its startup smoke test." }
    Write-Host "Packaged startup verified at $app"
}
finally {
    Pop-Location
}
