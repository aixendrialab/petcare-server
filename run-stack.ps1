# run-stack.ps1  — Windows PowerShell 5.1+ compatible
# One-button dev flow: DB (docker) → schema → seed → venv+deps → tests → app.

param(
  [Parameter(Position=0)]
  [ValidateSet('help','fast','full','schema','schema_seed','seed','seed-run',
               'tests','start','status','logs','stop','info',
               'start-docker','stop-docker','doctor','ui-start','ui-stop')]
  [string]$Command = 'help'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Trace-Enter {
  param([string]$Name)
  # no-op tracer to avoid failures when not defined elsewhere
}

function Load-DotEnv([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return }
  Get-Content -LiteralPath $path | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq '' -or $line.StartsWith('#')) { return }

    $parts = $line -split '=', 2
    if ($parts.Count -lt 2) { return }

    $name  = $parts[0].Trim()
    $value = $parts[1].Trim()

    if ( ($value.StartsWith('"') -and $value.EndsWith('"')) -or
         ($value.StartsWith("'") -and $value.EndsWith("'")) ) {
      $value = $value.Substring(1, $value.Length - 2)
    }

    if ($name) { [Environment]::SetEnvironmentVariable($name, $value, "Process") }
  }
}


#function Ensure-Default([string]$name, [string]$default) {
#  if ([string]::IsNullOrWhiteSpace($env:$name)) {
#    $env:$name = $default
#  }
#}


function Resolve-Python311 {
    if ($env:PY_EXE -eq 'python3') {
        Write-Host " - ignoring PY_EXE=python3 (Microsoft Store alias)" -ForegroundColor Yellow
        Remove-Item Env:\PY_EXE -ErrorAction SilentlyContinue
    }

    # Respect override: supports "py -3.11" or a full path with args
    if ($env:PY_EXE) {
        try {
            $parts = $env:PY_EXE -split '\s+'
            $head  = $parts[0]
            $tail  = @()
            if ($parts.Length -gt 1) { $tail = $parts[1..($parts.Length-1)] }

            $ver = & $head @($tail + @('-c', "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))"))
            if ($LASTEXITCODE -eq 0 -and $ver -like '3.11*') {
                $exe = & $head @($tail + @('-c', 'import sys; print(sys.executable)'))
                return $exe
            }
        } catch {}
        Write-Host " - PY_EXE is set but not 3.11; ignoring: '$($env:PY_EXE)'" -ForegroundColor Yellow
    }

    # Windows launcher
    try {
        $exe = & py -3.11 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and $exe) { return $exe }
    } catch {}

    # Common installs
    $candidates = @(
        'C:\Python311\python.exe',
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        'python'
    )
    foreach ($c in $candidates) {
        try {
            $ver = & $c -c "import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))"
            if ($LASTEXITCODE -eq 0 -and $ver -like '3.11*') {
                $exe = & $c -c "import sys; print(sys.executable)"
                return $exe
            }
        } catch {}
    }

    throw "Python 3.11 not found. Install it or set `$env:PY_EXE='py -3.11'."
}


