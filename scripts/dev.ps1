#requires -Version 5.1

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Action,

    [string]$EnvFile,

    [ValidateScript({ $_ -ge 1 })]
    [int]$Workers = 2,

    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root "var/dev"
$LogDirectory = Join-Path $Runtime "logs"
$PidFile = Join-Path $Runtime "dev.pid"
$RuntimeLockFile = Join-Path $Runtime "dev.lock"
$ControlLockFile = Join-Path $Runtime "control.lock"
$SupervisorLog = Join-Path $Runtime "dev.log"
$SupervisorErrorLog = Join-Path $Runtime "dev.error.log"
$ShutdownSeconds = 30

function Show-Usage {
    Write-Output @"
Usage:
  .\scripts\dev.ps1 start [-EnvFile PATH] [-Workers N]
  .\scripts\dev.ps1 stop
  .\scripts\dev.ps1 restart [-EnvFile PATH] [-Workers N]
  .\scripts\dev.ps1 status
  .\scripts\dev.ps1 -Help

Defaults:
  EnvFile: backend/.env.dev
  Workers: 2

Requires:
  Windows PowerShell 5.1 or later.
"@
}

function Ensure-RuntimeDirectories {
    [void](New-Item -ItemType Directory -Path $Runtime -Force)
    [void](New-Item -ItemType Directory -Path $LogDirectory -Force)
}

function Resolve-EnvFile {
    param([string]$Path)

    $candidate = if ([string]::IsNullOrWhiteSpace($Path)) {
        Join-Path $Root "backend/.env.dev"
    } elseif ([System.IO.Path]::IsPathRooted($Path)) {
        $Path
    } else {
        Join-Path $Root $Path
    }

    $resolved = [System.IO.Path]::GetFullPath($candidate)
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "environment file does not exist: $resolved"
    }
    return $resolved
}

function Test-ServicePrerequisites {
    param([string]$ResolvedEnvFile)

    $jar = Join-Path $Root "backend/backend-app/target/backend-app-0.0.1-SNAPSHOT.jar"
    if (-not (Test-Path -LiteralPath $jar -PathType Leaf)) {
        throw "build the backend first with mvn -f backend/pom.xml install"
    }

    $rsbuild = Join-Path $Root "frontend/node_modules/.bin/rsbuild"
    if (-not (Test-Path -LiteralPath $rsbuild -PathType Leaf)) {
        throw "install frontend dependencies first with pnpm --dir frontend install --frozen-lockfile"
    }

    $java = Get-Command java -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $java) {
        throw "java was not found on PATH"
    }

    $node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $node) {
        throw "node was not found on PATH"
    }

    return [pscustomobject]@{
        EnvFile = $ResolvedEnvFile
        Jar = $jar
        Java = $java.Source
        Node = $node.Source
    }
}

function Enter-FileLock {
    param(
        [string]$Path,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            return [System.IO.File]::Open(
                $Path,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
        } catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 100
        }
    }
    throw "timed out waiting for launcher lock: $Path"
}

function Test-RuntimeLock {
    try {
        $stream = [System.IO.File]::Open(
            $RuntimeLockFile,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $stream.Dispose()
        return $false
    } catch [System.IO.IOException] {
        return $true
    }
}

function Read-RuntimeState {
    if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) {
        return $null
    }

    $lines = @(Get-Content -LiteralPath $PidFile)
    if ($lines.Count -eq 0) {
        return $null
    }

    [int]$supervisorPid = 0
    if (-not [int]::TryParse($lines[0], [ref]$supervisorPid) -or $supervisorPid -le 1) {
        throw "Could not read the active supervisor PID from $PidFile"
    }

    $children = foreach ($line in $lines | Select-Object -Skip 1) {
        $name, $pidText = $line -split "=", 2
        [int]$childPid = 0
        if ($name -and [int]::TryParse($pidText, [ref]$childPid)) {
            [pscustomobject]@{ Name = $name; Pid = $childPid }
        }
    }

    return [pscustomobject]@{
        SupervisorPid = $supervisorPid
        Children = @($children)
    }
}

