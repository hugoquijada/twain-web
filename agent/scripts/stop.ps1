param(
  [ValidateRange(1, 65535)]
  [int]$Port = 8765
)

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -eq 0) {
  Write-Output "DeviceBridge no está escuchando en el puerto $Port."
}

$processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $processIds) {
  $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
  if (-not $process) {
    continue
  }
  if ($process.ProcessName -notmatch '^python') {
    Write-Error "El puerto $Port pertenece a $($process.ProcessName) (PID $processId), no a un proceso Python. No se detuvo."
    continue
  }
  Stop-Process -Id $processId -Force
  Write-Output "DeviceBridge detenido (PID $processId, puerto $Port)."
}

# naps2-scan launches this helper for TWAIN. It can survive when a driver blocks
# the Python process, retaining the scanner's TWAIN source after the agent stops.
$twainWorkers = @(Get-Process -Name "NAPS2.Worker" -ErrorAction SilentlyContinue)
foreach ($twainWorker in $twainWorkers) {
  Stop-Process -Id $twainWorker.Id -Force
  Write-Output "Auxiliar TWAIN detenido (NAPS2.Worker, PID $($twainWorker.Id))."
}
