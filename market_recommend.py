import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ai_provider import recommend_candidates_with_ai
from analysis_engine import analyze_stock
from market_state import get_market_state
from stock_common import fetch_quote, infer_market
from stock_news import analyze_news_bias, fetch_stock_news


RISK_LEVEL_ORDER = {"偏低": 0, "中等": 1, "偏高": 2}
EASTMONEY_POOL_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23"
    "&fields=f12,f14,f2,f3"
)


def _is_kcb(symbol: str, market: str | None = None) -> bool:
    symbol = str(symbol or "").strip()
    return symbol.startswith("688") or symbol.startswith("689")


def _limit_up_threshold(symbol: str) -> float:
    code = str(symbol or "").strip()
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("8", "4")):
        return 30.0
    return 10.0


def _build_local_pool(stocks: list[dict], limit: int = 6) -> list[dict]:
    pool = []
    for item in stocks:
        symbol = str(item.get("symbol", "")).strip()
        if not symbol.isdigit():
            continue
        if item.get("status") == "closed":
            continue
        priority = 0
        if item.get("status") == "favorite":
            priority += 3
        if item.get("status") == "holding":
            priority += 2
        if item.get("levels"):
            priority += 2
        if item.get("manual_mark"):
            priority += 1
        pool.append((priority, item))
    pool.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _priority, item in pool[:limit]]


