from market_state import get_market_state
from stock_common import fetch_intraday_points, fetch_quote


def _describe_trend(change_pct: float) -> str:
    if change_pct <= -5:
        return "弱势下跌"
    if change_pct <= -2:
        return "偏弱震荡"
    if change_pct < 2:
        return "震荡整理"
    if change_pct < 5:
        return "温和走强"
    return "强势上攻"


def _safe_levels(levels: list[float], price: float) -> tuple[list[float], list[float]]:
    above = sorted([level for level in levels if level >= price])
    below = sorted([level for level in levels if level <= price], reverse=True)
    return above, below


def _intraday_position_ratio(points: list[tuple[str, float, float]]) -> float | None:
    if not points:
        return None
    prices = [item[1] for item in points]
    high = max(prices)
    low = min(prices)
    span = max(high - low, 0.01)
    return (prices[-1] - low) / span


def _open_session_strength(points: list[tuple[str, float, float]]) -> dict:
    if len(points) < 5:
        return {"status": "信息不足", "score": 0, "detail": "缺少足够的开盘前段分时数据。"}
    open_price = points[0][1]
    early_prices = [item[1] for item in points[:5]]
    if early_prices[-1] >= open_price and max(early_prices) >= open_price:
        return {"status": "开盘承接偏强", "score": 1, "detail": "前五个分时点整体没有明显走弱。"}
    if early_prices[-1] < open_price and min(early_prices) < open_price:
        return {"status": "开盘承接偏弱", "score": -1, "detail": "开盘后较快走弱，承接一般。"}
    return {"status": "开盘强弱一般", "score": 0, "detail": "前段分时没有明显优势，也没有极端走坏。"}


def _close_strength(points: list[tuple[str, float, float]], quote: dict) -> dict:
    if not points:
        return {"status": "信息不足", "score": 0, "detail": "缺少分时数据，无法判断尾盘强度。"}
    ratio = _intraday_position_ratio(points) or 0
    last_prices = [item[1] for item in points[-5:]] if len(points) >= 5 else [item[1] for item in points]
    close_price = points[-1][1]
    prev_close = quote["prev_close"]
    if ratio >= 0.75 and close_price >= prev_close and close_price >= max(last_prices):
        return {"status": "尾盘强", "score": 2, "detail": "收盘位置接近日内高位，尾盘承接较好。"}
    if ratio <= 0.35 or close_price <= min(last_prices):
        return {"status": "尾盘弱", "score": -2, "detail": "收盘位置偏低，尾盘承接偏弱。"}
    return {"status": "尾盘一般", "score": 0, "detail": "尾盘没有明显抢筹，也没有极端走坏。"}


def _volume_price_pattern(quote: dict, points: list[tuple[str, float, float]]) -> dict:
    if not points:
        return {"status": "信息不足", "score": 0, "detail": "缺少分时数据，无法识别量价结构。"}
    prices = [item[1] for item in points]
    prev_close = quote["prev_close"]
    day_high = max(prices)
    day_low = min(prices)
    close_price = prices[-1]
    amplitude = (day_high - day_low) / max(prev_close, 0.01)
    ratio = _intraday_position_ratio(points) or 0
    if amplitude > 0.05 and quote["change_pct"] < 0 and ratio < 0.45:
        return {"status": "冲高回落风险", "score": -2, "detail": "振幅较大但收盘偏弱，更像分歧放大后的回落。"}
    if amplitude < 0.02 and 0.45 <= ratio <= 0.7:
        return {"status": "窄幅整理", "score": 0, "detail": "更像等待方向选择的整理结构。"}
    if quote["change_pct"] > 2 and ratio >= 0.7 and close_price >= prev_close:
        return {"status": "价强结构偏正面", "score": 1, "detail": "日内价格重心偏上，结构相对完整。"}
    return {"status": "普通波动结构", "score": 0, "detail": "没有特别强的进攻信号，也没有极端弱势结构。"}


def _one_to_two_candidate(quote: dict, points: list[tuple[str, float, float]]) -> dict:
    if not points:
        return {"status": "信息不足", "score": 0, "detail": "缺少分时数据，无法做一进二过滤。"}
    close_strength = _close_strength(points, quote)
    if quote["change_pct"] >= 3 and close_strength["score"] >= 1:
        return {"status": "可列入短线候选", "score": 1, "detail": "日内表现和尾盘承接都不差，适合次日继续观察。"}
    if quote["change_pct"] <= 0 or close_strength["score"] < 0:
        return {"status": "不适合一进二", "score": -1, "detail": "日内不够强，或者尾盘承接偏弱，延续性要打折。"}
    return {"status": "仅弱观察", "score": 0, "detail": "有一定表现，但还不到优先短线候选标准。"}


