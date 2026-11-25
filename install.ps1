# WhisperFlow Windows Installer
$ErrorActionPreference = "Stop"

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "         WhisperFlow Windows Installer                " -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Cyan

$AppDir = "$env:LOCALAPPDATA\whisperflow"
$VenvDir = "$AppDir\venv"
$ConfigDir = "$env:USERPROFILE\.config\whisperflow"

New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

Write-Host "`n[*] Creating Python virtual environment..."
python -m venv $VenvDir

Write-Host "[*] Installing dependencies (faster-whisper, pynput, sounddevice, pyperclip, pystray)..."
& "$VenvDir\Scripts\pip.exe" install --upgrade pip --quiet
& "$VenvDir\Scripts\pip.exe" install -r "$PSScriptRoot\requirements.txt" --quiet

Copy-Item "$PSScriptRoot\whisperflow.py" "$AppDir\whisperflow.py" -Force

if (!(Test-Path "$ConfigDir\config.json")) {
    Copy-Item "$PSScriptRoot\config.default.json" "$ConfigDir\config.json"
    Write-Host "[OK] Created default config at $ConfigDir\config.json" -ForegroundColor Green
}

Write-Host "`n======================================================" -ForegroundColor Cyan
Write-Host "         WhisperFlow installed successfully!          " -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "Run WhisperFlow with:"
Write-Host "  $VenvDir\Scripts\python.exe $AppDir\whisperflow.py" -ForegroundColor Yellow
Write-Host "`nHold Right Alt to speak, release to type anywhere!"
