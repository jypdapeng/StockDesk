import base64
import datetime as dt
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

from stock_common import USER_DATA_DIR

AI_SETTINGS_PATH = USER_DATA_DIR / "ai_settings.json"
LEGACY_AI_SETTINGS_PATH = pathlib.Path(__file__).resolve().parent / "ai_settings.json"
OPENCLAW_CONFIG_PATH = pathlib.Path.home() / ".openclaw" / "openclaw.json"
AI_RUNTIME_CACHE: dict[str, dict] = {}
BUILTIN_PROVIDERS = ("router", "local", "deepseek", "bailian")


def _default_settings() -> dict:
    return {
        "provider": "auto",
        "router": {
            "base_url": "http://127.0.0.1:4000/v1",
            "model": "stockdesk-auto",
            "enabled": False,
            "api_key": "",
        },
        "local": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b",
            "enabled": False,
            "api_key": "",
        },
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
        "custom_providers": [],
    }


def _normalize_custom_providers(items: object) -> list[dict]:
    normalized: list[dict] = []
    if not isinstance(items, list):
        return normalized
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen or key in BUILTIN_PROVIDERS or key == "auto":
            continue
        seen.add(key)
        normalized.append(
            {
                "name": name,
                "enabled": bool(raw.get("enabled", True)),
                "base_url": str(raw.get("base_url", "")).strip(),
                "model": str(raw.get("model", "")).strip(),
                "api_key": str(raw.get("api_key", "")).strip(),
            }
        )
    return normalized


def get_custom_provider(settings: dict, provider: str) -> dict | None:
    target = str(provider or "").strip().lower()
    for item in settings.get("custom_providers", []):
        if str(item.get("name", "")).strip().lower() == target:
            return item
    return None


def provider_choices(settings: dict | None = None) -> list[str]:
    data = settings or load_ai_settings()
    choices = ["auto", *BUILTIN_PROVIDERS]
    for item in data.get("custom_providers", []):
        name = str(item.get("name", "")).strip()
        if name:
            choices.append(name)
    return choices


def provider_enabled(settings: dict, provider: str) -> bool:
    if provider in BUILTIN_PROVIDERS:
        return bool(settings.get(provider, {}).get("enabled", False))
    custom = get_custom_provider(settings, provider)
    return bool(custom and custom.get("enabled"))


def provider_config(settings: dict, provider: str) -> dict:
    if provider in BUILTIN_PROVIDERS:
        return dict(settings.get(provider, {}))
    return dict(get_custom_provider(settings, provider) or {})