function Ensure-Venv {
  $basePy = Resolve-Python311
  try { $verFull = & $basePy -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null } catch { $verFull = 'unknown' }
  Write-Host "Resolved Python: $basePy (version $verFull)" -ForegroundColor Cyan

  $VENV_PATH = _IfEmpty $env:VENV_PATH '.venv'
  $venvPy = Join-Path $VENV_PATH 'Scripts\python.exe'

  # 🧠 SHORT-CIRCUIT for FAST MODE
  if ($INSTALL_DEPS -eq 0 -and (Test-Path $VENV_PATH) -and (Test-Path $venvPy)) {
    Write-Host " - fast mode: keeping existing venv (no rebuild or pip install)"
    $script:PYBIN = $venvPy
    $script:PIP   = Join-Path $VENV_PATH 'Scripts\pip.exe'
    return
  }

  $needsRebuild = $false
  if (Test-Path $VENV_PATH) {
    try {
      if (-not (Test-Path $venvPy)) {
        $needsRebuild = $true
      } else {
        $vMajMin = & $venvPy -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $vMajMin -or ($vMajMin -notlike '3.11*')) {
          $needsRebuild = $true
        }
      }
    } catch { $needsRebuild = $true }
  } else {
    $needsRebuild = $true
  }

  if ($needsRebuild) {
    if (Test-Path $VENV_PATH) { Remove-Item -Recurse -Force $VENV_PATH }
    Write-Host " - creating venv at $VENV_PATH (base: $basePy)"
    & $basePy -m venv $VENV_PATH
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
  } else {
    Write-Host " - venv present: keeping existing Python 3.11 environment."
  }

  $script:PYBIN = $venvPy
  $script:PIP   = Join-Path $VENV_PATH 'Scripts\pip.exe'

  if (-not (Test-Path $script:PYBIN)) { Fail "venv Python not found at '$script:PYBIN'" }

  Write-Host " - venv python: $script:PYBIN"
  Write-Host " - venv pip   : $script:PIP"

  if ($INSTALL_DEPS -eq 1) {
    $timeout = [string]([int](_IfEmpty $env:PIP_DEFAULT_TIMEOUT '60'))
    Write-Host " - upgrading pip/setuptools/wheel (timeout ${timeout}s)"
    & $script:PYBIN -m pip --default-timeout $timeout install --upgrade pip setuptools wheel --no-input
    if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }

    $REQ_FILE = _IfEmpty $env:REQ_FILE (Join-Path $PSScriptRoot 'requirements.txt')
    $REQ_DEV_FILE = _IfEmpty $env:REQ_DEV_FILE (Join-Path $PSScriptRoot 'requirements-dev.txt')

    if (Test-Path $REQ_FILE) {
      Write-Host " - pip install -r $REQ_FILE (timeout ${timeout}s)"
      & $script:PYBIN -m pip --default-timeout $timeout install -r $REQ_FILE --no-input
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r $REQ_FILE failed" }
    } else {
      Write-Host " - requirements.txt not found; installing essentials"
      & $script:PYBIN -m pip install uvicorn[standard] fastapi
      if ($LASTEXITCODE -ne 0) { Fail "pip install essentials failed" }
    }

    if (Test-Path $REQ_DEV_FILE) {
      Write-Host " - pip install -r $REQ_DEV_FILE (timeout ${timeout}s)"
      & $script:PYBIN -m pip --default-timeout $timeout install -r $REQ_DEV_FILE --no-input
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r $REQ_DEV_FILE failed" }
    }
  } else {
    Write-Host " - skipping pip install (fast mode)"
  }
}



function Pip {
    param(
        [Parameter(Mandatory=$true)][string]$VenvPython,
        [Parameter(ValueFromRemainingArguments=$true)]$Args
    )
    # Always use -m pip to avoid broken pip.exe shims
    & $VenvPython -m pip @Args
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed with exit code $LASTEXITCODE"
    }
}


function Fail($m){ Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Step($m){ Write-Host "==> $m" -ForegroundColor Cyan }
function Run-Cmd {
  param([Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][string[]]$Args)
  Write-Host " > $Exe $($Args -join ' ')" -ForegroundColor DarkGray
  & $Exe @Args
  if ($LASTEXITCODE -ne 0) { Write-Host "Exit $LASTEXITCODE" -ForegroundColor Yellow }
}

# ----- Load .dbstack.env (KEY=VAL) -------------------------------------------
$EnvFile = Join-Path $PSScriptRoot '.dbstack.env'
if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      $k=$Matches[1]; $v=$Matches[2]
      if ($v -match '^"(.*)"$') { $v=$Matches[1] }
      if ($v -match "^\x27(.*)\x27$") { $v=$Matches[1] }
      # do not override if already set in this process
      if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($k,'Process'))) {
        [Environment]::SetEnvironmentVariable($k,$v,'Process')
      }

    }
  }
}

# ----- Defaults (overridable via .dbstack.env) ----------------------------
function _IfEmpty([string]$val, [string]$fallback){
  if ([string]::IsNullOrWhiteSpace($val)) { return $fallback } else { return $val }
}

$COMPOSE_FILE      = _IfEmpty $env:COMPOSE_FILE       (Join-Path $PSScriptRoot 'docker-compose.yml')
$PG_CONTAINER      = _IfEmpty $env:PG_CONTAINER       'db'
$PG_DB             = _IfEmpty $env:PG_DB              'petcare'
$PG_USER           = _IfEmpty $env:PG_USER            'postgres'
$PGPASSWORD        = _IfEmpty $env:PGPASSWORD         'postgres'
$PG_READY_TIMEOUT  = [int](_IfEmpty $env:PG_READY_TIMEOUT '90')

$SCHEMA_FILE       = _IfEmpty $env:SCHEMA_FILE        (Join-Path $PSScriptRoot 'schema.sql')
$SEED_FILE         = _IfEmpty $env:SEED_FILE          (Join-Path $PSScriptRoot 'seed.sql')
$RESET_PUBLIC      = [int](_IfEmpty $env:RESET_PUBLIC '0')

