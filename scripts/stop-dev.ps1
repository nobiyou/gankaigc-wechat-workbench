$ErrorActionPreference = "Stop"

$ports = @(3000, 8000)
$connections = Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue
$processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique

$repoRoot = Split-Path -Parent $PSScriptRoot
$devProcesses = Get-CimInstance Win32_Process | Where-Object {
  ($_.CommandLine -like "*$repoRoot*uvicorn*app.main:app*") -or
  ($_.CommandLine -like "*$repoRoot*vite.js*--port*3000*") -or
  ($_.CommandLine -like "*$repoRoot*apps\\frontend*node_modules\\vite\\bin\\vite.js*")
}

if ($devProcesses) {
  $processIds = @($processIds + ($devProcesses | Select-Object -ExpandProperty ProcessId -Unique)) | Sort-Object -Unique
}

if (-not $processIds) {
  Write-Output "No dev processes listening on ports 3000/8000."
  exit 0
}

foreach ($processId in $processIds) {
  try {
    Stop-Process -Id $processId -Force -ErrorAction Stop
    Wait-Process -Id $processId -Timeout 5 -ErrorAction SilentlyContinue
    Write-Output "Stopped process $processId."
  } catch {
    Write-Output ("Failed to stop process {0}: {1}" -f $processId, $_.Exception.Message)
  }
}
