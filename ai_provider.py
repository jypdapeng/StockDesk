import base64
import json
import mimetypes
import os
import pathlib
import tempfile
import urllib.request

try:
    from PIL import Image
except ImportError:
    Image = None


AI_SETTINGS_PATH = pathlib.Path(__file__).resolve().parent / "ai_settings.json"
OPENCLAW_CONFIG_PATH = pathlib.Path.home() / ".openclaw" / "openclaw.json"


def _default_settings() -> dict:
    return {
        "provider": "bailian",
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "enabled": True,
            "api_key": "",
        },
        "bailian": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
            "enabled": True,
            "api_key": "",
        },
    }


def load_ai_settings() -> dict:
    if not AI_SETTINGS_PATH.exists():
        save_ai_settings(_default_settings())
    data = json.loads(AI_SETTINGS_PATH.read_text(encoding="utf-8"))
    base = _default_settings()
    base["provider"] = data.get("provider", base["provider"])
    for key in ("deepseek", "bailian"):
        if isinstance(data.get(key), dict):
            base[key].update(data[key])
    return base


def save_ai_settings(settings: dict) -> None:
    AI_SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_openclaw_env_key(*names: str) -> str | None:
    if not OPENCLAW_CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
        env = data.get("env", {})
    except Exception:
        return None
    for name in names:
        value = env.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _provider_api_key(provider: str, settings: dict | None = None) -> str | None:
    if settings:
        configured = settings.get(provider, {}).get("api_key")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY") or _read_openclaw_env_key("DEEPSEEK_API_KEY")
    if provider == "bailian":
        return (
            os.getenv("BAILIAN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or _read_openclaw_env_key("BAILIAN_API_KEY", "DASHSCOPE_API_KEY")
        )
    return None


def _resolve_provider(settings: dict) -> tuple[str | None, str | None, str | None]:
    provider = settings.get("provider", "auto")
    if provider in {"deepseek", "bailian"}:
        key = _provider_api_key(provider, settings)
        if key:
            cfg = settings[provider]
            return provider, cfg["base_url"], cfg["model"]
        return None, None, None

    for provider_name in ("deepseek", "bailian"):
        if settings[provider_name].get("enabled") and _provider_api_key(provider_name, settings):
            cfg = settings[provider_name]
            return provider_name, cfg["base_url"], cfg["model"]
    return None, None, None


def _request_chat(request: urllib.request.Request, timeout: int = 60) -> str:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    return data["choices"][0]["message"]["content"].strip()


def _extract_json_block(content: str) -> dict | list:
    text = content.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start_positions = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not start_positions:
        raise ValueError("AI 未返回可解析的 JSON。")
    start = min(start_positions)
    end_object = text.rfind("}")
    end_array = text.rfind("]")
    end = max(end_object, end_array)
    if end <= start:
        raise ValueError("AI 返回内容里没有完整 JSON。")
    return json.loads(text[start : end + 1])


def _encode_image_as_data_url(image_path: str) -> dict:
    path = pathlib.Path(image_path)
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime_type};base64,{encoded}",
        },
    }


def _resolve_vision_provider(settings: dict) -> tuple[str | None, str | None, str | None]:
    bailian_key = _provider_api_key("bailian", settings)
    if bailian_key:
        base = settings.get("bailian", {}).get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        model = settings.get("bailian", {}).get("vision_model") or "qwen-vl-max-latest"
        return "bailian", base, model
    return None, None, None


def _request_vision_json(prompt: str, image_paths: list[str]) -> dict | list:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_vision_provider(settings)
    if not provider or not base_url or not model:
        raise RuntimeError("未检测到可用的百炼视觉模型配置。")
    api_key = _provider_api_key(provider, settings)
    if not api_key:
        raise RuntimeError("百炼已启用，但缺少 API Key。")

    content = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append(_encode_image_as_data_url(image_path))

    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "你是一个严谨的证券截图结构化提取助手，只输出 JSON，不要输出解释文字。",
            },
            {
                "role": "user",
                "content": content,
            },
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    content_text = _request_chat(request, timeout=90)
    return _extract_json_block(content_text)