$PY_EXE_RAW        = _IfEmpty $env:PY_EXE             ''        # e.g. "py -3.11" or "C:\...\python.exe"
$VENV_PATH         = _IfEmpty $env:VENV_PATH          '.venv'
$REQ_FILE          = _IfEmpty $env:REQ_FILE           (Join-Path $PSScriptRoot 'requirements.txt')
$REQ_DEV_FILE      = _IfEmpty $env:REQ_DEV_FILE       (Join-Path $PSScriptRoot 'requirements-dev.txt')  # optional
$APP_IMPORT        = _IfEmpty $env:APP_IMPORT         'app.main:app'
$APP_HOST          = _IfEmpty $env:APP_HOST           '127.0.0.1'
$PORT              = [int](_IfEmpty $env:APP_PORT     '8000')

$UI_DIR            = _IfEmpty $env:UI_DIR             ''
$UI_PORT           = [int](_IfEmpty $env:UI_PORT      '5173')

$PIP_DEFAULT_TIMEOUT = [int](_IfEmpty $env:PIP_DEFAULT_TIMEOUT '60')
$RUN_IN_FOREGROUND = [int](_IfEmpty $env:RUN_IN_FOREGROUND '1')
$ENV_PATH          = _IfEmpty $env:ENV_FILE           (Join-Path $PSScriptRoot 'env')
$INSTALL_DEPS      = [int](_IfEmpty $env:INSTALL_DEPS '1')

# ----- Test behavior controls -----------------------------------------------
$SKIP_TESTS        = [int](_IfEmpty $env:SKIP_TESTS '0')           # 1 = skip tests
$PYTEST_ARGS       = _IfEmpty $env:PYTEST_ARGS ''                  # e.g., "tests\test_users.py -k smoke"
$PYTEST_TIMEOUT_S  = [int](_IfEmpty $env:PYTEST_TIMEOUT_S '300')   # hard stop after N seconds
$PYTEST_NOOUTPUT_S = [int](_IfEmpty $env:PYTEST_NOOUTPUT_S '90')   # kill if no output for N seconds

$RUN_DIR = Join-Path $PSScriptRoot '.run'
New-Item -Force -ItemType Directory -Path $RUN_DIR | Out-Null

# ----- Compose helpers --------------------------------------------------------
function Compose([string[]]$args) {
  & docker compose -f $COMPOSE_FILE @args
  if ($LASTEXITCODE -ne 0) {
    & docker-compose -f $COMPOSE_FILE @args
    if ($LASTEXITCODE -ne 0) { Fail "docker compose failed: $($args -join ' ')" }
  }
}
function Compose-IsHealthy {
  $id = (& docker compose -f $COMPOSE_FILE ps -q $PG_CONTAINER).Trim()
  if (-not $id) { $id = (& docker-compose -f $COMPOSE_FILE ps -q $PG_CONTAINER).Trim() }
  if (-not $id) { return $false }
  $h = & docker inspect -f "{{.State.Health.Status}}" $id 2>$null
  return ($LASTEXITCODE -eq 0 -and $h -eq 'healthy')
}
function Wait-DbHealthy([int]$Seconds=60) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Compose-IsHealthy) { return $true }
    $cmd = @('exec','-T','-e',"PGPASSWORD=$PGPASSWORD",$PG_CONTAINER,'psql','-U',$PG_USER,'-d','postgres','-t','-q','-w','-c','select 1')
    & docker compose -f $COMPOSE_FILE @cmd 2>$null; if ($LASTEXITCODE -eq 0) { return $true }
    & docker-compose -f $COMPOSE_FILE @cmd 2>$null; if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

# ----- Python resolution ------------------------------------------------------
$script:PY_CMD = $null  # array like @('py','-3.11') or @('C:\...\python.exe')

