[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Vault,

    [Parameter(Mandatory = $true)]
    [string]$NotebookTitle,

    [string[]]$IncludeDir = @(),
    [string[]]$ExcludeDir = @(".trash"),
    [string[]]$IncludeTag = @(),
    [string[]]$ExcludeTag = @(),
    [string]$StateFile = (Join-Path (Get-Location).Path ".notebooklm-obsidian-sync.json"),
    [int]$Limit = 0,
    [switch]$Force,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$scriptPath = Join-Path $PSScriptRoot "sync_obsidian_to_notebooklm.py"
$args = @(
    $scriptPath,
    "--vault", $Vault,
    "--notebook-title", $NotebookTitle,
    "--state-file", $StateFile,
    "--limit", $Limit
)

foreach ($item in $IncludeDir) {
    $args += @("--include-dir", $item)
}
foreach ($item in $ExcludeDir) {
    $args += @("--exclude-dir", $item)
}
foreach ($item in $IncludeTag) {
    $args += @("--include-tag", $item)
}
foreach ($item in $ExcludeTag) {
    $args += @("--exclude-tag", $item)
}
if ($Force) {
    $args += "--force"
}
if (-not $Execute) {
    $args += "--dry-run"
}

& python @args
exit $LASTEXITCODE
