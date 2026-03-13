# StockDesk

StockDesk is a lightweight Windows desktop stock monitor for A-share users.

It includes:

- A floating widget that docks to the right edge of the screen
- Real-time quote refresh
- Price level alerts with Windows notifications
- Multiple-stock management
- Cost price and lots tracking
- Real-time profit/loss display
- One-click jump to the stock quote page
- Packaged Windows app and installer build scripts

## Features

- Right-edge auto-hide widget
- Hover to expand, leave to hide
- Add, edit, delete stocks from the widget
- Configure alert levels for each stock
- Track cost price and lots
- Show current P/L based on realtime quote
- Open selected stock in the browser
- Windows notification alerts when price crosses configured levels

## Project Structure

- `stock_suite.py`
  Main desktop entry. Runs widget and alert monitor together.
- `stock_widget.py`
  Floating realtime widget UI.
- `stock_monitor.py`
  Background price crossing monitor and notification logic.
- `stock_common.py`
  Shared config and quote fetching utilities.
- `stocks.json`
  Local stock configuration.
- `build_stock_app.ps1`
  Builds the packaged Windows app with PyInstaller.
- `StockDesk.iss`
  Inno Setup script for building the installer.

## Requirements

- Windows 10/11
- Python 3.10+

Python packages used:

- `pyinstaller`
- `Pillow`

## Run From Source

Run the full app:

```powershell
python stock_suite.py
```

Run only the widget:

```powershell
python stock_widget.py
```

Run only the monitor:

```powershell
python stock_monitor.py
```

## Configuration

Edit `stocks.json`:

```json
{
  "interval": 1,
  "log_file": "stock_monitor.log",
  "stocks": [
    {
      "symbol": "600759",
      "market": "sh",
      "levels": [7.6, 7.1],
      "cost_price": 7.545,
      "lots": 19
    }
  ]
}
```

Field notes:

- `symbol`: stock code
- `market`: `sh` or `sz`
- `levels`: alert price levels
- `cost_price`: average holding cost
- `lots`: position size in hands, where 1 hand = 100 shares

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_stock_app.ps1
```

Output:

- `dist/StockDesk/StockDesk.exe`

## Build Installer

Install Inno Setup, then run:

```powershell
& 'C:\Users\11317\AppData\Local\Programs\Inno Setup 6\ISCC.exe' 'C:\Users\11317\Documents\Playground\StockDesk.iss'
```

Output:

- `installer/StockDesk-Setup.exe`

## Notes

- Quote source is Tencent quote data.
- This tool is intended for personal monitoring and convenience.
- It does not provide investment advice.
