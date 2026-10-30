param(
    [string]$IdfPath = $env:IDF_PATH,
    [string]$ToolsPath = $env:IDF_TOOLS_PATH,
    [string]$BuildRoot = '',
    [string]$Profile = '',
    [switch]$RealMicrophone,
    [switch]$PhysicalHaptic
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $IdfPath -or -not (Test-Path -LiteralPath (Join-Path $IdfPath 'export.ps1'))) {
    throw 'Set IDF_PATH to the installed ESP-IDF v5.5.1 checkout. See docs/DEVELOPMENT.ko.md.'
}
if (-not $ToolsPath) { throw 'Set IDF_TOOLS_PATH to the isolated Espressif tools directory.' }
if (-not $BuildRoot) { $BuildRoot = Join-Path $env:USERPROFILE 'shdev\firmware-work' }
if ($BuildRoot -match '[^\x00-\x7F]|\s') { throw 'Choose an ASCII build path without spaces (a dedicated subst drive is supported).' }
$mode = if ($RealMicrophone) { 'mic' } else { 'synthetic' }
$mode += if ($PhysicalHaptic) { '-physical' } else { '-mock' }
$stage = Join-Path $BuildRoot $mode
New-Item -ItemType Directory -Force -Path $stage | Out-Null
# Only copy this repository's firmware; do not reset or delete any external tree.
Copy-Item -LiteralPath (Join-Path $projectRoot 'firmware') -Destination $stage -Recurse -Force
$stagedProject = Join-Path $stage 'firmware'
if (-not $Profile) {
    $profileName = if ($PhysicalHaptic) { 'xiao-dm161-3v-prototype.json' } else { 'xiao-inmp441-drv2605l.json' }
    $Profile = Join-Path $projectRoot "hardware\profiles\$profileName"
}
$py = Join-Path $projectRoot '.venv\Scripts\python.exe'
$profileValue = Get-Content -LiteralPath $Profile -Raw | ConvertFrom-Json
if ($PhysicalHaptic) {
    $profileValue = Get-Content -LiteralPath $Profile -Raw | ConvertFrom-Json
    if (-not $profileValue.haptic.enabled) { throw 'Physical output requires an enabled hardware profile.' }
    if ($profileValue.haptic.prototype) { Write-Host 'Prototype physical output: configured for 3V ERM; NOT physically verified/calibrated.' }
}
& $py (Join-Path $PSScriptRoot 'hardware-header.py') $Profile (Join-Path $stagedProject 'main\hardware_profile.h')
if ($LASTEXITCODE -ne 0) { throw 'Hardware profile validation failed.' }
$defaults = Get-Content -LiteralPath (Join-Path $projectRoot 'firmware\sdkconfig.defaults') -Raw
if ($RealMicrophone) { $defaults = $defaults.Replace('CONFIG_SH_SYNTHETIC_AUDIO=y','# CONFIG_SH_SYNTHETIC_AUDIO is not set') }
if ($PhysicalHaptic) { $defaults = $defaults.Replace('CONFIG_SH_SIMULATED_HAPTIC=y','# CONFIG_SH_SIMULATED_HAPTIC is not set') }
Set-Content -LiteralPath (Join-Path $stagedProject 'sdkconfig.defaults') -Value $defaults -Encoding utf8
$pins = "`nCONFIG_SH_I2S_BCLK=$($profileValue.i2s.bclk_gpio)`nCONFIG_SH_I2S_WS=$($profileValue.i2s.ws_gpio)`nCONFIG_SH_I2S_DIN=$($profileValue.i2s.din_gpio)`n"
if ($profileValue.button) { $pins += "CONFIG_SH_BUTTON_GPIO=$($profileValue.button.gpio)`n" }
# Recreate the selected configuration so cached sdkconfig cannot retain old pins/modes.
Set-Content -LiteralPath (Join-Path $stagedProject 'sdkconfig') -Value ($defaults + $pins) -Encoding utf8
$env:IDF_TOOLS_PATH = $ToolsPath
$env:IDF_PATH = $IdfPath
$env:IDF_COMPONENT_MANAGER = '0'
$env:TMP = Join-Path $BuildRoot 'tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null
$bundledPythonDir = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python'
if (Test-Path -LiteralPath $bundledPythonDir) { $env:PATH = "$bundledPythonDir;$env:PATH" }
. (Join-Path $IdfPath 'export.ps1')
if ($LASTEXITCODE -ne 0) { throw 'ESP-IDF activation failed.' }
Push-Location -LiteralPath $stagedProject
try {
    $idfPython = Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $idfPython)) { throw 'ESP-IDF Python environment was not found.' }
    & $idfPython (Join-Path $IdfPath 'tools\idf.py') -D IDF_TARGET=esp32s3 build
    if ($LASTEXITCODE -ne 0) { throw 'ESP-IDF build failed.' }
} finally { Pop-Location }
$destination = Join-Path $projectRoot "build\firmware-$mode"
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -LiteralPath (Join-Path $stagedProject 'build\sound_haptic.bin'),(Join-Path $stagedProject 'build\sound_haptic.elf'),(Join-Path $stagedProject 'build\flasher_args.json') -Destination $destination -Force
New-Item -ItemType Directory -Force -Path (Join-Path $destination 'bootloader'),(Join-Path $destination 'partition_table') | Out-Null
Copy-Item -LiteralPath (Join-Path $stagedProject 'build\bootloader\bootloader.bin') -Destination (Join-Path $destination 'bootloader\bootloader.bin') -Force
Copy-Item -LiteralPath (Join-Path $stagedProject 'build\partition_table\partition-table.bin') -Destination (Join-Path $destination 'partition_table\partition-table.bin') -Force
Write-Host "Built successfully: $destination"
Write-Host 'Flashing is a separate action that requires an explicitly identified board/serial port.'