def load_ai_settings() -> dict:
    if not AI_SETTINGS_PATH.exists() and LEGACY_AI_SETTINGS_PATH.exists():
        try:
            AI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            AI_SETTINGS_PATH.write_text(LEGACY_AI_SETTINGS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    if not AI_SETTINGS_PATH.exists():
        save_ai_settings(_default_settings())
    data = json.loads(AI_SETTINGS_PATH.read_text(encoding="utf-8"))
    base = _default_settings()
    base["provider"] = data.get("provider", base["provider"])
    for key in ("router", "local", "deepseek", "bailian"):
        if isinstance(data.get(key), dict):
            base[key].update(data[key])
    base["custom_providers"] = _normalize_custom_providers(data.get("custom_providers", []))
    return base


def save_ai_settings(settings: dict) -> None:
    AI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        configured = provider_config(settings, provider).get("api_key")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
    if provider in {"local", "router"}:
        return None
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
    if provider != "auto":
        cfg = provider_config(settings, provider)
        if provider in {"router", "local"}:
            if provider_enabled(settings, provider) and cfg.get("base_url") and cfg.get("model"):
                return provider, cfg["base_url"], cfg["model"]
        else:
            key = _provider_api_key(provider, settings)
            if provider_enabled(settings, provider) and cfg.get("base_url") and cfg.get("model") and (key or provider not in BUILTIN_PROVIDERS):
                return provider, cfg["base_url"], cfg["model"]
        return None, None, None

    router_cfg = provider_config(settings, "router")
    if provider_enabled(settings, "router") and router_cfg.get("base_url") and router_cfg.get("model"):
        return "router", router_cfg["base_url"], router_cfg["model"]

    local_cfg = provider_config(settings, "local")
    if provider_enabled(settings, "local") and local_cfg.get("base_url") and local_cfg.get("model"):
        return "local", local_cfg["base_url"], local_cfg["model"]

    for provider_name in ("bailian", "deepseek"):
        if provider_enabled(settings, provider_name) and _provider_api_key(provider_name, settings):
            cfg = provider_config(settings, provider_name)
            return provider_name, cfg["base_url"], cfg["model"]
    for item in settings.get("custom_providers", []):
        provider_name = str(item.get("name", "")).strip()
        if not provider_name:
            continue
        if provider_enabled(settings, provider_name) and item.get("base_url") and item.get("model"):
            return provider_name, str(item["base_url"]), str(item["model"])
    return None, None, None


def _candidate_providers(settings: dict) -> list[tuple[str, str, str, str | None]]:
    provider = settings.get("provider", "auto")
    ordered: list[tuple[str, str, str, str | None]] = []

    def add_provider(name: str) -> None:
        cfg = provider_config(settings, name)
        if not provider_enabled(settings, name):
            return
        if not cfg.get("base_url") or not cfg.get("model"):
            return
        key = _provider_api_key(name, settings)
        if name in {"router", "local"} or name not in BUILTIN_PROVIDERS:
            ordered.append((name, str(cfg["base_url"]), str(cfg["model"]), key))
            return
        if key:
            ordered.append((name, str(cfg["base_url"]), str(cfg["model"]), key))

    if provider == "router":
        add_provider("router")
        return ordered
    if provider == "local":
        add_provider("local")
        return ordered
    if provider in {"bailian", "deepseek"}:
        add_provider(provider)
        return ordered
    if provider != "auto":
        add_provider(provider)
        return ordered

    add_provider("router")
    add_provider("local")
    add_provider("bailian")
    add_provider("deepseek")
    for item in settings.get("custom_providers", []):
        add_provider(str(item.get("name", "")).strip())
    return ordered


def test_provider_connection(settings: dict, provider: str, timeout: int = 20) -> tuple[bool, str]:
    cfg = provider_config(settings, provider)
    if not cfg.get("base_url") or not cfg.get("model"):
        return False, "请先填写 Base URL 和 Model。"
    api_key = _provider_api_key(provider, settings)
    payload = {
        "messages": [
            {"role": "system", "content": "你是连接测试助手，只需简短回答。"},
            {"role": "user", "content": "请回复：连接成功"},
        ],
        "temperature": 0.1,
        "max_tokens": 32,
    }
    ok, actual_provider, text = _request_chat_with_candidates(
        [(provider, str(cfg["base_url"]), str(cfg["model"]), api_key)],
        payload,
        timeout=timeout,
    )
    if ok:
        return True, f"{actual_provider} 连接成功：{text[:80]}"
    return False, text


def _build_headers(provider: str, api_key: str | None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "StockDesk/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider not in {"local", "router"}:
        headers["Authorization"] = "Bearer "
    return headers


def _request_chat_with_fallback(settings: dict, payload: dict, timeout: int = 60) -> tuple[bool, str | None, str]:
    candidates = _candidate_providers(settings)
    if not candidates:
        return False, None, "未检测到可用的本地模型 / DeepSeek / 百炼配置。"

    errors: list[str] = []
    for provider, base_url, model, api_key in candidates:
        request_payload = dict(payload)
        request_payload["model"] = model
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=body,
            method="POST",
            headers=_build_headers(provider, api_key),
        )
        try:
            return True, provider, _request_chat(request, timeout=timeout)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    return False, candidates[0][0], "；".join(errors) if errors else "未知错误"


def _cache_get(cache_key: str, ttl_seconds: int) -> dict | None:
    item = AI_RUNTIME_CACHE.get(cache_key)
    if not item:
        return None
    created_at = item.get("created_at")
    if not isinstance(created_at, dt.datetime):
        return None
    if (dt.datetime.now() - created_at).total_seconds() > ttl_seconds:
        AI_RUNTIME_CACHE.pop(cache_key, None)
        return None
    return item.get("value")


def _cache_set(cache_key: str, value: dict) -> None:
    AI_RUNTIME_CACHE[cache_key] = {
        "created_at": dt.datetime.now(),
        "value": value,
    }


def _request_chat(request: urllib.request.Request, timeout: int = 60) -> str:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or json.dumps(error, ensure_ascii=False)
            raise RuntimeError(str(message))
        if data.get("message"):
            extra = f"（code={data.get('code')}）" if data.get("code") else ""
            raise RuntimeError(f"{data.get('message')}{extra}")
    raise RuntimeError("返回结果缺少 choices，接口可能不是标准 OpenAI 兼容格式。")


def _request_chat_with_candidates(
    candidates: list[tuple[str, str, str, str | None]],
    payload: dict,
    timeout: int = 60,
) -> tuple[bool, str | None, str]:
    if not candidates:
        return False, None, "no candidates"

    errors: list[str] = []
    for provider, base_url, model, api_key in candidates:
        request_payload = dict(payload)
        request_payload["model"] = model
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=body,
            method="POST",
            headers=_build_headers(provider, api_key),
        )
        try:
            return True, provider, _request_chat(request, timeout=timeout)
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    return False, candidates[0][0], " | ".join(errors) if errors else "unknown error"


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
        headers=_build_headers(provider, api_key),
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
        headers=_build_headers(provider, api_key),
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


