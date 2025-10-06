param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
$scriptPath = Join-Path $PSScriptRoot 'run-stack.ps1'
if (-not (Test-Path $scriptPath)) {
  Write-Host "run-stack.ps1 not found next to make.ps1" -ForegroundColor Red
  exit 1
}
& $scriptPath @Args
exit $LASTEXITCODE
