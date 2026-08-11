param(
    [int]$Port = 5001,
    [string]$HostName = "127.0.0.1",
    [switch]$Debug,
    [switch]$UseSystemPython
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$VenvPythonCandidates = @(
    (Join-Path $ProjectDir ".venv\Scripts\python.exe"),
    (Join-Path $ProjectDir ".venv\bin\python.exe")
)
$RuntimeDataDir = Join-Path $ProjectDir "workflow_code_skeleton\runtime_data"

Set-Location $ProjectDir

if (-not $env:RUNTIME_DATA_DIR) {
    $env:RUNTIME_DATA_DIR = $RuntimeDataDir
}
if (-not $env:WRITABLE_ROOT) {
    $env:WRITABLE_ROOT = $ProjectDir
}

New-Item -ItemType Directory -Force -Path $env:RUNTIME_DATA_DIR | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $env:WRITABLE_ROOT "cache") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $env:WRITABLE_ROOT "debug") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $env:WRITABLE_ROOT "logs") | Out-Null

if (-not (Test-Path "workflow_code_skeleton\.env")) {
    Write-Warning "workflow_code_skeleton\.env not found. Copy .env.example and fill the 18 TENCENT_WORKFLOW_*_API_KEY values."
}

$PythonExe = "python"
if (-not $UseSystemPython) {
    foreach ($candidate in $VenvPythonCandidates) {
        if (Test-Path $candidate) {
            $PythonExe = $candidate
            break
        }
    }
}

$ArgsList = @("main.py", "serve", "--host", $HostName, "--port", [string]$Port)
if ($Debug) {
    $ArgsList += "--debug"
}

Write-Host "[run-windows] Project: $ProjectDir"
Write-Host "[run-windows] RUNTIME_DATA_DIR: $env:RUNTIME_DATA_DIR"
Write-Host "[run-windows] WRITABLE_ROOT: $env:WRITABLE_ROOT"
Write-Host "[run-windows] Starting: http://$HostName`:$Port"

& $PythonExe @ArgsList