def _group_candidates_by_tier(settings: dict) -> tuple[list[tuple[str, str, str, str | None]], list[tuple[str, str, str, str | None]]]:
    local_like: list[tuple[str, str, str, str | None]] = []
    cloud_like: list[tuple[str, str, str, str | None]] = []
    for candidate in _candidate_providers(settings):
        if candidate[0] in {"router", "local"}:
            local_like.append(candidate)
        else:
            cloud_like.append(candidate)
    return local_like, cloud_like


def _compact_lines(items: list[str], limit: int = 4) -> str:
    return "\n".join(f"- {item}" for item in items[:limit] if str(item).strip())


def _build_local_analysis_prompt(stock_item: dict, analysis: dict) -> str:
    latest_facts = _compact_lines(analysis.get("facts", []), 3)
    key_observations = _compact_lines(analysis.get("observations", []), 4)
    key_risks = _compact_lines(analysis.get("risks", []), 3)
    next_plan = _compact_lines(analysis.get("suggestions", []), 3)
    score = analysis.get("score", {})
    return (
        f"你是本地轻量股票分析助手，请基于压缩后的事实上下文，用中文给出一版 120 字以内的简短判断。\n"
        f"只输出三段：当前状态、关键风险、下一步观察。\n"
        f"标的：{analysis.get('name') or stock_item.get('label') or stock_item.get('symbol')}（{stock_item.get('symbol','')}）\n"
        f"最新事实：\n{latest_facts}\n"
        f"观察：\n{key_observations}\n"
        f"风险：\n{key_risks}\n"
        f"建议：\n{next_plan}\n"
        f"量价评分：{score.get('score', 0)}/100，风险级别：{score.get('risk', '未知')}"
    )