def _fetch_market_candidates(limit: int = 8) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        EASTMONEY_POOL_URL.format(limit=max(limit * 2, 16)),
        headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    rows = payload.get("data", {}).get("diff", []) or []
    candidates: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("f12", "")).strip()
        label = str(row.get("f14", "")).strip()
        if not symbol.isdigit() or not label:
            continue
        if "ST" in label.upper():
            continue
        try:
            price = float(row.get("f2") or 0)
            change_pct = float(row.get("f3") or 0)
        except Exception:
            continue
        if price <= 0:
            continue
        candidates.append(
            {
                "symbol": symbol,
                "market": infer_market(symbol),
                "label": label,
                "levels": [],
                "status": "recommended",
                "source": "market",
                "market_price": price,
                "market_change_pct": change_pct,
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def _combine_candidate_pool(stocks: list[dict], local_limit: int = 5, market_limit: int = 6) -> list[dict]:
    combined: list[dict] = []
    seen: set[str] = set()

    for item in _build_local_pool(stocks, limit=local_limit):
        symbol = str(item.get("symbol", "")).strip()
        if symbol and symbol not in seen:
            combined.append(item)
            seen.add(symbol)

    for item in _fetch_market_candidates(limit=market_limit):
        symbol = str(item.get("symbol", "")).strip()
        if symbol and symbol not in seen:
            combined.append(item)
            seen.add(symbol)

    return combined


def _candidate_summary(item: dict) -> dict[str, Any] | None:
    try:
        analysis = analyze_stock(item)
    except Exception:
        return None

    try:
        quote = fetch_quote(item["symbol"], item.get("market"))
        latest_price = float(quote.get("price") or 0)
        latest_change_pct = float(quote.get("change_pct") or 0)
    except Exception:
        latest_price = float(item.get("market_price") or 0)
        latest_change_pct = float(item.get("market_change_pct") or 0)

    try:
        news_items = fetch_stock_news(item["symbol"], item.get("market"), limit=8)
        news_bias = analyze_news_bias(news_items)
    except Exception:
        news_bias = {"overall": "中性", "positive": [], "negative": [], "neutral": []}

    return {
        "symbol": item["symbol"],
        "label": item.get("label") or item["symbol"],
        "status": item.get("status"),
        "source": item.get("source", "local"),
        "market": item.get("market") or infer_market(item["symbol"]),
        "levels": item.get("levels", []),
        "latest_price": latest_price,
        "latest_change_pct": latest_change_pct,
        "score": analysis["score"]["score"],
        "risk": analysis["score"]["risk"],
        "quant_risk": analysis["quant_risk"]["status"],
        "quant_risk_label": analysis["quant_risk"]["risk"],
        "next_day_plan": analysis["next_day_plan"][:2],
        "open_strength": analysis["open_strength"]["status"],
        "close_strength": analysis["close_strength"]["status"],
        "one_to_two": analysis["one_to_two"]["status"],
        "facts": analysis["facts"][:2],
        "observations": analysis["observations"][:3],
        "news_bias": news_bias["overall"],
        "market_mood": analysis["market_state"]["mood"],
        "market_tactic": analysis["market_state"]["tactic"],
    }


def _apply_filters(candidates: list[dict], filters: dict[str, Any] | None) -> list[dict]:
    if not filters:
        return candidates

    min_price = filters.get("min_price", "")
    max_price = filters.get("max_price", "")
    min_score = int(filters.get("min_score", 45) or 45)
    max_quant_risk = str(filters.get("max_quant_risk", "中等"))
    require_levels = bool(filters.get("require_levels", True))
    prefer_positive_news = bool(filters.get("prefer_positive_news", False))
    allow_kcb = bool(filters.get("allow_kcb", False))
    avoid_limit_up = bool(filters.get("avoid_limit_up", True))
    try:
        max_chase_pct = float(filters.get("max_chase_pct", 7.5) or 7.5)
    except Exception:
        max_chase_pct = 7.5

    try:
        min_price_value = float(min_price) if str(min_price).strip() else None
    except Exception:
        min_price_value = None
    try:
        max_price_value = float(max_price) if str(max_price).strip() else None
    except Exception:
        max_price_value = None

    max_risk_order = RISK_LEVEL_ORDER.get(max_quant_risk, 1)
    filtered: list[dict] = []
    for item in candidates:
        latest_price = float(item.get("latest_price") or 0)
        if min_price_value is not None and latest_price < min_price_value:
            continue
        if max_price_value is not None and latest_price > max_price_value:
            continue
        if int(item.get("score", 0) or 0) < min_score:
            continue
        if RISK_LEVEL_ORDER.get(str(item.get("quant_risk") or "中等"), 1) > max_risk_order:
            continue
        if require_levels and item.get("source") == "local" and not item.get("levels"):
            continue
        news_bias = str(item.get("news_bias") or "").strip()
        if prefer_positive_news and news_bias not in {"偏正向", "positive"}:
            continue
        if not allow_kcb and _is_kcb(item.get("symbol", ""), item.get("market")):
            continue
        change_pct = float(item.get("latest_change_pct") or 0)
        if change_pct >= max_chase_pct:
            continue
        if avoid_limit_up:
            up_limit = _limit_up_threshold(str(item.get("symbol", "")))
            if change_pct >= max(0.0, up_limit - 0.3):
                continue
        filtered.append(item)
    return filtered


def generate_recommendations(stocks: list[dict], filters: dict[str, Any] | None = None) -> dict[str, Any]:
    market = get_market_state()
    candidates: list[dict[str, Any]] = []
    pool = _combine_candidate_pool(stocks)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_candidate_summary, item): item for item in pool}
        for future in as_completed(futures):
            try:
                summary = future.result()
            except Exception:
                summary = None
            if summary:
                candidates.append(summary)

    candidates = _apply_filters(candidates, filters)
    if not candidates:
        return {
            "market": market,
            "picks": [],
            "content": "当前没有符合推荐条件的候选股票，请调整推荐条件或稍后再试。",
            "candidates": [],
        }

    ai_result = recommend_candidates_with_ai(market, candidates)
    picks = ai_result.get("picks", [])
    candidate_map = {item["symbol"]: item for item in candidates}
    if picks:
        enriched_picks = []
        for item in picks:
            symbol = str(item.get("symbol", "")).strip()
            base = candidate_map.get(symbol, {})
            merged = dict(base)
            merged.update(item)
            enriched_picks.append(merged)
        picks = enriched_picks
    if not picks:
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.get("score", 0),
                item.get("news_bias") in {"偏正向", "positive"},
                item.get("quant_risk") != "偏高",
                item.get("latest_change_pct", 0),
            ),
            reverse=True,
        )[:5]
        picks = [
            {
                "symbol": item["symbol"],
                "label": item["label"],
                "market": item.get("market"),
                "action": "观察",
                "score": item["score"],
                "reason": f"{item['market_mood']} / {item['open_strength']} / {item['close_strength']} / {item['news_bias']}",
                "playbook": item["next_day_plan"][0] if item["next_day_plan"] else "先看关键位承接。",
                "risk_note": item["quant_risk_label"],
                "source": item.get("source", "local"),
            }
            for item in ranked
        ]

    return {
        "market": market,
        "picks": picks[:5],
        "content": ai_result.get("content", ""),
        "candidates": candidates,
    }

