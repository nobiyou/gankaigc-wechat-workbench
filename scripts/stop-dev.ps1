$ErrorActionPreference = "Stop"

$ports = @(3000, 8000)
$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-ListeningDevProcessIds {
  Get-NetTCPConnection -LocalPort $ports -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
}

function Get-RepoDevProcesses {
  Get-CimInstance Win32_Process | Where-Object {
    ($_.CommandLine -like "*$repoRoot*uvicorn*app.main:app*") -or
    ($_.CommandLine -like "*$repoRoot*vite.js*--port*3000*") -or
    ($_.CommandLine -like "*$repoRoot*apps\\frontend*node_modules\\vite\\bin\\vite.js*")
  }
}

function Get-ChildProcessIds {
  param([int[]]$ParentProcessIds)

  if (-not $ParentProcessIds -or $ParentProcessIds.Count -eq 0) {
    return @()
  }

  $children = Get-CimInstance Win32_Process | Where-Object {
    $ParentProcessIds -contains $_.ParentProcessId
  }
  $childIds = @($children | Select-Object -ExpandProperty ProcessId -Unique)
  if ($childIds.Count -eq 0) {
    return @()
  }

  @($childIds + (Get-ChildProcessIds -ParentProcessIds $childIds)) | Sort-Object -Unique
}

$listeningProcessIds = @(Get-ListeningDevProcessIds)
$devProcesses = @(Get-RepoDevProcesses)
$devProcessIds = @($devProcesses | Select-Object -ExpandProperty ProcessId -Unique)
$childProcessIds = @(Get-ChildProcessIds -ParentProcessIds @($listeningProcessIds + $devProcessIds))
$processIds = @($listeningProcessIds + $devProcessIds + $childProcessIds) |
  Where-Object { $_ -and $_ -ne 0 } |
  Sort-Object -Unique

if ($processIds.Count -eq 0) {
  Write-Output "No dev processes listening on ports 3000/8000."
  exit 0
}

foreach ($processId in ($processIds | Sort-Object -Descending)) {
  try {
    Stop-Process -Id $processId -Force -ErrorAction Stop
    Wait-Process -Id $processId -Timeout 5 -ErrorAction SilentlyContinue
    Write-Output "Stopped process $processId."
  } catch {
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
      Write-Output ("Failed to stop process {0}: {1}" -f $processId, $_.Exception.Message)
    } else {
      Write-Output "Process $processId already stopped."
    }
  }
}

$deadline = (Get-Date).AddSeconds(10)
do {
  Start-Sleep -Milliseconds 500
  $remainingListeners = @(Get-ListeningDevProcessIds)
} while ($remainingListeners.Count -gt 0 -and (Get-Date) -lt $deadline)

if ($remainingListeners.Count -gt 0) {
  Write-Output ("Ports still listening after stop: {0}" -f (($remainingListeners | Sort-Object -Unique) -join ", "))
  exit 1
}

Write-Output "Dev ports 3000/8000 are stopped."
