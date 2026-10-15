# ============================================================================
#  texpipe launcher (PowerShell)
#  Run from PowerShell: .\texpipe.ps1
#  Or right-click → "Run with PowerShell"
#  - Detects Python (python / py)
#  - Auto-installs missing Python packages on first run
#  - Launches the GUI
# ============================================================================

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Write-Info([string]$msg) { Write-Host "  [info] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "  [ ok ] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [warn] $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg)  { Write-Host " [error] $msg" -ForegroundColor Red }
# Pause for the user to read the message; never throws in non-interactive shells.
function Wait-Exit { try { Read-Host "Press Enter to exit" } catch { } }

# --- Find a runnable Python (prefer Windows py launcher, force Python 3) ---
$py = $null
$pyArgs = @()
$storeStub = $false
$pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & py -3 --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $py = "py"
        $pyArgs = @("-3")
    }
}
if (-not $py) {
    $pythonCommand = Get-Command "python" -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        # A real python works; a Microsoft Store placeholder (WindowsApps)
        # just pops the Store window and exits, so flag it for the error msg.
        if ($pythonCommand.Source -like "*WindowsApps*") { $storeStub = $true }
        & python --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $py = "python"
        }
    }
}
if (-not $py) {
    Write-Err "Python 3 was not found on this computer."
    if ($storeStub) {
        Write-Host "  A Microsoft Store placeholder was detected, but a real Python is NOT"
        Write-Host "  installed. The placeholder alone cannot run texpipe."
    } else {
        Write-Host "  texpipe is a Python program and needs Python to start."
    }
    Write-Host ""
    Write-Host "  Install Python 3.10+ with ONE of these options, then run this file again:"
    Write-Host ""
    Write-Host "    [Option 1 - recommended] Windows package manager, one command:"
    Write-Host "       winget install Python.Python.3.12"
    Write-Host ""
    Write-Host "    [Option 2] Manual installer - tick 'Add python.exe to PATH':"
    Write-Host "       https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "    [Option 3] Microsoft Store - search for 'Python 3.12'"
    Write-Host ""
    Write-Host "  After installing, close this window and run this file again."
    Write-Host ""
    Wait-Exit
    exit 1
}

# --- texpipe needs Python 3.10+ ---
& $py @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Err "texpipe needs Python 3.10+, but an older version was found:"
    & $py @pyArgs --version
    Write-Host ""
    Write-Host "  Please install Python 3.10+ (https://www.python.org/downloads/)"
    Write-Host "  and run this file again."
    Write-Host ""
    Wait-Exit
    exit 1
}

Write-Info "Using Python: $py $($pyArgs -join ' ')"
& $py @pyArgs --version

# --- 验证关键依赖;缺则装 ---
Write-Info "Verifying required packages (numpy / Pillow / PySide6 / PNG / TIFF / EXR) ..."
$needInstall = $false
try {
    & $py @pyArgs -c "import numpy, PIL, PySide6, png, tifffile, OpenEXR" 2>$null
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
} catch {
    $needInstall = $true
}

if ($needInstall) {
    Write-Warn "Missing packages detected. Installing from requirements.txt ..."
    & $py @pyArgs -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install failed. Check your network and try again."
        Wait-Exit
        exit 1
    }
    Write-Ok "Dependencies installed."
}

# --- Optional: Skybox Noise plugin speedup (numba) ---
# Missing numba is fine (falls back to numpy); install failure is non-fatal.
Write-Info "Trying to install numba (optional, ~150MB, skybox-noise speedup) ..."
try {
    & $py @pyArgs -m pip install --quiet numba 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "numba ready."
    } else {
        Write-Warn "numba install skipped (skybox-noise will use numpy fallback)."
    }
} catch {
    Write-Warn "numba install skipped (skybox-noise will use numpy fallback)."
}

# --- 启动 GUI ---
Write-Info "Launching texpipe GUI ..."
Write-Host ""
& $py @pyArgs -m src.ui.main
$rc = $LASTEXITCODE

if ($rc -ne 0) {
    Write-Err "GUI exited with code $rc"
    Wait-Exit
    exit $rc
}
