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

function Invoke-QuietCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & $FilePath @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    return ($output | Out-String).Trim()
}

function Test-GitRepoCanAutoUpdate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GitExe,

        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    if (-not (Test-Path (Join-Path $ProjectDir ".git"))) {
        return $false
    }

    $upstream = Invoke-QuietCommand $GitExe @("-C", $ProjectDir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if (-not $upstream) {
        return $false
    }

    $changes = Invoke-QuietCommand $GitExe @("-C", $ProjectDir, "status", "--porcelain", "--untracked-files=no")
    if ($changes) {
        return $false
    }

    return $true
}

function Update-RepoIfNeeded {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GitExe,

        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    if (-not (Test-GitRepoCanAutoUpdate -GitExe $GitExe -ProjectDir $ProjectDir)) {
        return $false
    }

    & $GitExe -C $ProjectDir fetch --quiet origin 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    $behind = Invoke-QuietCommand $GitExe @("-C", $ProjectDir, "rev-list", "--count", "HEAD..@{u}")
    if (-not $behind -or [int]$behind -le 0) {
        return $false
    }

    Invoke-CheckedCommand $GitExe @("-C", $ProjectDir, "pull", "--ff-only")
    return $true
}

try {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ProjectDir = Split-Path -Parent $ScriptDir
    $VenvDir = Join-Path $ProjectDir ".venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    $VenvPythonGui = Join-Path $VenvDir "Scripts\pythonw.exe"
    $RequirementsPath = Join-Path $ProjectDir "requirements.txt"

    Set-Location $ProjectDir

    $Git = Get-Command git -ErrorAction SilentlyContinue
    if ($Git) {
        [void](Update-RepoIfNeeded -GitExe $Git.Source -ProjectDir $ProjectDir)
    }

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

    $ManagerDataDir = Join-Path $ProjectDir "manager_data"
    $LauncherLog = Join-Path $ManagerDataDir "manager_launcher.log"
    $ExitFlag = Join-Path $ManagerDataDir "allow_manager_exit.flag"
    New-Item -ItemType Directory -Force -Path $ManagerDataDir | Out-Null
    Remove-Item -LiteralPath $ExitFlag -Force -ErrorAction SilentlyContinue

    while ($true) {
        & $VenvPythonGui -m manager_app.main
        $managerExitCode = $LASTEXITCODE
        if ($null -eq $managerExitCode) {
            $managerExitCode = 0
        }

        if (($managerExitCode -eq 0) -and (Test-Path $ExitFlag)) {
            Remove-Item -LiteralPath $ExitFlag -Force -ErrorAction SilentlyContinue
            exit 0
        }

        $timestamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
        Add-Content -Path $LauncherLog -Value "$timestamp Manager exited with code $managerExitCode; relaunching in 5 seconds."
        Start-Sleep -Seconds 5
    }
} catch {
    $message = $_.Exception.Message
    if (-not $message) {
        $message = $_ | Out-String
    }

    Show-WarehouseMessage -Message $message -Title "Warehouse Dashboard Manager Startup Error" -Icon ([System.Windows.Forms.MessageBoxIcon]::Error)
    exit 1
}
