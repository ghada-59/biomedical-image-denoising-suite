# Development helper for Windows: start, stop or check the API (port 8000) and the dashboard (port 5173).
#   .\dev.cmd start [-NoBrowser]   start the API, wait until its health check answers, start the dashboard, check the connection between them, open the browser
#   .\dev.cmd stop [-DryRun]       stop only this project's API and dashboard (a program that listens on port 8000/5173 AND is uvicorn api:app / the Vite server),
#                                and the console windows this helper opened; -DryRun lists what would be stopped
#   .\dev.cmd status               show what listens, which Python is used and whether every address answers (a diagnosis, nothing is changed)
# Each service runs in its own visible window, so a startup error is never hidden. Nothing is installed except `npm ci` when node_modules is missing.
param(
    [Parameter(Position = 0)][ValidateSet('start', 'stop', 'status')][string]$Action = 'start',
    [switch]$NoBrowser,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$apiPort = 8000
$webPort = 5173
$apiUrl = "http://127.0.0.1:$apiPort"
$webUrl = "http://127.0.0.1:$webPort"
$runDir = 'docs/results/benchmark_v2_methods_2026-10-25'      # the recorded benchmark run that ships with the repository

function Write-Step($text) { Write-Host "[dev] $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "[ ok] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "[warn] $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "[FAIL] $text" -ForegroundColor Red; exit 1 }

function Get-Json($url, $timeout = 4) {
    try { return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeout).Content | ConvertFrom-Json } catch { return $null }
}

function Get-StatusCode($url) {
    try { return [int](Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4).StatusCode }
    catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return $null
    }
}

function Resolve-Python {
    if ($env:DENOISING_PYTHON) {
        if (-not (Test-Path $env:DENOISING_PYTHON)) { Fail "DENOISING_PYTHON points to a file that does not exist: $env:DENOISING_PYTHON" }
        return $env:DENOISING_PYTHON
    }
    $venv = Join-Path $backend '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    Fail "No Python found. Create the environment described in the README (backend\.venv), activate your Conda environment, or set DENOISING_PYTHON."
}

function Get-Listener($port) {
    return @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

function Get-OwnedProcess($processId) {
    return Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
}

# A process belongs to this project only if it LISTENS on one of its ports AND is the right program running the right module.
# Matching text in command lines is not enough: other tools (shells, editors) can contain the same words.
function Test-ProjectApi($process) { return ($process -and $process.Name -match '^pythonw?\.exe$' -and $process.CommandLine -match 'uvicorn\s+api:app') }
function Test-ProjectDashboard($process) { return ($process -and $process.Name -eq 'node.exe' -and $process.CommandLine -match 'vite[\\/]bin[\\/]vite\.js') }

function Get-ProjectProcesses {
    $found = @{}
    foreach ($port in @($apiPort, $webPort)) {
        foreach ($listener in (Get-Listener $port)) {
            $process = Get-OwnedProcess $listener.OwningProcess
            if ((Test-ProjectApi $process) -or (Test-ProjectDashboard $process)) {
                $found[[int]$process.ProcessId] = $process
                # the npm wrapper (node running npm-cli.js) that started the dashboard server; never a user's own shell
                $parent = Get-OwnedProcess $process.ParentProcessId
                if ($parent -and $parent.Name -eq 'node.exe' -and $parent.CommandLine -match 'npm-cli\.js') { $found[[int]$parent.ProcessId] = $parent }
            }
        }
    }
    # the console windows this helper opened (their command line starts with the title it sets)
    foreach ($window in (Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue)) {
        if ($window.CommandLine -match 'title Denoising (API|dashboard) &') { $found[[int]$window.ProcessId] = $window }
    }
    return @($found.Values)
}

function Describe-Owner($port) {
    foreach ($listener in (Get-Listener $port)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process) { return "process $($process.ProcessId) ($($process.Name)): $($process.CommandLine)" }
    }
    return 'unknown process'
}

function Show-Status {
    $python = Resolve-Python
    Write-Step "Python used for the API: $python"
    foreach ($entry in @(@('API', $apiPort), @('dashboard', $webPort))) {
        $listeners = Get-Listener $entry[1]
        if ($listeners.Count -eq 0) { Write-Warn "$($entry[0]): nothing is listening on port $($entry[1])" }
        else { Write-Ok "$($entry[0]): listening on $((($listeners | ForEach-Object { $_.LocalAddress + ':' + $_.LocalPort }) -join ', '))  <- $(Describe-Owner $entry[1])" }
    }
    $good = $true
    foreach ($url in @("$apiUrl/api/health", "http://localhost:$apiPort/api/health", "$webUrl/api/health", "http://localhost:$webPort/api/health")) {
        $body = Get-Json $url
        if ($body -and $body.status -eq 'ok') { Write-Ok "$url -> ok" }
        else { Write-Warn "$url -> no valid answer (status $(Get-StatusCode $url))"; $good = $false }
    }
    $health = Get-Json "$apiUrl/api/health"
    if ($health -and $health.problems -and $health.problems.Count -gt 0) { foreach ($problem in $health.problems) { Write-Warn "API reports: $problem" } }
    $page = Get-StatusCode "$webUrl/"
    if ($page -eq 200) { Write-Ok "$webUrl/ -> the dashboard page is served" } else { Write-Warn "$webUrl/ -> $page"; $good = $false }
    if (-not $good) { Write-Host "[dev] Something is not answering. Start it with: .\dev.cmd start   (the README, section 'If the dashboard shows an error', explains each message)" }
    return $good
}