def _request_vision_text(prompt: str, image_paths: list[str]) -> str:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_vision_provider(settings)
    if not provider or not base_url or not model:
        raise RuntimeError("未检测到可用的百炼视觉模型配置。")
    api_key = _provider_api_key(provider, settings)
    if not api_key:
        raise RuntimeError("百炼已启用，但缺少 API Key。")

    content = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append(_encode_image_as_data_url(image_path))

    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": "你是一个严谨的证券截图文字提取助手，只输出结果，不要解释。",
            },
            {
                "role": "user",
                "content": content,
            },
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    return _request_chat(request, timeout=90)


def _split_tall_images(image_paths: list[str], segment_height: int = 2200, overlap: int = 120) -> list[str]:
    if Image is None:
        return image_paths
    output = []
    for image_path in image_paths:
        path = pathlib.Path(image_path)
        try:
            with Image.open(path) as image:
                width, height = image.size
                if height <= segment_height:
                    output.append(str(path))
                    continue
                top = 0
                index = 0
                while top < height:
                    bottom = min(height, top + segment_height)
                    cropped = image.crop((0, top, width, bottom))
                    temp_path = pathlib.Path(tempfile.gettempdir()) / f"stockdesk_import_{path.stem}_{index}.png"
                    cropped.save(temp_path, format="PNG")
                    output.append(str(temp_path))
                    if bottom >= height:
                        break
                    top = max(0, bottom - overlap)
                    index += 1
        except Exception:
            output.append(str(path))
    return output


def build_ai_prompt(stock_item: dict, analysis: dict) -> str:
    facts = "\n".join(f"- {item}" for item in analysis["facts"])
    observations = "\n".join(f"- {item}" for item in analysis["observations"])
    risks = "\n".join(f"- {item}" for item in analysis["risks"])
    suggestions = "\n".join(f"- {item}" for item in analysis["suggestions"])
    score = analysis["score"]
    overnight = analysis["overnight"]
    return f"""你是一个保守型 A 股分析助手。请基于以下规则分析结果，用中文给出简明、克制、风险优先的解释。
要求：
1. 明确区分事实与推断。
2. 不要给出绝对化买卖指令。
3. 重点解释当前走势、关键位、持仓压力和“一夜持股法”是否适用。
4. 用四个小节输出：事实解读、方法解释、风险、保守建议。
5. 控制在 400 字以内。

标的：{analysis['name']}（{stock_item['symbol']}）

规则分析事实：
{facts}

方法观察：
{observations}

风险提示：
{risks}

保守建议：
{suggestions}

补充信息：
- 量价评分：{score['score']} / 100
- 风险级别：{score['risk']}
- 一夜持股法：{overnight['status']}
"""


def get_ai_explanation(stock_item: dict, analysis: dict) -> dict:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的 DeepSeek / 百炼配置，当前仅显示规则分析结果。",
        }

    api_key = _provider_api_key(provider, settings)
    if not api_key:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"{provider} 已配置但缺少 API Key。",
        }

    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": "你是一个保守、克制、事实优先的股票分析助手。"},
            {"role": "user", "content": build_ai_prompt(stock_item, analysis)},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    try:
        content = _request_chat(request, timeout=60)
        return {"enabled": True, "provider": provider, "content": content}
    except Exception as exc:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"AI 解释暂时不可用：{exc}",
        }