def _level_signals(price: float, levels: list[float]) -> list[str]:
    signals = []
    for level in sorted(levels, reverse=True)[:5]:
        diff = price - float(level)
        pct = abs(diff) / max(float(level), 0.01)
        if pct <= 0.003:
            signals.append(f"关键位 {level:.2f}：当前正在附近反复博弈。")
        elif diff > 0 and pct <= 0.02:
            signals.append(f"关键位 {level:.2f}：已收复，但仍需要继续站稳。")
        elif diff < 0 and pct <= 0.02:
            signals.append(f"关键位 {level:.2f}：尚未收复，仍是上方压力。")
    return signals


def _next_day_plan(quote: dict, points: list[tuple[str, float, float]], stock_item: dict) -> list[str]:
    plans = []
    price = quote["price"]
    levels = sorted(stock_item.get("levels", []), reverse=True)
    above, below = _safe_levels(levels, price)
    close_strength = _close_strength(points, quote)

    if above:
        plans.append(f"如果次日高开并站上 {above[0]:.2f}，重点看能否放量站稳，而不是只看瞬间冲高。")
    else:
        plans.append("如果次日高开，重点看是否能维持高位承接，避免冲高回落。")

    if below:
        plans.append(f"如果次日平开震荡，优先看 {below[0]:.2f} 一带是否守住。")
        plans.append(f"如果次日低开并跌破 {below[0]:.2f}，更偏向防守而不是盲目补仓。")
    else:
        plans.append("如果次日平开震荡，重点看分时承接和价格重心是否上移。")

    if close_strength["score"] < 0:
        plans.append("由于当前尾盘承接偏弱，次日更需要先确认强度，避免把弱修复当成反转。")
    else:
        plans.append("如果次日继续强于大盘且尾盘维持强势，可继续保守跟踪，不要情绪化追价。")
    return plans


def _quant_risk_analysis(quote: dict, points: list[tuple[str, float, float]], stock_item: dict) -> dict:
    if not points:
        return {"status": "中等", "risk": "信息不足", "detail": "缺少分时数据，暂时无法判断量化风险。"}

    prices = [item[1] for item in points]
    prev_close = quote["prev_close"]
    day_high = max(prices)
    day_low = min(prices)
    close_ratio = _intraday_position_ratio(points) or 0
    amplitude = (day_high - day_low) / max(prev_close, 0.01)
    change_pct = quote["change_pct"]
    levels = sorted(stock_item.get("levels", []) or [])
    nearest = min((abs(quote["price"] - level) / max(level, 0.01) for level in levels), default=1)

    if change_pct <= -3 and close_ratio <= 0.35:
        return {"status": "偏高", "risk": "弱势追击风险", "detail": "日内走弱且收盘位置偏低，这类结构更容易出现弱修复反复收割。"}
    if amplitude >= 0.05 and close_ratio < 0.5:
        return {"status": "偏高", "risk": "冲高回落风险", "detail": "振幅较大但收盘不强，高波动分歧环境里不适合追单。"}
    if nearest <= 0.003:
        return {"status": "中等", "risk": "关键位博弈", "detail": "当前处于关键位附近，多空博弈容易放大，适合等方向确认。"}
    if change_pct >= 2 and close_ratio >= 0.7:
        return {"status": "偏低", "risk": "结构尚可", "detail": "日内重心偏上，至少不是典型的弱势被动局面，但仍要防追高。"}
    return {"status": "中等", "risk": "普通波动", "detail": "当前更像正常波动结构，关键是别在模糊区间频繁操作。"}


def _trading_risk_flags(quote: dict, points: list[tuple[str, float, float]], stock_item: dict, market_state: dict) -> list[str]:
    flags: list[str] = []
    if not points:
        return flags
    prices = [item[1] for item in points]
    prev_close = quote["prev_close"]
    day_high = max(prices)
    day_low = min(prices)
    close_ratio = _intraday_position_ratio(points) or 0
    amplitude = (day_high - day_low) / max(prev_close, 0.01)
    change_pct = quote["change_pct"]

    if amplitude >= 0.05 and close_ratio < 0.5:
        flags.append("冲高回落")
    if change_pct <= -2 and close_ratio <= 0.4:
        flags.append("弱市降权")
    if change_pct >= 3 and close_ratio < 0.6:
        flags.append("拥挤观察")
    if market_state["mood"] in {"偏弱", "震荡偏弱"}:
        flags.append("先防守")
    if stock_item.get("levels"):
        price = quote["price"]
        nearest = min(abs(price - float(level)) / max(float(level), 0.01) for level in stock_item.get("levels", []))
        if nearest <= 0.003:
            flags.append("关键位博弈")
    return flags


