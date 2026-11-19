param(
  [switch]$SkipInstaller
)

$agentDirectory = Split-Path -Parent $PSScriptRoot
Set-Location $agentDirectory

$python = Join-Path $agentDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

& $python -B -m PyInstaller --noconfirm --clean --onedir --noconsole `
  --name "PuenteEscaner" `
  --paths "src" `
  --collect-all "naps2_scan" `
  --collect-all "pystray" `
  --collect-all "PIL" `
  --hidden-import "pythoncom" `
  --hidden-import "win32com.client" `
  --hidden-import "clr_loader" `
  "src\devicebridge\main.py"

if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

if ($SkipInstaller) {
  Write-Output "Ejecutable generado en dist\PuenteEscaner\PuenteEscaner.exe"
  exit 0
}

$runtimeVersion = "8.0.34"
$runtimeDirectory = Join-Path $agentDirectory "installer\prerequisites"
$runtimeInstaller = Join-Path $runtimeDirectory "dotnet-runtime-$runtimeVersion-win-x64.exe"
$runtimeUrl = "https://builds.dotnet.microsoft.com/dotnet/Runtime/$runtimeVersion/dotnet-runtime-$runtimeVersion-win-x64.exe"

if (-not (Test-Path $runtimeInstaller)) {
  New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
  Write-Output "Descargando .NET Runtime $runtimeVersion x64..."
  Invoke-WebRequest -Uri $runtimeUrl -OutFile $runtimeInstaller
}

$iscc = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "$env:USERPROFILE\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
  (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
  Write-Error "No se encontró Inno Setup 6. Instálelo y ejecute de nuevo .\scripts\build-installer.ps1"
  exit 1
}

& $iscc "installer\PuenteEscaner.iss"
exit $LASTEXITCODE