def chat_with_stock_context(stock_item: dict, analysis: dict, history: list[dict], user_message: str) -> dict:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的 DeepSeek / 百炼配置。",
        }

    api_key = _provider_api_key(provider, settings)
    if not api_key:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"{provider} 已配置但缺少 API Key。",
        }

    facts = "\n".join(f"- {item}" for item in analysis["facts"])
    observations = "\n".join(f"- {item}" for item in analysis["observations"])
    risks = "\n".join(f"- {item}" for item in analysis["risks"])
    suggestions = "\n".join(f"- {item}" for item in analysis["suggestions"])

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个保守、克制、事实优先的 A 股分析助手。"
                "请围绕当前股票做连续对话，明确区分事实与推断，不要给出绝对化喊单式建议。"
            ),
        },
        {
            "role": "system",
            "content": (
                f"当前标的：{analysis['name']}（{stock_item['symbol']}）\n"
                f"最新事实：\n{facts}\n\n"
                f"方法观察：\n{observations}\n\n"
                f"风险提示：\n{risks}\n\n"
                f"保守建议：\n{suggestions}\n\n"
                f"量价评分：{analysis['score']['score']} / 100\n"
                f"风险级别：{analysis['score']['risk']}\n"
                f"一夜持股法：{analysis['overnight']['status']}"
            ),
        },
    ]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": messages,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    try:
        content = _request_chat(request, timeout=60)
        return {"enabled": True, "provider": provider, "content": content}
    except Exception as exc:
        fallback = (
            f"AI 对话暂时不可用：{exc}\n\n"
            "先给你一版本地规则兜底：\n"
            f"- 量价评分：{analysis['score']['score']} / 100，风险级别：{analysis['score']['risk']}\n"
            f"- 一夜持股法：{analysis['overnight']['status']}\n"
            "- 当前最该看的不是情绪判断，而是关键位能否收复，以及反弹时量能是否跟上。"
        )
        return {
            "enabled": False,
            "provider": provider,
            "content": fallback,
        }


def analyze_news_with_ai(stock_item: dict, news_items: list[dict]) -> dict:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的 AI 配置，当前仅显示规则型新闻判断。",
        }

    api_key = _provider_api_key(provider, settings)
    if not api_key:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"{provider} 已配置但缺少 API Key。",
        }

    news_text = "\n".join(f"- {item['time']} {item['title']}" for item in news_items[:10])
    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {
                "role": "system",
                "content": "你是一个保守、事实优先的 A 股新闻解读助手。请基于新闻标题做偏正向、偏负向、中性的解释，不要喊单。",
            },
            {
                "role": "user",
                "content": (
                    f"标的：{stock_item.get('label') or stock_item['symbol']}（{stock_item['symbol']}）\n"
                    f"相关新闻如下：\n{news_text}\n\n"
                    "请输出三段：正向因素、负向因素、总体判断。总体判断只允许写“偏正向”“偏负向”或“中性”。控制在 220 字以内。"
                ),
            },
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    try:
        content = _request_chat(request, timeout=60)
        return {"enabled": True, "provider": provider, "content": content}
    except Exception as exc:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"AI 新闻解读暂时不可用：{exc}",
        }


def recommend_candidates_with_ai(market_snapshot: dict, candidates: list[dict]) -> dict:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {"enabled": False, "provider": None, "content": "未检测到可用的 AI 配置。", "picks": []}

    api_key = _provider_api_key(provider, settings)
    if not api_key:
        return {"enabled": False, "provider": provider, "content": f"{provider} 已配置但缺少 API Key。", "picks": []}

    prompt = build_recommend_prompt(market_snapshot, candidates)

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "你是一个保守、克制、风险优先的 A 股推荐助手。只能从候选池里选择，不要编造股票。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    try:
        content = _request_chat(request, timeout=90)
        data = _extract_json_block(content)
        if isinstance(data, dict):
            return {
                "enabled": True,
                "provider": provider,
                "content": data.get("summary", content),
                "picks": data.get("picks", []),
            }
        return {"enabled": True, "provider": provider, "content": content, "picks": []}
    except Exception as exc:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"AI 推荐暂时不可用：{exc}",
            "picks": [],
        }