def _discipline_reminder(quote: dict, points: list[tuple[str, float, float]], stock_item: dict) -> str:
    close_strength = _close_strength(points, quote) if points else {"score": 0}
    levels = sorted(stock_item.get("levels", []) or [], reverse=True)
    below = sorted([level for level in levels if level <= quote["price"]], reverse=True)
    if close_strength["score"] < 0 and below:
        return f"如果次日继续走弱并跌破 {below[0]:.2f}，优先执行防守，不把弱修复当成反转。"
    if levels:
        return f"如果次日反弹，先看 {' / '.join(f'{x:.2f}' for x in levels[:2])} 附近的收复与站稳情况。"
    return "先设好高开、平开、低开的观察条件，再决定是否继续持有或减压。"


def _score_analysis(quote: dict, points: list[tuple[str, float, float]], stock_item: dict, market_state: dict) -> dict:
    score = 50
    reasons: list[str] = []

    change_pct = quote["change_pct"]
    if change_pct >= 3:
        score += 15
        reasons.append("日内涨幅偏强，加分。")
    elif change_pct >= 0:
        score += 5
        reasons.append("日内未走弱，略加分。")
    elif change_pct <= -5:
        score -= 20
        reasons.append("日内跌幅较大，明显减分。")
    elif change_pct <= -2:
        score -= 10
        reasons.append("日内偏弱，减分。")

    if points:
        open_strength = _open_session_strength(points)
        close_strength = _close_strength(points, quote)
        vp_pattern = _volume_price_pattern(quote, points)
        score += open_strength["score"] * 4
        score += close_strength["score"] * 6
        score += vp_pattern["score"] * 5
        reasons.append(f"开盘强弱：{open_strength['status']}。")
        reasons.append(f"尾盘强弱：{close_strength['status']}。")
        reasons.append(f"量价结构：{vp_pattern['status']}。")

        ratio = _intraday_position_ratio(points)
        if ratio is not None:
            if ratio >= 0.75:
                score += 10
                reasons.append("收盘位置接近日内高位，加分。")
            elif ratio <= 0.35:
                score -= 10
                reasons.append("收盘位置偏低，减分。")

    if market_state["mood"] in {"偏弱", "震荡偏弱"}:
        score -= 8
        reasons.append("市场环境偏弱，同样图形成功率要打折。")
    elif market_state["mood"] in {"偏强", "震荡偏强"}:
        score += 5
        reasons.append("市场环境不差，结构延续性略有加分。")

    cost_price = stock_item.get("cost_price")
    if cost_price not in (None, ""):
        if quote["price"] >= float(cost_price):
            score += 5
            reasons.append("现价不低于成本，持仓压力较小。")
        else:
            score -= 5
            reasons.append("现价低于成本，持仓压力偏大。")

    score = max(0, min(100, score))
    if score >= 70:
        risk = "低到中"
    elif score >= 45:
        risk = "中"
    else:
        risk = "中到高"
    return {"score": score, "risk": risk, "reasons": reasons}


def _overnight_hold_analysis(quote: dict, points: list[tuple[str, float, float]], market_state: dict) -> dict:
    matched: list[str] = []
    blocked: list[str] = []

    if not points:
        blocked.append("缺少当日分时数据，无法判断尾盘位置。")
        return {"status": "信息不足", "matched": matched, "blocked": blocked}

    position_ratio = _intraday_position_ratio(points) or 0
    prices = [item[1] for item in points]
    day_high = max(prices)
    day_low = min(prices)
    prev_close = points[-1][2]
    amplitude = (day_high - day_low) / max(prev_close, 0.01)

    if position_ratio >= 0.75:
        matched.append("收盘位置接近日内高位。")
    else:
        blocked.append("收盘位置不够强，不符合尾盘强势优先条件。")

    if quote["change_pct"] > 0:
        matched.append("日线涨跌幅为正。")
    else:
        blocked.append("日线表现偏弱，不符合偏强隔夜思路。")

    if amplitude <= 0.08:
        matched.append("日内波动没有极端失控。")
    else:
        blocked.append("日内波动偏大，隔夜不确定性更高。")

    if quote["price"] >= prev_close:
        matched.append("现价不低于昨收。")
    else:
        blocked.append("现价低于昨收，次日延续性要打折。")

    if market_state["mood"] in {"偏弱", "震荡偏弱"}:
        blocked.append("市场环境偏弱，隔夜战法整体应降权。")

    if len(blocked) == 0:
        status = "偏符合"
    elif len(matched) >= 2:
        status = "部分符合"
    else:
        status = "不符合"
    return {"status": status, "matched": matched, "blocked": blocked}


