[CmdletBinding()]
param(
    [string]$TaskName = "NotebookLM-NFRA-Daily-Sync",
    [datetime]$At = "20:00"
)

$ErrorActionPreference = "Stop"
$syncScript = Join-Path $PSScriptRoot "Invoke-NfraNotebookLmSync.ps1"
if (-not (Test-Path -LiteralPath $syncScript)) {
    throw "NFRA sync wrapper not found: $syncScript"
}

$quotedScript = '"{0}"' -f $syncScript
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File $quotedScript" `
    -WorkingDirectory (Split-Path $PSScriptRoot -Parent)
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Check NFRA English Rules and Regulations, create PDFs, and upload new daily rules to NotebookLM NFRA." `
    -Force

Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
