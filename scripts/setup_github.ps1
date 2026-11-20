param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root ".git"))) {
    throw "Kein Git-Checkout: $root"
}
if (git -C $root status --porcelain) {
    throw "Arbeitsbaum ist nicht sauber. Bitte zuerst committen."
}
$existing = git -C $root remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) {
    if ($existing -ne $RepoUrl) {
        throw "Remote origin zeigt bereits auf $existing. Bitte bewusst ändern."
    }
} else {
    git -C $root remote add origin $RepoUrl
}
git -C $root push -u origin $Branch
Write-Output "Upstream gesetzt: origin/$Branch"
Write-Output "Nächster Schritt: seoboy update --check"