def _build_method_hits(quote: dict, points: list[tuple[str, float, float]]) -> list[str]:
    hits: list[str] = []
    open_strength = _open_session_strength(points) if points else {"status": "信息不足", "detail": ""}
    close_strength = _close_strength(points, quote) if points else {"status": "信息不足", "detail": ""}
    vp_pattern = _volume_price_pattern(quote, points) if points else {"status": "信息不足", "detail": ""}
    one_to_two = _one_to_two_candidate(quote, points) if points else {"status": "信息不足", "detail": ""}

    if quote["change_pct"] <= -5:
        hits.append("高危节点：当前跌幅较大，优先防守，避免把弱反弹误判成转强。")
    elif quote["change_pct"] >= 3:
        hits.append("强弱延续观察：今日整体表现偏强，可继续看量价是否同步。")

    hits.append(f"开盘强弱：{open_strength['status']}。{open_strength['detail']}")
    hits.append(f"尾盘强度：{close_strength['status']}。{close_strength['detail']}")
    hits.append(f"量价形态：{vp_pattern['status']}。{vp_pattern['detail']}")
    hits.append(f"一进二过滤：{one_to_two['status']}。{one_to_two['detail']}")
    return hits


def analyze_stock(stock_item: dict) -> dict:
    symbol = stock_item["symbol"]
    market = stock_item.get("market")
    quote = fetch_quote(symbol, market)
    points = fetch_intraday_points(symbol, market)
    market_state = get_market_state()

    price = quote["price"]
    prev_close = quote["prev_close"]
    change_pct = quote["change_pct"]
    levels = stock_item.get("levels", [])
    above_levels, below_levels = _safe_levels(levels, price)
    cost_price = stock_item.get("cost_price")
    lots = int(stock_item.get("lots", 0) or 0)
    shares = lots * 100
    pnl = (price - float(cost_price)) * shares if cost_price not in (None, "") and lots > 0 else None

    overnight = _overnight_hold_analysis(quote, points, market_state)
    open_strength = _open_session_strength(points)
    close_strength = _close_strength(points, quote)
    vp_pattern = _volume_price_pattern(quote, points)
    one_to_two = _one_to_two_candidate(quote, points)
    quant_risk = _quant_risk_analysis(quote, points, stock_item)
    risk_flags = _trading_risk_flags(quote, points, stock_item, market_state)
    discipline_tip = _discipline_reminder(quote, points, stock_item)
    level_signals = _level_signals(price, levels)
    next_day_plan = _next_day_plan(quote, points, stock_item)
    score = _score_analysis(quote, points, stock_item, market_state)

    facts = [
        f"{quote['name']}（{symbol}）最新价格 {price:.2f}，较昨收 {prev_close:.2f} 变动 {change_pct:+.2f}%。",
        f"当前走势状态：{_describe_trend(change_pct)}。",
        f"今日市场状态：{market_state['mood']}，更偏向“{market_state['tactic']}”。",
        f"量价评分：{score['score']} / 100，当前风险级别：{score['risk']}。",
    ]
    if points:
        day_high = max(p[1] for p in points)
        day_low = min(p[1] for p in points)
        facts.append(f"当日分时区间约为 {day_low:.2f} - {day_high:.2f}，共抓到 {len(points)} 个分时点。")
    if cost_price not in (None, "") and lots > 0 and pnl is not None:
        facts.append(f"你的持仓成本 {float(cost_price):.3f}，持仓 {lots} 手，当前浮动盈亏 {pnl:+.2f} 元。")

    observations = []
    if above_levels:
        observations.append(f"上方关注位：{' / '.join(f'{x:.2f}' for x in above_levels[:3])}。")
    if below_levels:
        observations.append(f"下方观察位：{' / '.join(f'{x:.2f}' for x in below_levels[:3])}。")
    observations.extend(level_signals)
    observations.extend(_build_method_hits(quote, points))
    observations.append(f"市场环境：{market_state['summary']}")
    observations.append(f"量化风险：{quant_risk['status']}。{quant_risk['detail']}")
    if risk_flags:
        observations.append(f"交易风险标签：{' / '.join(risk_flags)}。")

    risks = []
    if change_pct <= -5:
        risks.append("事实：当前日内跌幅较大，短线承压明显。")
    if cost_price not in (None, "") and price < float(cost_price):
        risks.append("事实：现价低于你的持仓成本，情绪上更容易出现被动操作。")
    risks.append("推断：若后续反弹不能重新站稳关键位，更多仍应视为修复而不是反转。")
    risks.append(f"量化/拥挤交易提醒：{quant_risk['risk']}。")
    if "弱市降权" in risk_flags or market_state["mood"] in {"偏弱", "震荡偏弱"}:
        risks.append("弱市降权：当前市场偏弱时，同样的短线图形和打法，成功率通常会打折。")
    if "冲高回落" in risk_flags:
        risks.append("冲高回落风险：分时若继续拉高后承接不足，更容易出现高位回落。")

    suggestions = []
    if cost_price not in (None, "") and price < float(cost_price):
        suggestions.append("更偏保守的思路是先看关键位收复情况，再决定是否继续持有或减压。")
    if above_levels:
        suggestions.append(f"优先观察价格能否重新站回 {above_levels[0]:.2f} 附近。")
    if below_levels:
        suggestions.append(f"若后续继续走弱，下方 {below_levels[0]:.2f} 附近更值得重点盯防。")
    if quant_risk["status"] == "偏高":
        suggestions.append("更适合等关键位确认后再动，不要在弱势或冲高回落结构里频繁追单。")
    elif quant_risk["status"] == "中等":
        suggestions.append("如果要操作，尽量围绕明确支撑/压力位做计划，少在中间模糊区间来回折腾。")
    suggestions.append(f"结合今天市场，更偏向：{market_state['tactic']}。")
    suggestions.append(f"兑现纪律提醒：{discipline_tip}")
    if one_to_two["score"] < 0:
        suggestions.append("按短线延续思路看，这只票暂时不适合当一进二候选，先看强度修复。")
    elif one_to_two["score"] > 0:
        suggestions.append("如果你偏短线，这只票更适合次日跟踪强弱延续，而不是盘中追情绪。")
    if close_strength["score"] < 0:
        suggestions.append("尾盘承接一般，若后续反弹不能改善收盘位置，更多偏向弱修复。")
    if not suggestions:
        suggestions.append("先以观察量价和分时强弱为主，不要只凭单一指标下结论。")

    return {
        "symbol": symbol,
        "name": quote["name"],
        "quote": quote,
        "points": points,
        "facts": facts,
        "observations": observations,
        "risks": risks,
        "suggestions": suggestions,
        "score": score,
        "overnight": overnight,
        "quant_risk": quant_risk,
        "risk_flags": risk_flags,
        "discipline_tip": discipline_tip,
        "open_strength": open_strength,
        "close_strength": close_strength,
        "volume_price_pattern": vp_pattern,
        "one_to_two": one_to_two,
        "level_signals": level_signals,
        "next_day_plan": next_day_plan,
        "market_state": market_state,
    }


