param(
  [string]$BaseUrl = "http://127.0.0.1:3000",
  [string]$ProjectSlug = "office-burnout-recovery-weekly",
  [int]$TimeoutMs = 8000,
  [string]$EdgePath = ""
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "verify-workbench-ui-smoke.cjs"

$arguments = @(
  $scriptPath,
  "--base-url", $BaseUrl,
  "--project-slug", $ProjectSlug,
  "--timeout-ms", $TimeoutMs
)

if ($EdgePath) {
  $arguments += @("--edge-path", $EdgePath)
}

node @arguments
exit $LASTEXITCODE