def _build_local_chat_context(stock_item: dict, analysis: dict, history: list[dict], user_message: str) -> list[dict]:
    compact_history = []
    for item in history[-4:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            compact_history.append({"role": role, "content": content[:220]})
    return [
        {
            "role": "system",
            "content": (
                "你是本地值班股票助手，只做简短、保守、基于事实的回答。"
                "如果问题明显涉及大盘、新闻、持仓策略、详细计划或多只股票比较，请回答：需要升级云分析。"
            ),
        },
        {"role": "system", "content": _build_local_analysis_prompt(stock_item, analysis)},
        *compact_history,
        {"role": "user", "content": user_message},
    ]


def _stock_chat_needs_cloud(user_message: str, analysis: dict, history: list[dict]) -> tuple[bool, str]:
    text = user_message.strip()
    if len(text) >= 60:
        return True, "问题较长"
    keywords = ("结合", "详细", "完整", "大盘", "新闻", "持仓", "最近", "前几天", "为什么", "预案", "推荐", "对比", "复盘")
    if any(keyword in text for keyword in keywords):
        return True, "涉及复杂上下文"
    if len(history) >= 6:
        return True, "历史上下文较长"
    if len(analysis.get("risks", [])) >= 4:
        return True, "风险维度较多"
    return False, "本地可答"


def _build_local_news_prompt(stock_item: dict, news_items: list[dict]) -> str:
    compact_news = "\n".join(f"- {item['time']} {item['title']}" for item in news_items[:4])
    return (
        f"你是本地值班新闻助手，请用中文做 120 字以内的简短新闻判断。\n"
        f"标的：{stock_item.get('label') or stock_item.get('symbol')}（{stock_item.get('symbol', '')}）\n"
        f"新闻：\n{compact_news}\n"
        "只输出三段：正向因素、负向因素、总体判断。总体判断只允许写偏正向、偏负向或中性。"
    )


def _news_needs_cloud(news_items: list[dict]) -> tuple[bool, str]:
    if len(news_items) >= 6:
        return True, "新闻条数较多"
    title_length = sum(len(item.get("title", "")) for item in news_items[:6])
    if title_length >= 120:
        return True, "新闻信息较长"
    return False, "本地可答"


def _build_local_recommend_prompt(market_snapshot: dict, candidates: list[dict]) -> str:
    compact_candidates = []
    for item in candidates[:5]:
        compact_candidates.append(
            f"- {item.get('label') or item.get('name') or item.get('symbol')}（{item.get('symbol', '')}）"
            f" 评分 {item.get('score', 0)} 涨跌 {item.get('change_pct', 0):+.2f}%"
            f" 新闻 {item.get('news_bias', '中性')} 风险 {item.get('quant_risk', '中等')}"
        )
    return (
        "你是本地值班推荐助手，请从候选池里挑最多 3 只更值得优先观察的股票。\n"
        f"市场情绪：{market_snapshot.get('mood', '未知')}，策略：{market_snapshot.get('tactic', '等待确认')}\n"
        f"候选池：\n" + "\n".join(compact_candidates) + "\n"
        "请直接输出 JSON："
        '{"summary":"一句话总结","picks":[{"symbol":"股票代码","reason":"不超过30字","setup":"不超过20字","risk":"不超过20字"}]}'
    )


def _recommend_needs_cloud(market_snapshot: dict, candidates: list[dict]) -> tuple[bool, str]:
    if len(candidates) > 8:
        return True, "候选较多"
    if len(market_snapshot.get("main_directions", [])) >= 3:
        return True, "主线方向较多"
    if any(str(item.get("news_bias", "")) == "偏负向" for item in candidates[:5]):
        return True, "候选分化较明显"
    return False, "本地可答"


def _request_chat_by_strategy(
    settings: dict,
    payload: dict,
    *,
    timeout: int = 60,
    prefer_local: bool = False,
    prefer_cloud: bool = False,
) -> tuple[bool, str | None, str]:
    local_like, cloud_like = _group_candidates_by_tier(settings)
    ordered_groups: list[list[tuple[str, str, str, str | None]]] = []
    if prefer_cloud:
        ordered_groups = [cloud_like, local_like]
    elif prefer_local:
        ordered_groups = [local_like, cloud_like]
    else:
        ordered_groups = [local_like + cloud_like]

    first_provider: str | None = None
    errors: list[str] = []
    for group in ordered_groups:
        if not group:
            continue
        first_provider = first_provider or group[0][0]
        ok, resolved_provider, result = _request_chat_with_candidates(group, payload, timeout=timeout)
        if ok:
            return True, resolved_provider, result
        if result:
            errors.append(result)
    return False, first_provider, " | ".join(item for item in errors if item) or "no available providers"


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
    latest_fact = next((item for item in analysis.get("facts", []) if "最新价" in item), "")
    cache_key = f"explain:{stock_item.get('symbol','')}:{latest_fact}:{analysis.get('score', {}).get('score', 0)}"
    cached = _cache_get(cache_key, ttl_seconds=90)
    if cached:
        return cached

    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的本地模型 / DeepSeek / 百炼配置，当前仅显示规则分析结果。",
        }

    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": "你是一个保守、克制、事实优先的股票分析助手。"},
            {"role": "user", "content": build_ai_prompt(stock_item, analysis)},
        ],
    }
    ok, resolved_provider, result = _request_chat_with_fallback(settings, payload, timeout=60)
    if ok:
        value = {"enabled": True, "provider": resolved_provider, "content": result}
        _cache_set(cache_key, value)
        return value
    value = {
        "enabled": False,
        "provider": resolved_provider,
        "content": f"AI 解释暂时不可用：{result}",
    }
    _cache_set(cache_key, value)
    return value


