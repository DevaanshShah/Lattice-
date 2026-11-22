param([Parameter(Mandatory=$true)][string]$AppUrl, [Parameter(Mandatory=$true)][string]$Contact)
$src = Join-Path $PSScriptRoot "."
$out = Join-Path $PSScriptRoot "..\site-out"
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($f in "index.html","privacy.html","terms.html") {
  (Get-Content (Join-Path $src $f) -Raw -Encoding UTF8).Replace("{{APP_URL}}", $AppUrl.TrimEnd("/")).Replace("{{CONTACT}}", $Contact) |
    Set-Content (Join-Path $out $f) -Encoding UTF8
}
Write-Host "Wrote $out  ->  deploy this folder"
