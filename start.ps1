<#
.SYNOPSIS
    RailPulse OSS — one-click bootstrap and run script.

.DESCRIPTION
    This script:
      1. Creates a Python virtual environment (if missing).
      2. Installs all pip dependencies.
      3. Copies .env.example → .env (if .env does not exist).
      4. Starts PostgreSQL and Ollama via Docker Compose.
      5. Waits for PostgreSQL to be healthy.
      6. Pulls required Ollama models (llama3.1:8b + nomic-embed-text).
      7. Starts the FastAPI backend (uvicorn).
      8. Starts the sensor simulator.
      9. Opens the Swagger UI in the default browser.

    Press Ctrl+C to stop everything gracefully.

.NOTES
    Prerequisites:
      - Python 3.10+
      - Docker Desktop (running)
      - Ollama installed locally OR use the Compose Ollama service
#>

param(
    [switch]$SkipDocker,       # Skip Docker Compose steps (if services are already running)
    [switch]$SkipOllamaModels  # Skip model pulls (if already downloaded)
)

$ErrorActionPreference = "Stop"

# ── Paths ────────────────────────────────────────────────────────────────
$ProjectRoot = $PSScriptRoot
$VenvDir     = Join-Path $ProjectRoot ".venv"
$PythonExe   = Join-Path $VenvDir "Scripts\python.exe"
$PipExe      = Join-Path $VenvDir "Scripts\pip.exe"
$EnvFile     = Join-Path $ProjectRoot ".env"
$EnvExample  = Join-Path $ProjectRoot ".env.example"

# -- Helpers ---------------------------------------------------------------
function Write-Step  { param($msg) Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red }

# -- Banner ----------------------------------------------------------------
Write-Host @'

  +=================================================+
  |         RailPulse OSS  -  Start Script           |
  |  Railway telemetry + anomaly detection + LLM QA  |
  +=================================================+

'@ -ForegroundColor Magenta

# ══════════════════════════════════════════════════════════════════════════
# Pre-flight checks
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Pre-flight checks...'

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Fail "python not found. Install Python 3.10+ from https://python.org"
    exit 1
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Fail "docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    exit 1
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Fail "ollama not found. Install Ollama from https://ollama.com/download"
    exit 1
}
Write-OK "python, docker, ollama all found"

# ══════════════════════════════════════════════════════════════════════════
# 1. Virtual environment
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Checking Python virtual environment...'

if (-not (Test-Path $PythonExe)) {
    Write-Warn "No venv found - creating one at $VenvDir"
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to create venv"; exit 1 }
}
Write-OK "venv ready ($VenvDir)"

# ══════════════════════════════════════════════════════════════════════════
# 2. Install dependencies
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Installing Python dependencies...'
& $PythonExe -m pip install --quiet --upgrade pip 2>$null
& $PipExe install --quiet -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install failed"; exit 1 }
Write-OK "All dependencies installed"

# ══════════════════════════════════════════════════════════════════════════
# 3. .env file
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Checking .env file...'

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-OK "Created .env from .env.example"
} else {
    Write-OK ".env already exists"
}

# ══════════════════════════════════════════════════════════════════════════
# 4. Docker Compose (PostgreSQL only)
# ══════════════════════════════════════════════════════════════════════════
if (-not $SkipDocker) {
    Write-Step 'Starting Docker services (postgres)...'

    # Check Docker is running (tolerate harmless stderr warnings)
    try {
        $dockerOut = docker info 2>&1
    } catch {
        $dockerOut = $_.Exception.Message
    }
    $dockerOk = ($LASTEXITCODE -eq 0) -or ($dockerOut -match "WARNING")

    if (-not $dockerOk) {
        Write-Fail "Docker is not running. Please start Docker Desktop and try again."
        Write-Warn "Or re-run with -SkipDocker if services are already running."
        exit 1
    }
    Write-OK "Docker daemon: running"

    Push-Location $ProjectRoot
    docker compose up -d postgres
    Pop-Location

    if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed"; exit 1 }

    # Wait for PostgreSQL health check
    Write-Step 'Waiting for PostgreSQL to be healthy...'
    $maxWait = 60
    $waited  = 0
    while ($waited -lt $maxWait) {
        $health = docker inspect --format="{{.State.Health.Status}}" railpulse_postgres 2>$null
        if ($health -eq "healthy") { break }
        Start-Sleep -Seconds 2
        $waited += 2
        Write-Host "." -NoNewline
    }
    Write-Host ""

    if ($waited -ge $maxWait) {
        Write-Fail "PostgreSQL did not become healthy within ${maxWait}s"
        exit 1
    }
    Write-OK "PostgreSQL is healthy"
} else {
    Write-Warn 'Skipping Docker (-SkipDocker flag)'
}