def chat_with_stock_context(stock_item: dict, analysis: dict, history: list[dict], user_message: str) -> dict:
    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的本地模型 / DeepSeek / 百炼配置。",
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
    ok, resolved_provider, result = _request_chat_with_fallback(settings, payload, timeout=60)
    if ok:
        return {"enabled": True, "provider": resolved_provider, "content": result}
    fallback = (
        f"AI 对话暂时不可用：{result}\n\n"
        "先给你一版本地规则兜底：\n"
        f"- 量价评分：{analysis['score']['score']} / 100，风险级别：{analysis['score']['risk']}\n"
        f"- 一夜持股法：{analysis['overnight']['status']}\n"
        "- 当前最该看的不是情绪判断，而是关键位能否收复，以及反弹时量能是否跟上。"
    )
    return {
        "enabled": False,
        "provider": resolved_provider,
        "content": fallback,
    }


def explain_runtime_event(stock_item: dict, quote: dict, market_state: dict, event_text: str) -> dict:
    settings = load_ai_settings()
    if not _candidate_providers(settings):
        return {
            "enabled": False,
            "provider": None,
            "content": "先按规则处理，不急着升级到云分析。",
        }

    latest_price = float(quote.get("price", 0) or 0)
    change_pct = float(quote.get("change_pct", 0) or 0)
    cost_price = stock_item.get("cost_price")
    lots = int(stock_item.get("lots", 0) or 0)
    levels = ", ".join(f"{float(level):.2f}" for level in (stock_item.get("levels", []) or [])[:4]) or "暂无"
    cost_text = f"{float(cost_price):.3f}" if cost_price not in (None, "") else "--"

    cache_key = (
        f"event:{stock_item.get('symbol','')}:{event_text}:"
        f"{latest_price:.2f}:{change_pct:+.2f}:{market_state.get('mood','未知')}"
    )
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached:
        return cached

    prompt = (
        "你是一个克制、保守的 A 股盘中事件助手。"
        "请根据下面的事实，输出一句不超过36字的中文提示。"
        "要求：只说当前该先看什么或先做什么；"
        "不要喊单，不要保证涨跌，不要输出编号。\n\n"
        f"股票：{stock_item.get('label', stock_item.get('symbol', ''))}（{stock_item.get('symbol', '')}）\n"
        f"最新价：{latest_price:.2f}\n"
        f"涨跌幅：{change_pct:+.2f}%\n"
        f"成本：{cost_text}\n"
        f"持仓：{lots}手\n"
        f"关键位：{levels}\n"
        f"市场状态：{market_state.get('mood', '未知')} / {market_state.get('tactic', '等待确认')}\n"
        f"触发事件：{event_text}\n\n"
        "请只输出一句简短提示。"
    )

    payload = {
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是盘中值班助手，回答短、稳、实用。"},
            {"role": "user", "content": prompt},
        ],
    }
    ok, resolved_provider, result = _request_chat_by_strategy(
        settings,
        payload,
        timeout=20,
        prefer_local=True,
    )
    if ok:
        content = result.strip().replace("\n", " ")
        value = {"enabled": True, "provider": resolved_provider, "content": content[:60]}
        _cache_set(cache_key, value)
        return value

    value = {
        "enabled": False,
        "provider": resolved_provider,
        "content": "先按防守和关键位承接处理。",
    }
    _cache_set(cache_key, value)
    return value


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
                f" 次日预案={item['next_day_summary']}"
            )
        )
    return (
        "你是一个保守、克制、风险优先的 A 股推荐助手。\n"
        "请根据市场状态和候选池，从中选出最多 5 只更值得优先观察的股票。\n"
        "不要给绝对化指令，不要编造新股票，只能从候选池里选。\n"
        "请输出 JSON，格式为：\n"
        '{\n  "summary": "一句话总结",\n  "picks": [\n    {\n      "symbol": "股票代码",\n      "reason": "为什么推荐",\n      "setup": "怎么打，不超过 40 字",\n      "risk": "最大风险，不超过 30 字"\n    }\n  ]\n}\n\n'
        f"今日市场状态：\n{market_snapshot.get('summary', '暂无')}\n"
        f"指数：\n{chr(10).join(market_lines) if market_lines else '- 暂无'}\n\n"
        f"候选池：\n{chr(10).join(candidate_lines)}"
    )


