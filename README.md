# StockDesk

[简体中文](README.zh-CN.md)

StockDesk is a lightweight Windows desktop stock monitor for A-share users.

## Download

- Installer: [StockDesk-Setup.exe](https://github.com/jypdapeng/StockDesk/releases/latest/download/StockDesk-Setup.exe)
- Website / Demo: [GitHub Pages](https://jypdapeng.github.io/StockDesk/)
- Project plan: [PROJECT_PLAN.md](./PROJECT_PLAN.md)
- Development progress: [DEVELOPMENT_PROGRESS.md](./DEVELOPMENT_PROGRESS.md)

## Features

- Draggable floating widget with left/right edge docking
- Tabs for `Recommended / Favorites / Holdings / Closed`
- Intraday chart with hover price inspection
- Price alerts for touch / breakout / breakdown
- Closed positions are excluded from alert monitoring
- Cost, lots, profit/loss, and add/reduce position records
- Rule-based analysis plus AI explanation
- AI chat with per-stock history
- Follow-up AI chat for recommendation results using the current market context
- News analysis with positive / negative bias
- Screenshot import for holdings and watchlists
- AI recommendations based on market context, local pool, and strong market candidates

## AI

Supported providers:

- Bailian
- DeepSeek

Notes:

- `ai_settings.json` is local only and ignored by git
- `ai_chat_history.json` is local only
- `ai_recommend_chat_history.json` is local only
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