function Try-Python {
  param([string[]]$Cmd)
  $head = $Cmd[0]; $tail = @(); if ($Cmd.Count -gt 1) { $tail = $Cmd[1..($Cmd.Count-1)] }
  Write-Host " > $($Cmd -join ' ') -c 'import sys;...'" -ForegroundColor DarkGray
  & $head @($tail + @('-c',"import sys; print('{}.{}'.format(sys.version_info.major, sys.version_info.minor))"))
  if ($LASTEXITCODE -eq 0) { $script:PY_CMD = $Cmd; return $true }
  return $false
}
function Ensure-Python310Plus {
  Trace-Enter $MyInvocation.MyCommand.Name
  Step "STEP 4/5: Python env & deps"

  # Resolve base interpreter (force 3.11)
  $basePy = Resolve-Python311
  Write-Host "Resolved Python: $basePy" -ForegroundColor Cyan

  # Build/repair venv and install deps
  Ensure-Venv
}
function Ensure-Venv1 {
  # Resolve base 3.11 Python and rebuild venv if base changed
  $basePy = Resolve-Python311
  $VENV_PATH = _IfEmpty $env:VENV_PATH '.venv'
  $venvPy = Join-Path $VENV_PATH 'Scripts\python.exe'
  $venvCfg = Join-Path $VENV_PATH 'pyvenv.cfg'

  $needsRebuild = $false
  if (Test-Path $VENV_PATH) {
    try {
      $cfg = Get-Content $venvCfg -ErrorAction Stop
      $homeLine = ($cfg | Where-Object { $_ -match '^\s*home\s*=\s*(.+)$' })
      if ($homeLine) {
        $home = $homeLine -replace '^\s*home\s*=\s*',''
        if (-not (Test-Path $venvPy) -or ($home -ne (Split-Path -Parent $basePy))) {
          $needsRebuild = $true
        }
      } else {
        $needsRebuild = $true
      }
    } catch {
      $needsRebuild = $true
    }
  } else {
    $needsRebuild = $true
  }

  if ($needsRebuild) {
    if (Test-Path $VENV_PATH) { Remove-Item -Recurse -Force $VENV_PATH }
    Write-Host " - creating venv at $VENV_PATH (base: $basePy)"
    & $basePy -m venv $VENV_PATH
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
  } else {
    Write-Host " - venv exists and matches base interpreter."
  }

  $script:PYBIN = $venvPy
  $script:PIP   = Join-Path $VENV_PATH 'Scripts\pip.exe'  # kept for legacy calls elsewhere

  if (-not (Test-Path $script:PYBIN)) { Fail "venv Python not found at '$script:PYBIN'" }

  Write-Host " - venv python: $script:PYBIN"
  Write-Host " - venv pip   : $script:PIP"

  if ($INSTALL_DEPS -eq 1) {
    $timeout = [string]([int](_IfEmpty $env:PIP_DEFAULT_TIMEOUT '60'))
    Write-Host " - upgrading pip/setuptools/wheel (timeout ${timeout}s)"
    & $script:PYBIN -m pip --default-timeout $timeout install --upgrade pip setuptools wheel --no-input
    if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed" }

    $REQ_FILE = _IfEmpty $env:REQ_FILE (Join-Path $PSScriptRoot 'requirements.txt')
    $REQ_DEV_FILE = _IfEmpty $env:REQ_DEV_FILE (Join-Path $PSScriptRoot 'requirements-dev.txt')

    if (Test-Path $REQ_FILE) {
      Write-Host " - pip install -r $REQ_FILE (timeout ${timeout}s)"
      & $script:PYBIN -m pip --default-timeout $timeout install -r $REQ_FILE --no-input
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r $REQ_FILE failed" }
    } else {
      Write-Host " - requirements.txt not found; installing essentials"
      & $script:PYBIN -m pip install uvicorn[standard] fastapi
      if ($LASTEXITCODE -ne 0) { Fail "pip install essentials failed" }
    }

    if (Test-Path $REQ_DEV_FILE) {
      Write-Host " - pip install -r $REQ_DEV_FILE (timeout ${timeout}s)"
      & $script:PYBIN -m pip --default-timeout $timeout install -r $REQ_DEV_FILE --no-input
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r $REQ_DEV_FILE failed" }
    }
  } else {
    Write-Host " - skipping pip install (fast mode)"
  }
}
function Ensure-Pip {
  if (-not $script:PIP -or -not (Test-Path $script:PIP) -or -not $script:PYBIN -or -not (Test-Path $script:PYBIN)) {
    Ensure-Venv
  }
}