def render_analysis_text(stock_item: dict) -> str:
    analysis = analyze_stock(stock_item)
    score = analysis["score"]
    quant_risk = analysis["quant_risk"]
    risk_flags = analysis.get("risk_flags", [])
    discipline_tip = analysis.get("discipline_tip", "")
    parts = [
        f"标的：{analysis['name']}（{analysis['symbol']}）",
        f"时间：{analysis['quote']['time']}",
        "",
        "最新事实",
    ]
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["facts"], start=1)])
    parts.append("")
    parts.append("量价评分")
    parts.append(f"1. 综合评分：{score['score']} / 100")
    parts.append(f"2. 风险级别：{score['risk']}")
    parts.extend([f"{idx + 2}. {item}" for idx, item in enumerate(score["reasons"], start=1)])
    parts.append("")
    parts.append("量化风险")
    parts.append(f"1. 当前判断：{quant_risk['status']}")
    parts.append(f"2. 风险标签：{quant_risk['risk']}")
    parts.append(f"3. 说明：{quant_risk['detail']}")
    if risk_flags:
        parts.append(f"4. 交易风险：{' / '.join(risk_flags)}")
    if discipline_tip:
        parts.append(f"5. 兑现纪律：{discipline_tip}")
    parts.append("")
    parts.append("关键位标签")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["level_signals"], start=1)] or ["1. 暂无可用关键位标签。"])
    parts.append("")
    parts.append("方法观察")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["observations"], start=1)])
    parts.append("")
    parts.append("次日预案")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["next_day_plan"], start=1)])
    parts.append("")
    parts.append("风险提示")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["risks"], start=1)])
    parts.append("")
    parts.append("保守建议")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["suggestions"], start=1)])
    return "\n".join(parts)


