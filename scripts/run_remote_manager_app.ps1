param(
    [string]$ManagerUrl = "",
    [switch]$GuiLaunch
)

$ErrorActionPreference = "Stop"

try {
    function Show-LauncherError {
        param([Parameter(Mandatory = $true)][string]$Message)

        if ($GuiLaunch) {
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.MessageBox]::Show(
                $Message,
                "Warehouse Remote Manager",
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error
            )
        } else {
            Write-Host ""
            Write-Host "Warehouse Remote Manager failed:" -ForegroundColor Red
            Write-Host $Message
            Write-Host ""
            Read-Host "Press Enter to close"
        }
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

    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ProjectDir = Split-Path -Parent $ScriptDir
    $VenvDir = Join-Path $ProjectDir ".venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    $VenvPythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
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

    $RemoteArgs = @("-m", "manager_app.remote_main")
    if (-not [string]::IsNullOrWhiteSpace($ManagerUrl)) {
        $RemoteArgs += $ManagerUrl
    }

    if ($GuiLaunch -and (Test-Path $VenvPythonw)) {
        $Process = Start-Process -FilePath $VenvPythonw -ArgumentList $RemoteArgs -WorkingDirectory $ProjectDir -Wait -PassThru -WindowStyle Hidden
        if ($Process.ExitCode -ne 0) {
            throw "Remote manager exited with code $($Process.ExitCode)."
        }
    } else {
        & $VenvPython @RemoteArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Remote manager exited with code $LASTEXITCODE."
        }
    }
} catch {
    Show-LauncherError $_.Exception.Message
    exit 1
}