# ----- DB tasks ---------------------------------------------------------------
function Ensure-Db {
  Step "STEP 1/5: Docker + DB"
  if (-not (Test-Path $COMPOSE_FILE)) { Fail "compose file missing: $COMPOSE_FILE" }
  Compose @('up','-d','--no-recreate', $PG_CONTAINER) | Out-Null
  if (-not (Wait-DbHealthy -Seconds $PG_READY_TIMEOUT)) {
    Write-Host "Recent DB logs:" -ForegroundColor Yellow
    Compose @('logs','--tail','200', $PG_CONTAINER)
    Fail ("Postgres not healthy within {0}s" -f $PG_READY_TIMEOUT)
  }
  Write-Host " - ensuring database '$PG_DB' exists..."
  $exists = (& docker compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER `
    psql -U $PG_USER -d postgres -t -q -w -c "SELECT 1 FROM pg_database WHERE datname='${PG_DB}';" 2>$null) `
    | ForEach-Object { $_.Trim() } | Select-Object -First 1
  if ($LASTEXITCODE -ne 0 -or $exists -ne '1') {
    & docker compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER `
      psql -U $PG_USER -d postgres -v ON_ERROR_STOP=1 -q -w -c "CREATE DATABASE `"$PG_DB`";"
    if ($LASTEXITCODE -ne 0) {
      & docker-compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER `
        psql -U $PG_USER -d postgres -v ON_ERROR_STOP=1 -q -w -c "CREATE DATABASE `"$PG_DB`";"
      if ($LASTEXITCODE -ne 0) { Fail "CREATE DATABASE $PG_DB failed." }
    }
    Write-Host "   created."
  } else {
    Write-Host "   already present."
  }
}
function Apply-Schema {
  Step "STEP 2/5: Schema"
  if (-not (Test-Path $SCHEMA_FILE)) { Fail "Schema file not found: $SCHEMA_FILE" }
  if ($RESET_PUBLIC -eq 1) { Write-Host " - resetting public schema"; $block = @"
DO \$\$
BEGIN
  EXECUTE 'DROP SCHEMA IF EXISTS public CASCADE';
  EXECUTE 'CREATE SCHEMA public AUTHORIZATION postgres';
END\$\$;
"@; & docker compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER psql -U $PG_USER -d $PG_DB -v ON_ERROR_STOP=1 -w -c $block }
  Write-Host " - applying schema from $SCHEMA_FILE"
  $schemaRaw = Get-Content $SCHEMA_FILE -Raw
  $null = $schemaRaw | & docker compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER psql -U $PG_USER -d $PG_DB -v ON_ERROR_STOP=1 -w -f -
  if ($LASTEXITCODE -ne 0) {
    $null = $schemaRaw | & docker-compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER psql -U $PG_USER -d $PG_DB -v ON_ERROR_STOP=1 -w -f -
    if ($LASTEXITCODE -ne 0) { Fail "Schema apply failed." }
  }
}
function Apply-Seed {
  Step "STEP 3/5: Seed (tolerant)"
  if (-not (Test-Path $SEED_FILE)) { Fail "Seed file not found: $SEED_FILE" }
  $preamble = @'
\set ON_ERROR_STOP 0
\set ON_ERROR_ROLLBACK on
\set ECHO errors
\errverbose
'@
  Write-Host " - applying seed from $SEED_FILE (errors ignored)"
  ($preamble + (Get-Content $SEED_FILE -Raw)) |
    & docker compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER psql -U $PG_USER -d $PG_DB -w -f -
  if ($LASTEXITCODE -ne 0) {
    ($preamble + (Get-Content $SEED_FILE -Raw)) |
      & docker-compose -f $COMPOSE_FILE exec -T -e PGPASSWORD=$PGPASSWORD $PG_CONTAINER psql -U $PG_USER -d $PG_DB -w -f -
  }
  Write-Host " - seeding finished."
}

# ----- Tests: chatty, auto-DB URL, no hang -----------------------------------
function Derive-DatabaseUrl {
  param([string]$ComposePath)
  $PG_USER = _IfEmpty $env:PG_USER 'postgres'
  $PG_PWD  = _IfEmpty $env:PGPASSWORD 'postgres'
  $PG_DB   = _IfEmpty $env:PG_DB 'petcare'
  $PG_HOST = _IfEmpty $env:PG_HOST '127.0.0.1'
  $PG_PORT = $env:PG_PORT

  if (-not $PG_PORT -and (Test-Path $ComposePath)) {
    Step "Detecting Postgres host port from docker compose"
    $portLine = (& docker compose -f $ComposePath port $PG_CONTAINER 5432 2>$null)
    if (-not $portLine) { $portLine = (& docker-compose -f $ComposePath port $PG_CONTAINER 5432 2>$null) }
    if ($portLine -and $portLine -match ':(\d+)\s*$') { $PG_PORT = $Matches[1] }
  }
  if (-not $PG_PORT) { $PG_PORT = 5432 }
  return "postgresql://$PG_USER`:$PG_PWD@$PG_HOST`:$PG_PORT/$PG_DB"
}

function Test-PyModule {
  param([Parameter(Mandatory=$true)][string]$Name)
  try {
    & $script:PYBIN -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$Name') else 1)" 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Run-Tests {
  Step "STEP 5/5: Tests"
  if ($SKIP_TESTS -eq 1) { Write-Host " - SKIP_TESTS=1 set; skipping tests."; return }

  # Ensure venv/python & pip objects exist (this won't reinstall unless missing)
  Ensure-Pip

  # Neutralize env that can confuse Python on Windows
  Remove-Item Env:\PYTHONHOME -ErrorAction SilentlyContinue
  Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
  $env:PYTHONHOME = $null; $env:PYTHONPATH = $null

  $REQ_FILE     = _IfEmpty $env:REQ_FILE     (Join-Path $PSScriptRoot 'requirements.txt')
  $REQ_DEV_FILE = _IfEmpty $env:REQ_DEV_FILE (Join-Path $PSScriptRoot 'requirements-dev.txt')

  # --- Ensure APP deps (fastapi, etc.) if missing ---------------------------
  if (-not (Test-PyModule 'fastapi')) {
    if (Test-Path $REQ_FILE) {
      Write-Host " - installing app deps (requirements.txt)"
      & $script:PYBIN -m pip install -r $REQ_FILE --no-input
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r $REQ_FILE failed" }
    } else {
      Write-Host " - requirements.txt not found; installing essentials (fastapi + uvicorn)"
      & $script:PYBIN -m pip install fastapi uvicorn[standard]
      if ($LASTEXITCODE -ne 0) { Fail "pip install essentials failed" }
    }
  } else {
    Write-Host " - app deps already present" -ForegroundColor DarkGray
  }

  # --- Ensure TEST deps (pytest, etc.) if missing ---------------------------
  if (-not (Test-PyModule 'pytest')) {
    if (Test-Path $REQ_DEV_FILE) {
      Write-Host " - installing test deps (requirements-dev.txt)"
      & $script:PYBIN -m pip install -r $REQ_DEV_FILE --no-input
      if ($LASTEXITCODE -ne 0) { Fail "pip install -r $REQ_DEV_FILE failed" }
    } else {
      Write-Host " - requirements-dev.txt not found; installing pytest basics"
      & $script:PYBIN -m pip install pytest pytest-asyncio pytest-cov
      if ($LASTEXITCODE -ne 0) { Fail "pip install pytest basics failed" }
    }
  } else {
    Write-Host " - pytest already present" -ForegroundColor DarkGray
  }

  # --- DB URL for tests -----------------------------------------------------
  if (-not $env:DATABASE_URL -and -not $env:DATABASE_URL_TEST) {
    $PG_USER = _IfEmpty $env:PG_USER 'postgres'
    $PG_PWD  = _IfEmpty $env:PGPASSWORD 'postgres'
    $PG_DB   = _IfEmpty $env:PG_DB 'petcare'
    $PG_HOST = _IfEmpty $env:PG_HOST '127.0.0.1'
    $PG_PORT = $env:PG_PORT

    if (-not $PG_PORT -and (Test-Path $COMPOSE_FILE)) {
      Step "Detecting Postgres host port from docker compose"
      $portLine = (& docker compose -f $COMPOSE_FILE port $PG_CONTAINER 5432 2>$null)
      if (-not $portLine) { $portLine = (& docker-compose -f $COMPOSE_FILE port $PG_CONTAINER 5432 2>$null) }
      if ($portLine -and $portLine -match ':(\d+)\s*$') { $PG_PORT = $Matches[1] }
    }
    if (-not $PG_PORT) { $PG_PORT = 5432 }

    $env:DATABASE_URL_TEST = "postgresql://$PG_USER`:$PG_PWD@$PG_HOST`:$PG_PORT/$PG_DB"
    Write-Host " - using DATABASE_URL_TEST=$($env:DATABASE_URL_TEST)" -ForegroundColor DarkGray
  } else {
    Write-Host " - DATABASE_URL_TEST already set" -ForegroundColor DarkGray
  }

  # --- Pytest run -----------------------------------------------------------
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
  $env:PYTHONUNBUFFERED = '1'

  $args = @('-m','pytest','-vv','-s','--maxfail=1','-r','a','--color=yes','--durations=10')
  if ($PYTEST_ARGS) { $args += ($PYTEST_ARGS -split '\s+') } else { $args += @('tests') }

  Write-Host " - invoking (live): $script:PYBIN $($args -join ' ')" -ForegroundColor DarkGray
  & $script:PYBIN @args
  $exit = $LASTEXITCODE

  if ($exit -eq 0) { Write-Host " - tests PASSED" } else { Write-Host " - tests FAILED (exit $exit)" -ForegroundColor Yellow }

  Remove-Item Env:\PYTEST_DISABLE_PLUGIN_AUTOLOAD -ErrorAction SilentlyContinue
}



# ----- App run/stop/status ----------------------------------------------------
function Load-AppEnv {
  [CmdletBinding()]
  param(
    # load base first, then overrides
    [string[]] $Paths = @(".env", ".dbstack.env"),
    [switch]   $Quiet
  )

  foreach ($p in $Paths) {
    if (-not (Test-Path -LiteralPath $p)) { continue }

    Get-Content -LiteralPath $p | ForEach-Object {
      $line = $_.Trim()
      if ($line -eq '' -or $line.StartsWith('#')) { return }

      # split on FIRST '=' only
      $parts = $line -split '=', 2
      if ($parts.Count -lt 2) { return }

      $name  = $parts[0].Trim()
      $value = $parts[1].Trim()

      # strip "..." or '...'
      if ( ($value.StartsWith('"') -and $value.EndsWith('"')) -or
           ($value.StartsWith("'") -and $value.EndsWith("'")) ) {
        $value = $value.Substring(1, $value.Length - 2)
      }

      if ($name) {
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
        if (-not $Quiet) { Write-Verbose "ENV: $name=$value (from $p)" }
      }
    }
  }
}





function Run-App {
  param([switch]$Daemon = $false)

  # Load env files into *process* env
  Load-AppEnv   # reads .env then .dbstack.env

  # Bridge env -> script/local vars *if present* (no defaults here)
  $envHost   = [Environment]::GetEnvironmentVariable("APP_HOST",   "Process")
  $envPort   = [Environment]::GetEnvironmentVariable("PORT",       "Process")
  $envImport = [Environment]::GetEnvironmentVariable("APP_IMPORT", "Process")

  if ($envHost)   { $script:APP_HOST   = $envHost }
  if ($envPort)   { $script:PORT       = $envPort }
  if ($envImport) { $script:APP_IMPORT = $envImport }  # e.g. "app.main:app"

  # assume venv is already prepared in STEP 4/5
  if (-not $script:PYBIN -or -not (Test-Path $script:PYBIN)) {
    Fail "venv not ready; run Ensure-Venv first"
  }

  $UVI = Join-Path $VENV_PATH 'Scripts\uvicorn.exe'
  if (-not (Test-Path $UVI)) {
    Write-Host " - uvicorn not found; installing uvicorn[standard]"
    & $script:PYBIN -m pip install uvicorn[standard] | Out-Null
  }

  $LOG = Join-Path $RUN_DIR 'uvicorn.out'
  $ERR = Join-Path $RUN_DIR 'uvicorn.err'
  $appStr = $APP_IMPORT  # e.g., "app.main:app"

  # Build args *conditionally* so uvicorn’s own defaults apply when unset
  $uvArgs = @()
  if ($APP_HOST) { $uvArgs += "--host=$APP_HOST" }
  if ($PORT)     { $uvArgs += "--port=$PORT"     }
  $uvArgs += $appStr

  # For the message only (purely cosmetic)
  $displayHost = if ($APP_HOST) { $APP_HOST } else { "127.0.0.1" }
  $displayPort = if ($PORT)     { $PORT }     else { "8000" }

  if ($Command -eq "fast") {
    $uvArgs += "--reload"
  }

  if ($Daemon) {
    Write-Host (" - starting app (daemon) on http://{0}:{1}" -f $displayHost, $displayPort)
    Start-Job -Name 'app-job' -ScriptBlock {
      param($UVI,$argsArray,$LOG,$ERR)
      & $UVI @argsArray 1>$LOG 2>$ERR
    } -ArgumentList $UVI,$uvArgs,$LOG,$ERR | Out-Null
    Write-Host " - app started (job: app-job)"
  } else {
    Write-Host (" - starting app (foreground) on http://{0}:{1}" -f $displayHost, $displayPort)
    & $UVI @uvArgs
  }
}





function Show-Status {
  $job = Get-Job -Name 'app-job' -ErrorAction SilentlyContinue
  if ($job -and $job.State -eq 'Running') { Write-Host "App job is running." }
  else { Write-Host "App job is not running." }
}


function Stop-App {
  $job = Get-Job -Name 'app-job' -ErrorAction SilentlyContinue
  if ($job) { Stop-Job -Job $job | Out-Null; Remove-Job -Job $job | Out-Null; Write-Host "Stopped."; return }
  Write-Host "No running app job found."
}

# ----- Doctor (health + auth paths) ------------------------------------------
function Doctor {
  Write-Host "=== Doctor ==="
  try {
    $spec = Invoke-RestMethod ("http://127.0.0.1:{0}/openapi.json" -f $PORT)
    $paths = $spec.paths.PSObject.Properties.Name | Sort-Object
    Write-Host "OpenAPI paths (subset):"
    $paths | Where-Object { $_ -match '/api/v1/(health|auth)' } | ForEach-Object { " - $_" }
  } catch { Write-Host "Cannot fetch openapi.json: $($_.Exception.Message)" -ForegroundColor Yellow }
  try {
    $health = Invoke-RestMethod ("http://127.0.0.1:{0}/api/v1/health" -f $PORT)
    Write-Host "Health: $(($health|ConvertTo-Json))"
  } catch { Write-Host "Health check failed: $($_.Exception.Message)" -ForegroundColor Yellow }
}

# ----- UI helpers (optional) --------------------------------------------------
function Ui-Start {
  if (-not $UI_DIR) { Fail "UI_DIR not set" }
  $args = @('run','--','web','--port',$UI_PORT)
  Write-Host " - starting UI (Expo web) at http://127.0.0.1:$UI_PORT"
  Push-Location $UI_DIR; try { npm @args } finally { Pop-Location }
}
function Ui-Stop {
  Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*node*" } | Stop-Process -Force
  Write-Host " - stopped UI (best effort)"
}

# ----- CLI dispatcher ---------------------------------------------------------
switch ($Command) {
  'help'         {
    @"
Usage: .\run-stack.ps1 <command>

Env vars you can use:
  SKIP_TESTS=1            -> skip pytest step entirely
  PYTEST_ARGS="..."        -> pass extra args (e.g., tests\test_db_smoke.py -k smoke)
  PYTEST_NOOUTPUT_S=90     -> kill pytest if no output for N seconds (default 90)
  PYTEST_TIMEOUT_S=300     -> hard kill after N seconds (default 300)

Commands:
  help            - show this help
  fast            - DB up -> schema -> seed -> venv+deps -> tests -> start app (daemon)
  full            - DB up -> schema -> seed -> venv+deps -> tests -> start app (daemon)
  schema          - DB up -> schema
  schema_seed     - DB up -> schema -> seed
  seed            - DB up -> seed
  seed-run        - DB up -> seed -> deps (skip install) -> start app (daemon)
  tests           - DB up -> deps (skip install) -> pytest
  start           - DB up -> deps (skip install) -> start app (daemon)
  status          - show app status
  logs            - tail app logs
  stop            - stop app
  info            - print config
  start-docker    - compose up -d (all services)
  stop-docker     - compose down
  doctor          - print health + list important OpenAPI paths
  ui-start        - start Expo web (requires UI_DIR)
  ui-stop         - stop Expo web job
"@ | Write-Host; break }

  'fast'         { Write-Host "MODE: fast";   $INSTALL_DEPS=0; Ensure-Db; Ensure-Venv; Run-App }
  'full'         { Write-Host "MODE: full";   Ensure-Db; Apply-Schema; Apply-Seed; Ensure-Venv; Run-Tests; $INSTALL_DEPS=0; Run-App }
  'schema'       { Ensure-Db; Apply-Schema }
  'schema_seed'  { Ensure-Db; Apply-Schema; Apply-Seed }
  'seed'         { Ensure-Db; Apply-Seed }
  'seed-run'     { Ensure-Db; Apply-Seed; $INSTALL_DEPS=0; Ensure-Venv; if ($RUN_IN_FOREGROUND -eq 1){ Run-App } else { Run-App -Daemon } }
  'tests'        { Ensure-Db; $INSTALL_DEPS=0; Ensure-Venv; Run-Tests }
  'start'        { Ensure-Db; $INSTALL_DEPS=0; Ensure-Venv; if ($RUN_IN_FOREGROUND -eq 1){ Run-App } else { Run-App -Daemon } }
  'status'       { Show-Status }
  'logs'         { $LOG = Join-Path $RUN_DIR 'uvicorn.out'; if (Test-Path $LOG) { Get-Content $LOG -Wait } else { Write-Host "No logs at $LOG" } }
  'stop'         { Stop-App }
  'info'         {
                    Write-Host "COMPOSE_FILE : $COMPOSE_FILE"
                    Write-Host "PG_CONTAINER : $PG_CONTAINER"
                    Write-Host "PG_DB        : $PG_DB"
                    Write-Host "APP_IMPORT   : $APP_IMPORT"
                    Write-Host ("HOST:PORT    : {0}:{1}" -f $APP_HOST,$PORT)
                    Write-Host "VENV_PATH    : $VENV_PATH"
                    if ($UI_DIR) { Write-Host ("UI_DIR       : {0} (port {1})" -f $UI_DIR,$UI_PORT) }
                 }
  'start-docker' { Compose @('up','-d') }
  'stop-docker'  { Compose @('down','-v') }
  'doctor'       { Doctor }
  'ui-start'     { Ui-Start }
  'ui-stop'      { Ui-Stop }
  'full-daemon'  { Write-Host "MODE: full-daemon"; Ensure-Db; Apply-Schema; Apply-Seed; Ensure-Venv; Run-Tests; $INSTALL_DEPS=0; Run-App -Daemon }
}