def analyze_news_with_ai(stock_item: dict, news_items: list[dict]) -> dict:
    latest_news = news_items[0] if news_items else {}
    cache_key = f"news:{stock_item.get('symbol','')}:{latest_news.get('time','')}:{latest_news.get('title','')}:{len(news_items)}"
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached:
        return cached

    settings = load_ai_settings()
    if not _candidate_providers(settings):
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的 AI 配置，当前仅显示规则型新闻判断。",
        }

    needs_cloud, _reason = _news_needs_cloud(news_items)
    ok = False
    resolved_provider = None
    result = ""

    if not needs_cloud:
        local_payload = {
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "你是本地值班新闻助手，只做简短、克制、基于事实的解释。"},
                {"role": "user", "content": _build_local_news_prompt(stock_item, news_items)},
            ],
        }
        ok, resolved_provider, result = _request_chat_by_strategy(
            settings,
            local_payload,
            timeout=25,
            prefer_local=True,
        )

    if not ok:
        news_text = "\n".join(f"- {item['time']} {item['title']}" for item in news_items[:10])
        cloud_payload = {
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
        ok, resolved_provider, result = _request_chat_by_strategy(
            settings,
            cloud_payload,
            timeout=70,
            prefer_cloud=True,
        )

    if ok:
        value = {"enabled": True, "provider": resolved_provider, "content": result}
        _cache_set(cache_key, value)
        return value

    value = {
        "enabled": False,
        "provider": resolved_provider,
        "content": f"AI 新闻解读暂时不可用：{result}",
    }
    _cache_set(cache_key, value)
    return value


def recommend_candidates_with_ai(market_snapshot: dict, candidates: list[dict]) -> dict:
    top_signature = "|".join(
        f"{item.get('symbol','')}:{item.get('score',0)}:{item.get('close_strength','')}:{item.get('news_bias','')}"
        for item in candidates[:8]
    )
    cache_key = f"recommend:{market_snapshot.get('generated_at','')}:{market_snapshot.get('mood','')}:{top_signature}"
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached:
        return cached

    settings = load_ai_settings()
    if not _candidate_providers(settings):
        return {"enabled": False, "provider": None, "content": "未检测到可用的 AI 配置。", "picks": []}

    needs_cloud, _reason = _recommend_needs_cloud(market_snapshot, candidates)
    ok = False
    resolved_provider = None
    result = ""

    if not needs_cloud:
        local_payload = {
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "你是本地值班推荐助手，只能从候选池里挑观察名单，不编造股票。",
                },
                {"role": "user", "content": _build_local_recommend_prompt(market_snapshot, candidates)},
            ],
        }
        ok, resolved_provider, result = _request_chat_by_strategy(
            settings,
            local_payload,
            timeout=30,
            prefer_local=True,
        )

    if not ok:
        prompt = build_recommend_prompt(market_snapshot, candidates)
        cloud_payload = {
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个保守、克制、风险优先的 A 股推荐助手。只能从候选池里选择，不要编造股票。",
                },
                {"role": "user", "content": prompt},
            ],
        }
        ok, resolved_provider, result = _request_chat_by_strategy(
            settings,
            cloud_payload,
            timeout=90,
            prefer_cloud=True,
        )

    if not ok:
        value = {
            "enabled": False,
            "provider": resolved_provider,
            "content": f"AI 推荐暂时不可用：{result}",
            "picks": [],
        }
        _cache_set(cache_key, value)
        return value

    try:
        data = _extract_json_block(result)
        if isinstance(data, dict):
            value = {
                "enabled": True,
                "provider": resolved_provider,
                "content": data.get("summary", result),
                "picks": data.get("picks", []),
            }
            _cache_set(cache_key, value)
            return value
        value = {"enabled": True, "provider": resolved_provider, "content": result, "picks": []}
        _cache_set(cache_key, value)
        return value
    except Exception as exc:
        value = {
            "enabled": False,
            "provider": resolved_provider,
            "content": f"AI 推荐结果解析失败：{exc}",
            "picks": [],
        }
        _cache_set(cache_key, value)
        return value