def build_recommend_prompt(market_snapshot: dict, candidates: list[dict]) -> str:
    market_lines = [f"- {item['label']} {item['change_pct']:+.2f}%" for item in market_snapshot.get("indices", [])]
    candidate_lines = []
    for item in candidates[:18]:
        candidate_lines.append(
            (
                f"- {item['label']}（{item['symbol']}）"
                f" 评分={item['score']}"
                f" 风险={item['risk']}"
                f" 量化风险={item['quant_risk_label']}"
                f" 新闻={item['news_bias']}"
                f" 开盘={item['open_strength']}"
                f" 尾盘={item['close_strength']}"
                f" 一进二={item['one_to_two']}"
                f" 预案={'；'.join(item['next_day_plan'][:1]) if item['next_day_plan'] else '暂无'}"
            )
        )
    return (
        "你是一个保守型 A 股观察候选筛选助手。"
        "请结合当前大盘环境、候选股走势、新闻偏向和风险，"
        "从候选池里挑出最多 5 只更适合下一交易日观察的股票。"
        "不要推荐明显弱势追击、冲高回落高风险、量化拥挤严重的标的。"
        "输出严格 JSON，对象格式为："
        '{"picks":[{"symbol":"代码","label":"名称","action":"观察/低吸观察/突破跟踪/等待","score":80,"reason":"推荐原因","playbook":"打法","risk_note":"风险提醒"}],"summary":"一段总说明"}'
        "\n\n当前大盘：\n"
        f"市场状态：{market_snapshot.get('mood', '未知')}\n"
        + "\n".join(market_lines)
        + "\n\n候选池：\n"
        + "\n".join(candidate_lines)
    )


def chat_with_recommend_context(recommend_result: dict, history: list[dict], user_message: str) -> dict:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的 AI 配置。",
        }

    api_key = _provider_api_key(provider, settings)
    if not api_key:
        return {
            "enabled": False,
            "provider": provider,
            "content": f"{provider} 已配置但缺少 API Key。",
        }

    market_snapshot = recommend_result.get("market", {})
    picks = recommend_result.get("picks", []) or []
    candidates = recommend_result.get("candidates", []) or []

    pick_lines = []
    for item in picks[:5]:
        pick_lines.append(
            f"- {item.get('label', item.get('symbol', ''))}（{item.get('symbol', '')}）"
            f" 动作={item.get('action', '观察')}"
            f" 原因={item.get('reason', '暂无')}"
            f" 打法={item.get('playbook', '暂无')}"
            f" 风险={item.get('risk_note', '暂无')}"
        )

    candidate_lines = []
    for item in candidates[:12]:
        candidate_lines.append(
            f"- {item.get('label', item.get('symbol', ''))}（{item.get('symbol', '')}）"
            f" 评分={item.get('score', 0)}"
            f" 新闻={item.get('news_bias', '中性')}"
            f" 量化风险={item.get('quant_risk_label', '普通')}"
            f" 尾盘={item.get('close_strength', '未知')}"
        )

    system_prompt = (
        "你是一个保守、克制、风险优先的 A 股推荐对话助手。"
        "你要围绕今天的市场环境和上一轮推荐结果继续回答。"
        "回答时要明确区分事实、推断和交易计划。"
        "不要给绝对化喊单，不要脱离当前市场状态乱推票。"
        "更偏向给出观察框架、关键位、打法节奏和风险点。"
    )
    context_prompt = (
        f"今天市场状态：{market_snapshot.get('mood', '未知')}\n"
        + ("\n".join(f"- {item['label']} {item['change_pct']:+.2f}%" for item in market_snapshot.get("indices", [])) or "- 无指数数据")
        + "\n\n上一轮推荐结果：\n"
        + ("\n".join(pick_lines) if pick_lines else "- 暂无推荐结果")
        + "\n\n候选池摘要：\n"
        + ("\n".join(candidate_lines) if candidate_lines else "- 暂无候选池摘要")
        + "\n\n请基于这些上下文继续回答用户问题。"
    )

    messages = [{"role": "system", "content": system_prompt}, {"role": "system", "content": context_prompt}]
    for item in history[-12:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": messages,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "StockDesk/1.0",
        },
    )
    try:
        content = _request_chat(request, timeout=90)
        return {"enabled": True, "provider": provider, "content": content}
    except Exception as exc:
        fallback = []
        if pick_lines:
            fallback.append("当前可继续观察的候选仍以上一轮推荐结果为主。")
            fallback.append("建议先围绕推荐列表里的关键位、尾盘强弱和量化风险来追问，不要脱离今天盘面重新激进选股。")
        if market_snapshot.get("mood"):
            fallback.append(f"今天市场环境偏向：{market_snapshot.get('mood')}。")
        fallback.append(f"AI 推荐对话暂时不可用：{exc}")
        return {
            "enabled": False,
            "provider": provider,
            "content": "\n".join(fallback),
        }


