import json
import pathlib
import sys
import urllib.request

APP_VERSION = "1.0.9"

if getattr(sys, "frozen", False):
    APP_DIR = pathlib.Path(sys.executable).resolve().parent
    RESOURCE_DIR = APP_DIR / "_internal"
    APP_RUNTIME = pathlib.Path(sys.executable).resolve()
else:
    APP_DIR = pathlib.Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR
    APP_RUNTIME = pathlib.Path(__file__).resolve()

BASE_DIR = APP_DIR
DEFAULT_CONFIG = APP_DIR / "stocks.json"
QQ_QUOTE_URL = "https://qt.gtimg.cn/q={market}{symbol}"
QQ_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={market}{symbol}"


def default_config_payload() -> dict:
    return {
        "interval": 1,
        "log_file": str(APP_DIR / "stock_monitor.log"),
        "stocks": [],
        "widget": {
            "show_title": False,
            "dock_side": "right",
            "y": 80,
            "active_tab": "holding",
            "sort_by": "default",
            "sort_desc": True,
            "favorite_search": "",
            "favorite_filter": "all",
            "recommend_filter": {
                "min_price": "",
                "max_price": "",
                "min_score": 45,
                "max_quant_risk": "中等",
                "require_levels": True,
                "prefer_positive_news": False,
            },
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


def fetch_intraday_points(symbol: str, market: str | None = None) -> list[tuple[str, float, float]]:
    market = market or infer_market(symbol)
    url = QQ_MINUTE_URL.format(market=market, symbol=symbol)
    request = urllib.request.Request(
        url,
        headers={
            "Referer": "https://gu.qq.com/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))

    payload = data.get("data", {}).get(f"{market}{symbol}", {}).get("data", {})
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    qt = payload.get("qt", {}).get(f"{market}{symbol}", [])
    if not rows:
        return []

    prev_close = None
    if isinstance(qt, list) and len(qt) > 4:
        try:
            prev_close = float(qt[4])
        except (TypeError, ValueError):
            prev_close = None
    if prev_close in (None, 0):
        try:
            prev_close = fetch_quote(symbol, market)["prev_close"]
        except Exception:
            prev_close = None

    points: list[tuple[str, float, float]] = []
    for row in rows:
        parts = row.split(" ")
        if len(parts) < 2:
            continue
        try:
            price = float(parts[1])
        except ValueError:
            continue
        baseline = prev_close if prev_close not in (None, 0) else price
        points.append((parts[0], price, baseline))
    return points


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
        status = str(item.get("status", "")).strip().lower()
        if status not in {"recommended", "favorite", "holding", "closed"}:
            status = "holding" if int(item.get("lots", 0) or 0) > 0 else "favorite"
        trades = item.get("trades", []) if isinstance(item.get("trades"), list) else []
        stocks.append(
            {
                "symbol": symbol,
                "market": item.get("market") or infer_market(symbol),
                "levels": levels,
                "label": item.get("label", symbol),
                "cost_price": float(item["cost_price"]) if item.get("cost_price") not in (None, "") else None,
                "lots": int(item["lots"]) if item.get("lots") not in (None, "") else 0,
                "status": status,
                "trades": trades,
                "manual_mark": item.get("manual_mark", {}) if isinstance(item.get("manual_mark"), dict) else {},
                "ai_mark": item.get("ai_mark", {}) if isinstance(item.get("ai_mark"), dict) else {},
                "recommended_pick": item.get("recommended_pick", {}) if isinstance(item.get("recommended_pick"), dict) else {},
                "pinned": bool(item.get("pinned", False)),
                "import_source": item.get("import_source"),
                "imported_at": item.get("imported_at"),
                "last_import_source": item.get("last_import_source"),
                "last_import_at": item.get("last_import_at"),
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
            "active_tab": widget.get("active_tab", "holding")
            if widget.get("active_tab") in {"recommended", "favorite", "holding", "closed"}
            else "holding",
            "sort_by": widget.get("sort_by", "default")
            if widget.get("sort_by") in {"default", "ai_score", "price", "change_pct"}
            else "default",
            "sort_desc": bool(widget.get("sort_desc", True)),
            "favorite_search": str(widget.get("favorite_search", "")),
            "favorite_filter": widget.get("favorite_filter", "all"),
            "recommend_filter": widget.get("recommend_filter", default_config_payload()["widget"]["recommend_filter"]),
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
            "active_tab": config.get("widget", {}).get("active_tab", "holding"),
            "sort_by": config.get("widget", {}).get("sort_by", "default"),
            "sort_desc": bool(config.get("widget", {}).get("sort_desc", True)),
            "favorite_search": config.get("widget", {}).get("favorite_search", ""),
            "favorite_filter": config.get("widget", {}).get("favorite_filter", "all"),
            "recommend_filter": config.get("widget", {}).get("recommend_filter", default_config_payload()["widget"]["recommend_filter"]),
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
        if item.get("status") in {"recommended", "favorite", "holding", "closed"}:
            stock["status"] = item["status"]
        if isinstance(item.get("trades"), list) and item["trades"]:
            stock["trades"] = item["trades"]
        if isinstance(item.get("manual_mark"), dict) and item["manual_mark"]:
            stock["manual_mark"] = item["manual_mark"]
        if isinstance(item.get("ai_mark"), dict) and item["ai_mark"]:
            stock["ai_mark"] = item["ai_mark"]
        if isinstance(item.get("recommended_pick"), dict) and item["recommended_pick"]:
            stock["recommended_pick"] = item["recommended_pick"]
        if item.get("pinned"):
            stock["pinned"] = True
        if item.get("import_source"):
            stock["import_source"] = item["import_source"]
        if item.get("imported_at"):
            stock["imported_at"] = item["imported_at"]
        if item.get("last_import_source"):
            stock["last_import_source"] = item["last_import_source"]
        if item.get("last_import_at"):
            stock["last_import_at"] = item["last_import_at"]
        payload["stocks"].append(stock)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
