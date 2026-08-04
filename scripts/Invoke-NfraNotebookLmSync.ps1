[CmdletBinding()]
param(
    [string]$TargetDate,
    [switch]$NoUpload,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = Split-Path $PSScriptRoot -Parent
$pythonScript = Join-Path $PSScriptRoot "nfra_to_notebooklm.py"
$runtimeDir = Join-Path $repoRoot ".runtime"
$logDir = Join-Path $runtimeDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$arguments = @(
    $pythonScript,
    "--output-dir", (Join-Path $repoRoot "output\pdf"),
    "--state-file", (Join-Path $runtimeDir "nfra-sync-state.json"),
    "--notebook-title", "NFRA"
)
if ($TargetDate) {
    $arguments += @("--target-date", $TargetDate)
}
if ($NoUpload) {
    $arguments += "--no-upload"
}
if ($Force) {
    $arguments += "--force"
}

$logPath = Join-Path $logDir ("nfra-sync-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
Push-Location $repoRoot
try {
    $commandOutput = & python @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $commandOutput | Tee-Object -FilePath $logPath
    exit $exitCode
}
finally {
    Pop-Location
}
