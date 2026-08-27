# Coleta frequente (mortes novas + resolução de guild). Roda a cada ~15 min.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # raiz do projeto
Set-Location $root
New-Item -ItemType Directory -Force -Path "$root\data" | Out-Null
$log = "$root\data\collector.log"
$py  = "python"

"$(Get-Date -Format o)  [frequent] start" | Add-Content $log
& $py -m deusold.collect deaths --pages 5      *>> $log
& $py -m deusold.collect characters --limit 100 *>> $log
"$(Get-Date -Format o)  [frequent] done"  | Add-Content $log
