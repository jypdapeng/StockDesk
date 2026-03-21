import threading
import tkinter as tk
from tkinter import scrolledtext
import webbrowser

from ai_provider import analyze_news_with_ai
from stock_news import analyze_news_bias, fetch_stock_news


BG = "#0f172a"
PANEL = "#111827"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
BORDER = "#334155"
POS = "#22c55e"
NEG = "#ef4444"
NEU = "#f59e0b"
BTN = "#1d4ed8"
BTN_HOVER = "#2563eb"


def open_news_panel(parent: tk.Tk, stock_item: dict, on_mouse_enter=None, center_dialog=None) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("相关新闻")
    dialog.configure(bg=BG)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)
    dialog.geometry("940x640")
    dialog.minsize(860, 560)

    title = stock_item.get("label") or stock_item["symbol"]

    state = {
        "all_items": [],
        "filtered_items": [],
        "bias": {"overall": "中性", "positive": [], "negative": [], "neutral": []},
        "filter": "all",
    }

    container = tk.Frame(dialog, bg=BG, padx=16, pady=16)
    container.pack(fill="both", expand=True)

    header = tk.Frame(container, bg=BG)
    header.pack(fill="x")

    title_box = tk.Frame(header, bg=BG)
    title_box.pack(side="left", fill="x", expand=True)
    tk.Label(
        title_box,
        text=f"{title} · 相关新闻",
        fg=TEXT,
        bg=BG,
        font=("Microsoft YaHei UI", 14, "bold"),
    ).pack(anchor="w")
    tk.Label(
        title_box,
        text="按偏正向、偏负向、中性整理新闻，并给出 AI 辅助解读。",
        fg=MUTED,
        bg=BG,
        font=("Microsoft YaHei UI", 9),
    ).pack(anchor="w", pady=(4, 0))

    toolbar = tk.Frame(header, bg=BG)
    toolbar.pack(side="right")

    def make_button(parent_widget, text, command, bg=BTN):
        button = tk.Button(
            parent_widget,
            text=text,
            command=command,
            fg=TEXT,
            bg=bg,
            activebackground=BTN_HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            font=("Microsoft YaHei UI", 9, "bold"),
            cursor="hand2",
        )
        return button

    refresh_button = make_button(toolbar, "刷新", lambda: start_fetch())
    refresh_button.pack(side="left", padx=(0, 8))
    open_stock_button = make_button(
        toolbar,
        "打开股票页",
        lambda: webbrowser.open(f"https://gu.qq.com/{stock_item['market']}{stock_item['symbol']}", new=2),
        bg="#065f46",
    )
    open_stock_button.pack(side="left")

    summary_row = tk.Frame(container, bg=BG)
    summary_row.pack(fill="x", pady=(14, 12))

    overall_card = tk.Frame(summary_row, bg=PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER)
    overall_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
    count_card = tk.Frame(summary_row, bg=PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER)
    count_card.pack(side="left", fill="both", expand=True, padx=8)
    ai_card = tk.Frame(summary_row, bg=PANEL, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER)
    ai_card.pack(side="left", fill="both", expand=True, padx=(8, 0))

    tk.Label(overall_card, text="规则判断", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
    overall_value = tk.Label(overall_card, text="加载中...", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 20, "bold"))
    overall_value.pack(anchor="w", pady=(8, 0))
    overall_desc = tk.Label(overall_card, text="", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9))
    overall_desc.pack(anchor="w", pady=(6, 0))

    tk.Label(count_card, text="新闻分布", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
    badge_row = tk.Frame(count_card, bg=PANEL)
    badge_row.pack(anchor="w", pady=(10, 0))

    positive_badge = tk.Label(badge_row, text="利好 0", fg=TEXT, bg="#14532d", padx=10, pady=5, font=("Microsoft YaHei UI", 9, "bold"))
    positive_badge.pack(side="left", padx=(0, 8))
    negative_badge = tk.Label(badge_row, text="利空 0", fg=TEXT, bg="#7f1d1d", padx=10, pady=5, font=("Microsoft YaHei UI", 9, "bold"))
    negative_badge.pack(side="left", padx=(0, 8))
    neutral_badge = tk.Label(badge_row, text="中性 0", fg=TEXT, bg="#92400e", padx=10, pady=5, font=("Microsoft YaHei UI", 9, "bold"))
    neutral_badge.pack(side="left")

    tk.Label(ai_card, text="AI 新闻解读", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
    ai_value = tk.Label(
        ai_card,
        text="加载中...",
        fg=TEXT,
        bg=PANEL,
        font=("Microsoft YaHei UI", 10),
        justify="left",
        wraplength=280,
    )
    ai_value.pack(anchor="w", pady=(8, 0))

    content = tk.Frame(container, bg=BG)
    content.pack(fill="both", expand=True)
    content.grid_columnconfigure(0, weight=7)
    content.grid_columnconfigure(1, weight=5)
    content.grid_rowconfigure(1, weight=1)

    filter_bar = tk.Frame(content, bg=BG)
    filter_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=(0, 8))

    filter_buttons: dict[str, tk.Button] = {}

    def set_filter(filter_key: str) -> None:
        state["filter"] = filter_key
        for key, button in filter_buttons.items():
            is_active = key == filter_key
            button.configure(bg=BTN if is_active else PANEL)
        apply_filter()

    for key, label in (("all", "全部"), ("positive", "利好"), ("negative", "利空"), ("neutral", "中性")):
        button = tk.Button(
            filter_bar,
            text=label,
            command=lambda selected=key: set_filter(selected),
            fg=TEXT,
            bg=BTN if key == "all" else PANEL,
            activebackground=BTN_HOVER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            font=("Microsoft YaHei UI", 9, "bold"),
            cursor="hand2",
        )
        button.pack(side="left", padx=(0, 8))
        filter_buttons[key] = button

    list_card = tk.Frame(content, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    list_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
    list_card.grid_rowconfigure(1, weight=1)
    list_card.grid_columnconfigure(0, weight=1)
    tk.Label(list_card, text="新闻列表", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))

    list_frame = tk.Frame(list_card, bg=PANEL)
    list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
    list_frame.grid_rowconfigure(0, weight=1)
    list_frame.grid_columnconfigure(0, weight=1)

    news_list = tk.Listbox(
        list_frame,
        bg=PANEL,
        fg=TEXT,
        selectbackground="#1e3a8a",
        selectforeground=TEXT,
        activestyle="none",
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 9),
    )
    news_list.grid(row=0, column=0, sticky="nsew")
    list_scroll = tk.Scrollbar(list_frame, orient="vertical", command=news_list.yview)
    list_scroll.grid(row=0, column=1, sticky="ns")
    news_list.configure(yscrollcommand=list_scroll.set)

    detail_card = tk.Frame(content, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    detail_card.grid(row=1, column=1, sticky="nsew")
    detail_card.grid_rowconfigure(2, weight=1)
    detail_card.grid_columnconfigure(0, weight=1)

    tk.Label(detail_card, text="新闻详情", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
    detail_time = tk.Label(detail_card, text="请选择一条新闻", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9))
    detail_time.grid(row=1, column=0, sticky="w", padx=12)
    detail_text = scrolledtext.ScrolledText(
        detail_card,
        wrap="word",
        bg=PANEL,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 10),
    )
    detail_text.grid(row=2, column=0, sticky="nsew", padx=12, pady=(8, 10))
    detail_text.configure(state="disabled")

    detail_actions = tk.Frame(detail_card, bg=PANEL)
    detail_actions.grid(row=3, column=0, sticky="e", padx=12, pady=(0, 10))
    current_link = {"url": None}

    open_news_button = make_button(detail_actions, "打开原文", lambda: current_link["url"] and webbrowser.open(current_link["url"], new=2), bg="#065f46")
    open_news_button.pack(side="right")

    def classify_item(item: dict) -> str:
        title_text = item["title"]
        pos_score = sum(1 for keyword in ("签订", "中标", "增长", "增持", "回购", "盈利", "预增", "突破", "扩产", "复产", "利好", "合作") if keyword in title_text)
        neg_score = sum(1 for keyword in ("风险", "下跌", "减持", "亏损", "预亏", "警惕", "终止", "诉讼", "处罚", "调查", "违约", "压力") if keyword in title_text)
        if pos_score > neg_score and pos_score > 0:
            return "positive"
        if neg_score > pos_score and neg_score > 0:
            return "negative"
        return "neutral"

    def show_detail(index: int) -> None:
        if index < 0 or index >= len(state["filtered_items"]):
            return
        item = state["filtered_items"][index]
        current_link["url"] = item["url"]
        detail_time.configure(text=item["time"])
        detail_text.configure(state="normal")
        detail_text.delete("1.0", "end")
        detail_text.insert("1.0", item["title"])
        detail_text.configure(state="disabled")

    def on_select(_event=None) -> None:
        selection = news_list.curselection()
        if not selection:
            return
        show_detail(selection[0])

    def on_double_click(_event=None) -> None:
        selection = news_list.curselection()
        if not selection:
            return
        item = state["filtered_items"][selection[0]]
        webbrowser.open(item["url"], new=2)

    news_list.bind("<<ListboxSelect>>", on_select, add="+")
    news_list.bind("<Double-Button-1>", on_double_click, add="+")

    def render_list() -> None:
        news_list.delete(0, "end")
        for item in state["filtered_items"]:
            news_list.insert("end", f"{item['time'][5:]}  {item['title']}")
        if state["filtered_items"]:
            news_list.selection_clear(0, "end")
            news_list.selection_set(0)
            news_list.activate(0)
            show_detail(0)
        else:
            detail_time.configure(text="暂无新闻")
            detail_text.configure(state="normal")
            detail_text.delete("1.0", "end")
            detail_text.insert("1.0", "当前筛选条件下暂无新闻。")
            detail_text.configure(state="disabled")
            current_link["url"] = None

    def apply_filter() -> None:
        filter_key = state["filter"]
        if filter_key == "all":
            state["filtered_items"] = list(state["all_items"])
        else:
            state["filtered_items"] = [item for item in state["all_items"] if item.get("tone") == filter_key]
        render_list()

    def apply_result(items: list[dict], bias: dict, ai_result: dict) -> None:
        state["all_items"] = []
        for item in items:
            enriched = dict(item)
            enriched["tone"] = classify_item(item)
            state["all_items"].append(enriched)
        state["bias"] = bias

        overall = bias["overall"]
        if overall == "偏正向":
            overall_value.configure(text=overall, fg=POS)
        elif overall == "偏负向":
            overall_value.configure(text=overall, fg=NEG)
        else:
            overall_value.configure(text=overall, fg=NEU)

        desc_parts = []
        if bias["positive"]:
            desc_parts.append(f"利好线索较多，共 {len(bias['positive'])} 条")
        if bias["negative"]:
            desc_parts.append(f"利空线索较多，共 {len(bias['negative'])} 条")
        if bias["neutral"]:
            desc_parts.append(f"中性新闻 {len(bias['neutral'])} 条")
        overall_desc.configure(text="，".join(desc_parts) if desc_parts else "暂无可分析的新闻样本")

        positive_badge.configure(text=f"利好 {len(bias['positive'])}")
        negative_badge.configure(text=f"利空 {len(bias['negative'])}")
        neutral_badge.configure(text=f"中性 {len(bias['neutral'])}")

        ai_value.configure(text=ai_result["content"])
        apply_filter()

    def start_fetch() -> None:
        overall_value.configure(text="加载中...", fg=TEXT)
        overall_desc.configure(text="")
        ai_value.configure(text="正在获取相关新闻与 AI 解读...")
        state["all_items"] = []
        apply_filter()

        def worker() -> None:
            try:
                items = fetch_stock_news(stock_item["symbol"], stock_item["market"])
                bias = analyze_news_bias(items)
                ai_result = analyze_news_with_ai(stock_item, items) if items else {
                    "enabled": False,
                    "provider": None,
                    "content": "暂无可分析的新闻。",
                }
            except Exception as exc:
                items = []
                bias = {"overall": "中性", "positive": [], "negative": [], "neutral": []}
                ai_result = {"enabled": False, "provider": None, "content": f"加载新闻失败：{exc}"}
            parent.after(0, lambda: apply_result(items, bias, ai_result))

        threading.Thread(target=worker, daemon=True).start()

    close_row = tk.Frame(container, bg=BG)
    close_row.pack(fill="x", pady=(10, 0))
    make_button(close_row, "关闭", dialog.destroy, bg="#374151").pack(side="right")

    if center_dialog:
        center_dialog(dialog)
    if on_mouse_enter:
        dialog.bind("<Enter>", on_mouse_enter, add="+")

    start_fetch()
