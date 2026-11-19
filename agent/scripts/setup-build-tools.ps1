[CmdletBinding()]
param(
  [string]$PythonVersion = "3.13"
)

$ErrorActionPreference = "Stop"
$agentDirectory = Split-Path -Parent $PSScriptRoot
Set-Location $agentDirectory

function Install-WithWinget([string]$packageId, [string]$label) {
  $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "No se encontró winget. Instale '$label' manualmente y vuelva a ejecutar este script."
  }

  Write-Output "Instalando $label..."
  & $winget.Source install --id $packageId --exact --source winget --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    throw "No se pudo instalar $label mediante winget (código $LASTEXITCODE)."
  }
}

$pythonLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
$pythonAvailable = $false
if ($pythonLauncher) {
  & $pythonLauncher.Source "-$PythonVersion" --version 2>$null
  $pythonAvailable = $LASTEXITCODE -eq 0
}
if (-not $pythonAvailable) {
  Install-WithWinget "Python.Python.$PythonVersion" "Python $PythonVersion"
  $pythonLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
  if (-not $pythonLauncher) {
    throw "Python se instaló, pero el iniciador 'py' aún no está disponible. Cierre PowerShell, ábralo de nuevo y ejecute este script."
  }
}

$isccCandidates = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "$env:USERPROFILE\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
  (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
)
if (-not ($isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)) {
  Install-WithWinget "JRSoftware.InnoSetup" "Inno Setup 6"
}

$venvPython = Join-Path $agentDirectory ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Output "Creando entorno virtual con Python $PythonVersion..."
  & $pythonLauncher.Source "-$PythonVersion" -m venv .venv
  if ($LASTEXITCODE -ne 0) {
    throw "No se pudo crear el entorno virtual de Python."
  }
}

Write-Output "Instalando dependencias de compilación..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
  throw "No se pudo actualizar pip."
}
& $venvPython -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) {
  throw "No se pudieron instalar las dependencias de compilación."
}

Write-Output "Preparación terminada. Ahora ejecute: .\scripts\build-installer.ps1"
