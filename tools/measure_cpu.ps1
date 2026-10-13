# Measures average CPU use of MyKeys Studio (Electron + Python backend) over a time window.
param([int]$Seconds = 10)
$procs = { @(Get-Process electron -ErrorAction SilentlyContinue) + @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'mykeys.studio' } | ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }) }
$a = @{}; & $procs | ForEach-Object { $a[$_.Id] = @($_.ProcessName, $_.TotalProcessorTime.TotalMilliseconds) }
Start-Sleep -Seconds $Seconds
$cores = [Environment]::ProcessorCount
$rows = & $procs | Where-Object { $a.ContainsKey($_.Id) } | ForEach-Object {
    $ms = $_.TotalProcessorTime.TotalMilliseconds - $a[$_.Id][1]
    [pscustomobject]@{ Process = $_.ProcessName; Id = $_.Id; 'CPU % (of one core)' = [math]::Round($ms / ($Seconds * 10), 1); 'MB' = [math]::Round($_.WorkingSet64 / 1MB) }
}
$rows | Sort-Object 'CPU % (of one core)' -Descending | Format-Table -AutoSize
$total = ($rows | Measure-Object 'CPU % (of one core)' -Sum).Sum
"TOTAL: {0}% of one core ({1}% of the whole {2}-thread CPU), {3} MB RAM" -f [math]::Round($total, 1), [math]::Round($total / $cores, 2), $cores, ($rows | Measure-Object MB -Sum).Sum
