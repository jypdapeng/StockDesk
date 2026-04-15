$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match "python|py" -and $_.CommandLine -match "litellm" -and $_.CommandLine -match "--port 4000"
}

if (-not $existing) {
    Write-Host "No running LiteLLM proxy found."
    exit 0
}

$existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "LiteLLM proxy stopped."
