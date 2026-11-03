# Development helper for Windows: start, stop or check the API (port 8000) and the dashboard (port 5173).
#   .\dev.cmd start [-NoBrowser]   start the API in the background, wait until its health check answers, start the dashboard, check the connection
#                                  between them, open the browser. Both keep running when the window that ran this command is closed.
#   .\dev.cmd stop [-DryRun]       stop only this project's API and dashboard (a program that listens on port 8000/5173 AND is uvicorn api:app / the Vite
#                                  server AND does not belong to another copy of the project); -DryRun lists what would be stopped
#   .\dev.cmd status               show what listens, which Python is used and whether every address answers (a diagnosis, nothing is changed)
# The services run without any console window, so no window can be closed by mistake; their output goes to logs\dev\api.log and dashboard.log, and the
# last lines are printed when a start fails. Nothing is installed except `npm ci` when node_modules is missing.
param(
    [Parameter(Position = 0)][ValidateSet('start', 'stop', 'status')][string]$Action = 'start',
    [switch]$NoBrowser,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$logDir = Join-Path $root 'logs\dev'
$apiLog = Join-Path $logDir 'api.log'
$webLog = Join-Path $logDir 'dashboard.log'
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

# A failing command (an import that raises, npm printing a warning) writes to stderr. With $ErrorActionPreference = 'Stop', Windows PowerShell 5.1
# turns that into a terminating NativeCommandError (even with 2>$null) and the script dies with a stack trace instead of its own message,
# so native commands run with 'Continue'.
function Test-PythonImport($python, $modules) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $null = & $python -c "import $modules" 2>&1; return ($LASTEXITCODE -eq 0) }
    finally { $ErrorActionPreference = $previous }
}
$requiredModules = 'fastapi, uvicorn, multipart, cv2, skimage, pandas, pydicom, plotly, PIL, scipy'

# Reports what is missing in the chosen Python; returns $false when a package the API cannot start without is missing.
function Test-Packages($python) {
    $installHint = "`"$python`" -m pip install -r `"$backend\requirements-api.txt`""
    $ready = Test-PythonImport $python $requiredModules
    if (-not $ready) { Write-Warn "The Python above lacks packages the API needs. Install them with:`n    $installHint" }
    if (-not (Test-PythonImport $python 'pywt')) { Write-Warn "PyWavelets is not installed: the API will run, the wavelet method will be marked unavailable. Fix: $installHint" }
    return $ready
}

