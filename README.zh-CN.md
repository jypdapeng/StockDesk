# StockDesk

[English README](README.md)

StockDesk 是一个面向 A 股用户的轻量级 Windows 桌面盯盘工具。

它包含：

- 吸附在屏幕右侧的悬浮小窗
- 实时报价刷新
- 到价 Windows 通知提醒
- 多股票管理
- 成本价与持仓手数跟踪
- 实时盈亏展示
- 一键跳转股票网页行情
- 可直接打包的 Windows 应用与安装包脚本

## 下载

- 安装包：[StockDesk-Setup.exe](https://github.com/jypdapeng/StockDesk/releases/latest/download/StockDesk-Setup.exe)

## 赞赏

如果 StockDesk 对你有帮助，欢迎打赏支持。

支付宝

![支付宝收款码](assets/donate_alipay.jpg)

微信支付

![微信收款码](assets/donate_wechat.jpg)

## 功能特性

- 右侧自动吸附小窗
- 鼠标移入展开，移出自动隐藏
- 直接在小窗里新增、编辑、删除股票
- 为每只股票配置提醒价位
- 跟踪成本价与持仓手数
- 按实时行情展示当前盈亏
- 一键在浏览器中打开选中股票的行情页
- 当价格穿越设定阈值时发送 Windows 通知
- 内置赞赏弹窗，支持支付宝和微信收款码展示

## 项目结构

- `stock_suite.py`
  桌面应用主入口，同时启动小窗和提醒监控。
- `stock_widget.py`
  实时悬浮小窗 UI。
- `stock_monitor.py`
  后台到价监控与通知逻辑。
- `stock_common.py`
  公共配置和行情获取工具。
- `stocks.json`
  本地股票配置文件。
- `build_stock_app.ps1`
  使用 PyInstaller 构建 Windows 应用。
- `StockDesk.iss`
  使用 Inno Setup 构建安装包。

## 环境要求

- Windows 10/11
- Python 3.10+

使用到的 Python 包：

- `pyinstaller`
- `Pillow`

## 源码运行

运行完整应用：

```powershell
python stock_suite.py
```

仅运行小窗：

```powershell
python stock_widget.py
```

仅运行提醒监控：

```powershell
python stock_monitor.py
```

## 配置说明

编辑 `stocks.json`：

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

字段说明：

- `symbol`：股票代码
- `market`：`sh` 或 `sz`
- `levels`：提醒价位
- `cost_price`：平均持仓成本
- `lots`：持仓手数，1 手 = 100 股

## 构建 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build_stock_app.ps1
```

输出：

- `dist/StockDesk/StockDesk.exe`

## 构建安装包

安装 Inno Setup 后运行：

```powershell
& 'C:\Users\11317\AppData\Local\Programs\Inno Setup 6\ISCC.exe' 'C:\Users\11317\Documents\Playground\StockDesk.iss'
```

输出：

- `installer/StockDesk-Setup.exe`

## 说明

- 行情数据当前使用腾讯行情接口。
- 该工具主要用于个人盯盘与便捷查看。
- 不构成任何投资建议。
