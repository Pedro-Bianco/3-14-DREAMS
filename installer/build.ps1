# PI dreams build: tests -> PIDreams.exe (PyInstaller) -> installer (Inno Setup).
# Usage, from the repository root:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
#
# Requirements: Python 3.12 from python.org (NOT the Microsoft Store one — its sandbox
# blocks the camera) and Inno Setup 6 (winget install JRSoftware.InnoSetup).

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step "Build environment (.venv-dev)"
$Python = "$Root\.venv-dev\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $PythonOrg = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $PythonOrg)) { throw "Python 3.12 from python.org not found: winget install Python.Python.3.12" }
    & $PythonOrg -m venv .venv-dev
}
& $Python -m pip install --quiet -r requirements\build.txt
if ($LASTEXITCODE -ne 0) { throw "failed to install the dependencies" }

if (Test-Path tests) {
    Step "Tests"
    & $Python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "tests failed — build stopped" }
}

Step "PIDreams.exe (PyInstaller)"
& $Python -m PyInstaller installer\pidreams.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Step "Installer (Inno Setup)"
$Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 not found: winget install JRSoftware.InnoSetup" }
& $Iscc -Q installer\pidreams.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Step "Sizes (target: app <= 0.9 GB without models)"
$App = (Get-ChildItem dist\PIDreams -Recurse -File | Measure-Object Length -Sum).Sum
$Setup = Get-ChildItem installer\Output\PIDreams-Setup-*.exe | Sort-Object LastWriteTime | Select-Object -Last 1
"app (dist\PIDreams): {0:N2} GB" -f ($App / 1GB)
"installer ({0}): {1:N0} MB" -f $Setup.Name, ($Setup.Length / 1MB)
if ($App -gt 0.9GB) { Write-Warning "app above the 0.9 GB target" }
