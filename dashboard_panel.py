import datetime as dt
import tkinter as tk
from tkinter import messagebox, scrolledtext


BG = "#0f172a"
PANEL = "#111827"
CARD = "#1f2937"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
BORDER = "#334155"
BLUE = "#2563eb"
GREEN = "#065f46"
PURPLE = "#7c3aed"
RED = "#7f1d1d"
AMBER = "#92400e"
TEAL = "#0f766e"


def open_dashboard_panel(parent: tk.Tk, payload_getter, on_mouse_enter=None, center_dialog=None) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("交易指挥台")
    dialog.configure(bg=BG)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)
    dialog.geometry("1360x920")

    container = tk.Frame(dialog, bg=BG, padx=16, pady=16)
    container.pack(fill="both", expand=True)

    top_bar = tk.Frame(container, bg=BG)
    top_bar.pack(fill="x")
    tk.Label(top_bar, text="交易指挥台", fg=TEXT, bg=BG, font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
    tk.Label(
        top_bar,
        text="先看市场，再看账户，再决定今天做什么。",
        fg=MUTED,
        bg=BG,
        font=("Microsoft YaHei UI", 9),
    ).pack(side="left", padx=(12, 0))
    session_label = tk.Label(top_bar, text="时段：盘前", fg="#93c5fd", bg=BG, font=("Microsoft YaHei UI", 9, "bold"))
    session_label.pack(side="right", padx=(12, 0))
    status_label = tk.Label(top_bar, text="等待刷新...", fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 9))
    status_label.pack(side="right")

    grid = tk.Frame(container, bg=BG)
    grid.pack(fill="both", expand=True, pady=(14, 0))
    for col in range(3):
        grid.grid_columnconfigure(col, weight=1)
    for row in range(4):
        grid.grid_rowconfigure(row, weight=1)

    market_card = _card(grid, "今日市场状态", PURPLE)
    market_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
    direction_card = _card(grid, "主线与风险方向", BLUE)
    direction_card.grid(row=0, column=1, sticky="nsew", padx=8, pady=(0, 8))
    account_card = _card(grid, "账户概览", GREEN)
    account_card.grid(row=0, column=2, sticky="nsew", padx=(8, 0), pady=(0, 8))

    focus_card = _card(grid, "今日重点盯盘", AMBER)
    focus_card.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 8), pady=8)
    risk_card = _card(grid, "风险与纪律", RED)
    risk_card.grid(row=1, column=2, sticky="nsew", padx=(8, 0), pady=8)

    action_card = _card(grid, "今日行动建议", TEAL)
    action_card.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=8)
    todo_card = _card(grid, "统一行动清单", "#155e75")
    todo_card.grid(row=2, column=1, columnspan=2, sticky="nsew", padx=(8, 0), pady=8)

    opening_card = _card(grid, "开盘预测", "#1e40af")
    opening_card.grid(row=3, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
    noon_card = _card(grid, "午盘总结", "#7c2d12")
    noon_card.grid(row=3, column=1, sticky="nsew", padx=8, pady=(8, 0))
    close_card = _card(grid, "收盘总结", "#14532d")
    close_card.grid(row=3, column=2, sticky="nsew", padx=(8, 0), pady=(8, 0))

    market_box = _text_box(market_card, height=12)
    direction_box = _text_box(direction_card, height=12)
    account_box = _text_box(account_card, height=12)
    focus_box = _text_box(focus_card, height=18)
    risk_box = _text_box(risk_card, height=18)
    action_box = _text_box(action_card, height=12)
    todo_box = _text_box(todo_card, height=12)
    opening_box = _text_box(opening_card, height=10)
    noon_box = _text_box(noon_card, height=10)
    close_box = _text_box(close_card, height=10)

    footer = tk.Frame(container, bg=BG)
    footer.pack(fill="x", pady=(12, 0))

    report_cache = {"text": ""}

    def refresh_view() -> None:
        payload = payload_getter()
        market = payload.get("market", {})
        account = payload.get("account", [])
        focus = payload.get("focus", [])
        risks = payload.get("risks", [])
        actions = payload.get("actions", [])
        todo = payload.get("todo", [])
        do_list = payload.get("do_list", [])
        avoid_list = payload.get("avoid_list", [])

        market_lines = [
            f"市场情绪：{market.get('mood', '未知')}",
            f"建议策略：{market.get('tactic', '等待确认')}",
            f"风险偏置：{market.get('risk_bias', '中等')}",
            f"市场评分：{market.get('score', 0)}/100",
            f"最强指数：{market.get('strongest_index', '未知')}",
            f"主线强度：{market.get('main_strength', '等待刷新')}",
            f"风险信号：{market.get('risk_signal', '等待刷新')}",
            "",
            "一句话判断：",
            market.get("summary", "暂无"),
        ]

        direction_lines = ["主线方向："]
        direction_lines.extend([f"- {line}" for line in market.get("main_directions", [])] or ["- 暂无"])
        direction_lines.append("")
        direction_lines.append("风险方向：")
        direction_lines.extend([f"- {line}" for line in market.get("avoid_directions", [])] or ["- 暂无"])
        direction_lines.append("")
        direction_lines.append("执行重点：")
        direction_lines.append(f"- {market.get('execution_focus', '暂无')}")
        direction_lines.append("")
        direction_lines.append("纪律建议：")
        direction_lines.extend([f"- {line}" for line in market.get("discipline", [])] or ["- 暂无"])

        action_lines = ["今天该做："]
        action_lines.extend([f"- {line}" for line in do_list] or ["- 暂无"])
        action_lines.append("")
        action_lines.append("今天别做：")
        action_lines.extend([f"- {line}" for line in avoid_list] or ["- 暂无"])
        action_lines.append("")
        action_lines.append("行动建议：")
        action_lines.extend([f"- {line}" for line in actions] or ["- 暂无"])

        opening_lines = _build_opening_forecast(market, focus, risks)
        noon_lines = _build_noon_summary(market, focus, risks, todo)
        close_lines = _build_close_summary(market, account, focus, risks, todo)

        _write_box(market_box, "\n".join(market_lines).strip())
        _write_box(direction_box, "\n".join(direction_lines).strip())
        _write_box(account_box, "\n".join(account).strip() or "暂无账户数据。")
        _write_box(focus_box, "\n".join(focus).strip() or "暂无重点盯盘标的。")
        _write_box(risk_box, "\n".join(risks).strip() or "暂无特别风险提示。")
        _write_box(action_box, "\n".join(action_lines).strip())
        _write_box(todo_box, "\n".join(todo).strip() or "暂无待执行动作。")
        _write_box(opening_box, "\n".join(opening_lines).strip())
        _write_box(noon_box, "\n".join(noon_lines).strip())
        _write_box(close_box, "\n".join(close_lines).strip())

        report_cache["text"] = _build_daily_report_text(
            market=market,
            opening_lines=opening_lines,
            noon_lines=noon_lines,
            close_lines=close_lines,
        )

        session_label.configure(text=f"时段：{_trading_session_label(dt.datetime.now())}")
        status_label.configure(text=f"已刷新：{market.get('generated_at', '刚刚')}")

    def copy_daily_report() -> None:
        if not report_cache["text"]:
            refresh_view()
        text = report_cache["text"].strip()
        if not text:
            messagebox.showinfo("复制日报", "当前没有可复制内容。")
            return
        dialog.clipboard_clear()
        dialog.clipboard_append(text)
        messagebox.showinfo("复制日报", "已复制到剪贴板，可直接粘贴到日报。")

    tk.Button(footer, text="刷新", command=refresh_view, bg=BLUE, fg=TEXT, relief="flat", bd=0, padx=12, pady=6).pack(side="left")
    tk.Button(footer, text="复制日报", command=copy_daily_report, bg="#0ea5e9", fg=TEXT, relief="flat", bd=0, padx=12, pady=6).pack(side="left", padx=(8, 0))
    tk.Button(footer, text="关闭", command=dialog.destroy, bg=BORDER, fg=TEXT, relief="flat", bd=0, padx=12, pady=6).pack(side="right")

    if center_dialog:
        center_dialog(dialog)
    if on_mouse_enter:
        dialog.bind("<Enter>", on_mouse_enter, add="+")

    refresh_view()


def _trading_session_label(now: dt.datetime) -> str:
    hm = now.hour * 100 + now.minute
    if hm < 930:
        return "盘前"
    if hm <= 1130:
        return "上午盘中"
    if hm < 1300:
        return "午休"
    if hm <= 1500:
        return "下午盘中"
    return "收盘后"


def _build_opening_forecast(market: dict, focus: list[str], risks: list[str]) -> list[str]:
    lines = ["明日开盘预判："]
    mood = market.get("mood", "未知")
    tactic = market.get("tactic", "等待确认")
    lines.append(f"- 预估开盘环境：{mood}")
    lines.append(f"- 开盘打法：{tactic}")
    lines.append("- 重点看三件事：")
    lines.append("1. 最强指数是否继续领涨")
    lines.append("2. 持仓标的是否站稳关键位")
    lines.append("3. 早盘是否放量承接而非冲高回落")
    if focus:
        lines.append("")
        lines.append("开盘优先观察：")
        lines.extend([f"- {item}" for item in focus[:2]])
    if risks:
        lines.append("")
        lines.append("开盘风险提醒：")
        lines.append(f"- {risks[0]}")
    return lines


def _build_noon_summary(market: dict, focus: list[str], risks: list[str], todo: list[str]) -> list[str]:
    lines = ["午盘复盘框架："]
    lines.append(f"- 市场状态：{market.get('mood', '未知')} / 评分 {market.get('score', 0)}/100")
    lines.append(f"- 主线强度：{market.get('main_strength', '等待刷新')}")
    lines.append("- 午盘要判断：")
    lines.append("1. 上午强势是否有持续性")
    lines.append("2. 持仓分时重心是否抬高")
    lines.append("3. 风险事件是否在增多")
    if todo:
        lines.append("")
        lines.append("午后优先动作：")
        lines.extend([f"- {item}" for item in todo[:2]])
    elif focus:
        lines.append("")
        lines.append("午后观察名单：")
        lines.extend([f"- {item}" for item in focus[:2]])
    if risks:
        lines.append("")
        lines.append("午盘风险：")
        lines.append(f"- {risks[0]}")
    return lines


def _build_close_summary(market: dict, account: list[str], focus: list[str], risks: list[str], todo: list[str]) -> list[str]:
    lines = ["收盘总结模板："]
    lines.append(f"- 今日市场：{market.get('mood', '未知')}（{market.get('summary', '暂无')}）")
    lines.append("- 今晚复盘三步：")
    lines.append("1. 先复盘执行：计划内动作是否按纪律完成")
    lines.append("2. 再复盘持仓：哪些票该减压，哪些票可继续观察")
    lines.append("3. 最后排计划：次日开盘 A/B 预案写清楚")
    if account:
        lines.append("")
        lines.append("账户状态摘要：")
        lines.extend([f"- {line}" for line in account[:2]])
    if risks:
        lines.append("")
        lines.append("收盘风险结论：")
        lines.append(f"- {risks[0]}")
    if todo:
        lines.append("")
        lines.append("次日待办起点：")
        lines.extend([f"- {line}" for line in todo[:2]])
    elif focus:
        lines.append("")
        lines.append("次日观察起点：")
        lines.extend([f"- {line}" for line in focus[:2]])
    return lines


def _build_daily_report_text(market: dict, opening_lines: list[str], noon_lines: list[str], close_lines: list[str]) -> str:
    generated = market.get("generated_at", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    title = f"交易指挥台日报（{generated}）"
    opening = "\n".join(opening_lines).strip()
    noon = "\n".join(noon_lines).strip()
    close = "\n".join(close_lines).strip()
    return f"{title}\n\n【开盘预测】\n{opening}\n\n【午盘总结】\n{noon}\n\n【收盘总结】\n{close}\n"


def _card(parent, title, accent):
    frame = tk.Frame(parent, bg=CARD, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
    head = tk.Frame(frame, bg=CARD)
    head.pack(fill="x", pady=(0, 8))
    tk.Label(head, text=title, fg=TEXT, bg=CARD, font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
    tk.Frame(head, bg=accent, width=12, height=12).pack(side="right")
    return frame


def _text_box(parent, height=10):
    box = scrolledtext.ScrolledText(
        parent,
        wrap="word",
        height=height,
        bg=PANEL,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        font=("Microsoft YaHei UI", 9),
    )
    box.pack(fill="both", expand=True)
    box.configure(state="disabled")
    box.bind("<MouseWheel>", lambda event, widget=box: widget.yview_scroll(int(-1 * (event.delta / 120)), "units"), add="+")
    return box


def _write_box(box, text):
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", text)
    box.configure(state="disabled")
