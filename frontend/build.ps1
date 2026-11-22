param(
  [Parameter(Mandatory=$true)][string]$Api,       # the backend's origin, e.g. https://api.example.com
  [Parameter(Mandatory=$true)][string]$Contact    # public contact email shown on the privacy page and terms
)
# Builds the folder to upload to Vercel: a copy of frontend\ with the API address written into
# static\config.js and the contact email filled into the legal pages. Nothing else changes.
$src = $PSScriptRoot
$out = Join-Path $PSScriptRoot "..\frontend-out"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out | Out-Null
Copy-Item -Recurse -Force (Join-Path $src "*") $out
Remove-Item (Join-Path $out "build.ps1"), (Join-Path $out "README.md") -ErrorAction SilentlyContinue
$cfg = Join-Path $out "static\config.js"
(Get-Content $cfg -Raw -Encoding UTF8).Replace('window.LATTICE_API = "";', "window.LATTICE_API = `"$($Api.TrimEnd('/'))`";") | Set-Content $cfg -Encoding UTF8
foreach ($f in "privacy.html","terms.html") {
  $p = Join-Path $out "static\$f"
  (Get-Content $p -Raw -Encoding UTF8).Replace("{{CONTACT}}", $Contact) | Set-Content $p -Encoding UTF8
}
Write-Host "Built $out  ->  upload this folder to Vercel (API = $Api)"
