import datetime as dt
import json
import urllib.request
from typing import Any

from stock_common import fetch_quote


INDEX_POOL = [
    {"symbol": "000001", "market": "sh", "label": "上证指数"},
    {"symbol": "399001", "market": "sz", "label": "深证成指"},
    {"symbol": "399006", "market": "sz", "label": "创业板指"},
]

BREADTH_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz={limit}&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23"
    "&fields=f2,f3"
)


def _fetch_breadth(limit: int = 120) -> dict[str, Any]:
    request = urllib.request.Request(
        BREADTH_URL.format(limit=limit),
        headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    rows = payload.get("data", {}).get("diff", []) or []
    up = 0
    down = 0
    flat = 0
    for row in rows:
        try:
            change_pct = float(row.get("f3") or 0)
            price = float(row.get("f2") or 0)
        except Exception:
            continue
        if price <= 0:
            continue
        if change_pct > 0:
            up += 1
        elif change_pct < 0:
            down += 1
        else:
            flat += 1
    total = up + down + flat
    return {
        "sample_size": total,
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": round(up / total, 3) if total else 0.0,
        "down_ratio": round(down / total, 3) if total else 0.0,
    }


def _summarize_mood(avg_change: float, breadth: dict[str, Any]) -> tuple[str, str, str, int]:
    up_ratio = breadth.get("up_ratio", 0.0)
    down_ratio = breadth.get("down_ratio", 0.0)

    if avg_change >= 1 and up_ratio >= 0.58:
        return "偏强", "顺势跟随", "偏低", 75
    if avg_change <= -1 and down_ratio >= 0.58:
        return "偏弱", "防守优先", "偏高", 25
    if avg_change >= 0.3 and up_ratio > down_ratio:
        return "震荡偏强", "只做强承接", "中等", 60
    if avg_change <= -0.3 and down_ratio > up_ratio:
        return "震荡偏弱", "谨慎观察", "中等偏高", 40
    return "震荡", "少折腾等确认", "中等", 50


def _direction_suggestions(mood: str, strongest_label: str | None) -> tuple[list[str], list[str], list[str]]:
    if strongest_label == "创业板指":
        main = ["成长 / 科技更活跃", "优先看量价更强的科技股", "只跟随有承接的主线分支"]
        avoid = ["高位一致性追涨", "尾盘情绪高潮接力", "弱分时硬做隔夜"]
    elif strongest_label == "深证成指":
        main = ["中盘趋势票更容易活跃", "看修复承接而不是拍脑袋抄底", "优先看放量站回关键位的标的"]
        avoid = ["缩量弱反抽", "单纯消息刺激股", "没有承接的尾盘偷拉"]
    else:
        main = ["权重 / 电力 / 设备更稳", "优先看低位承接和防守进攻兼备方向", "适合控制节奏做确认"]
        avoid = ["纯情绪题材追高", "高位妖股接最后一棒", "弱市中做超短重仓隔夜"]

    discipline = [
        "先定高开、平开、低开的处理预案，再决定是否下手",
        "模糊区间少折腾，优先等关键位确认",
        "如果板块和大盘不同步，优先按风险处理而不是幻想",
    ]

    if mood in {"偏弱", "震荡偏弱"}:
        main = ["先守住节奏和仓位", "优先看抗跌和承接，而不是找最猛的", "更适合观察，不适合乱追"]
        avoid = ["弱市追涨", "高波动题材硬接", "没有止损计划的隔夜单"]
    elif mood == "偏强":
        discipline[0] = "市场偏强也别无脑追，优先选尾盘不弱且次日更容易有承接的。"

    return main, avoid, discipline


def _main_strength(score: int, strongest_label: str | None) -> str:
    if score >= 70:
        return f"{strongest_label or '当前主线'}偏强，可顺势观察"
    if score <= 35:
        return f"{strongest_label or '当前主线'}偏弱，先防守再谈出手"
    return f"{strongest_label or '当前主线'}一般，优先做确认不做冲动单"


def _risk_signal(mood: str, breadth: dict[str, Any]) -> str:
    if mood == "偏弱":
        return "弱市环境，短线容错率低"
    if breadth.get("down_ratio", 0) >= 0.6:
        return "下跌家数偏多，情绪承接偏弱"
    if mood == "偏强":
        return "偏强环境，但尾盘一致性过高时仍要防回落"
    return "震荡环境，最怕模糊区间来回试错"


def _rotation_speed(breadth: dict[str, Any], avg_change: float) -> str:
    spread = abs(breadth.get("up_ratio", 0.0) - breadth.get("down_ratio", 0.0))
    if spread >= 0.25 and abs(avg_change) >= 0.7:
        return "偏快"
    if spread <= 0.08 and abs(avg_change) <= 0.3:
        return "偏慢"
    return "中等"


def _chase_risk(mood: str, strongest_label: str | None, breadth: dict[str, Any]) -> str:
    if mood == "偏弱":
        return "高：弱市追涨很容易被反手收割"
    if breadth.get("up_ratio", 0.0) >= 0.6 and strongest_label == "创业板指":
        return "中高：热点一致性一旦过高，尾盘接力容易吃回落"
    if mood in {"震荡", "震荡偏弱"}:
        return "中高：模糊区间追涨，容错率偏低"
    return "中等：可以跟随，但别在一致高潮时接最后一棒"


def _overnight_risk(mood: str, breadth: dict[str, Any]) -> str:
    if mood in {"偏弱", "震荡偏弱"}:
        return "高：隔夜成功率会明显打折"
    if breadth.get("down_ratio", 0.0) > 0.52:
        return "中高：次日承接不确定，隔夜宜保守"
    if mood == "偏强":
        return "中等：只适合尾盘强、次日更容易有承接的票"
    return "中等：看尾盘强弱和关键位，不宜无计划隔夜"


def _execution_focus(mood: str, strongest_label: str | None) -> str:
    if mood == "偏强":
        return f"优先顺着 {strongest_label or '当前主线'} 做确认后的跟随，不做情绪后排。"
    if mood in {"偏弱", "震荡偏弱"}:
        return "优先处理持仓风险和关键位，减少新开仓。"
    return "优先看承接、关键位和尾盘位置，确认后再动手。"


def get_market_state() -> dict[str, Any]:
    indices = []
    for item in INDEX_POOL:
        try:
            quote = fetch_quote(item["symbol"], item["market"])
        except Exception:
            continue
        indices.append(
            {
                "symbol": item["symbol"],
                "label": item["label"],
                "price": quote["price"],
                "change_pct": quote["change_pct"],
            }
        )

    breadth = _fetch_breadth()
    avg_change = sum(index["change_pct"] for index in indices) / len(indices) if indices else 0.0
    mood, tactic, risk_bias, score = _summarize_mood(avg_change, breadth)

    strongest = max(indices, key=lambda item: item.get("change_pct", 0), default=None)
    strongest_label = strongest.get("label") if strongest else None
    main_directions, avoid_directions, discipline = _direction_suggestions(mood, strongest_label)
    main_strength = _main_strength(score, strongest_label)
    risk_signal = _risk_signal(mood, breadth)
    rotation_speed = _rotation_speed(breadth, avg_change)
    chase_risk = _chase_risk(mood, strongest_label, breadth)
    overnight_risk = _overnight_risk(mood, breadth)
    execution_focus = _execution_focus(mood, strongest_label)

    if mood == "偏强":
        summary = "大盘和样本个股整体偏强，更适合顺势跟随，但仍要防止尾盘一致性过高后的回落。"
    elif mood == "偏弱":
        summary = "大盘整体偏弱，先防守、少追单，优先等待关键位和承接确认。"
    elif mood == "震荡偏强":
        summary = "指数不算弱，但更多是结构性机会，适合只做承接更强、位置更好的标的。"
    elif mood == "震荡偏弱":
        summary = "市场偏震荡偏弱，短线成功率会打折，优先控制节奏和仓位。"
    else:
        summary = "市场处于震荡状态，主线和承接比盲目追涨更重要，模糊区间少折腾。"

    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indices": indices,
        "breadth": breadth,
        "avg_change_pct": round(avg_change, 2),
        "mood": mood,
        "tactic": tactic,
        "risk_bias": risk_bias,
        "score": score,
        "summary": summary,
        "main_directions": main_directions,
        "avoid_directions": avoid_directions,
        "discipline": discipline,
        "strongest_index": strongest_label or "未知",
        "main_strength": main_strength,
        "risk_signal": risk_signal,
        "rotation_speed": rotation_speed,
        "chase_risk": chase_risk,
        "overnight_risk": overnight_risk,
        "execution_focus": execution_focus,
    }
