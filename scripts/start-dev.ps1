$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tmpDir = Join-Path $repoRoot ".tmp"
$backendLog = Join-Path $tmpDir "backend.log"
$backendErrLog = Join-Path $tmpDir "backend.err.log"
$frontendLog = Join-Path $tmpDir "frontend.log"
$frontendErrLog = Join-Path $tmpDir "frontend.err.log"
$powershellPath = (Get-Command powershell -ErrorAction Stop).Source

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

function Resolve-CommandPath {
  param(
    [string]$PreferredPath,
    [string]$CommandName,
    [string]$Label
  )

  if ($PreferredPath -and (Test-Path $PreferredPath)) {
    return (Resolve-Path $PreferredPath).Path
  }

  $command = Get-Command $CommandName -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  throw "Missing $Label executable. Expected '$PreferredPath' or a '$CommandName' command in PATH."
}

function Test-PythonModule {
  param(
    [string]$PythonPath,
    [string]$ModuleName
  )

  if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
    return $false
  }

  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $PythonPath
  $startInfo.Arguments = "-c `"import $ModuleName`""
  $startInfo.UseShellExecute = $false
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $startInfo.CreateNoWindow = $true

  $process = [System.Diagnostics.Process]::Start($startInfo)
  $process.WaitForExit()
  return $process.ExitCode -eq 0
}

function Resolve-PythonPath {
  $candidates = @()
  $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    $candidates += (Resolve-Path $venvPython).Path
  }

  $pathPython = Get-Command "python" -ErrorAction SilentlyContinue
  if ($pathPython) {
    $candidates += $pathPython.Source
  }

  foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (Test-PythonModule -PythonPath $candidate -ModuleName "uvicorn") {
      return $candidate
    }
    Write-Host "Skipping Python without uvicorn: $candidate"
  }

  throw "Missing backend runtime. Install backend dependencies or use a Python environment with uvicorn available."
}

function Start-DetachedPowerShell {
  param(
    [string]$LauncherPath,
    [string]$ScriptContent
  )

  Set-Content -Path $LauncherPath -Value $ScriptContent -Encoding UTF8
  Start-Process `
    -FilePath $powershellPath `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $LauncherPath `
    -WindowStyle Hidden | Out-Null
}

$pythonPath = Resolve-PythonPath

$nodePath = Resolve-CommandPath `
  -PreferredPath "" `
  -CommandName "node" `
  -Label "Node.js"

$vitePath = Join-Path $repoRoot "apps\frontend\node_modules\vite\bin\vite.js"
$backendLauncher = Join-Path $tmpDir "backend-launcher.ps1"
$frontendLauncher = Join-Path $tmpDir "frontend-launcher.ps1"

if (-not (Test-Path $vitePath)) {
  throw "Missing Vite runtime at $vitePath. Run npm install in apps/frontend first."
}

Start-DetachedPowerShell `
  -LauncherPath $backendLauncher `
  -ScriptContent @"
Set-Location '$repoRoot'
& '$pythonPath' -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000 --reload 1>> '$backendLog' 2>> '$backendErrLog'
"@

Start-DetachedPowerShell `
  -LauncherPath $frontendLauncher `
  -ScriptContent @"
Set-Location '$(Join-Path $repoRoot 'apps\frontend')'
& '$nodePath' '$vitePath' --host 127.0.0.1 --port 3000 1>> '$frontendLog' 2>> '$frontendErrLog'
"@

$deadline = (Get-Date).AddSeconds(30)
do {
  Start-Sleep -Seconds 1
  $listeners = Get-NetTCPConnection -LocalPort 3000,8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalPort, OwningProcess |
    Sort-Object LocalPort
} while ((($listeners | Measure-Object).Count -lt 2) -and ((Get-Date) -lt $deadline))

if (($listeners | Measure-Object).Count -lt 2) {
  Write-Output "Startup incomplete. Check .tmp/backend.err.log and .tmp/frontend.err.log"
  exit 1
}

Write-Output "Backend: http://127.0.0.1:8000"
Write-Output "Frontend: http://127.0.0.1:3000"
Write-Output "Logs: $tmpDir"
exit 0
