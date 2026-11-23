# Runs the w3bb screen and publishes it (Task Scheduler "w3bb Daily Screen", Mon-Fri 7:00 AM).
# Log: logs\YYYY-MM-DD.log. Pushing results/ updates https://cleetus.github.io/w3bb/
$root = $PSScriptRoot
New-Item -ItemType Directory -Force (Join-Path $root 'logs') | Out-Null
$log = Join-Path $root "logs\$(Get-Date -Format yyyy-MM-dd).log"
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'w3bb.py') *>> $log
if ($LASTEXITCODE -eq 0) {
    Set-Location $root
    git add results *>> $log
    git commit -m "Picks for $(Get-Date -Format yyyy-MM-dd)" *>> $log
    git push *>> $log
}
