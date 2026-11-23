# Copy the server's data to this PC, into a dated folder. Run it from PowerShell on your own machine:
#
#   powershell -File deploy\oracle\backup-to-pc.ps1
#
# The data directory holds everything object storage does not: accounts, the usage ledger, daily limit
# counts, ownership, projects, decks, lessons and (without R2) the finished videos. The server's .env is
# copied too, as env.txt: it holds secrets, so keep the backup folder private.
param(
  [string]$Server     = "dev@34.100.251.174",
  [string]$Key        = "$HOME\.ssh\oracle_lattice",
  [string]$RemoteData = "/home/dev/lattice/out",                 # LATTICE_OUT_DIR on the server
  [string]$RemoteEnv  = "/home/dev/lattice-new/backend/.env",
  [string]$Dest       = "$HOME\lattice-backups",
  [int]$Keep          = 8                                         # how many dated backups to keep
)
$ErrorActionPreference = "Stop"
$stamp  = Get-Date -Format "yyyy-MM-dd_HHmm"
$target = Join-Path $Dest $stamp
New-Item -ItemType Directory -Force $target | Out-Null

Write-Host "==> data: ${Server}:$RemoteData"
scp -r -q -i $Key "${Server}:$RemoteData" $target
if ($LASTEXITCODE -ne 0) { throw "copying the data failed (exit $LASTEXITCODE)" }

Write-Host "==> config: ${Server}:$RemoteEnv"
scp -q -i $Key "${Server}:$RemoteEnv" (Join-Path $target "env.txt")
if ($LASTEXITCODE -ne 0) { Write-Warning "could not copy .env (data backup is still complete)" }

$size = (Get-ChildItem $target -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("==> saved {0:N1} MB to {1}" -f $size, $target)

# keep the newest $Keep backups, delete older ones
$old = Get-ChildItem $Dest -Directory | Sort-Object Name -Descending | Select-Object -Skip $Keep
foreach ($d in $old) { Remove-Item -Recurse -Force $d.FullName; Write-Host "removed old backup $($d.Name)" }