def analyze_news_with_ai(stock_item: dict, news_items: list[dict]) -> dict:
    latest_news = news_items[0] if news_items else {}
    cache_key = f"news:{stock_item.get('symbol','')}:{latest_news.get('time','')}:{latest_news.get('title','')}:{len(news_items)}"
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached:
        return cached

    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的 AI 配置，当前仅显示规则型新闻判断。",
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
    ok, resolved_provider, result = _request_chat_with_fallback(settings, payload, timeout=60)
    if ok:
        value = {"enabled": True, "provider": resolved_provider, "content": result}
        _cache_set(cache_key, value)
        return value
    value = {
        "enabled": False,
        "provider": resolved_provider,
        "content": f"AI 新闻解读暂时不可用：{result}",
    }
    _cache_set(cache_key, value)
    return value


def recommend_candidates_with_ai(market_snapshot: dict, candidates: list[dict]) -> dict:
    top_signature = "|".join(
        f"{item.get('symbol','')}:{item.get('score',0)}:{item.get('close_strength','')}:{item.get('news_bias','')}"
        for item in candidates[:8]
    )
    cache_key = f"recommend:{market_snapshot.get('generated_at','')}:{market_snapshot.get('mood','')}:{top_signature}"
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached:
        return cached

    settings = load_ai_settings()
    provider, base_url, model = _resolve_provider(settings)
    if not provider or not base_url or not model:
        return {"enabled": False, "provider": None, "content": "未检测到可用的 AI 配置。", "picks": []}

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
    ok, resolved_provider, result = _request_chat_with_fallback(settings, payload, timeout=90)
    if not ok:
        value = {
            "enabled": False,
            "provider": resolved_provider,
            "content": f"AI 推荐暂时不可用：{result}",
            "picks": [],
        }
        _cache_set(cache_key, value)
        return value
    try:
        data = _extract_json_block(result)
        if isinstance(data, dict):
            value = {
                "enabled": True,
                "provider": resolved_provider,
                "content": data.get("summary", result),
                "picks": data.get("picks", []),
            }
            _cache_set(cache_key, value)
            return value
        value = {"enabled": True, "provider": resolved_provider, "content": result, "picks": []}
        _cache_set(cache_key, value)
        return value
    except Exception as exc:
        value = {
            "enabled": False,
            "provider": resolved_provider,
            "content": f"AI 推荐结果解析失败：{exc}",
            "picks": [],
        }
        _cache_set(cache_key, value)
        return value


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
    ok, resolved_provider, result = _request_chat_with_fallback(settings, payload, timeout=90)
    if ok:
        return {"enabled": True, "provider": resolved_provider, "content": result}
    fallback = []
    if pick_lines:
        fallback.append("当前可继续观察的候选仍以上一轮推荐结果为主。")
        fallback.append("建议先围绕推荐列表里的关键位、尾盘强弱和量化风险来追问，不要脱离今天盘面重新激进选股。")
    if market_snapshot.get("mood"):
        fallback.append(f"今天市场环境偏向：{market_snapshot.get('mood')}。")
    fallback.append(f"AI 推荐对话暂时不可用：{result}")
    return {
        "enabled": False,
        "provider": resolved_provider,
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


def build_ai_prompt(stock_item: dict, analysis: dict) -> str:
    facts = "\n".join(f"- {item}" for item in analysis["facts"])
    observations = "\n".join(f"- {item}" for item in analysis["observations"])
    risks = "\n".join(f"- {item}" for item in analysis["risks"])
    suggestions = "\n".join(f"- {item}" for item in analysis["suggestions"])
    score = analysis["score"]
    next_day_plan = "\n".join(f"- {item}" for item in analysis.get("next_day_plan", []))
    return (
        "你是一个保守、克制、事实优先的 A 股分析助手。\n"
        "请基于以下规则分析结果，用中文给出简明、稳健的解释。\n"
        "要求：1. 明确区分事实与推断。2. 不要给绝对化买卖指令。"
        "3. 重点解释当前走势、关键位、风险和次日观察框架。"
        "4. 输出四个小节：事实解读、方法解释、风险、保守建议。"
        "5. 控制在 400 字以内。\n\n"
        f"标的：{analysis['name']}（{stock_item['symbol']}）\n"
        f"规则分析事实：\n{facts}\n\n"
        f"方法观察：\n{observations}\n\n"
        f"风险提示：\n{risks}\n\n"
        f"保守建议：\n{suggestions}\n\n"
        f"次日预案：\n{next_day_plan}\n\n"
        f"补充信息：\n- 量价评分：{score['score']} / 100\n- 风险级别：{score['risk']}"
    )


def get_ai_explanation(stock_item: dict, analysis: dict) -> dict:
    latest_fact = next((item for item in analysis.get("facts", []) if "最新价" in item), "")
    cache_key = f"explain:{stock_item.get('symbol','')}:{latest_fact}:{analysis.get('score', {}).get('score', 0)}"
    cached = _cache_get(cache_key, ttl_seconds=90)
    if cached:
        return cached

    settings = load_ai_settings()
    if not _candidate_providers(settings):
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的本地模型、路由网关或云模型配置，当前仅显示规则分析结果。",
        }

    local_payload = {
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是本地值班股票助手，请基于事实做简短、克制、保守的分析。"},
            {"role": "user", "content": _build_local_analysis_prompt(stock_item, analysis)},
        ],
    }
    ok, resolved_provider, result = _request_chat_by_strategy(
        settings,
        local_payload,
        timeout=25,
        prefer_local=True,
    )
    if ok:
        value = {"enabled": True, "provider": resolved_provider, "content": result}
        _cache_set(cache_key, value)
        return value

    cloud_payload = {
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": "你是一个保守、克制、事实优先的股票分析助手。"},
            {"role": "user", "content": build_ai_prompt(stock_item, analysis)},
        ],
    }
    ok, resolved_provider, result = _request_chat_by_strategy(
        settings,
        cloud_payload,
        timeout=70,
        prefer_cloud=True,
    )
    if ok:
        value = {"enabled": True, "provider": resolved_provider, "content": result}
        _cache_set(cache_key, value)
        return value

    value = {
        "enabled": False,
        "provider": resolved_provider,
        "content": f"AI解释暂时不可用：{result}",
    }
    _cache_set(cache_key, value)
    return value