def _sell_plan(quote: dict, stock_item: dict, points: list[tuple[str, float, float]]) -> dict:
    price = float(quote.get("price", 0) or 0)
    change_pct = float(quote.get("change_pct", 0) or 0)
    cost_price = stock_item.get("cost_price")
    lots = int(stock_item.get("lots", 0) or 0)
    levels = sorted([float(level) for level in (stock_item.get("levels", []) or [])], reverse=True)

    if cost_price in (None, "") or lots <= 0:
        buy_trigger = None
        buy_size = "试仓 1-2 手"
        if levels:
            top_level = levels[0]
            bottom_level = levels[-1]
            if float(quote.get("change_pct", 0) or 0) >= 0:
                buy_trigger = f"放量站上 {top_level:.2f} 或回踩 {bottom_level:.2f} 不破再看"
            else:
                buy_trigger = f"先等站回 {top_level:.2f} 再考虑试仓"
        if levels:
            return {
                "action": "继续观察",
                "defense_price": levels[-1],
                "take_profit_price": levels[0],
                "trailing_stop_price": None,
                "reason": "当前没有有效持仓，先按关键位做观察计划。",
                "summary": f"卖点计划  先看 {levels[0]:.2f} / {levels[-1]:.2f}",
                "buy_trigger": buy_trigger,
                "buy_size": buy_size,
                "sell_step": "暂无持仓，不谈卖点",
                "sell_size": "0%",
            }
        return {
            "action": "继续观察",
            "defense_price": None,
            "take_profit_price": None,
            "trailing_stop_price": None,
            "reason": "当前没有有效持仓，先看分时强弱和关键位再决定。",
            "summary": "卖点计划  暂无持仓，先观察",
            "buy_trigger": "先等分时转强和关键位确认",
            "buy_size": "试仓 1 手",
            "sell_step": "暂无持仓，不谈卖点",
            "sell_size": "0%",
        }

    cost = float(cost_price)
    profit_pct = ((price - cost) / max(cost, 0.01)) * 100

    above_levels, below_levels = _safe_levels(levels, price)
    defense_price = below_levels[0] if below_levels else round(cost * 0.98, 2)
    take_profit_price = above_levels[0] if above_levels else round(max(price, cost) * 1.03, 2)
    trailing_stop_price = None

    action = "继续观察"
    reason = "当前更适合盯分时承接和关键位站稳情况。"
    buy_trigger = "不急着加仓，先看关键位确认"
    buy_size = "若要加，只加 1-2 手或不超过当前仓位 1/3"
    sell_step = "先观察，不急着卖"
    sell_size = "0%"

    if profit_pct >= 6:
        action = "分批止盈"
        trailing_stop_price = round(max(price * 0.985, cost * 1.02), 2)
        reason = "已有较明显浮盈，更适合先锁一部分利润，剩余仓位用移动止盈保护。"
        sell_step = "先卖 1/3，余下仓位用跟踪止盈"
        sell_size = "33%"
    elif profit_pct >= 3:
        action = "冲高减仓"
        trailing_stop_price = round(max(price * 0.99, cost), 2)
        reason = "已经脱离成本区，遇到冲高更适合减一点，把主动权拿回来。"
        sell_step = "先卖 1/4，冲高不过压力再减"
        sell_size = "25%"
    elif change_pct <= -4:
        action = "防守减仓"
        reason = "日内走弱明显，优先看防守位是否失守，不宜继续硬扛。"
        sell_step = "若继续走弱，先减半"
        sell_size = "50%"
    elif price <= defense_price:
        action = "防守减仓"
        reason = "价格已经靠近下方关键位，若继续失守更偏向执行防守。"
        sell_step = "失守防守位先减半，再弱则离场"
        sell_size = "50%"
    elif price > cost and change_pct > 0:
        action = "持有观察"
        reason = "现价仍在成本上方，先看能否继续站稳并向上冲击压力位。"
        sell_step = "暂不卖，冲到压力位附近再锁利润"
        sell_size = "0%"

    summary_parts = [f"卖点计划  {action}"]
    if defense_price:
        summary_parts.append(f"防守 {defense_price:.2f}")
    if take_profit_price:
        summary_parts.append(f"止盈 {take_profit_price:.2f}")
    if trailing_stop_price:
        summary_parts.append(f"跟踪 {trailing_stop_price:.2f}")

    return {
        "action": action,
        "defense_price": defense_price,
        "take_profit_price": take_profit_price,
        "trailing_stop_price": trailing_stop_price,
        "reason": reason,
        "summary": "｜".join(summary_parts),
        "buy_trigger": buy_trigger,
        "buy_size": buy_size,
        "sell_step": sell_step,
        "sell_size": sell_size,
    }


