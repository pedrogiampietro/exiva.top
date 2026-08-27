# Snapshot diário de experiência (para o "exp today"). Roda 1x/dia, ~10:05
# (o site atualiza os rankings às 10:00). Um snapshot por dia = delta limpo.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path "$root\data" | Out-Null
$log = "$root\data\collector.log"
$py  = "python"

"$(Get-Date -Format o)  [daily] start" | Add-Content $log
& $py -m deusold.collect exp --pages 12 *>> $log
"$(Get-Date -Format o)  [daily] done"  | Add-Content $log
