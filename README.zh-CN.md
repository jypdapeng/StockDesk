# StockDesk

[简体中文说明](README.md)

StockDesk is a lightweight Windows desktop stock monitor for A-share users.

It includes:

- A draggable floating widget with left/right edge docking
- Tabs for `Recommended / Favorites / Holdings / Closed`
- Intraday chart with hover price inspection
- Price alerts for touch / breakout / breakdown
- Cost, lots, profit/loss, and add/reduce position records
- Rule-based analysis plus AI explanation
- AI chat with per-stock history
- News analysis with positive / negative bias
- Screenshot import for holdings and watchlists
- AI recommendations based on market context, local pool, and strong market candidates

## Download

- Installer: [StockDesk-Setup.exe](https://github.com/jypdapeng/StockDesk/releases/latest/download/StockDesk-Setup.exe)
- Website / Demo: [GitHub Pages](https://jypdapeng.github.io/StockDesk/)

## AI

Supported providers:

- Bailian
- DeepSeek

Notes:

- `ai_settings.json` is local only and is ignored by git
- `ai_chat_history.json` is also local only
- API keys, personal holdings, and local chat history are not committed to this repository

## Run

Run the widget:

```powershell
python stock_widget.py
```

Run the alert monitor:

```powershell
python stock_monitor.py
```

## Build

Build the EXE:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_stock_app.ps1
```

Build the installer:

```powershell
& 'C:\Users\11317\AppData\Local\Programs\Inno Setup 6\ISCC.exe' 'C:\Users\11317\Documents\Playground\StockDesk.iss'
```

## Donate

Alipay

![Alipay QR Code](assets/donate_alipay.jpg)

WeChat Pay

![WeChat Pay QR Code](assets/donate_wechat.jpg)

## Disclaimer

This project is for monitoring, recording, and analysis assistance only.
It does not constitute investment advice.