def analyze_stock(stock_item: dict) -> dict:
    symbol = stock_item["symbol"]
    market = stock_item.get("market")
    quote = fetch_quote(symbol, market)
    points = fetch_intraday_points(symbol, market)
    market_state = get_market_state()

    price = float(quote.get("price", 0) or 0)
    levels = [float(level) for level in (stock_item.get("levels", []) or [])]
    above_levels, below_levels = _safe_levels(levels, price)
    cost_price = stock_item.get("cost_price")
    lots = int(stock_item.get("lots", 0) or 0)
    shares = lots * 100
    pnl = (price - float(cost_price)) * shares if cost_price not in (None, "") and lots > 0 else None

    overnight = _overnight_hold_analysis(quote, points, market_state)
    open_strength = _open_session_strength(points)
    close_strength = _close_strength(points, quote)
    vp_pattern = _volume_price_pattern(quote, points)
    one_to_two = _one_to_two_candidate(quote, points)
    quant_risk = _quant_risk_analysis(quote, points, stock_item)
    risk_flags = _trading_risk_flags(quote, points, stock_item, market_state)
    discipline_tip = _discipline_reminder(quote, points, stock_item)
    level_signals = _level_signals(price, levels)
    next_day_plan = _next_day_plan(quote, points, stock_item)
    score = _score_analysis(quote, points, stock_item, market_state)
    sell_plan = _sell_plan(quote, stock_item, points)

    facts: list[str] = [
        f"最新价格 {price:.2f}，涨跌幅 {float(quote.get('change_pct', 0) or 0):+.2f}%，时间 {quote.get('time', '--')}",
        f"当前走势判断：{_describe_trend(float(quote.get('change_pct', 0) or 0))}",
    ]
    if points:
        day_high = max(p[1] for p in points)
        day_low = min(p[1] for p in points)
        facts.append(f"当日分时区间约为 {day_low:.2f} - {day_high:.2f}，共抓到 {len(points)} 个分时点。")
    if cost_price not in (None, "") and lots > 0 and pnl is not None:
        facts.append(f"你的持仓成本 {float(cost_price):.3f}，持仓 {lots} 手，当前浮动盈亏 {pnl:+.2f} 元。")

    observations: list[str] = []
    if above_levels:
        observations.append(f"上方关注位：{' / '.join(f'{x:.2f}' for x in above_levels[:3])}。")
    if below_levels:
        observations.append(f"下方观察位：{' / '.join(f'{x:.2f}' for x in below_levels[:3])}。")
    observations.extend(level_signals)
    observations.extend(_build_method_hits(quote, points))
    observations.append(f"市场环境：{market_state.get('summary', '等待市场状态刷新')}")
    observations.append(f"量化风险：{quant_risk['status']}。{quant_risk['detail']}")
    if risk_flags:
        observations.append(f"交易风险标签：{' / '.join(risk_flags)}。")

    risks: list[str] = []
    if float(quote.get("change_pct", 0) or 0) <= -5:
        risks.append("事实：当前日内跌幅较大，短线承压明显。")
    if cost_price not in (None, "") and price < float(cost_price):
        risks.append("事实：现价低于你的持仓成本，情绪上更容易出现被动操作。")
    risks.append("推断：若后续反弹不能重新站稳关键位，更多应视为修复而不是反转。")
    risks.append(f"量化/拥挤交易提醒：{quant_risk['risk']}。")
    if "弱市降权" in risk_flags or market_state.get("mood") in {"偏弱", "震荡偏弱"}:
        risks.append("弱市降权：当前市场偏弱时，同样的短线图形和打法，成功率通常会打折。")
    if "冲高回落" in risk_flags:
        risks.append("冲高回落风险：分时若继续拉高后承接不足，更容易出现高位回落。")

    suggestions: list[str] = []
    if cost_price not in (None, "") and price < float(cost_price):
        suggestions.append("更偏保守的思路是先看关键位收复情况，再决定是否继续持有或减压。")
    if above_levels:
        suggestions.append(f"优先观察价格能否重新站回 {above_levels[0]:.2f} 附近。")
    if below_levels:
        suggestions.append(f"若后续继续走弱，下方 {below_levels[0]:.2f} 附近更值得重点盯防。")
    if quant_risk["status"] == "偏高":
        suggestions.append("更适合等关键位确认后再动，不要在弱势或冲高回落结构里频繁追单。")
    elif quant_risk["status"] == "中等":
        suggestions.append("如果要操作，尽量围绕明确支撑/压力位做计划，少在中间模糊区间来回折腾。")
    suggestions.append(f"结合今天市场，更偏向：{market_state.get('tactic', '先观察，再行动')}。")
    suggestions.append(f"兑现纪律提醒：{discipline_tip}")
    suggestions.append(f"卖点计划：{sell_plan['reason']}")

    return {
        "symbol": symbol,
        "name": quote["name"],
        "quote": quote,
        "points": points,
        "facts": facts,
        "observations": observations,
        "risks": risks,
        "suggestions": suggestions,
        "score": score,
        "overnight": overnight,
        "quant_risk": quant_risk,
        "risk_flags": risk_flags,
        "discipline_tip": discipline_tip,
        "open_strength": open_strength,
        "close_strength": close_strength,
        "volume_price_pattern": vp_pattern,
        "one_to_two": one_to_two,
        "level_signals": level_signals,
        "next_day_plan": next_day_plan,
        "market_state": market_state,
        "sell_plan": sell_plan,
    }


