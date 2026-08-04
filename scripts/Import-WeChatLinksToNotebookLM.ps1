[CmdletBinding()]
param(
    [string]$NotebookTitle = "",
    [string]$DateYmd = (Get-Date).ToString("yyyyMMdd"),
    [string]$LinkDir = (Get-Location).Path,
    [string]$TempDir = (Join-Path $env:TEMP "notebooklm-wechat-import"),
    [ValidateSet("chromium", "chrome", "msedge")]
    [string]$LoginBrowser = "chrome",
    [switch]$SkipLogin,
    [switch]$SkipAuthRefresh
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$scriptPath = Join-Path $PSScriptRoot "import_wechat_links.py"
if ([string]::IsNullOrWhiteSpace($NotebookTitle)) {
    $NotebookTitle = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5b6u5L+h5LyY56eA5paH56ug"))
}
$notebookTitleB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($NotebookTitle))
$args = @(
    $scriptPath,
    "--notebook-title-b64", $notebookTitleB64,
    "--date-ymd", $DateYmd,
    "--link-dir", $LinkDir,
    "--temp-dir", $TempDir,
    "--login-browser", $LoginBrowser
)

if ($SkipLogin -or $SkipAuthRefresh) {
    $args += "--skip-login"
}

& python @args
exit $LASTEXITCODE
