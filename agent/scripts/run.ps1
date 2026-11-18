param(
  [string]$Config = "config.yaml"
)

$agentDirectory = Split-Path -Parent $PSScriptRoot
$projectDirectory = Split-Path -Parent $agentDirectory
$env:PYTHONPYCACHEPREFIX = Join-Path $projectDirectory ".runtime\pycache"
New-Item -ItemType Directory -Force -Path $env:PYTHONPYCACHEPREFIX | Out-Null

& python -m devicebridge --config $Config
exit $LASTEXITCODE
