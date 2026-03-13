$ErrorActionPreference = "Stop"

$root = "C:\Users\11317\Documents\Playground"
$target = Join-Path $root "dist\StockDesk\StockDesk.exe"
$icon = Join-Path $root "assets\stock_app.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutName = ([string][char]0x80A1) + ([char]0x7968) + ([char]0x76EF) + ([char]0x76D8) + ".lnk"
$shortcutDescription = ([string][char]0x80A1) + ([char]0x7968) + ([char]0x76EF) + ([char]0x76D8) + ([char]0x684C) + ([char]0x9762) + ([char]0x7248)
$shortcutPath = Join-Path $desktop $shortcutName

if (-not (Test-Path $target)) {
  throw "App not built yet: $target"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = Split-Path $target
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = $shortcutDescription
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath"
