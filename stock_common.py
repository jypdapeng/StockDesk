import json
import pathlib
import sys
import urllib.request


if getattr(sys, "frozen", False):
    APP_DIR = pathlib.Path(sys.executable).resolve().parent
    RESOURCE_DIR = APP_DIR / "_internal"
else:
    APP_DIR = pathlib.Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR

BASE_DIR = APP_DIR
DEFAULT_CONFIG = APP_DIR / "stocks.json"
QQ_QUOTE_URL = "https://qt.gtimg.cn/q={market}{symbol}"


def default_config_payload() -> dict:
    return {
        "interval": 1,
        "log_file": str(APP_DIR / "stock_monitor.log"),
        "stocks": [],
        "widget": {
            "show_title": False,
            "dock_side": "right",
            "y": 80,
        },
    }


def infer_market(symbol: str) -> str:
    if symbol.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def fetch_quote(symbol: str, market: str | None = None) -> dict:
    market = market or infer_market(symbol)
    url = QQ_QUOTE_URL.format(market=market, symbol=symbol)
    request = urllib.request.Request(
        url,
        headers={
            "Referer": "https://gu.qq.com/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        content = response.read().decode("gbk", errors="replace").strip()

    if '"' not in content:
        raise ValueError(f"unexpected response: {content}")

    payload = content.split('"', 1)[1].rsplit('"', 1)[0]
    fields = payload.split("~")
    if len(fields) < 50:
        raise ValueError(f"incomplete quote payload: {payload}")

    price = float(fields[3])
    prev_close = float(fields[4])
    high = float(fields[33]) if fields[33] else price
    low = float(fields[34]) if fields[34] else price
    change = float(fields[31]) if fields[31] else round(price - prev_close, 2)
    change_pct = float(fields[32]) if fields[32] else 0.0

    return {
        "market": market,
        "symbol": fields[2],
        "name": fields[1],
        "price": price,
        "prev_close": prev_close,
        "open": float(fields[5]),
        "high": high,
        "low": low,
        "change": change,
        "change_pct": change_pct,
        "time": fields[30],
    }


def load_config(path: pathlib.Path | None = None) -> dict:
    path = path or DEFAULT_CONFIG
    path = pathlib.Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(default_config_payload(), fh, ensure_ascii=False, indent=2)
    with pathlib.Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if "stocks" not in data or not isinstance(data["stocks"], list):
        raise ValueError("config must contain a 'stocks' list")

    interval = int(data.get("interval", 30))
    stocks = []
    for item in data["stocks"]:
        symbol = str(item["symbol"]).strip()
        levels = sorted({float(level) for level in item.get("levels", [])}, reverse=True)
        stocks.append(
            {
                "symbol": symbol,
                "market": item.get("market") or infer_market(symbol),
                "levels": levels,
                "label": item.get("label", symbol),
                "cost_price": float(item["cost_price"]) if item.get("cost_price") not in (None, "") else None,
                "lots": int(item["lots"]) if item.get("lots") not in (None, "") else 0,
            }
        )

    widget = data.get("widget", {}) if isinstance(data.get("widget"), dict) else {}
    return {
        "interval": interval,
        "stocks": stocks,
        "log_file": data.get("log_file"),
        "widget": {
            "show_title": bool(widget.get("show_title", False)),
            "dock_side": widget.get("dock_side", "right") if widget.get("dock_side") in {"left", "right"} else "right",
            "y": int(widget.get("y", 80)),
        },
    }


def save_config(path: pathlib.Path, config: dict) -> None:
    path = pathlib.Path(path)
    payload = {
        "interval": int(config.get("interval", 30)),
        "log_file": config.get("log_file"),
        "stocks": [],
        "widget": {
            "show_title": bool(config.get("widget", {}).get("show_title", False)),
            "dock_side": config.get("widget", {}).get("dock_side", "right"),
            "y": int(config.get("widget", {}).get("y", 80)),
        },
    }
    for item in config.get("stocks", []):
        stock = {
            "symbol": str(item["symbol"]).strip(),
            "levels": [float(level) for level in item.get("levels", [])],
        }
        if item.get("market"):
            stock["market"] = item["market"]
        if item.get("label") and item["label"] != stock["symbol"]:
            stock["label"] = item["label"]
        if item.get("cost_price") not in (None, ""):
            stock["cost_price"] = float(item["cost_price"])
        if item.get("lots") not in (None, "", 0):
            stock["lots"] = int(item["lots"])
        payload["stocks"].append(stock)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
