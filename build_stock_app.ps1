$ErrorActionPreference = "Stop"

$python = "C:\Users\11317\AppData\Local\Programs\Python\Python310\python.exe"
$root = "C:\Users\11317\Documents\Playground"
$icon = Join-Path $root "assets\stock_app.ico"
$assets = Join-Path $root "assets"
$dist = Join-Path $root "dist"
$build = Join-Path $root "build"
$spec = Join-Path $root "StockDesk.spec"
$config = Join-Path $root "stocks.json"
$template = Join-Path $root "stocks.template.json"
$backup = Join-Path $root "stocks.user.backup.json"

Set-Location $root

if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
if (Test-Path $spec) { Remove-Item $spec -Force }

Copy-Item $config $backup -Force
Copy-Item $template $config -Force

try {
  & $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name StockDesk `
    --icon $icon `
    --add-data "stocks.json;." `
    --add-data "assets;assets" `
    stock_suite.py
}
finally {
  if (Test-Path $backup) {
    Move-Item $backup $config -Force
  }
}

Write-Host "Build complete: $root\dist\StockDesk\StockDesk.exe"
