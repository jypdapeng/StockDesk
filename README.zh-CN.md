# 股票盯盘

[English](README.md)

`股票盯盘` 是一个面向 A 股用户的轻量级 Windows 桌面盯盘工具。

## 下载

- 安装包：[StockDesk-Setup.exe](https://github.com/jypdapeng/StockDesk/releases/latest/download/StockDesk-Setup.exe)
- 官网 / 演示页：[GitHub Pages](https://jypdapeng.github.io/StockDesk/)

## 主要功能

- 可拖动悬浮小窗，支持左侧 / 右侧吸附
- `推荐 / 收藏 / 持有 / 清仓` 四个页签
- 当天完整分时图，支持鼠标悬停查看价格
- 到价 / 突破 / 跌破提醒
- 清仓后自动停止提醒
- 持仓成本、手数、盈亏、加仓 / 减仓记录
- 规则分析 + AI 解释
- 单只股票 AI 对话，并保留历史记录
- 推荐结果 AI 继续追问，自动带上当天市场环境
- 相关新闻分析，区分正向 / 负向 / 中性
- 支持券商截图导入持仓、自选
- 基于市场环境、本地股票池和市场强势候选生成 AI 推荐

## AI

支持接入：

- 百炼
- DeepSeek

说明：

- `ai_settings.json` 仅保存在本机，不会提交到仓库
- `ai_chat_history.json` 仅保存在本机
- `ai_recommend_chat_history.json` 仅保存在本机
- 仓库不会包含你的 API Key、个人持仓和本地对话记录

## 运行

启动小窗：

```powershell
python stock_widget.py
```

启动提醒：

```powershell
python stock_monitor.py
```

## 打包

生成 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_stock_app.ps1
```

生成安装包：

```powershell
& 'C:\Users\11317\AppData\Local\Programs\Inno Setup 6\ISCC.exe' 'C:\Users\11317\Documents\Playground\StockDesk.iss'
```

## 赞赏

支付宝

![支付宝收款码](assets/donate_alipay.jpg)

微信支付

![微信收款码](assets/donate_wechat.jpg)

## 免责声明

本项目仅用于盯盘、记录和辅助分析，不构成任何投资建议。