def chat_with_stock_context(stock_item: dict, analysis: dict, history: list[dict], user_message: str) -> dict:
    settings = load_ai_settings()
    if not _candidate_providers(settings):
        return {
            "enabled": False,
            "provider": None,
            "content": "未检测到可用的本地模型、路由网关或云模型配置。",
        }

    needs_cloud, reason = _stock_chat_needs_cloud(user_message, analysis, history)
    if not needs_cloud:
        local_payload = {
            "temperature": 0.2,
            "messages": _build_local_chat_context(stock_item, analysis, history, user_message),
        }
        ok, resolved_provider, result = _request_chat_by_strategy(
            settings,
            local_payload,
            timeout=35,
            prefer_local=True,
        )
        if ok and "需要升级云分析" not in result:
            return {"enabled": True, "provider": resolved_provider, "content": result}
        reason = f"{reason}，本地答复不足"

    facts = "\n".join(f"- {item}" for item in analysis["facts"])
    observations = "\n".join(f"- {item}" for item in analysis["observations"])
    risks = "\n".join(f"- {item}" for item in analysis["risks"])
    suggestions = "\n".join(f"- {item}" for item in analysis["suggestions"])
    next_day_plan = "\n".join(f"- {item}" for item in analysis.get("next_day_plan", []))

    payload = {
        "temperature": 0.3,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个保守、克制、事实优先的 A 股分析助手。"
                    "请围绕当前股票做连续对话，明确区分事实与推断，不要给绝对化喊单。"
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
                    f"次日预案：\n{next_day_plan}\n\n"
                    f"量价评分：{analysis['score']['score']} / 100\n"
                    f"风险级别：{analysis['score']['risk']}\n"
                    f"升级原因：{reason}"
                ),
            },
            *history[-6:],
            {"role": "user", "content": user_message},
        ],
    }
    ok, resolved_provider, result = _request_chat_by_strategy(
        settings,
        payload,
        timeout=70,
        prefer_cloud=True,
    )
    if ok:
        return {"enabled": True, "provider": resolved_provider, "content": result}

    fallback = (
        f"AI 对话暂时不可用：{result}\n\n"
        "先给你一版本地规则兜底：\n"
        f"- 量价评分：{analysis['score']['score']} / 100，风险级别：{analysis['score']['risk']}\n"
        "- 当前更重要的是看关键位能否收复，以及反弹时量能是否跟上。"
    )
    return {
        "enabled": False,
        "provider": resolved_provider,
        "content": fallback,
    }
