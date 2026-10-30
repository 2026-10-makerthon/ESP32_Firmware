param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Force -Path '.tools\tmp' | Out-Null
$env:TEMP = Join-Path $projectRoot '.tools\tmp'
$env:TMP = $env:TEMP
if (-not $Python) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $Python = $bundledPython } else { $Python = 'python' }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ and venv are required.' }
}
& '.\.venv\Scripts\python.exe' -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed.' }
$requirements = if (Test-Path 'requirements.lock.txt') { 'requirements.lock.txt' } else { 'requirements-dev.txt' }
& '.\.venv\Scripts\python.exe' -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready: .\.venv\Scripts\python.exe -m harness demo'
