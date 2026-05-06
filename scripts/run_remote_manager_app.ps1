param(
    [Parameter(Mandatory = $true)]
    [string]$ManagerUrl
)

$ErrorActionPreference = "Stop"

try {
    function Invoke-CheckedCommand {
        param(
            [Parameter(Mandatory = $true)]
            [string]$FilePath,
            [Parameter(Mandatory = $true)]
            [string[]]$Arguments
        )

        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed: $FilePath $($Arguments -join ' ')"
        }
    }

    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ProjectDir = Split-Path -Parent $ScriptDir
    $VenvDir = Join-Path $ProjectDir ".venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    $RequirementsPath = Join-Path $ProjectDir "requirements.txt"

    Set-Location $ProjectDir

    $Git = Get-Command git -ErrorAction SilentlyContinue
    if ($Git) {
        & $Git.Source -C $ProjectDir pull --ff-only 2>$null
    }

    if (-not (Test-Path $VenvPython)) {
        $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            Invoke-CheckedCommand $PyLauncher.Source @("-3", "-m", "venv", $VenvDir)
        } else {
            $Python = Get-Command python -ErrorAction SilentlyContinue
            if (-not $Python) {
                throw "Python was not found. Install Python and tick 'Add python.exe to PATH'."
            }
            Invoke-CheckedCommand $Python.Source @("-m", "venv", $VenvDir)
        }
    }

    & $VenvPython -c "import flask, PySide6, requests" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "-r", $RequirementsPath)
    }

    & $VenvPython -m manager_app.remote_main $ManagerUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Remote manager exited with code $LASTEXITCODE."
    }
} catch {
    Write-Host ""
    Write-Host "Warehouse Remote Manager failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}