function Write-RuntimePidFile {
    param(
        [int]$SupervisorPid,
        [object[]]$Services
    )

    $lines = @([string]$SupervisorPid)
    foreach ($service in $Services) {
        $lines += "$($service.Name)=$($service.Process.Id)"
    }
    [System.IO.File]::WriteAllLines(
        $PidFile,
        [string[]]$lines,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Clear-RuntimePidFile {
    if (Test-Path -LiteralPath $PidFile -PathType Leaf) {
        Remove-Item -LiteralPath $PidFile -Force
    }
}

function Quote-ProcessArgument {
    param([string]$Value)

    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Join-ProcessArguments {
    param([string[]]$Arguments)

    return ($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join " "
}

function Stop-ProcessTree {
    param(
        [int]$ProcessId,
        [int]$TimeoutSeconds = $ShutdownSeconds
    )

    if ($null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        return
    }

    $taskkill = Join-Path $env:SystemRoot "System32/taskkill.exe"
    & $taskkill /PID $ProcessId /T /F 2>$null | Out-Null

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) -and
            [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 100
    }
    if ($null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        throw "Process tree $ProcessId did not stop within $TimeoutSeconds seconds."
    }
}

function Get-ServiceDefinitions {
    param([object]$Prerequisites)

    $backend = Join-Path $Root "backend"
    $frontend = Join-Path $Root "frontend"
    $backendArguments = @(
        "-jar",
        $Prerequisites.Jar,
        "--env-file=$($Prerequisites.EnvFile)"
    )

    $definitions = @(
        [pscustomobject]@{
            Name = "api"
            FilePath = $Prerequisites.Java
            Arguments = $backendArguments
            WorkingDirectory = $backend
        },
        [pscustomobject]@{
            Name = "scheduler"
            FilePath = $Prerequisites.Java
            Arguments = @($backendArguments + "--spring.profiles.active=delivery-scheduler")
            WorkingDirectory = $backend
        }
    )

    for ($index = 1; $index -le $Workers; $index++) {
        $definitions += [pscustomobject]@{
            Name = "worker-$index"
            FilePath = $Prerequisites.Java
            Arguments = @($backendArguments + "--spring.profiles.active=delivery-worker")
            WorkingDirectory = $backend
        }
    }

    $definitions += [pscustomobject]@{
        Name = "frontend"
        FilePath = $Prerequisites.Node
        Arguments = @("dev.mjs")
        WorkingDirectory = $frontend
    }
    return $definitions
}

function Start-ManagedService {
    param([object]$Definition)

    $stdout = Join-Path $LogDirectory "$($Definition.Name).out.log"
    $stderr = Join-Path $LogDirectory "$($Definition.Name).err.log"
    $argumentLine = Join-ProcessArguments $Definition.Arguments
    $process = Start-Process `
        -FilePath $Definition.FilePath `
        -ArgumentList $argumentLine `
        -WorkingDirectory $Definition.WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    return [pscustomobject]@{
        Name = $Definition.Name
        Process = $process
    }
}

function Stop-ManagedServices {
    param([object[]]$Services)

    foreach ($service in $Services) {
        try {
            if (-not $service.Process.HasExited) {
                Stop-ProcessTree -ProcessId $service.Process.Id
            }
        } catch {
            [Console]::Out.WriteLine("Could not stop $($service.Name): $($_.Exception.Message)")
        }
    }
}

function Invoke-Supervisor {
    param([string]$SelectedEnvFile)

    Ensure-RuntimeDirectories
    $runtimeLock = $null
    $services = @()
    try {
        $runtimeLock = Enter-FileLock -Path $RuntimeLockFile -TimeoutSeconds 1
        Clear-RuntimePidFile
        [System.IO.File]::WriteAllText(
            $PidFile,
            [string]$PID,
            [System.Text.UTF8Encoding]::new($false)
        )

        $prerequisites = Test-ServicePrerequisites $SelectedEnvFile
        foreach ($definition in Get-ServiceDefinitions $prerequisites) {
            [Console]::Out.WriteLine("Starting $($definition.Name)...")
            $services += Start-ManagedService $definition
        }
        Write-RuntimePidFile -SupervisorPid $PID -Services $services
        [Console]::Out.WriteLine("Supervisor started (PID $PID).")

        while ($true) {
            foreach ($service in $services) {
                if ($service.Process.HasExited) {
                    $exitCode = $service.Process.ExitCode
                    $result = if ($exitCode -gt 0) { $exitCode } else { 1 }
                    [Console]::Out.WriteLine(
                        "$($service.Name) exited ($exitCode). Stopping development services."
                    )
                    return $result
                }
            }
            Start-Sleep -Milliseconds 200
        }
    } finally {
        Stop-ManagedServices $services
        Clear-RuntimePidFile
        if ($null -ne $runtimeLock) {
            $runtimeLock.Dispose()
        }
    }
}

function Start-DevelopmentServices {
    param([string]$SelectedEnvFile)

    if (Test-RuntimeLock) {
        $state = Read-RuntimeState
        if ($null -eq $state) {
            throw "Development services are running without a readable PID file."
        }
        Write-Output "Already running (PID $($state.SupervisorPid))."
        return
    }

    $resolvedEnvFile = Resolve-EnvFile $SelectedEnvFile
    [void](Test-ServicePrerequisites $resolvedEnvFile)
    Clear-RuntimePidFile

    $pwsh = (Get-Process -Id $PID).Path
    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-File",
        $PSCommandPath,
        "_supervise",
        "-EnvFile",
        $resolvedEnvFile,
        "-Workers",
        [string]$Workers
    )
    $argumentLine = Join-ProcessArguments $arguments
    $process = Start-Process `
        -FilePath $pwsh `
        -ArgumentList $argumentLine `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $SupervisorLog `
        -RedirectStandardError $SupervisorErrorLog `
        -WindowStyle Hidden `
        -PassThru

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
        $state = Read-RuntimeState
        if ($null -ne $state -and $state.SupervisorPid -eq $process.Id -and (Test-RuntimeLock)) {
            Write-Output "Started (PID $($process.Id)). Log: $SupervisorLog"
            Write-Output "Service logs: $LogDirectory"
            return
        }
        Start-Sleep -Milliseconds 100
    }

    if (-not $process.HasExited) {
        Stop-ProcessTree -ProcessId $process.Id -TimeoutSeconds ($ShutdownSeconds + 5)
    }
    throw "Development services did not start. See $SupervisorLog and $SupervisorErrorLog"
}

function Stop-DevelopmentServices {
    if (-not (Test-RuntimeLock)) {
        Clear-RuntimePidFile
        Write-Output "Not running."
        return
    }

    $state = Read-RuntimeState
    if ($null -eq $state) {
        throw "Development services are running without a readable PID file."
    }

    $supervisor = Get-Process -Id $state.SupervisorPid -ErrorAction SilentlyContinue
    if ($null -eq $supervisor) {
        throw "Supervisor $($state.SupervisorPid) is no longer running. See $SupervisorLog"
    }

    Stop-ProcessTree -ProcessId $state.SupervisorPid -TimeoutSeconds ($ShutdownSeconds + 5)

    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while ((Test-RuntimeLock) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 100
    }
    if (Test-RuntimeLock) {
        throw "Launcher lock is still held after supervisor $($state.SupervisorPid) stopped."
    }

    Clear-RuntimePidFile
    Write-Output "Stopped (PID $($state.SupervisorPid))."
}

function Get-DevelopmentStatus {
    if (-not (Test-RuntimeLock)) {
        return [pscustomobject]@{
            ExitCode = 1
            Lines = @("Not running.")
        }
    }

    $state = Read-RuntimeState
    if ($null -eq $state) {
        throw "Development services are running without a readable PID file."
    }

    $lines = @(
        "Running (PID $($state.SupervisorPid)). Log: $SupervisorLog",
        "Service logs: $LogDirectory"
    )
    foreach ($child in $state.Children) {
        $lines += "  $($child.Name) (PID $($child.Pid))"
    }
    return [pscustomobject]@{
        ExitCode = 0
        Lines = $lines
    }
}

if ($Help -or $Action -eq "help" -or [string]::IsNullOrWhiteSpace($Action)) {
    Show-Usage
    exit 0
}

if ($env:OS -ne "Windows_NT") {
    [Console]::Error.WriteLine("dev.ps1: this launcher requires Windows and PowerShell 5.1 or later")
    exit 1
}

$normalizedAction = if ($Action -eq "_supervise") { $Action } else { $Action.ToLowerInvariant() }
if ($normalizedAction -in @("stop", "status") -and
        ($PSBoundParameters.ContainsKey("EnvFile") -or $PSBoundParameters.ContainsKey("Workers"))) {
    [Console]::Error.WriteLine("dev.ps1: -EnvFile and -Workers are available with start or restart")
    exit 2
}
if ($normalizedAction -notin @("start", "stop", "restart", "status", "_supervise")) {
    Show-Usage
    exit 2
}

try {
    Ensure-RuntimeDirectories
    if ($normalizedAction -eq "_supervise") {
        $supervisorExitCode = Invoke-Supervisor -SelectedEnvFile (Resolve-EnvFile $EnvFile)
        exit $supervisorExitCode
    }

    $controlLock = Enter-FileLock -Path $ControlLockFile
    try {
        switch ($normalizedAction) {
            "start" {
                Start-DevelopmentServices $EnvFile
            }
            "stop" {
                Stop-DevelopmentServices
            }
            "restart" {
                $resolvedEnvFile = Resolve-EnvFile $EnvFile
                [void](Test-ServicePrerequisites $resolvedEnvFile)
                Stop-DevelopmentServices
                Start-DevelopmentServices $resolvedEnvFile
            }
            "status" {
                $status = Get-DevelopmentStatus
                $status.Lines | Write-Output
                exit $status.ExitCode
            }
        }
    } finally {
        $controlLock.Dispose()
    }
} catch {
    [Console]::Error.WriteLine("dev.ps1: $($_.Exception.Message)")
    exit 1
}
