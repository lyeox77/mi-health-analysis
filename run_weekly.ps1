# Run with the Python executable from the bridge virtual environment.
param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [string]$OutputRoot = "$PSScriptRoot\private_runs",
    [switch]$Sync
)
$ErrorActionPreference = 'Stop'
$PythonExe = (Resolve-Path $PythonExe).Path
$bridge = Join-Path (Split-Path $PythonExe) 'mi-fitness-bridge.exe'
if (-not (Test-Path $bridge)) { throw 'Bridge executable not found next to Python.' }
# Always use China reporting dates, independently of Windows local timezone.
$chinaNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'China Standard Time')
$end = $chinaNow.Date.AddDays(-1)
$start = $end.AddDays(-6)
# Export one extra day because bridge sleep exports filter by start date.
$fetchStart = $start.AddDays(-1).ToString('yyyy-MM-dd')
$finish = $end.ToString('yyyy-MM-dd')
$run = Join-Path $OutputRoot ($chinaNow.ToString('yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $run -Force | Out-Null
if ($Sync) {
    foreach ($kind in @('sleep','daily_activity','heart_rate')) {
        & $bridge sync --type $kind --start-date $fetchStart --end-date $finish
        if ($LASTEXITCODE -ne 0) { throw "Sync command failed for $kind. Check per-type status as well." }
    }
}
# Full export includes extra datasets locally; the analysis adapter emits an allowlist only.
$raw = Join-Path $run 'private_raw.json'
& $bridge export --format json --start-date $fetchStart --end-date $finish --output $raw
if ($LASTEXITCODE -ne 0) { throw 'Bridge export failed.' }
& $PythonExe "$PSScriptRoot\health_demo.py" --input $raw --start $start.ToString('yyyy-MM-dd') --end $finish --out (Join-Path $run 'analysis')
if ($LASTEXITCODE -ne 0) { throw 'Analysis packaging failed.' }
Write-Host "Created local analysis package under $run"
Write-Host 'Check coverage and compare with Mi Fitness before sharing. Nothing uploaded.'
