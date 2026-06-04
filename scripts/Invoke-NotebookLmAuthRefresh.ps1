[CmdletBinding()]
param(
    [string]$Browser = "chrome",
    [switch]$SkipBrowserCookies,
    [switch]$AllowInteractiveLogin,
    [int]$LoginTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-NotebookLm {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "notebooklm"
    $escapedArgs = foreach ($arg in $Arguments) {
        if ($arg -match '\s') {
            '"' + $arg.Replace('"', '\"') + '"'
        } else {
            $arg
        }
    }
    $psi.Arguments = [string]::Join(" ", $escapedArgs)
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    $output = @($stdout.TrimEnd(), $stderr.TrimEnd()) | Where-Object { $_ }

    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "notebooklm $($Arguments -join ' ') failed with exit code $exitCode.`n$output"
    }

    [pscustomobject]@{
        ExitCode = $exitCode
        Output   = ($output -join [Environment]::NewLine)
    }
}

function Test-NotebookLmAuth {
    $result = Invoke-NotebookLm -Arguments @("auth", "check", "--test", "--json") -AllowFailure
    if ($result.ExitCode -ne 0) {
        return $false
    }

    try {
        $json = $result.Output | ConvertFrom-Json -ErrorAction Stop
        return -not $json.error
    } catch {
        return $false
    }
}

function Invoke-RefreshAttempt {
    param(
        [string[]]$Arguments,
        [string]$Mode
    )

    $result = Invoke-NotebookLm -Arguments $Arguments -AllowFailure
    [pscustomobject]@{
        Mode     = $Mode
        ExitCode = $result.ExitCode
        Output   = $result.Output
        Success  = ($result.ExitCode -eq 0)
    }
}

$attempts = @()

if (-not $SkipBrowserCookies) {
    $cookieAttempt = Invoke-RefreshAttempt -Arguments @("auth", "refresh", "--browser-cookies", $Browser, "-q") -Mode "browser-cookies:$Browser"
    $attempts += $cookieAttempt
    if ($cookieAttempt.Success -and (Test-NotebookLmAuth)) {
        Write-Output (ConvertTo-Json @{
                ok      = $true
                method  = "browser-cookies:$Browser"
                attempts = $attempts
            } -Depth 6)
        exit 0
    }
}

$refreshAttempt = Invoke-RefreshAttempt -Arguments @("auth", "refresh", "-q") -Mode "refresh"
$attempts += $refreshAttempt
if ($refreshAttempt.Success -and (Test-NotebookLmAuth)) {
    Write-Output (ConvertTo-Json @{
            ok      = $true
            method  = "refresh"
            attempts = $attempts
        } -Depth 6)
    exit 0
}

if ($AllowInteractiveLogin) {
    $loginJob = Start-Job -ScriptBlock {
        param($TimeoutSeconds)
        & notebooklm login --browser chrome 2>&1
        exit $LASTEXITCODE
    } -ArgumentList $LoginTimeoutSeconds

    if (-not (Wait-Job $loginJob -Timeout $LoginTimeoutSeconds)) {
        Stop-Job $loginJob -Force | Out-Null
        $attempts += [pscustomobject]@{
            Mode     = "login"
            ExitCode = 124
            Output   = "Timed out waiting for notebooklm login after $LoginTimeoutSeconds seconds."
            Success  = $false
        }
    } else {
        $loginOutput = Receive-Job $loginJob
        $loginState = $loginJob.State
        Remove-Job $loginJob | Out-Null
        $attempts += [pscustomobject]@{
            Mode     = "login"
            ExitCode = if ($loginState -eq "Completed") { 0 } else { 1 }
            Output   = ($loginOutput -join [Environment]::NewLine)
            Success  = ($loginState -eq "Completed")
        }
        if (Test-NotebookLmAuth) {
            Write-Output (ConvertTo-Json @{
                    ok      = $true
                    method  = "login"
                    attempts = $attempts
                } -Depth 6)
            exit 0
        }
    }
}

Write-Output (ConvertTo-Json @{
        ok       = $false
        message  = "NotebookLM authentication could not be refreshed automatically."
        attempts = $attempts
    } -Depth 6)
exit 1