# The comma keeps a single listener an array: without it PowerShell hands back the bare CimInstance, which has no Count, so `.Count -gt 0` was
# false for a port with exactly one listener and the helper reported a port in use as free.
function Get-Listener($port) {
    return , @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

function Get-OwnedProcess($processId) {
    return Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
}

# A process belongs to this project only if it LISTENS on one of its ports AND is the right program running the right module.
# Matching text in command lines is not enough: other tools (shells, editors) can contain the same words.
function Test-ProjectApi($process) { return ($process -and $process.Name -match '^pythonw?\.exe$' -and $process.CommandLine -match 'uvicorn\s+api:app') }
function Test-ProjectDashboard($process) { return ($process -and $process.Name -eq 'node.exe' -and $process.CommandLine -match 'vite[\\/]bin[\\/]vite\.js') }

# Another copy (clone) of the project can run on the same ports. When the command line names the folder it runs from and that is not this
# copy, the folder is returned and the process is left alone. A command line without such a folder (started by hand) is taken as this copy's.
function Get-OtherCopy($process) {
    $text = [string]$process.CommandLine
    if ($process.Name -eq 'node.exe' -and $text -match '"([A-Za-z]:\\[^"]*?)\\node_modules\\') { if ($Matches[1] -ne $frontend) { return $Matches[1] } }
    if ($process.Name -match '^pythonw?\.exe$' -and $text -match '--app-dir\s+"([^"]+)"') { if ($Matches[1] -ne $backend) { return $Matches[1] } }
    return $null
}

# The programs that start a service and wait for it: the venv launcher of python, npm and the shells around them.
function Test-LauncherParent($process) {
    if (-not $process) { return $false }
    if (Test-ProjectApi $process) { return $true }
    $text = [string]$process.CommandLine
    if ($process.Name -eq 'node.exe' -and $text -match 'npm-cli\.js') { return $true }
    if ($process.Name -eq 'cmd.exe' -and ($text -match '/d /s /c vite' -or $text.Contains($logDir))) { return $true }
    return $false
}

# Returns the processes to stop. Services of another copy of the project are not returned; they are listed in $script:otherCopies.
function Get-ProjectProcesses {
    $found = @{}
    $script:otherCopies = @()
    foreach ($port in @($apiPort, $webPort)) {
        foreach ($listener in (Get-Listener $port)) {
            $process = Get-OwnedProcess $listener.OwningProcess
            if (-not ((Test-ProjectApi $process) -or (Test-ProjectDashboard $process))) { continue }
            $other = Get-OtherCopy $process
            if ($other) { $script:otherCopies += "port $port (process $($process.ProcessId)) runs from $other"; continue }
            $found[[int]$process.ProcessId] = $process
            $current = $process
            for ($level = 0; $level -lt 5; $level++) {
                $parent = Get-OwnedProcess $current.ParentProcessId
                if (-not (Test-LauncherParent $parent)) { break }
                $found[[int]$parent.ProcessId] = $parent
                $current = $parent
            }
        }
    }
    # shells left by an earlier version of this helper, which opened a titled console window per service
    foreach ($window in (Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue)) {
        $text = [string]$window.CommandLine
        if ($text -match 'title Denoising (API|dashboard) &' -and ($text.Contains($backend) -or $text.Contains($frontend))) { $found[[int]$window.ProcessId] = $window }
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
    $packagesOk = Test-Packages $python
    $null = Get-ProjectProcesses
    foreach ($entry in @(@('API', $apiPort), @('dashboard', $webPort))) {
        $listeners = Get-Listener $entry[1]
        if ($listeners.Count -eq 0) { Write-Warn "$($entry[0]): nothing is listening on port $($entry[1])" }
        else { Write-Ok "$($entry[0]): listening on $((($listeners | ForEach-Object { $_.LocalAddress + ':' + $_.LocalPort }) -join ', '))  <- $(Describe-Owner $entry[1])" }
    }
    foreach ($note in $script:otherCopies) { Write-Warn "Another copy of the project is running: $note. Run .\dev.cmd stop in that folder." }
    $good = $packagesOk
    foreach ($url in @("$apiUrl/api/health", "http://localhost:$apiPort/api/health", "$webUrl/api/health", "http://localhost:$webPort/api/health")) {
        $body = Get-Json $url
        if ($body -and $body.status -eq 'ok') { Write-Ok "$url -> ok" }
        else { Write-Warn "$url -> no valid answer (status $(Get-StatusCode $url))"; $good = $false }
    }
    $health = Get-Json "$apiUrl/api/health"
    if ($health -and $health.problems -and $health.problems.Count -gt 0) { foreach ($problem in $health.problems) { Write-Warn "API reports: $problem" } }
    $page = Get-StatusCode "$webUrl/"
    if ($page -eq 200) { Write-Ok "$webUrl/ -> the dashboard page is served" } else { Write-Warn "$webUrl/ -> $page"; $good = $false }
    foreach ($log in @($apiLog, $webLog)) { if (Test-Path $log) { Write-Step "Log: $log" } }
    if (-not $good) { Write-Host "[dev] Something is not answering. Start it with: .\dev.cmd start   (the README, section 'If the dashboard shows an error', explains each message)" }
    return $good
}

function Wait-For($url, $seconds, $test, $process = $null) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $body = Get-Json $url 3
        if ($body -and (& $test $body)) { return $body }
        if ($process -and $process.HasExited) { return $null }      # the service already ended: no reason to wait on
        Start-Sleep -Milliseconds 700
    }
    return $null
}

function Show-LogTail($file) {
    if (Test-Path $file) {
        Write-Host "---- last lines of $file ----"
        Get-Content $file -Tail 25 | ForEach-Object { Write-Host "    $_" }
        Write-Host "----"
    } else { Write-Warn "No log was written ($file)." }
}

