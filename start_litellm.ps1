$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $root "litellm.config.yaml"
$templatePath = Join-Path $root "litellm.config.template.yaml"
$logDir = Join-Path $root "output"
$logPath = Join-Path $logDir "litellm.log"
$errPath = Join-Path $logDir "litellm.err.log"

if (-not (Test-Path $configPath)) {
    if (-not (Test-Path $templatePath)) {
        throw "LiteLLM template config not found: $templatePath"
    }
    Copy-Item $templatePath $configPath -Force
    Write-Host "Created LiteLLM config: $configPath"
}

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "litellm" -and $_.CommandLine -match "--port 4000"
}
if ($existing) {
    $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep -Seconds 1
}

$litellm = "C:\Users\11317\AppData\Local\Programs\Python\Python310\Scripts\litellm.exe"
$litellmArgs = @("--config", $configPath, "--host", "127.0.0.1", "--port", "4000")
Start-Process -FilePath $litellm -ArgumentList $litellmArgs -WindowStyle Hidden -RedirectStandardOutput $logPath -RedirectStandardError $errPath
Write-Host "LiteLLM started at http://127.0.0.1:4000/v1"
