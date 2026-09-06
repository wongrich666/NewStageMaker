param(
    [int]$Port = 5173,
    [string]$HostName = "127.0.0.1",
    [switch]$SkipInstall,
    [switch]$SkipManifestRefresh
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$FrontendDir = Join-Path $ProjectDir "agent-flow-frontend"
$GeneratorPath = Join-Path $ProjectDir "scripts\generate_architecture_manifest.py"
$NodeModulesDir = Join-Path $FrontendDir "node_modules"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js, then reopen PowerShell."
}

if (-not $SkipManifestRefresh) {
    $PythonExe = "python"
    $VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPython) {
        $PythonExe = $VenvPython
    }
    Write-Host "[architecture-graph] Refreshing the code-driven manifest..."
    & $PythonExe $GeneratorPath
    if ($LASTEXITCODE -ne 0) {
        throw "Architecture manifest generation failed with exit code $LASTEXITCODE."
    }
}

Set-Location $FrontendDir

if (-not $SkipInstall -and -not (Test-Path -LiteralPath $NodeModulesDir)) {
    Write-Host "[architecture-graph] Installing frontend dependencies..."
    & npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed with exit code $LASTEXITCODE."
    }
}

Write-Host "[architecture-graph] Project: $FrontendDir"
Write-Host "[architecture-graph] Starting: http://$HostName`:$Port"
Write-Host "[architecture-graph] Press Ctrl+C to stop."

& npm run dev -- --host $HostName --port $Port --strictPort
