$ErrorActionPreference = "Stop"

$root = "C:\Users\11317\Documents\Playground"
$target = Join-Path $root "dist\StockDesk\StockDesk.exe"
$icon = Join-Path $root "assets\stock_app.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "StockDesk.lnk"

if (-not (Test-Path $target)) {
  throw "App not built yet: $target"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = Split-Path $target
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "StockDesk realtime stock monitor"
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath"