def extract_holdings_from_images(image_paths: list[str]) -> dict:
    prompt = """
请识别证券持仓截图，并输出 JSON 对象，格式严格如下：
{
  "holdings": [
    {
      "symbol": "6位股票代码，没有则留空字符串",
      "name": "股票名称",
      "lots": 0,
      "shares": 0,
      "current_price": 0,
      "cost_price": 0,
      "market_value": 0,
      "profit": 0
    }
  ],
  "notes": ["无法确认的项目"]
}

要求：
1. lots 是“手数”，按 1 手 = 100 股换算；如果截图里只有股数，则自动换算。
2. 只提取真实股票，不提取总资产、按钮、标题。
3. 数字用阿拉伯数字；没有的字段填 0 或空字符串。
4. 只输出 JSON。
"""
    result = _request_vision_json(prompt, image_paths)
    if not isinstance(result, dict):
        raise ValueError("持仓识别结果格式不正确。")
    result.setdefault("holdings", [])
    result.setdefault("notes", [])
    return result


def extract_trades_from_images(image_paths: list[str]) -> dict:
    prompt = """
请识别证券交易记录截图中的成交行。
要求：
1. 每行输出格式：股票名称|股票代码|买卖方向|成交时间|成交价|成交股数
2. 买卖方向只允许写 buy 或 sell
3. 如果没有代码，股票代码留空
4. 只输出识别结果，不要输出解释，不要输出 JSON
"""
    expanded_paths = _split_tall_images(image_paths)
    text = _request_vision_text(prompt, expanded_paths)
    trades = []
    notes = []
    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 6:
            continue
        name, symbol, action, time_value, price_text, shares_text = parts[:6]
        symbol = "".join(ch for ch in symbol if ch.isdigit())[:6]
        action = "buy" if action.lower() == "buy" or "买" in action else "sell"
        try:
            price = float(price_text)
        except Exception:
            price = 0
        try:
            shares = int(float("".join(ch for ch in shares_text if ch.isdigit() or ch == ".")))
        except Exception:
            shares = 0
        if not name:
            continue
        item = {
            "symbol": symbol,
            "name": name,
            "action": action,
            "time": time_value or "",
            "price": price,
            "shares": shares,
            "lots": shares // 100 if shares > 0 else 0,
            "amount": 0,
            "note": "",
        }
        fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        trades.append(item)
    if not trades:
        notes.append("未从截图中提取到有效成交记录。")
    return {"trades": trades, "notes": notes}


def extract_watchlist_from_images(image_paths: list[str]) -> dict:
    prompt = """
请识别证券自选列表截图中的股票名称与代码。
要求：
1. 每行只输出一只股票，格式为：股票名称|股票代码
2. 如果截图里没有代码，股票代码留空，格式仍然保持：股票名称|
3. 不要输出价格、涨跌、标题、按钮、解释
4. 不要输出 JSON
"""
    expanded_paths = _split_tall_images(image_paths)
    text = _request_vision_text(prompt, expanded_paths)
    favorites = []
    notes = []
    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line or "|" not in line:
            continue
        name, symbol = line.split("|", 1)
        name = name.strip()
        symbol = "".join(ch for ch in symbol if ch.isdigit())[:6]
        if not name:
            continue
        key = (name, symbol)
        if key in seen:
            continue
        seen.add(key)
        favorites.append({"name": name, "symbol": symbol})
    if not favorites:
        notes.append("未从截图中提取到有效自选股票。")
    return {"favorites": favorites, "notes": notes}
