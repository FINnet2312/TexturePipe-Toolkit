param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir",
    [switch]$SkipInstall,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$buildVenv = Join-Path $projectRoot ".venv-build"
$buildPython = Join-Path $buildVenv "Scripts\python.exe"
$workRoot = Join-Path $projectRoot "build\pyinstaller"
$distRoot = Join-Path $projectRoot "dist"

function Find-Python {
    $launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($launcher) {
        & py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))"
        if ($LASTEXITCODE -eq 0) {
            return @("py", "-3")
        }
    }

    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        & python -c "import sys; raise SystemExit(sys.version_info < (3, 10))"
        if ($LASTEXITCODE -eq 0) {
            return @("python")
        }
    }

    throw "Python 3.10 or newer was not found."
}

Set-Location $projectRoot

function Test-BuildPython {
    if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
        return $false
    }
    & $buildPython -c "import sys; raise SystemExit(sys.version_info < (3, 10))" 2>$null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-BuildPython)) {
    if (Test-Path -LiteralPath $buildVenv) {
        Write-Warning "The existing build environment is no longer runnable; recreating it."
        Remove-Item -LiteralPath $buildVenv -Recurse -Force
    }
    $pythonCommand = Find-Python
    Write-Host "[build] Creating isolated build environment: $buildVenv"
    if ($pythonCommand.Count -eq 1) {
        & $pythonCommand[0] -m venv $buildVenv
    } else {
        & $pythonCommand[0] $pythonCommand[1] -m venv $buildVenv
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the build environment."
    }
}

if (-not $SkipInstall) {
    Write-Host "[build] Installing runtime and build dependencies..."
    & $buildPython -m pip install --disable-pip-version-check -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
}

& $buildPython -c "import PyInstaller, PySide6, OpenEXR, tifffile, png; from src.ui.skybox_noise.plugin import PLUGIN; assert PLUGIN.is_available()[0]"
if ($LASTEXITCODE -ne 0) {
    throw "The build environment is incomplete. Run again without -SkipInstall."
}

# PyInstaller's --clean clears its global cache, but an interrupted build can
# still leave a locally valid-looking TOC with missing artifacts. Only remove
# this project's exact build workspace and the output target.
if (Test-Path -LiteralPath $workRoot) {
    Write-Host "[build] Removing stale analysis workspace..."
    Remove-Item -LiteralPath $workRoot -Recurse -Force
}
$distTarget = if ($Mode -eq "onefile") {
    Join-Path $distRoot "Texpipe.exe"
} else {
    Join-Path $distRoot "Texpipe"
}
if (Test-Path -LiteralPath $distTarget) {
    Remove-Item -LiteralPath $distTarget -Recurse -Force
}

$previousMode = $env:TEXPIPE_BUNDLE_MODE
try {
    $env:TEXPIPE_BUNDLE_MODE = $Mode
    Write-Host "[build] Building Texpipe ($Mode)..."
    & $buildPython -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distRoot `
        --workpath $workRoot `
        (Join-Path $projectRoot "texpipe.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($null -eq $previousMode) {
        Remove-Item Env:TEXPIPE_BUNDLE_MODE -ErrorAction SilentlyContinue
    } else {
        $env:TEXPIPE_BUNDLE_MODE = $previousMode
    }
}

$exePath = if ($Mode -eq "onefile") {
    Join-Path $projectRoot "dist\Texpipe.exe"
} else {
    Join-Path $projectRoot "dist\Texpipe\Texpipe.exe"
}
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Build finished but the expected executable was not found: $exePath"
}

if (-not $SkipSmokeTest) {
    Write-Host "[verify] Running the frozen application smoke test..."
    $smokeProcess = Start-Process `
        -FilePath $exePath `
        -ArgumentList "--smoke-test" `
        -WorkingDirectory (Split-Path -Parent $exePath) `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($smokeProcess.ExitCode -ne 0) {
        throw "Frozen application smoke test failed with exit code $($smokeProcess.ExitCode)."
    }
}

$sizeMiB = [math]::Round((Get-Item -LiteralPath $exePath).Length / 1MB, 1)
Write-Host "[done] $exePath ($sizeMiB MiB)" -ForegroundColor Green
