# 股票盯盘

[English README](README.zh-CN.md)

`股票盯盘` 是一个面向 A 股用户的轻量级 Windows 桌面盯盘工具，支持悬浮小窗、价格提醒、分时图、AI 分析、AI 对话、新闻分析、图片导入持仓/自选，以及推荐候选股。

## 下载

- 安装包：[StockDesk-Setup.exe](https://github.com/jypdapeng/StockDesk/releases/latest/download/StockDesk-Setup.exe)
- 官网 / 演示页：[GitHub Pages](https://jypdapeng.github.io/StockDesk/)

## 主要功能

- 悬浮盯盘小窗：可拖动到桌面任意位置，松手后自动吸附左侧或右侧
- 四个页签：`推荐 / 收藏 / 持有 / 清仓`
- 分时图：支持当天完整分时与鼠标悬停查看价格
- 价格提醒：到价、突破、跌破时弹出中文提醒
- 持仓管理：支持成本价、手数、盈亏、加仓/减仓记录
- AI 分析：结合规则、走势、关键位、风险标签、次日预案
- AI 对话：围绕当前股票持续追问，并保留单股历史对话
- 新闻分析：抓取相关新闻，给出正向 / 负向倾向和操作建议
- 图片导入：支持从券商截图导入持仓、自选
- AI 推荐：结合当前大盘、本地股票池和市场强势候选，推荐最多 5 只观察标的

## 推荐逻辑

推荐页支持：

- AI 推荐按钮
- 推荐条件过滤：
  - 最低价格 / 最高价格
  - 最低评分
  - 最大量化风险
  - 是否要求提醒位
  - 是否优先正向新闻

推荐来源不只限于本地自选，还会从市场里补充近期相对强势、符合条件的候选股。

## AI 相关

支持接入：

- 百炼（DashScope compatible mode）
- DeepSeek

说明：

- `ai_settings.json` 只保存在本机，不会提交到仓库
- AI 对话历史 `ai_chat_history.json` 也只保存在本机
- 本仓库不会包含你的 API Key、聊天记录或个人账户配置

## 项目结构

- `stock_widget.py`
  主悬浮小窗 UI
- `stock_monitor.py`
  后台到价提醒
- `stock_common.py`
  公共配置、行情和分时数据工具
- `analysis_engine.py`
  规则分析引擎
- `analysis_panel.py`
  AI 分析面板
- `ai_chat_panel.py`
  AI 对话面板
- `stock_news.py`
  新闻抓取与倾向分析
- `news_panel.py`
  相关新闻面板
- `image_import_panel.py`
  截图导入持仓 / 自选
- `market_recommend.py`
  推荐逻辑（本地股票池 + 市场候选）
- `ai_provider.py`
  AI 提供方接入
- `stocks.template.json`
  默认配置模板

## 运行

运行小窗：

```powershell
python stock_widget.py
```

运行到价提醒：

```powershell
python stock_monitor.py
```

## 打包

构建 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_stock_app.ps1
```

输出：

- `dist/StockDesk/StockDesk.exe`

构建安装包：

```powershell
& 'C:\Users\11317\AppData\Local\Programs\Inno Setup 6\ISCC.exe' 'C:\Users\11317\Documents\Playground\StockDesk.iss'
```

输出：

- `installer/StockDesk-Setup.exe`

## 赞赏

如果这个项目对你有帮助，欢迎支持：

支付宝

![Alipay QR Code](assets/donate_alipay.jpg)

微信支付

![WeChat Pay QR Code](assets/donate_wechat.jpg)

## 说明

- 行情数据当前主要使用腾讯行情接口
- 本工具用于盯盘、记录和辅助分析
- 不构成任何投资建议