# Starts a service in a console of its own that has no window, so it belongs to no terminal: closing the window that ran this helper
# (or any other) leaves it running. cmd only redirects the service's output to a log file; the previous log is kept as *.previous.log.
#
# CreateProcess is called directly, with handle inheritance off: System.Diagnostics.Process always inherits every inheritable handle of this
# window, and a service holding this window's output pipe (`.\dev.cmd start | more`, a CI log, a tool that captures output) keeps that pipe open
# for as long as it runs, so the helper would seem to hang. CREATE_NO_WINDOW gives the service a console without a window.
function Start-Detached($workingDirectory, $command, $logFile) {
    New-Item -ItemType Directory -Force $logDir | Out-Null
    if (Test-Path $logFile) { Move-Item -Force $logFile ([System.IO.Path]::ChangeExtension($logFile, 'previous.log')) }
    if (-not ('DevLauncher' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class DevLauncher {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO {
        public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2; public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct PROCESS_INFORMATION { public IntPtr hProcess; public IntPtr hThread; public int dwProcessId; public int dwThreadId; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateProcessW(string application, string commandLine, IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles,
        uint creationFlags, IntPtr environment, string currentDirectory, ref STARTUPINFO startup, out PROCESS_INFORMATION information);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    public static int Start(string commandLine, string workingDirectory) {
        var startup = new STARTUPINFO(); startup.cb = Marshal.SizeOf(typeof(STARTUPINFO));
        PROCESS_INFORMATION information;
        if (!CreateProcessW(null, commandLine, IntPtr.Zero, IntPtr.Zero, false, 0x08000000, IntPtr.Zero, workingDirectory, ref startup, out information))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        CloseHandle(information.hThread); CloseHandle(information.hProcess);
        return information.dwProcessId;
    }
}
'@
    }
    $line = "`"$env:ComSpec`" /c `"$command > `"$logFile`" 2>&1`""
    return Get-Process -Id ([DevLauncher]::Start($line, $workingDirectory))
}

if ($Action -eq 'status') {
    if (Show-Status) { exit 0 } else { exit 1 }
}

if ($Action -eq 'stop') {
    $targets = Get-ProjectProcesses
    if ($targets.Count -eq 0) { Write-Ok "No API or dashboard of this project is running (nothing listens on $apiPort or $webPort as this project's programs)." }
    foreach ($target in $targets) {
        $text = "$($target.Name) $($target.ProcessId): $($target.CommandLine)"
        if ($text.Length -gt 170) { $text = $text.Substring(0, 170) + '...' }
        if ($DryRun) { Write-Step "Would stop $text" } else { Write-Step "Stopping $text"; Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue }
    }
    foreach ($note in $script:otherCopies) { Write-Warn "Left alone, it belongs to another copy of the project: $note. Run .\dev.cmd stop in that folder." }
    if ($DryRun) { exit 0 }
    Start-Sleep -Seconds 1
    $left = 0
    foreach ($port in @($apiPort, $webPort)) {
        if ((Get-Listener $port).Count -gt 0) { Write-Warn "Port $port is still in use by $(Describe-Owner $port) - it is not this copy's API or dashboard, so it was left alone."; $left++ }
        else { Write-Ok "Port $port is free." }
    }
    if ($left -gt 0) { exit 1 } else { exit 0 }
}

# ---- start ----
$python = Resolve-Python
Write-Step "Python: $python"
if (-not (Test-Packages $python)) { Fail "The API cannot start with this Python (see above). Nothing was started." }
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Fail "Node.js was not found. Install Node.js 22.12 or newer from https://nodejs.org/ and open a new terminal." }
$nodeVersion = [version]((& node --version).TrimStart('v'))
if ($nodeVersion -lt [version]'22.12') { Fail "Node.js $nodeVersion is too old; version 22.12 or newer is required (frontend/package.json)." }

# 1. API
$health = Get-Json "$apiUrl/api/health"
if ($health -and $health.status -eq 'ok') { Write-Ok "The API already answers on $apiUrl - reusing it." }
else {
    if ((Get-Listener $apiPort).Count -gt 0) { Fail "Port $apiPort is in use by something that is not this API: $(Describe-Owner $apiPort)`n    Stop it, or run: .\dev.cmd stop" }
    Write-Step "Starting the API in the background ($apiUrl, log: $apiLog)"
    if (-not $env:BENCHMARK_RUN_DIRS) { $env:BENCHMARK_RUN_DIRS = $runDir }
    $apiProcess = Start-Detached $backend "`"$python`" -m uvicorn api:app --app-dir `"$backend`" --host 127.0.0.1 --port $apiPort" $apiLog
    $health = Wait-For "$apiUrl/api/health" 90 { param($b) $b.status -eq 'ok' } $apiProcess
    if (-not $health) {
        Show-LogTail $apiLog
        Fail "The API did not answer $apiUrl/api/health$(if ($apiProcess.HasExited) { ' (the process ended)' } else { ' within 90 seconds' }). Read its log above, or $apiLog."
    }
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
        $ErrorActionPreference = 'Continue'      # npm writes warnings to stderr
        try { & npm ci; if ($LASTEXITCODE -ne 0) { Fail "npm ci failed (see the messages above)." } } finally { Pop-Location; $ErrorActionPreference = 'Stop' }
    }
    Write-Step "Starting the dashboard in the background ($webUrl, log: $webLog)"
    $webProcess = Start-Detached $frontend 'npm run dev' $webLog
    $seen = Wait-For "$webUrl/api/health" 90 { param($b) $b.status -eq 'ok' } $webProcess
    if (-not $seen) {
        Show-LogTail $webLog
        Fail "The dashboard did not forward $webUrl/api/health to the API$(if ($webProcess.HasExited) { ' (the process ended)' } else { ' within 90 seconds' }). Read its log above, or $webLog; run: .\dev.cmd status"
    }
}

# 3. the connection that matters: browser address -> dashboard -> proxy -> API
$through = Get-Json "$webUrl/api/health"
if (-not ($through -and $through.status -eq 'ok')) { Fail "The dashboard is up but its /api forwarding does not reach the API. Run: .\dev.cmd status" }
Write-Ok "Dashboard -> API connection verified through $webUrl/api/health"
Write-Host ""
Write-Host "  Dashboard : $webUrl/" -ForegroundColor White
Write-Host "  API       : $apiUrl/  (interactive documentation: $apiUrl/docs)" -ForegroundColor White
Write-Host "  Both run in the background, without a window: closing this window does not stop them." -ForegroundColor White
Write-Host "  Check     : .\dev.cmd status      Stop both : .\dev.cmd stop      Logs: $logDir" -ForegroundColor White
Write-Host ""
if (-not $NoBrowser) { Start-Process $webUrl }
exit 0