def render_analysis_text(stock_item: dict) -> str:
    analysis = analyze_stock(stock_item)
    score = analysis["score"]
    quant_risk = analysis["quant_risk"]
    risk_flags = analysis.get("risk_flags", [])
    discipline_tip = analysis.get("discipline_tip", "")
    sell_plan = analysis.get("sell_plan", {})
    parts = [
        f"标的：{analysis['name']}（{analysis['symbol']}）",
        f"时间：{analysis['quote']['time']}",
        "",
        "最新事实",
    ]
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["facts"], start=1)])
    parts.append("")
    parts.append("量价评分")
    parts.append(f"1. 综合评分：{score['score']} / 100")
    parts.append(f"2. 风险级别：{score['risk']}")
    parts.extend([f"{idx + 2}. {item}" for idx, item in enumerate(score["reasons"], start=1)])
    parts.append("")
    parts.append("量化风险")
    parts.append(f"1. 当前判断：{quant_risk['status']}")
    parts.append(f"2. 风险标签：{quant_risk['risk']}")
    parts.append(f"3. 说明：{quant_risk['detail']}")
    if risk_flags:
        parts.append(f"4. 交易风险：{' / '.join(risk_flags)}")
    if discipline_tip:
        parts.append(f"5. 兑现纪律：{discipline_tip}")
    parts.append("")
    parts.append("关键位标签")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["level_signals"], start=1)] or ["1. 暂无可用关键位标签。"])
    parts.append("")
    parts.append("次日预案")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["next_day_plan"], start=1)])
    parts.append("")
    parts.append("卖点计划")
    parts.append(f"1. 当前动作：{sell_plan.get('action', '继续观察')}")
    if sell_plan.get("defense_price") is not None:
        parts.append(f"2. 防守位：{float(sell_plan['defense_price']):.2f}")
    if sell_plan.get("take_profit_price") is not None:
        parts.append(f"3. 止盈位：{float(sell_plan['take_profit_price']):.2f}")
    if sell_plan.get("trailing_stop_price") is not None:
        parts.append(f"4. 跟踪止盈：{float(sell_plan['trailing_stop_price']):.2f}")
    parts.append(f"5. 原因：{sell_plan.get('reason', '先看分时承接和关键位。')}")
    parts.append(f"6. 什么时候买：{sell_plan.get('buy_trigger', '先等关键位确认')}")
    parts.append(f"7. 买多少：{sell_plan.get('buy_size', '先小仓试')}")
    parts.append(f"8. 怎么卖：{sell_plan.get('sell_step', '先观察')}")
    parts.append(f"9. 卖多少：{sell_plan.get('sell_size', '0%')}")
    parts.append("")
    parts.append("方法观察")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["observations"], start=1)])
    parts.append("")
    parts.append("风险提示")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["risks"], start=1)])
    parts.append("")
    parts.append("保守建议")
    parts.extend([f"{idx}. {item}" for idx, item in enumerate(analysis["suggestions"], start=1)])
    return "\n".join(parts)
