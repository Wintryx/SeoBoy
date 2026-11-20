param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$hooks = Join-Path $RepoRoot ".git\hooks"
if (-not (Test-Path $hooks)) { throw "Kein Git-Hooks-Verzeichnis: $hooks" }
foreach ($name in @("pre-commit", "pre-push")) {
    $source = Join-Path $PSScriptRoot $name
    $target = Join-Path $hooks $name
    if (Test-Path $target) {
        Copy-Item $target "$target.bak" -Force
    }
    Copy-Item $source $target -Force
    Write-Output "Installiert: $target"
}
Write-Output "Secret-Scan ist jetzt vor Commit und Push aktiv."
