$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tmpDir = Join-Path $repoRoot ".tmp"
$backendLog = Join-Path $tmpDir "backend.log"
$backendErrLog = Join-Path $tmpDir "backend.err.log"
$frontendLog = Join-Path $tmpDir "frontend.log"
$frontendErrLog = Join-Path $tmpDir "frontend.err.log"

New-Item -ItemType Directory -Force $tmpDir | Out-Null

& (Join-Path $PSScriptRoot "stop-dev.ps1") | Out-Null
Start-Sleep -Seconds 2

foreach ($logPath in @($backendLog, $backendErrLog, $frontendLog, $frontendErrLog)) {
  try {
    Set-Content -Path $logPath -Value ""
  } catch {
    Write-Output ("Log file busy, keep existing content: {0}" -f $logPath)
  }
}

$pythonPath = "C:\Users\ltxxg\AppData\Local\Microsoft\WindowsApps\python.exe"
$nodePath = "C:\Program Files\nodejs\node.exe"
$vitePath = Join-Path $repoRoot "apps\frontend\node_modules\vite\bin\vite.js"

if (-not (Test-Path $vitePath)) {
  throw "Missing Vite runtime at $vitePath. Run npm install in apps/frontend first."
}

Start-Process `
  -FilePath $pythonPath `
  -ArgumentList '-m','uvicorn','app.main:app','--app-dir','apps/backend','--host','127.0.0.1','--port','8000','--reload' `
  -WorkingDirectory $repoRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $backendLog `
  -RedirectStandardError $backendErrLog | Out-Null

Start-Process `
  -FilePath $nodePath `
  -ArgumentList $vitePath,'--host','127.0.0.1','--port','3000' `
  -WorkingDirectory (Join-Path $repoRoot 'apps\frontend') `
  -WindowStyle Hidden `
  -RedirectStandardOutput $frontendLog `
  -RedirectStandardError $frontendErrLog | Out-Null

Start-Sleep -Seconds 3

$listeners = Get-NetTCPConnection -LocalPort 3000,8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalPort, OwningProcess |
  Sort-Object LocalPort

if (($listeners | Measure-Object).Count -lt 2) {
  Write-Output "Startup incomplete. Check .tmp/backend.err.log and .tmp/frontend.err.log"
  exit 1
}

Write-Output "Backend: http://127.0.0.1:8000"
Write-Output "Frontend: http://127.0.0.1:3000"
Write-Output "Logs: $tmpDir"
exit 0