# ══════════════════════════════════════════════════════════════════════════
# 5. Ollama (local, same approach as AutoResearcher)
# ══════════════════════════════════════════════════════════════════════════
if (-not $SkipOllamaModels) {
    Write-Step 'Setting up Ollama...'

    # Check if Ollama is already running, if not start it
    try {
        Invoke-WebRequest "http://localhost:11434" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop *> $null
        Write-OK "Ollama already running"
    }
    catch {
        Write-Warn "Ollama not running, starting it..."
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
        Write-OK "Ollama started"
    }

    # Pull required models using CLI (same as AutoResearcher)
    foreach ($model in @("llama3.2", "nomic-embed-text")) {
        $pulled = ollama list 2>$null | Select-String $model
        if (-not $pulled) {
            Write-Host "  Pulling $model (this may take a few minutes)..." -ForegroundColor DarkGray
            ollama pull $model
            Write-OK "$model ready"
        } else {
            Write-OK "$model already present"
        }
    }
} else {
    Write-Warn 'Skipping Ollama setup (-SkipOllamaModels flag)'
}

# ══════════════════════════════════════════════════════════════════════════
# 6. Start FastAPI backend
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Starting FastAPI backend...'

$apiJob = Start-Job -ScriptBlock {
    param($py, $root)
    Set-Location $root
    & $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload 2>&1
} -ArgumentList $PythonExe, $ProjectRoot

Write-OK "API server starting (job $($apiJob.Id)) - http://localhost:8000"

# Wait a few seconds for the server to initialise
Start-Sleep -Seconds 5

# Quick health check
$apiHealthy = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $apiHealthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}

if ($apiHealthy) {
    Write-OK "API health check passed"
} else {
    Write-Warn 'API did not respond to /health - it may still be starting. Check logs below.'
    Receive-Job $apiJob -ErrorAction SilentlyContinue | Write-Host -ForegroundColor DarkGray
}

# ══════════════════════════════════════════════════════════════════════════
# 7. Start sensor simulator
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Starting sensor simulator...'

$simJob = Start-Job -ScriptBlock {
    param($py, $root)
    Set-Location $root
    & $py -m simulator.sensor_stream 2>&1
} -ArgumentList $PythonExe, $ProjectRoot

Write-OK "Simulator started (job $($simJob.Id)) - publishing to http://localhost:8000/telemetry/ingest"

# ══════════════════════════════════════════════════════════════════════════
# 8. Open browser
# ══════════════════════════════════════════════════════════════════════════
Write-Step 'Opening Swagger UI...'
Start-Process "http://localhost:8000/docs"

# ══════════════════════════════════════════════════════════════════════════
# 9. Tail logs until Ctrl+C
# ══════════════════════════════════════════════════════════════════════════
Write-Host @'

  +=================================================+
  |   RailPulse is running!                          |
  |                                                  |
  |   API:       http://localhost:8000                |
  |   Swagger:   http://localhost:8000/docs           |
  |   ReDoc:     http://localhost:8000/redoc          |
  |                                                  |
  |   Press Ctrl+C to stop all services.             |
  +=================================================+

'@ -ForegroundColor Green

try {
    while ($true) {
        # Print any new output from the API and simulator jobs
        $apiOutput = Receive-Job $apiJob -ErrorAction SilentlyContinue
        if ($apiOutput) { $apiOutput | ForEach-Object { Write-Host "[API] $_" -ForegroundColor DarkCyan } }

        $simOutput = Receive-Job $simJob -ErrorAction SilentlyContinue
        if ($simOutput) { $simOutput | ForEach-Object { Write-Host "[SIM] $_" -ForegroundColor DarkYellow } }

        # Check if jobs died
        if ($apiJob.State -eq "Failed") {
            Write-Fail "API job failed!"
            Receive-Job $apiJob | Write-Host -ForegroundColor Red
            break
        }

        Start-Sleep -Seconds 2
    }
} finally {
    # ── Cleanup ──────────────────────────────────────────────────────────
    Write-Host "`nShutting down..." -ForegroundColor Yellow
    Stop-Job $apiJob -ErrorAction SilentlyContinue
    Stop-Job $simJob -ErrorAction SilentlyContinue
    Remove-Job $apiJob -Force -ErrorAction SilentlyContinue
    Remove-Job $simJob -Force -ErrorAction SilentlyContinue
    Write-OK "All processes stopped."
}
