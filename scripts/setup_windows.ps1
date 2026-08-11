param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$VenvDir = Join-Path $ProjectDir ".venv"
$Requirements = Join-Path $ProjectDir "workflow_code_skeleton\requirements.txt"
$EnvExample = Join-Path $ProjectDir "workflow_code_skeleton\.env.example"
$EnvFile = Join-Path $ProjectDir "workflow_code_skeleton\.env"

function Resolve-PythonCommand {
    if ($Python -eq "python") {
        try {
            & py -3.13 --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{
                    Command = "py"
                    Args = @("-3.13")
                    Label = "py -3.13"
                }
            }
        } catch {
        }
    }
    return @{
        Command = $Python
        Args = @()
        Label = $Python
    }
}

function Invoke-ConfiguredPython {
    param(
        [hashtable]$PythonCommand,
        [string[]]$Arguments
    )

    $allArgs = @($PythonCommand.Args) + @($Arguments)
    & $PythonCommand.Command @allArgs
}

function Resolve-VenvPython {
    param([string]$Root)

    $candidates = @(
        (Join-Path $Root "Scripts\python.exe"),
        (Join-Path $Root "bin\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

Set-Location $ProjectDir
$PythonCommand = Resolve-PythonCommand
Write-Host "[setup-windows] Using Python: $($PythonCommand.Label)"

if (-not (Test-Path $VenvDir)) {
    Write-Host "[setup-windows] Creating virtual environment: $VenvDir"
    Invoke-ConfiguredPython $PythonCommand @("-m", "venv", $VenvDir)
}

$PythonExe = Resolve-VenvPython $VenvDir
if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found in venv: $VenvDir"
}

Write-Host "[setup-windows] Installing dependencies from workflow_code_skeleton\requirements.txt"
& $PythonExe -m pip install --upgrade pip

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "[setup-windows] Using uv"
    & uv pip install --python $PythonExe -r $Requirements
} else {
    Write-Host "[setup-windows] Using pip"
    & $PythonExe -m pip install -r $Requirements
}

if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "[setup-windows] Created workflow_code_skeleton\.env from .env.example"
    Write-Host "[setup-windows] Fill the 18 TENCENT_WORKFLOW_*_API_KEY values before running workflows."
}

Write-Host "[setup-windows] Done"
Write-Host "[setup-windows] Start locally with: powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1"
