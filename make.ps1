# make.ps1 — thin wrapper so you can keep muscle memory
param([Parameter(Position=0)][string]$Target = 'help')

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $here 'run-stack.ps1'

switch ($Target) {
  'help'         { & $runner help }
  'fast'         { & $runner fast }
  'full'         { & $runner full }
  'schema'       { & $runner schema }
  'schema_seed'  { & $runner schema_seed }
  'seed'         { & $runner seed }
  'seed-run'     { & $runner 'seed-run' }
  'tests'        { & $runner tests }
  'start'        { & $runner start }
  'status'       { & $runner status }
  'logs'         { & $runner logs }
  'stop'         { & $runner stop }
  'info'         { & $runner info }
  'start-docker' { & $runner start-docker }
  'stop-docker'  { & $runner stop-docker }
  'doctor'       { & $runner doctor }
  'ui-start'     { & $runner ui-start }
  'ui-stop'      { & $runner ui-stop }
  default        { & $runner help }
}
