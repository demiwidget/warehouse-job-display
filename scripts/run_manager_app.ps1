param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

function Show-WarehouseMessage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [string]$Title = "Warehouse Dashboard Manager",
        [System.Windows.Forms.MessageBoxIcon]$Icon = [System.Windows.Forms.MessageBoxIcon]::Information
    )

    [void][System.Windows.Forms.MessageBox]::Show(
        $Message,
        $Title,
        [System.Windows.Forms.MessageBoxButtons]::OK,
        $Icon
    )
}

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

try {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ProjectDir = Split-Path -Parent $ScriptDir
    $VenvDir = Join-Path $ProjectDir ".venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    $VenvPythonGui = Join-Path $VenvDir "Scripts\pythonw.exe"
    $RequirementsPath = Join-Path $ProjectDir "requirements.txt"

    Set-Location $ProjectDir

    if (-not (Test-Path $VenvPython)) {
        $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            Invoke-CheckedCommand $PyLauncher.Source @("-3", "-m", "venv", $VenvDir)
        } else {
            $Python = Get-Command python -ErrorAction SilentlyContinue
            if (-not $Python) {
                throw "Python was not found. Install Python from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
            }

            Invoke-CheckedCommand $Python.Source @("-m", "venv", $VenvDir)
        }
    }

    & $VenvPython -c "import flask, PySide6, requests" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-CheckedCommand $VenvPython @("-m", "pip", "install", "-r", $RequirementsPath)
    }

    if ($CheckOnly) {
        Write-Host "[warehouse-manager] Startup check passed."
        exit 0
    }

    if (-not (Test-Path $VenvPythonGui)) {
        $VenvPythonGui = $VenvPython
    }

    & $VenvPythonGui -m manager_app.main
    exit $LASTEXITCODE
} catch {
    $message = $_.Exception.Message
    if (-not $message) {
        $message = $_ | Out-String
    }

    Show-WarehouseMessage -Message $message -Title "Warehouse Dashboard Manager Startup Error" -Icon ([System.Windows.Forms.MessageBoxIcon]::Error)
    exit 1
}