function Wait-For($url, $seconds, $test) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $body = Get-Json $url 3
        if ($body -and (& $test $body)) { return $body }
        Start-Sleep -Milliseconds 700
    }
    return $null
}

function Start-Window($title, $workingDirectory, $command) {
    $line = "title $title & cd /d `"$workingDirectory`" & $command"
    Start-Process -FilePath 'cmd.exe' -ArgumentList @('/k', "`"$line`"") | Out-Null
}

if ($Action -eq 'status') {
    if (Show-Status) { exit 0 } else { exit 1 }
}

if ($Action -eq 'stop') {
    $targets = Get-ProjectProcesses
    if ($targets.Count -eq 0) { Write-Ok "No API or dashboard of this project is running (nothing listens on $apiPort or $webPort as this project's programs)."; }
    foreach ($target in $targets) {
        $text = "$($target.Name) $($target.ProcessId): $($target.CommandLine)"
        if ($text.Length -gt 170) { $text = $text.Substring(0, 170) + '...' }
        if ($DryRun) { Write-Step "Would stop $text" } else { Write-Step "Stopping $text"; Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue }
    }
    if ($DryRun) { exit 0 }
    Start-Sleep -Seconds 1
    $left = 0
    foreach ($port in @($apiPort, $webPort)) {
        if ((Get-Listener $port).Count -gt 0) { Write-Warn "Port $port is still in use by $(Describe-Owner $port) - it is not this project's API or dashboard, so it was left alone."; $left++ }
        else { Write-Ok "Port $port is free." }
    }
    if ($left -gt 0) { exit 1 } else { exit 0 }
}

# ---- start ----
$python = Resolve-Python
Write-Step "Python: $python"
& $python -c "import fastapi, uvicorn, multipart, cv2, skimage, pandas, pydicom, plotly, PIL, scipy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "The Python environment above lacks packages the API needs. Install them with:`n    `"$python`" -m pip install -r `"$backend\requirements-api.txt`""
}
& $python -c "import pywt" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Warn "PyWavelets is not installed: the API will run, the wavelet method will be marked unavailable. Fix: `"$python`" -m pip install -r `"$backend\requirements-api.txt`"" }
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Node.js was not found. Install Node.js 22.12 or newer from https://nodejs.org/ and open a new terminal." }
$nodeVersion = [version]((& node --version).TrimStart('v'))
if ($nodeVersion -lt [version]'22.12') { Fail "Node.js $nodeVersion is too old; version 22.12 or newer is required (frontend/package.json)." }

# 1. API
$health = Get-Json "$apiUrl/api/health"
if ($health -and $health.status -eq 'ok') { Write-Ok "The API already answers on $apiUrl - reusing it." }
else {
    if ((Get-Listener $apiPort).Count -gt 0) { Fail "Port $apiPort is in use by something that is not this API: $(Describe-Owner $apiPort)`n    Stop it, or run: .\dev.cmd stop" }
    Write-Step "Starting the API in its own window ($apiUrl)"
    if (-not $env:BENCHMARK_RUN_DIRS) { $env:BENCHMARK_RUN_DIRS = $runDir }
    Start-Window 'Denoising API' $backend "`"$python`" -m uvicorn api:app --host 127.0.0.1 --port $apiPort"
    $health = Wait-For "$apiUrl/api/health" 90 { param($b) $b.status -eq 'ok' }
    if (-not $health) { Fail "The API did not answer $apiUrl/api/health within 90 seconds. Read the error in the 'Denoising API' window." }
    Write-Ok "The API is ready (version $($health.version))."
}
foreach ($problem in @($health.problems)) { if ($problem) { Write-Warn "API reports: $problem" } }

# 2. dashboard (started only now, so its first requests find a ready backend)
$page = Get-StatusCode "$webUrl/"
if ($page -eq 200) { Write-Ok "The dashboard already answers on $webUrl - reusing it." }
else {
    if ((Get-Listener $webPort).Count -gt 0) { Fail "Port $webPort is in use by something that does not serve the dashboard: $(Describe-Owner $webPort)`n    Stop it, or run: .\dev.cmd stop" }
    if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
        Write-Step "node_modules is missing: running npm ci (once)"
        Push-Location $frontend
        try { & npm ci; if ($LASTEXITCODE -ne 0) { Fail "npm ci failed (see the messages above)." } } finally { Pop-Location }
    }
    Write-Step "Starting the dashboard in its own window ($webUrl)"
    Start-Window 'Denoising dashboard' $frontend 'npm run dev'
    $seen = Wait-For "$webUrl/api/health" 90 { param($b) $b.status -eq 'ok' }
    if (-not $seen) { Fail "The dashboard did not forward $webUrl/api/health to the API within 90 seconds. Read the 'Denoising dashboard' window; run: .\dev.cmd status" }
}

# 3. the connection that matters: browser address -> dashboard -> proxy -> API
$through = Get-Json "$webUrl/api/health"
if (-not ($through -and $through.status -eq 'ok')) { Fail "The dashboard is up but its /api forwarding does not reach the API. Run: .\dev.cmd status" }
Write-Ok "Dashboard -> API connection verified through $webUrl/api/health"
Write-Host ""
Write-Host "  Dashboard : $webUrl/" -ForegroundColor White
Write-Host "  API       : $apiUrl/  (interactive documentation: $apiUrl/docs)" -ForegroundColor White
Write-Host "  Stop both : .\dev.cmd stop      Check: .\dev.cmd status" -ForegroundColor White
Write-Host ""
if (-not $NoBrowser) { Start-Process $webUrl }
exit 0
