[CmdletBinding()]
param(
    [string]$TaskName = "NotebookLM Auth Refresh",
    [int]$IntervalMinutes = 15,
    [switch]$IncludeInteractiveLoginFallback
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 15 -or $IntervalMinutes -gt 20) {
    throw "IntervalMinutes must be between 15 and 20."
}

$scriptPath = Join-Path $PSScriptRoot "Invoke-NotebookLmAuthRefresh.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Auth refresh script not found: $scriptPath"
}

$arguments = @(
    "-NoProfile"
    "-ExecutionPolicy", "Bypass"
    "-File", "`"$scriptPath`""
)

if ($IncludeInteractiveLoginFallback) {
    $arguments += "-AllowInteractiveLogin"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($arguments -join " ")
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, Author
