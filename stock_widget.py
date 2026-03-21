import argparse
import datetime as dt
import pathlib
import re
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext
import urllib.error
import webbrowser

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

from ai_provider import analyze_news_with_ai, load_ai_settings, save_ai_settings
from ai_chat_panel import open_ai_chat_panel
from analysis_panel import open_analysis_panel
from image_import_panel import open_image_import_dialog
from market_recommend import generate_recommendations
from news_panel import open_news_panel
from stock_news import analyze_news_bias, fetch_stock_news
from stock_common import APP_RUNTIME, APP_VERSION, DEFAULT_CONFIG, RESOURCE_DIR, fetch_intraday_points, fetch_quote, infer_market, load_config, save_config

BG = "#111827"
PANEL = "#1f2937"
TEXT = "#f9fafb"
MUTED = "#9ca3af"
UP = "#ef4444"
DOWN = "#22c55e"
FLAT = "#f59e0b"
SELECTED = "#0f172a"
ACCENT = "#22c55e"
BORDER = "#374151"
BUTTON_BLUE = "#2563eb"
BUTTON_GREEN = "#065f46"
BUTTON_PURPLE = "#7c3aed"
BUTTON_RED = "#7f1d1d"
DONATE_ALIPAY = RESOURCE_DIR / "assets" / "donate_alipay.jpg"
DONATE_WECHAT = RESOURCE_DIR / "assets" / "donate_wechat.jpg"
TAB_LABELS = {"recommended": "推荐", "favorite": "收藏", "holding": "持有", "closed": "清仓"}
STATUS_OPTIONS = [("推荐", "recommended"), ("收藏", "favorite"), ("持有", "holding"), ("清仓", "closed")]
FAVORITE_FILTER_LABELS = {"全部": "all", "有代码": "with_code", "无代码": "without_code", "有提醒位": "with_levels", "无提醒位": "without_levels"}
FAVORITE_FILTER_KEYS = {value: key for key, value in FAVORITE_FILTER_LABELS.items()}

def color_for_change(change: float) -> str:
    if change > 0:
        return UP
    if change < 0:
        return DOWN
    return FLAT

class StockWidget:
    def __init__(self, config_path: pathlib.Path):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.interval_ms = max(1000, int(self.config["interval"]) * 1000)
        self.root = tk.Tk()
        self.root.title("股票盯盘")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        widget_cfg = self.config.get("widget", {})
        self.show_title = bool(widget_cfg.get("show_title", False))
        self.anchor_side = widget_cfg.get("dock_side", "right") if widget_cfg.get("dock_side") in {"left", "right"} else "right"
        self.saved_y = int(widget_cfg.get("y", 80))
        self.active_tab = widget_cfg.get("active_tab", "holding") if widget_cfg.get("active_tab") in TAB_LABELS else "holding"
        self.sort_by = widget_cfg.get("sort_by", "default") if widget_cfg.get("sort_by") in {"default", "ai_score", "price", "change_pct"} else "default"
        self.sort_desc = bool(widget_cfg.get("sort_desc", True))
        self.favorite_search_var = tk.StringVar(value=widget_cfg.get("favorite_search", ""))
        initial_filter = widget_cfg.get("favorite_filter", "all")
        self.favorite_filter_var = tk.StringVar(value=FAVORITE_FILTER_KEYS.get(initial_filter, "全部"))
        self.recommend_filter = widget_cfg.get(
            "recommend_filter",
            {
                "min_price": "",
                "max_price": "",
                "min_score": 45,
                "max_quant_risk": "中等",
                "require_levels": True,
                "prefer_positive_news": False,
            },
        )
        self.dragging = False
        self.drag_x = 0
        self.drag_y = 0
        self.selected_symbol = None
        self.rows = {}
        self.price_history = {}
        self.chart_fetching = set()
        self.chart_points_screen = []
        self.chart_hover_text_id = None
        self.chart_hover_line_id = None
        self.fetch_inflight = False
        self.runtime_quotes = {}
        self.runtime_scores = {}
        self.max_live_quotes = 10
        self.hide_job = None
        self.hidden = False
        self.visible_strip = 14
        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.on_move)
        self.root.bind("<ButtonRelease-1>", self.end_move)
        self.frame = tk.Frame(self.root, bg=PANEL, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER)
        self.frame.pack(fill="both", expand=True)
        self.header = tk.Frame(self.frame, bg=PANEL)
        self.header.pack(fill="x")
        self.title_label = tk.Label(self.header, text="股票盯盘", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 11, "bold"))
        if self.show_title:
            self.title_label.pack(side="left")
        self.time_label = tk.Label(self.header, text="--:--:--", fg=MUTED, bg=PANEL, font=("Consolas", 9))
        self.time_label.pack(side="left", padx=(8, 0))
        self.make_header_button("关闭", self.root.destroy, PANEL, fg=MUTED)
        self.make_header_button("⋯", self.open_actions_menu, BORDER)
        self.make_header_button("AI分析", self.open_ai_analysis_panel, BUTTON_PURPLE)
        self.recommend_button = tk.Button(
            self.header,
            text="AI推荐",
            command=self.open_ai_recommend_dialog,
            fg=TEXT,
            bg=BUTTON_GREEN,
            activebackground=BUTTON_GREEN,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=8,
            pady=2,
        )
        self.recommend_filter_button = tk.Button(
            self.header,
            text="推荐条件",
            command=self.open_recommend_filter_dialog,
            fg=TEXT,
            bg=BORDER,
            activebackground=BORDER,
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=8,
            pady=2,
        )
        self.tip_label = tk.Label(self.frame, text="可拖动到桌面任意位置，松手后自动吸附左侧或右侧", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8))
        self.tip_label.pack(anchor="w", pady=(4, 8))
        self.tab_bar = tk.Frame(self.frame, bg=PANEL)
        self.tab_bar.pack(fill="x", pady=(0, 8))
        self.tab_buttons = {}
        for key, text in TAB_LABELS.items():
            button = tk.Button(self.tab_bar, text=text, command=lambda tab=key: self.switch_tab(tab), fg=TEXT, bg=BG, activebackground=BG, activeforeground=TEXT, relief="flat", bd=0, font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=4)
            button.pack(side="left", padx=(0, 6))
            self.tab_buttons[key] = button
        self.favorite_filter_bar = tk.Frame(self.frame, bg=PANEL)
        tk.Label(self.favorite_filter_bar, text="搜索", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).pack(side="left")
        favorite_search_entry = tk.Entry(self.favorite_filter_bar, textvariable=self.favorite_search_var, width=16)
        favorite_search_entry.pack(side="left", padx=(6, 8))
        favorite_search_entry.bind("<KeyRelease>", lambda _event: self.on_favorite_filter_change())
        tk.Label(self.favorite_filter_bar, text="过滤", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).pack(side="left")
        tk.OptionMenu(self.favorite_filter_bar, self.favorite_filter_var, *FAVORITE_FILTER_LABELS.keys(), command=lambda _value: self.on_favorite_filter_change()).pack(side="left", padx=(6, 8))
        tk.Button(self.favorite_filter_bar, text="清空", command=self.clear_favorite_filters).pack(side="left")
        self.empty_label = tk.Label(self.frame, text="暂无股票，点击“新增”开始添加", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9))
        self.list_wrapper = tk.Frame(self.frame, bg=PANEL, height=5 * 136)
        self.list_wrapper.pack(fill="both", expand=False)
        self.list_wrapper.pack_propagate(False)
        self.list_canvas = tk.Canvas(self.list_wrapper, bg=PANEL, highlightthickness=0, bd=0, height=5 * 136)
        self.list_scrollbar = tk.Scrollbar(self.list_wrapper, orient="vertical", command=self.on_list_scrollbar)
        self.list_canvas.configure(yscrollcommand=self.list_scrollbar.set)
        self.list_canvas.pack(side="left", fill="both", expand=True)
        self.list_scrollbar.pack(side="right", fill="y")
        self.list_container = tk.Frame(self.list_canvas, bg=PANEL)
        self.list_canvas_window = self.list_canvas.create_window((0, 0), window=self.list_container, anchor="nw")
        self.list_container.bind("<Configure>", lambda _e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.bind("<Configure>", self.on_list_canvas_configure)
        self.list_canvas.bind_all("<MouseWheel>", self.on_list_mousewheel, add="+")
        self.chart_frame = tk.Frame(self.frame, bg=BG, padx=8, pady=8, highlightthickness=1, highlightbackground=BORDER)
        self.chart_title = tk.Label(self.chart_frame, text="分时图", fg=TEXT, bg=BG, font=("Microsoft YaHei UI", 9, "bold"))
        self.chart_title.pack(anchor="w")
        self.chart_meta = tk.Label(self.chart_frame, text="启动后实时采样", fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8))
        self.chart_meta.pack(anchor="w", pady=(2, 6))
        self.chart_canvas = tk.Canvas(self.chart_frame, width=280, height=88, bg=BG, highlightthickness=0, bd=0)
        self.chart_canvas.pack(fill="x", expand=True)
        self.chart_canvas.bind("<Motion>", self.on_chart_hover, add="+")
        self.chart_canvas.bind("<Leave>", self.on_chart_leave, add="+")
        self.build_rows()
        self.bind_hover_events()
        self.place_initial_position()
        if self.all_stocks() and self.visible_stocks():
            self.hide_to_edge()
        self.refresh()

    def make_header_button(self, text, command, bg, fg=TEXT):
        button = tk.Button(self.header, text=text, command=command, fg=fg, bg=bg, activebackground=bg, activeforeground=TEXT, relief="flat", bd=0, font=("Microsoft YaHei UI", 8, "bold"), padx=8 if text != "关闭" else 4, pady=2 if text != "关闭" else 0)
        button.pack(side="right", padx=(4, 0))

    def open_actions_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=TEXT, activebackground=BUTTON_BLUE, activeforeground=TEXT)
        menu.add_command(label="新增", command=self.open_add_dialog)
        menu.add_command(label="编辑", command=self.open_edit_dialog)
        menu.add_command(label="图片导入", command=self.open_image_import_dialog)
        sort_menu = tk.Menu(menu, tearoff=0, bg=PANEL, fg=TEXT, activebackground=BUTTON_BLUE, activeforeground=TEXT)
        sort_menu.add_command(label="默认顺序", command=lambda: self.set_sort("default", True))
        sort_menu.add_command(label="AI推荐评分", command=lambda: self.set_sort("ai_score", True))
        sort_menu.add_command(label="价格", command=lambda: self.set_sort("price", True))
        sort_menu.add_command(label="涨幅", command=lambda: self.set_sort("change_pct", True))
        sort_menu.add_separator()
        sort_menu.add_command(label="价格（低到高）", command=lambda: self.set_sort("price", False))
        sort_menu.add_command(label="涨幅（低到高）", command=lambda: self.set_sort("change_pct", False))
        sort_menu.add_command(label="AI推荐评分（低到高）", command=lambda: self.set_sort("ai_score", False))
        menu.add_cascade(label="排序", menu=sort_menu)
        menu.add_separator()
        menu.add_command(label="加仓", command=lambda: self.open_trade_dialog("add"))
        menu.add_command(label="减仓", command=lambda: self.open_trade_dialog("reduce"))
        menu.add_separator()
        menu.add_command(label="打开网页", command=self.open_selected_site)
        menu.add_command(label="相关新闻", command=self.open_news_panel)
        menu.add_command(label="AI对话", command=self.open_ai_chat_panel)
        menu.add_command(label="AI设置", command=self.open_ai_settings_dialog)
        menu.add_command(label="版本信息", command=self.show_version_info)
        if self.active_tab == "favorite":
            menu.add_separator()
            menu.add_command(label="批量删除当前筛选", command=self.batch_delete_filtered_favorites)
            menu.add_command(label="清空导入结果", command=self.clear_imported_favorites)
        menu.add_separator()
        menu.add_command(label="显示/隐藏标题", command=self.toggle_title_visibility)
        menu.add_command(label="赞赏", command=self.open_donate_dialog)
        menu.add_command(label="删除", command=self.delete_selected)
        try:
            x = self.root.winfo_rootx() + self.root.winfo_width() - 40
            y = self.root.winfo_rooty() + 28
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def bind_hover_events(self):
        widgets = [self.root]
        stack = list(self.root.winfo_children())
        while stack:
            widget = stack.pop()
            widgets.append(widget)
            stack.extend(widget.winfo_children())
        for widget in widgets:
            widget.bind("<Enter>", self.on_mouse_enter, add="+")
            widget.bind("<Leave>", self.on_mouse_leave, add="+")
            widget.bind("<ButtonPress-1>", self.start_move, add="+")
            widget.bind("<B1-Motion>", self.on_move, add="+")
            widget.bind("<ButtonRelease-1>", self.end_move, add="+")

    def toggle_title_visibility(self):
        self.show_title = not self.show_title
        if self.show_title:
            self.title_label.pack(side="left", before=self.time_label)
        else:
            self.title_label.pack_forget()
        self.save_widget_preferences()

    def all_stocks(self):
        return self.config.get("stocks", [])

    def visible_stocks(self):
        if self.active_tab == "recommended":
            visible = [
                item
                for item in self.all_stocks()
                if item.get("status") == "recommended" or isinstance(item.get("recommended_pick"), dict) and item.get("recommended_pick")
            ]
        else:
            visible = [item for item in self.all_stocks() if item.get("status", "favorite") == self.active_tab]
        if self.active_tab != "favorite":
            return visible
        keyword = self.favorite_search_var.get().strip().lower()
        filter_mode = FAVORITE_FILTER_LABELS.get(self.favorite_filter_var.get().strip() or "全部", "all")
        filtered = []
        for item in visible:
            symbol = str(item.get("symbol", ""))
            label = str(item.get("label", ""))
            levels = item.get("levels", []) or []
            has_code = symbol.isdigit()
            if keyword and keyword not in symbol.lower() and keyword not in label.lower():
                continue
            if filter_mode == "with_code" and not has_code:
                continue
            if filter_mode == "without_code" and has_code:
                continue
            if filter_mode == "with_levels" and not levels:
                continue
            if filter_mode == "without_levels" and levels:
                continue
            filtered.append(item)
        return filtered

    def sorted_visible_stocks(self):
        visible = list(self.visible_stocks())
        if self.sort_by != "default":
            visible = sorted(visible, key=self._item_sort_value, reverse=self.sort_desc)
        return visible

    def find_stock(self, symbol):
        if not symbol:
            return None
        return next((item for item in self.all_stocks() if item["symbol"] == symbol), None)

    def switch_tab(self, tab):
        if tab not in TAB_LABELS:
            return
        self.active_tab = tab
        self.save_widget_preferences()
        self.build_rows()

    def on_favorite_filter_change(self):
        if self.active_tab == "favorite":
            self.save_widget_preferences()
            self.build_rows()

    def clear_favorite_filters(self):
        self.favorite_search_var.set("")
        self.favorite_filter_var.set("全部")
        self.on_favorite_filter_change()

    def refresh_tab_styles(self):
        for key, button in self.tab_buttons.items():
            selected = key == self.active_tab
            button.configure(bg=BUTTON_BLUE if selected else BG, activebackground=BUTTON_BLUE if selected else BG, fg=TEXT)
        if self.active_tab == "recommended":
            if not self.recommend_button.winfo_manager():
                self.recommend_button.pack(side="right", padx=(4, 0))
            if not self.recommend_filter_button.winfo_manager():
                self.recommend_filter_button.pack(side="right", padx=(4, 0))
        elif self.recommend_button.winfo_manager():
            self.recommend_button.pack_forget()
        if self.active_tab != "recommended" and self.recommend_filter_button.winfo_manager():
            self.recommend_filter_button.pack_forget()

    def save_widget_preferences(self):
        widget_cfg = self.config.setdefault("widget", {})
        widget_cfg["show_title"] = self.show_title
        widget_cfg["dock_side"] = self.anchor_side
        widget_cfg["y"] = max(0, int(self.root.winfo_y()))
        widget_cfg["active_tab"] = self.active_tab
        widget_cfg["sort_by"] = self.sort_by
        widget_cfg["sort_desc"] = self.sort_desc
        widget_cfg["favorite_search"] = self.favorite_search_var.get()
        widget_cfg["favorite_filter"] = FAVORITE_FILTER_LABELS.get(self.favorite_filter_var.get(), "all")
        widget_cfg["recommend_filter"] = self.recommend_filter
        save_config(self.config_path, self.config)

    def set_sort(self, sort_by, sort_desc=True):
        self.sort_by = sort_by
        self.sort_desc = sort_desc
        self.save_widget_preferences()
        self.build_rows()

    def _item_sort_value(self, item):
        symbol = item["symbol"]
        if self.sort_by == "ai_score":
            return self.runtime_scores.get(symbol, 0)
        quote = self.runtime_quotes.get(symbol, {})
        if self.sort_by == "price":
            return float(quote.get("price", 0) or 0)
        if self.sort_by == "change_pct":
            return float(quote.get("change_pct", 0) or 0)
        return 0

    def on_list_canvas_configure(self, event):
        self.list_canvas.itemconfigure(self.list_canvas_window, width=event.width)

    def on_list_mousewheel(self, event):
        try:
            widget_under_pointer = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except Exception:
            widget_under_pointer = None
        current = widget_under_pointer
        in_list = False
        while current is not None:
            if current == self.list_canvas or current == self.list_container or current == self.list_wrapper:
                in_list = True
                break
            current = current.master
        if in_list:
            self.list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            if self.active_tab != "holding" and not self.fetch_inflight and self.visible_stocks():
                self.fetch_inflight = True
                self.fetch_quotes_async()

    def on_list_scrollbar(self, *args):
        self.list_canvas.yview(*args)
        if self.active_tab != "holding" and not self.fetch_inflight and self.visible_stocks():
            self.fetch_inflight = True
            self.fetch_quotes_async()

    def update_favorite_filter_bar(self):
        if self.active_tab == "favorite":
            if not self.favorite_filter_bar.winfo_manager():
                self.favorite_filter_bar.pack(fill="x", pady=(0, 8))
        elif self.favorite_filter_bar.winfo_manager():
            self.favorite_filter_bar.pack_forget()

    def current_empty_text(self):
        return {"recommended": "暂无推荐股票", "favorite": "暂无收藏股票", "holding": "暂无持有股票，点击“新增”或“加仓”开始记录", "closed": "暂无清仓记录"}.get(self.active_tab, "暂无股票")
    def build_rows(self):
        for child in self.list_container.winfo_children():
            child.destroy()
        self.rows.clear()
        self.refresh_tab_styles()
        self.update_favorite_filter_bar()
        visible = self.sorted_visible_stocks()
        all_symbols = {item["symbol"] for item in self.all_stocks()}
        self.price_history = {symbol: self.price_history.get(symbol, []) for symbol in all_symbols}
        self.chart_fetching.intersection_update(all_symbols)
        if not visible:
            self.selected_symbol = None
            self.empty_label.configure(text=self.current_empty_text())
            self.empty_label.pack(anchor="w", pady=(0, 4))
            self.chart_frame.pack_forget()
            self.list_canvas.yview_moveto(0)
            self.bind_hover_events()
            return
        self.empty_label.pack_forget()
        for item in visible:
            symbol = item["symbol"]
            self.price_history.setdefault(symbol, [])
            row = tk.Frame(self.list_container, bg=BG, padx=8, pady=6, highlightthickness=2, highlightbackground=BORDER, highlightcolor=ACCENT)
            row.pack(fill="x", pady=4)
            header_left = tk.Frame(row, bg=BG)
            header_left.grid(row=0, column=0, sticky="w")
            title = tk.Label(header_left, text=item.get("label", symbol), fg=TEXT, bg=BG, font=("Microsoft YaHei UI", 10, "bold"))
            title.pack(side="left")
            manual_btn = tk.Button(header_left, text="✎", command=lambda s=symbol: self.open_manual_mark_dialog(s), fg=TEXT, bg=BORDER, activebackground=BUTTON_BLUE, activeforeground=TEXT, relief="flat", bd=0, padx=4, pady=0, font=("Microsoft YaHei UI", 8, "bold"), cursor="hand2")
            manual_btn.pack(side="left", padx=(6, 4))
            ai_btn = tk.Button(header_left, text="!", command=lambda s=symbol: self.open_ai_news_mark_dialog(s), fg=TEXT, bg=BUTTON_RED, activebackground=BUTTON_RED, activeforeground=TEXT, relief="flat", bd=0, padx=6, pady=0, font=("Microsoft YaHei UI", 8, "bold"), cursor="hand2")
            ai_btn.pack(side="left")
            code = tk.Label(row, text=symbol, fg=MUTED, bg=BG, font=("Consolas", 9))
            code.grid(row=1, column=0, sticky="w")
            right_panel = tk.Frame(row, bg=BG)
            right_panel.grid(row=0, column=1, rowspan=5, sticky="ne", padx=(20, 0))
            price_change_box = tk.Frame(right_panel, bg=BG)
            price_change_box.pack(anchor="e")
            price = tk.Label(price_change_box, text="...", fg=TEXT, bg=BG, font=("Consolas", 18, "bold"))
            price.pack(side="left", anchor="n")
            change = tk.Label(price_change_box, text="加载中", fg=MUTED, bg=BG, font=("Consolas", 10))
            change.pack(side="left", anchor="n", padx=(10, 0))
            badge_box = tk.Frame(right_panel, bg=BG)
            badge_box.pack(anchor="e", pady=(6, 0))
            levels = ", ".join(f"{level:.2f}" for level in item.get("levels", [])) or "-"
            level_label = tk.Label(row, text=f"提醒位 {levels}", fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8))
            level_label.grid(row=2, column=0, sticky="w", pady=(4, 0))
            position_label = tk.Label(row, text=self.position_text(item), fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8))
            position_label.grid(row=3, column=0, sticky="w", pady=(2, 0))
            trade_text = self.recommendation_summary(item) if self.active_tab == "recommended" else self.trade_summary(item)
            trade_label = tk.Label(row, text=trade_text, fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8))
            trade_label.grid(row=4, column=0, sticky="w", pady=(2, 0))
            manual_mark = item.get("manual_mark", {}) if isinstance(item.get("manual_mark"), dict) else {}
            ai_mark = item.get("ai_mark", {}) if isinstance(item.get("ai_mark"), dict) else {}
            manual_badge_text, manual_badge_bg, manual_badge_fg = self.action_badge_style(manual_mark.get("action"))
            ai_badge_text, ai_badge_bg, ai_badge_fg = self.action_badge_style(ai_mark.get("action"))
            manual_badge = tk.Label(badge_box, text=manual_badge_text, fg=manual_badge_fg, bg=manual_badge_bg, font=("Microsoft YaHei UI", 8, "bold"), padx=8, pady=2)
            manual_badge.pack(anchor="e", pady=(0, 4))
            ai_badge = tk.Label(badge_box, text=ai_badge_text, fg=ai_badge_fg, bg=ai_badge_bg, font=("Microsoft YaHei UI", 8, "bold"), padx=8, pady=2)
            ai_badge.pack(anchor="e")
            profit_label = tk.Label(right_panel, text="盈亏 --", fg=MUTED, bg=BG, font=("Consolas", 9, "bold"))
            profit_label.pack(anchor="e", pady=(10, 0))
            chip_bar = tk.Frame(row, bg=BG)
            chip_bar.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
            self.render_level_chips(chip_bar, item)
            risk_bar = tk.Frame(row, bg=BG)
            risk_bar.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
            self.render_risk_chips(risk_bar, item)
            plan_tag = tk.Label(
                row,
                text=self.next_day_summary(item),
                fg="#93c5fd",
                bg="#0f2747",
                font=("Microsoft YaHei UI", 8, "bold"),
                padx=8,
                pady=4,
                anchor="w",
                justify="left",
            )
            plan_tag.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            manual_tag = tk.Label(row, text=f"笔记  {self.manual_mark_summary(item)}", fg=self.action_color(manual_mark.get("action")), bg="#172554", font=("Microsoft YaHei UI", 8, "bold"), padx=8, pady=4, anchor="w", justify="left")
            manual_tag.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            ai_tag = tk.Label(row, text=f"新闻  {self.ai_mark_summary(item)}", fg=self.action_color(ai_mark.get("action")), bg="#3f1d2e", font=("Microsoft YaHei UI", 8, "bold"), padx=8, pady=4, anchor="w", justify="left")
            ai_tag.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            row.grid_columnconfigure(0, weight=1)
            widgets = [row, header_left, title, code, right_panel, price_change_box, price, change, level_label, position_label, trade_label, badge_box, manual_badge, ai_badge, chip_bar, risk_bar, plan_tag, manual_tag, ai_tag, profit_label]
            for widget in widgets:
                widget.bind("<Button-1>", lambda event, s=symbol: self.select_symbol(s), add="+")
            self.rows[symbol] = {"frame": row, "title": title, "code": code, "price": price, "change": change, "position": position_label, "trade": trade_label, "chips": chip_bar, "risk_chips": risk_bar, "plan": plan_tag, "manual": manual_tag, "ai": ai_tag, "manual_badge": manual_badge, "ai_badge": ai_badge, "profit": profit_label, "widgets": widgets}
        available = {item["symbol"] for item in visible}
        if self.selected_symbol not in available:
            self.selected_symbol = visible[0]["symbol"]
        self.select_symbol(self.selected_symbol)
        self.list_canvas.yview_moveto(0)
        self.chart_frame.pack(fill="x", pady=(8, 0))
        self.bind_hover_events()

    def current_quote_targets(self):
        visible = self.sorted_visible_stocks()
        if not visible:
            return []
        if self.active_tab == "holding":
            snapshot = [{"symbol": item["symbol"], "market": item["market"]} for item in visible]
        else:
            visible_count = 5
            total = len(visible)
            if total <= visible_count:
                visible_slice = visible
            else:
                first_fraction, _second_fraction = self.list_canvas.yview()
                max_start = max(0, total - visible_count)
                start = max(0, min(max_start, int(round(first_fraction * max_start))))
                end = min(total, start + visible_count)
                visible_slice = visible[start:end]
            snapshot = [{"symbol": item["symbol"], "market": item["market"]} for item in visible_slice[: self.max_live_quotes]]
        if self.selected_symbol and all(item["symbol"] != self.selected_symbol for item in snapshot):
            selected_item = self.find_stock(self.selected_symbol)
            if selected_item:
                snapshot.append({"symbol": selected_item["symbol"], "market": selected_item.get("market") or infer_market(selected_item["symbol"])})
        unique = []
        seen = set()
        for item in snapshot:
            symbol = item["symbol"]
            if symbol in seen:
                continue
            seen.add(symbol)
            unique.append(item)
        return unique

    def batch_delete_filtered_favorites(self):
        if self.active_tab != "favorite":
            messagebox.showinfo("批量删除", "请先切换到收藏页。")
            return
        targets = self.visible_stocks()
        if not targets:
            messagebox.showinfo("批量删除", "当前筛选结果为空。")
            return
        if not messagebox.askyesno("批量删除", f"确认删除当前筛选出的 {len(targets)} 条收藏吗？"):
            return
        target_symbols = {item["symbol"] for item in targets}
        self.config["stocks"] = [item for item in self.all_stocks() if item.get("symbol") not in target_symbols]
        self.selected_symbol = None
        self.save_and_reload()

    def clear_imported_favorites(self):
        imported = []
        for item in self.all_stocks():
            if item.get("status") != "favorite":
                continue
            if item.get("import_source") == "image":
                imported.append(item)
                continue
            if not item.get("levels") and int(item.get("lots", 0) or 0) <= 0 and not item.get("trades") and item.get("cost_price") in (None, "", 0):
                imported.append(item)
        if not imported:
            messagebox.showinfo("清空导入结果", "当前没有可清理的导入收藏。")
            return
        if not messagebox.askyesno("清空导入结果", f"确认清空 {len(imported)} 条图片导入收藏吗？"):
            return
        target_symbols = {item["symbol"] for item in imported}
        self.config["stocks"] = [item for item in self.all_stocks() if item.get("symbol") not in target_symbols]
        self.selected_symbol = None
        self.save_and_reload()

    def position_text(self, item):
        lots = int(item.get("lots", 0) or 0)
        cost_price = item.get("cost_price")
        if lots > 0 and cost_price not in (None, ""):
            return f"成本 {float(cost_price):.3f}  持仓 {lots} 手"
        if lots > 0:
            return f"成本 --  持仓 {lots} 手"
        return "成本 --  持仓 --"

    def trade_summary(self, item):
        trades = item.get("trades", [])
        if not trades:
            return f"分组 {TAB_LABELS.get(item.get('status', 'favorite'), '收藏')}"
        last = trades[-1]
        action = {"add": "加仓", "reduce": "减仓", "create": "建仓"}.get(last.get("action"), last.get("action", "记录"))
        text = f"最近 {action} {last.get('lots', 0)} 手"
        if last.get("price") not in (None, ""):
            text += f" @ {float(last['price']):.3f}"
        return text

    def manual_mark_summary(self, item):
        mark = item.get("manual_mark", {}) if isinstance(item.get("manual_mark"), dict) else {}
        action = str(mark.get("action", "")).strip()
        comment = str(mark.get("comment", "")).strip()
        if not action and not comment:
            return "未备注"
        if action and comment:
            return f"{action} · {comment[:24]}"
        return action or comment[:24]

    def ai_mark_summary(self, item):
        mark = item.get("ai_mark", {}) if isinstance(item.get("ai_mark"), dict) else {}
        action = str(mark.get("action", "")).strip()
        bias = str(mark.get("bias", "")).strip()
        if not action and not bias:
            return "未生成"
        if action and bias:
            return f"{bias} · {action}"
        return bias or action

    def recommendation_summary(self, item):
        pick = item.get("recommended_pick", {}) if isinstance(item.get("recommended_pick"), dict) else {}
        action = str(pick.get("action", "")).strip()
        reason = str(pick.get("reason", "")).strip()
        if not action and not reason:
            return "AI 推荐待生成"
        if action and reason:
            short_reason = reason[:18] + "..." if len(reason) > 18 else reason
            return f"推荐 {action} · {short_reason}"
        return f"推荐 {action or reason}"

    def action_color(self, action: str):
        action = str(action or "").strip()
        if any(key in action for key in ("加", "买", "持有", "关注")):
            return DOWN
        if any(key in action for key in ("抛", "减", "卖", "清")):
            return UP
        return MUTED

    def action_badge_style(self, action: str):
        action = str(action or "").strip()
        if any(key in action for key in ("加", "买")):
            return "加", "#14532d", "#bbf7d0"
        if any(key in action for key in ("减",)):
            return "减", "#7c2d12", "#fdba74"
        if any(key in action for key in ("抛", "卖", "清")):
            return "抛", "#7f1d1d", "#fecaca"
        if any(key in action for key in ("持有", "观察")):
            return "持", "#1d4ed8", "#bfdbfe"
        return "等", "#374151", "#e5e7eb"

    def level_chip_data(self, item):
        quote = self.runtime_quotes.get(item.get("symbol", ""))
        if not quote:
            return []
        price = float(quote.get("price", 0) or 0)
        chips = []
        for level in sorted(item.get("levels", []) or [], reverse=True)[:3]:
            diff = price - float(level)
            pct = abs(diff) / max(float(level), 0.01)
            if pct <= 0.003:
                chips.append((f"{level:.2f} 博弈", "#1d4ed8", "#dbeafe"))
            elif diff > 0 and pct <= 0.02:
                chips.append((f"{level:.2f} 收复", "#14532d", "#dcfce7"))
            elif diff < 0 and pct <= 0.02:
                chips.append((f"{level:.2f} 压力", "#7f1d1d", "#fee2e2"))
        return chips[:2]

    def next_day_summary(self, item):
        quote = self.runtime_quotes.get(item.get("symbol", ""))
        if not quote:
            return "次日预案  等待行情刷新后生成"
        price = float(quote.get("price", 0) or 0)
        levels = sorted(item.get("levels", []) or [], reverse=True)
        above = [level for level in levels if level >= price]
        below = sorted([level for level in levels if level <= price], reverse=True)
        change_pct = float(quote.get("change_pct", 0) or 0)
        if above:
            if change_pct >= 0:
                return f"次日预案  先看能否站稳 {above[0]:.2f}"
            return f"次日预案  反弹先看 {above[0]:.2f} 压力"
        if below:
            return f"次日预案  回落重点盯 {below[0]:.2f}"
        return "次日预案  先看分时强弱与价格重心"

    def render_level_chips(self, container, item):
        for child in container.winfo_children():
            child.destroy()
        chips = self.level_chip_data(item)
        if not chips:
            tk.Label(
                container,
                text="关键位  暂无",
                fg=MUTED,
                bg=BG,
                font=("Microsoft YaHei UI", 8),
            ).pack(side="left")
            return
        for text, fg, bg in chips:
            tk.Label(
                container,
                text=text,
                fg=fg,
                bg=bg,
                font=("Microsoft YaHei UI", 8, "bold"),
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))

    def risk_chip_data(self, item):
        quote = self.runtime_quotes.get(item.get("symbol", ""))
        if not quote:
            return []
        chips = []
        change_pct = float(quote.get("change_pct", 0) or 0)
        price = float(quote.get("price", 0) or 0)
        levels = item.get("levels", []) or []
        nearest = min((abs(price - float(level)) / max(float(level), 0.01) for level in levels), default=1)
        if change_pct <= -2:
            chips.append(("弱市降权", "#7f1d1d", "#fee2e2"))
        elif change_pct >= 3:
            chips.append(("拥挤观察", "#92400e", "#fde68a"))
        if nearest <= 0.003:
            chips.append(("关键位博弈", "#1d4ed8", "#dbeafe"))
        if change_pct <= -3:
            chips.append(("先防守", "#991b1b", "#fecaca"))
        elif change_pct > 0:
            chips.append(("看承接", "#14532d", "#dcfce7"))
        return chips[:2]

    def render_risk_chips(self, container, item):
        for child in container.winfo_children():
            child.destroy()
        chips = self.risk_chip_data(item)
        if not chips:
            tk.Label(
                container,
                text="风险  普通波动",
                fg=MUTED,
                bg=BG,
                font=("Microsoft YaHei UI", 8),
            ).pack(side="left")
            return
        for text, fg, bg in chips:
            tk.Label(
                container,
                text=text,
                fg=fg,
                bg=bg,
                font=("Microsoft YaHei UI", 8, "bold"),
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))

    def recommendation_score(self, stock_item, quote):
        score = 50
        change_pct = float(quote.get("change_pct", 0) or 0)
        if change_pct > 3:
            score += 18
        elif change_pct > 0:
            score += 8
        elif change_pct < -5:
            score -= 18
        elif change_pct < -2:
            score -= 8

        cost_price = stock_item.get("cost_price")
        lots = int(stock_item.get("lots", 0) or 0)
        price = float(quote.get("price", 0) or 0)
        if cost_price not in (None, "") and lots > 0:
            if price >= float(cost_price):
                score += 6
            else:
                score -= 6

        if stock_item.get("status") == "recommended":
            score += 5
        elif stock_item.get("status") == "closed":
            score -= 5

        levels = stock_item.get("levels", [])
        if levels:
            nearest = min(abs(float(level) - price) for level in levels)
            if nearest <= 0.03:
                score += 4

        return max(0, min(100, int(score)))

    def select_symbol(self, symbol):
        self.selected_symbol = symbol
        if symbol:
            self.ensure_intraday_history(symbol)
        for row_symbol, parts in self.rows.items():
            is_selected = row_symbol == symbol
            bg = SELECTED if is_selected else BG
            border = ACCENT if is_selected else BORDER
            parts["frame"].configure(bg=bg, highlightbackground=border, highlightcolor=border)
            for widget in parts["widgets"]:
                widget.configure(bg=bg)
        self.update_chart()

    def append_history(self, symbol, sample_time, price, prev_close):
        history = self.price_history.setdefault(symbol, [])
        if history and history[-1][0] == sample_time:
            history[-1] = (sample_time, price, prev_close)
            return
        history.append((sample_time, price, prev_close))
        if len(history) > 240:
            del history[:-240]

    def ensure_intraday_history(self, symbol):
        if not symbol or self.price_history.get(symbol) or symbol in self.chart_fetching:
            return
        stock_item = self.find_stock(symbol)
        if not stock_item:
            return
        self.chart_fetching.add(symbol)
        self.update_chart()
        def worker():
            try:
                points = fetch_intraday_points(symbol, stock_item.get("market"))
            except Exception:
                points = []
            self.root.after(0, lambda: self.apply_intraday_history(symbol, points))
        threading.Thread(target=worker, daemon=True).start()

    def apply_intraday_history(self, symbol, points):
        self.chart_fetching.discard(symbol)
        if points:
            self.price_history[symbol] = points[-240:]
        if symbol == self.selected_symbol:
            self.update_chart()

    def update_chart(self):
        self.chart_canvas.delete("all")
        self.chart_points_screen = []
        self.chart_hover_text_id = None
        self.chart_hover_line_id = None
        if not self.selected_symbol:
            self.chart_frame.pack_forget()
            return
        history = self.price_history.get(self.selected_symbol, [])
        if not history:
            self.chart_frame.pack(fill="x", pady=(8, 0))
            self.chart_title.configure(text=f"{self.selected_symbol} 分时图")
            self.chart_meta.configure(text="正在加载当日完整分时..." if self.selected_symbol in self.chart_fetching else "等待采样数据...")
            self.chart_canvas.create_text(140, 44, text="暂无分时数据", fill=MUTED, font=("Microsoft YaHei UI", 9))
            return
        self.chart_frame.pack(fill="x", pady=(8, 0))
        width = max(280, self.chart_canvas.winfo_width() or 280)
        height = max(88, self.chart_canvas.winfo_height() or 88)
        self.chart_canvas.configure(width=width, height=height)
        prices = [item[1] for item in history]
        prev_close = history[-1][2]
        min_price = min(prices + [prev_close])
        max_price = max(prices + [prev_close])
        if abs(max_price - min_price) < 1e-6:
            max_price += 0.01
            min_price -= 0.01
        left_pad, right_pad, top_pad, bottom_pad = 6, 6, 8, 14
        chart_w = max(10, width - left_pad - right_pad)
        chart_h = max(10, height - top_pad - bottom_pad)
        def x_for(index):
            return left_pad + chart_w if len(history) == 1 else left_pad + (chart_w * index / (len(history) - 1))
        def y_for(value):
            ratio = (value - min_price) / (max_price - min_price)
            return top_pad + chart_h - ratio * chart_h
        baseline_y = y_for(prev_close)
        self.chart_canvas.create_line(left_pad, baseline_y, width - right_pad, baseline_y, fill=BORDER, dash=(3, 2))
        points = []
        for idx, (sample_time, price, _) in enumerate(history):
            x = x_for(idx)
            y = y_for(price)
            points.extend([x, y])
            self.chart_points_screen.append((x, y, sample_time, price))
        latest_price = history[-1][1]
        line_color = color_for_change(latest_price - prev_close)
        if len(points) >= 4:
            self.chart_canvas.create_line(*points, fill=line_color, width=2, smooth=True)
        else:
            self.chart_canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill=line_color, outline=line_color)
        self.chart_canvas.create_text(left_pad, 2, anchor="nw", text=f"{max_price:.2f}", fill=MUTED, font=("Consolas", 8))
        self.chart_canvas.create_text(left_pad, height - 2, anchor="sw", text=f"{min_price:.2f}", fill=MUTED, font=("Consolas", 8))
        self.chart_canvas.create_text(width - right_pad, 2, anchor="ne", text=f"昨收 {prev_close:.2f}", fill=MUTED, font=("Microsoft YaHei UI", 8))
        self.chart_title.configure(text=f"{self.selected_symbol} 分时图")
        self.chart_meta.configure(text=f"当日分时 {len(history)} 点  最新 {history[-1][0]}  现价 {latest_price:.2f}")
    def on_chart_hover(self, event):
        if not self.chart_points_screen:
            return
        x, y, sample_time, price = min(self.chart_points_screen, key=lambda item: abs(item[0] - event.x))
        if self.chart_hover_line_id is not None:
            self.chart_canvas.delete(self.chart_hover_line_id)
        if self.chart_hover_text_id is not None:
            self.chart_canvas.delete(self.chart_hover_text_id)
        self.chart_hover_line_id = self.chart_canvas.create_line(x, 8, x, max(8, (self.chart_canvas.winfo_height() or 88) - 14), fill=ACCENT, dash=(2, 2))
        label_x = min(max(58, x), max(58, (self.chart_canvas.winfo_width() or 280) - 58))
        label_y = max(16, y - 12)
        self.chart_hover_text_id = self.chart_canvas.create_text(label_x, label_y, text=f"{sample_time}  {price:.2f}", fill=TEXT, font=("Consolas", 8, "bold"))

    def on_chart_leave(self, _event=None):
        if self.chart_hover_line_id is not None:
            self.chart_canvas.delete(self.chart_hover_line_id)
            self.chart_hover_line_id = None
        if self.chart_hover_text_id is not None:
            self.chart_canvas.delete(self.chart_hover_text_id)
            self.chart_hover_text_id = None

    def place_initial_position(self):
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        screen_height = self.root.winfo_screenheight()
        self.saved_y = max(10, min(self.saved_y, max(10, screen_height - height - 60)))
        self.snap_to_edge(self.anchor_side, persist=False)

    def snap_to_edge(self, side, persist=True):
        self.root.update_idletasks()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        height = self.root.winfo_height() or self.root.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        y = max(10, min(self.saved_y, max(10, screen_height - height - 60)))
        x = 0 if side == "left" else screen_width - width
        self.anchor_side = side
        self.saved_y = y
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False
        if persist:
            self.save_widget_preferences()

    def hide_to_edge(self):
        self.root.update_idletasks()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        y = self.saved_y
        x = -(width - self.visible_strip) if self.anchor_side == "left" else self.root.winfo_screenwidth() - self.visible_strip
        self.root.geometry(f"+{x}+{y}")
        self.hidden = True

    def show_from_edge(self):
        self.root.update_idletasks()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        y = self.saved_y
        x = 0 if self.anchor_side == "left" else self.root.winfo_screenwidth() - width
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def schedule_hide(self):
        if self.dragging or not self.visible_stocks():
            return
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
        self.hide_job = self.root.after(300, self.hide_if_pointer_outside)

    def hide_if_pointer_outside(self):
        self.hide_job = None
        if self.dragging:
            return
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        left, top = self.root.winfo_x(), self.root.winfo_y()
        right, bottom = left + self.root.winfo_width(), top + self.root.winfo_height()
        if left <= pointer_x <= right and top <= pointer_y <= bottom:
            return
        self.hide_to_edge()

    def on_mouse_enter(self, _event=None):
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if self.hidden:
            self.show_from_edge()

    def on_mouse_leave(self, _event=None):
        self.schedule_hide()

    def start_move(self, event):
        if event.widget.winfo_class() in {"Button", "Entry", "Text"}:
            return
        self.dragging = True
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if self.hidden:
            self.show_from_edge()

    def on_move(self, event):
        if not self.dragging:
            return
        x = event.x_root - self.drag_x
        y = event.y_root - self.drag_y
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        height = self.root.winfo_height() or self.root.winfo_reqheight()
        x = max(-width + self.visible_strip, min(x, screen_width - self.visible_strip))
        y = max(10, min(y, screen_height - height - 60))
        self.saved_y = y
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def end_move(self, _event=None):
        if not self.dragging:
            return
        self.dragging = False
        side = "left" if self.root.winfo_pointerx() < self.root.winfo_screenwidth() // 2 else "right"
        self.snap_to_edge(side)

    def save_and_reload(self):
        save_config(self.config_path, self.config)
        self.config = load_config(self.config_path)
        self.interval_ms = max(1000, int(self.config["interval"]) * 1000)
        widget_cfg = self.config.get("widget", {})
        self.show_title = bool(widget_cfg.get("show_title", self.show_title))
        self.anchor_side = widget_cfg.get("dock_side", self.anchor_side)
        self.saved_y = int(widget_cfg.get("y", self.saved_y))
        self.active_tab = widget_cfg.get("active_tab", self.active_tab)
        self.sort_by = widget_cfg.get("sort_by", self.sort_by)
        self.sort_desc = bool(widget_cfg.get("sort_desc", self.sort_desc))
        self.favorite_search_var.set(widget_cfg.get("favorite_search", self.favorite_search_var.get()))
        self.favorite_filter_var.set(FAVORITE_FILTER_KEYS.get(widget_cfg.get("favorite_filter", "all"), "全部"))
        self.build_rows()
        if self.show_title and not self.title_label.winfo_manager():
            self.title_label.pack(side="left", before=self.time_label)
        if not self.show_title and self.title_label.winfo_manager():
            self.title_label.pack_forget()
        if self.hidden and self.visible_stocks():
            self.hide_to_edge()
        else:
            self.snap_to_edge(self.anchor_side, persist=False)

    def show_version_info(self):
        mode = "EXE 安装版" if getattr(__import__("sys"), "frozen", False) else "Python 调试版"
        messagebox.showinfo("当前版本", f"股票盯盘 {APP_VERSION}\n\n运行方式：{mode}\n运行路径：{APP_RUNTIME}\n配置文件：{self.config_path}")

    def open_ai_settings_dialog(self):
        settings = load_ai_settings()
        dialog = tk.Toplevel(self.root)
        dialog.title("AI设置")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()

        provider_var = tk.StringVar(value=settings.get("provider", "bailian"))
        deepseek_enabled = tk.BooleanVar(value=bool(settings["deepseek"].get("enabled", True)))
        bailian_enabled = tk.BooleanVar(value=bool(settings["bailian"].get("enabled", True)))
        fields = {
            "deepseek_base": tk.StringVar(value=settings["deepseek"].get("base_url", "")),
            "deepseek_model": tk.StringVar(value=settings["deepseek"].get("model", "")),
            "deepseek_key": tk.StringVar(value=settings["deepseek"].get("api_key", "")),
            "bailian_base": tk.StringVar(value=settings["bailian"].get("base_url", "")),
            "bailian_model": tk.StringVar(value=settings["bailian"].get("model", "")),
            "bailian_key": tk.StringVar(value=settings["bailian"].get("api_key", "")),
        }

        row = 0
        tk.Label(dialog, text="默认AI来源", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9, "bold")).grid(row=row, column=0, sticky="w", padx=12, pady=(12, 0))
        tk.OptionMenu(dialog, provider_var, "bailian", "deepseek", "auto").grid(row=row, column=1, sticky="ew", padx=12, pady=(12, 0))
        row += 1

        for name, enabled_var, prefix, title in (
            ("deepseek", deepseek_enabled, "deepseek", "DeepSeek"),
            ("bailian", bailian_enabled, "bailian", "百炼"),
        ):
            tk.Checkbutton(dialog, text=f"启用 {title}", variable=enabled_var, bg=PANEL, fg=TEXT, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 0))
            row += 1
            for label, key in (("Base URL", f"{prefix}_base"), ("Model", f"{prefix}_model"), ("API Key", f"{prefix}_key")):
                tk.Label(dialog, text=label, fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=row, column=0, sticky="w", padx=12, pady=(8, 0))
                show = "*" if key.endswith("_key") else ""
                tk.Entry(dialog, textvariable=fields[key], width=42, show=show).grid(row=row, column=1, sticky="ew", padx=12, pady=(8, 0))
                row += 1

        tk.Label(dialog, text="不填 API Key 时，会继续尝试读取你本机已有的本地配置。", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 0))
        row += 1

        def on_save():
            new_settings = {
                "provider": provider_var.get().strip() or "auto",
                "deepseek": {
                    "enabled": bool(deepseek_enabled.get()),
                    "base_url": fields["deepseek_base"].get().strip(),
                    "model": fields["deepseek_model"].get().strip(),
                    "api_key": fields["deepseek_key"].get().strip(),
                },
                "bailian": {
                    "enabled": bool(bailian_enabled.get()),
                    "base_url": fields["bailian_base"].get().strip(),
                    "model": fields["bailian_model"].get().strip(),
                    "api_key": fields["bailian_key"].get().strip(),
                },
            }
            save_ai_settings(new_settings)
            dialog.destroy()
            messagebox.showinfo("AI设置", "AI 配置已保存，新的分析将按最新设置生效。")

        bar = tk.Frame(dialog, bg=PANEL)
        bar.grid(row=row, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        tk.Button(bar, text="取消", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="保存", command=on_save).pack(side="right")
        dialog.grid_columnconfigure(1, weight=1)
        self.center_dialog(dialog)

    def open_ai_analysis_panel(self):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("AI分析", "请先选择一只股票。")
            return
        open_analysis_panel(self.root, stock_item, on_mouse_enter=self.on_mouse_enter, center_dialog=self.center_dialog)

    def open_recommend_filter_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("推荐条件")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()

        min_price_var = tk.StringVar(value=str(self.recommend_filter.get("min_price", "")))
        max_price_var = tk.StringVar(value=str(self.recommend_filter.get("max_price", "")))
        min_score_var = tk.StringVar(value=str(self.recommend_filter.get("min_score", 45)))
        max_risk_var = tk.StringVar(value=str(self.recommend_filter.get("max_quant_risk", "中等")))
        require_levels_var = tk.BooleanVar(value=bool(self.recommend_filter.get("require_levels", True)))
        prefer_positive_var = tk.BooleanVar(value=bool(self.recommend_filter.get("prefer_positive_news", False)))

        tk.Label(dialog, text="AI 推荐筛选条件", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 8))
        fields = (
            ("最低价格", min_price_var),
            ("最高价格", max_price_var),
            ("最低评分", min_score_var),
        )
        for idx, (label, variable) in enumerate(fields, start=1):
            tk.Label(dialog, text=label, fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=idx, column=0, sticky="w", padx=12, pady=(8, 0))
            tk.Entry(dialog, textvariable=variable, width=24).grid(row=idx, column=1, sticky="ew", padx=12, pady=(8, 0))

        tk.Label(dialog, text="最大量化风险", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=4, column=0, sticky="w", padx=12, pady=(8, 0))
        tk.OptionMenu(dialog, max_risk_var, "偏低", "中等", "偏高").grid(row=4, column=1, sticky="ew", padx=12, pady=(8, 0))
        tk.Checkbutton(dialog, text="要求有提醒位", variable=require_levels_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))
        tk.Checkbutton(dialog, text="只优先正向新闻", variable=prefer_positive_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 0))

        def on_save():
            self.recommend_filter = {
                "min_price": min_price_var.get().strip(),
                "max_price": max_price_var.get().strip(),
                "min_score": int(min_score_var.get().strip() or 45),
                "max_quant_risk": max_risk_var.get().strip() or "中等",
                "require_levels": bool(require_levels_var.get()),
                "prefer_positive_news": bool(prefer_positive_var.get()),
            }
            self.save_widget_preferences()
            dialog.destroy()
            messagebox.showinfo("推荐条件", "推荐条件已保存。")

        bar = tk.Frame(dialog, bg=PANEL)
        bar.grid(row=7, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        tk.Button(bar, text="取消", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="保存", command=on_save).pack(side="right")
        dialog.grid_columnconfigure(1, weight=1)
        self.center_dialog(dialog)

    def open_ai_recommend_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("AI推荐")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text="AI 推荐 5 只观察候选", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        status_label = tk.Label(dialog, text="正在结合当前大盘、本地股票池和市场强势候选生成推荐...", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9))
        status_label.pack(anchor="w", padx=12)
        result_box = scrolledtext.ScrolledText(dialog, width=60, height=18, bg=BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        result_box.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        result_box.insert("1.0", "生成中...")
        result_box.configure(state="disabled")

        def apply_result(result):
            picks = result.get("picks", [])
            pick_map = {str(item.get("symbol", "")).strip(): item for item in picks if str(item.get("symbol", "")).strip()}
            updated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stale_temp_symbols = []

            for stock in self.all_stocks():
                if stock["symbol"] in pick_map:
                    picked = pick_map[stock["symbol"]]
                    stock["recommended_pick"] = {
                        "action": picked.get("action", "观察"),
                        "reason": picked.get("reason", ""),
                        "playbook": picked.get("playbook", ""),
                        "risk_note": picked.get("risk_note", ""),
                        "score": picked.get("score", 0),
                        "updated_at": updated_at,
                    }
                else:
                    stock.pop("recommended_pick", None)
                    if stock.get("import_source") == "market-recommend-temp" and stock.get("status") == "recommended":
                        stale_temp_symbols.append(stock["symbol"])

            existing_symbols = {str(stock.get("symbol", "")).strip() for stock in self.all_stocks()}
            for picked in picks:
                symbol = str(picked.get("symbol", "")).strip()
                if not symbol or symbol in existing_symbols:
                    continue
                self.all_stocks().append(
                    {
                        "symbol": symbol,
                        "market": picked.get("market") or infer_market(symbol),
                        "label": picked.get("label") or symbol,
                        "cost_price": None,
                        "lots": 0,
                        "status": "recommended",
                        "trades": [],
                        "levels": [],
                        "manual_mark": {},
                        "ai_mark": {},
                        "recommended_pick": {
                            "action": picked.get("action", "观察"),
                            "reason": picked.get("reason", ""),
                            "playbook": picked.get("playbook", ""),
                            "risk_note": picked.get("risk_note", ""),
                            "score": picked.get("score", 0),
                            "updated_at": updated_at,
                        },
                        "import_source": "market-recommend-temp",
                        "imported_at": updated_at,
                    }
                )
                existing_symbols.add(symbol)

            if stale_temp_symbols:
                stale_temp_set = set(stale_temp_symbols)
                self.config["stocks"] = [
                    stock for stock in self.all_stocks() if str(stock.get("symbol", "")).strip() not in stale_temp_set
                ]

            lines = [f"市场状态：{result.get('market', {}).get('mood', '未知')}", ""]
            for index, picked in enumerate(picks, start=1):
                lines.extend(
                    [
                        f"{index}. {picked.get('label', picked.get('symbol', ''))}（{picked.get('symbol', '')}）",
                        f"推荐动作：{picked.get('action', '观察')}",
                        f"推荐原因：{picked.get('reason', '暂无')}",
                        f"打法：{picked.get('playbook', '暂无')}",
                        f"风险：{picked.get('risk_note', '暂无')}",
                        "",
                    ]
                )
            if result.get("content"):
                lines.extend(["AI总评：", result["content"]])

            result_box.configure(state="normal")
            result_box.delete("1.0", "end")
            result_box.insert("1.0", "\n".join(lines).strip() or "暂无推荐结果。")
            result_box.configure(state="disabled")
            status_label.configure(text=f"已生成 {len(picks)} 只推荐股票。", fg=TEXT if picks else MUTED)
            self.active_tab = "recommended"
            self.save_and_reload()

        def worker():
            try:
                result = generate_recommendations(self.all_stocks(), self.recommend_filter)
            except Exception as exc:
                result = {"market": {"mood": "未知"}, "picks": [], "content": f"生成失败：{exc}"}
            self.root.after(0, lambda: apply_result(result))

        threading.Thread(target=worker, daemon=True).start()

        bar = tk.Frame(dialog, bg=PANEL)
        bar.pack(fill="x", padx=12, pady=12)
        tk.Button(bar, text="关闭", command=dialog.destroy).pack(side="right")
        self.center_dialog(dialog)

    def open_ai_chat_panel(self):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("AI对话", "请先选择一只股票。")
            return
        open_ai_chat_panel(self.root, stock_item, on_mouse_enter=self.on_mouse_enter, center_dialog=self.center_dialog)

    def open_news_panel(self):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("相关新闻", "请先选择一只股票。")
            return
        open_news_panel(self.root, stock_item, on_mouse_enter=self.on_mouse_enter, center_dialog=self.center_dialog)

    def open_image_import_dialog(self):
        open_image_import_dialog(
            self.root,
            self.config,
            on_import_complete=self.save_and_reload,
            center_dialog=self.center_dialog,
            on_mouse_enter=self.on_mouse_enter,
        )

    def open_manual_mark_dialog(self, symbol=None):
        stock_item = self.find_stock(symbol or self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("手写标记", "请先选择一只股票。")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("手写标记")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text=f"{stock_item.get('label', stock_item['symbol'])} / 手写标记", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 8))
        action_options = ("加购", "减仓", "抛出", "持有观察", "等待")
        mark = stock_item.get("manual_mark", {}) if isinstance(stock_item.get("manual_mark"), dict) else {}
        action_var = tk.StringVar(value=str(mark.get("action", "")).strip() or "持有观察")
        reason_var = tk.StringVar(value=str(mark.get("reason", "")).strip())
        tk.Label(dialog, text="操作建议", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", padx=12, pady=(6, 0))
        tk.OptionMenu(dialog, action_var, *action_options).grid(row=1, column=1, sticky="ew", padx=12, pady=(6, 0))
        tk.Label(dialog, text="简短评价", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", padx=12, pady=(8, 0))
        tk.Entry(dialog, textvariable=reason_var, width=36).grid(row=2, column=1, sticky="ew", padx=12, pady=(8, 0))
        tk.Label(dialog, text="详细备注", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, sticky="nw", padx=12, pady=(8, 0))
        note_box = scrolledtext.ScrolledText(dialog, width=40, height=8, bg=BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        note_box.grid(row=3, column=1, sticky="nsew", padx=12, pady=(8, 0))
        note_box.insert("1.0", str(mark.get("comment", "")).strip())

        def on_save():
            stock_item["manual_mark"] = {
                "action": action_var.get().strip(),
                "reason": reason_var.get().strip(),
                "comment": note_box.get("1.0", "end").strip(),
                "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.save_and_reload()
            dialog.destroy()

        bar = tk.Frame(dialog, bg=PANEL)
        bar.grid(row=4, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        tk.Button(bar, text="取消", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="保存", command=on_save).pack(side="right")
        dialog.grid_columnconfigure(1, weight=1)
        dialog.grid_rowconfigure(3, weight=1)
        self.center_dialog(dialog)

    def open_ai_news_mark_dialog(self, symbol=None):
        stock_item = self.find_stock(symbol or self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("AI新闻标记", "请先选择一只股票。")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("AI新闻标记")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text=f"{stock_item.get('label', stock_item['symbol'])} / AI新闻标记", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 8))
        status_label = tk.Label(dialog, text="正在根据相关新闻生成标记...", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 9))
        status_label.pack(anchor="w", padx=12)
        result_box = scrolledtext.ScrolledText(dialog, width=52, height=14, bg=BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        result_box.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        result_box.insert("1.0", "加载中...")
        result_box.configure(state="disabled")

        def apply_result(mark):
            stock_item["ai_mark"] = mark
            self.save_and_reload()
            result_box.configure(state="normal")
            result_box.delete("1.0", "end")
            result_box.insert("1.0", mark.get("summary", ""))
            result_box.configure(state="disabled")
            status_label.configure(text=f"结论：{mark.get('bias', '中性')} · 操作建议：{mark.get('action', '等待')}", fg=self.action_color(mark.get("action")))

        def worker():
            try:
                items = fetch_stock_news(stock_item["symbol"], stock_item.get("market") or infer_market(stock_item["symbol"]))
                bias = analyze_news_bias(items)
                ai_result = analyze_news_with_ai(stock_item, items) if items else {"content": "暂无可分析新闻。", "provider": None, "enabled": False}
                if bias.get("overall") == "偏正向":
                    action = "加购"
                elif bias.get("overall") == "偏负向":
                    action = "抛出"
                else:
                    action = "等待"
                summary_lines = [
                    f"新闻判断：{bias.get('overall', '中性')}",
                    f"建议动作：{action}",
                    "",
                    f"利好：{len(bias.get('positive', []))} 条",
                    f"利空：{len(bias.get('negative', []))} 条",
                    f"中性：{len(bias.get('neutral', []))} 条",
                    "",
                    "AI解读：",
                    ai_result.get("content", "暂无 AI 解读。"),
                ]
                mark = {
                    "bias": bias.get("overall", "中性"),
                    "action": action,
                    "summary": "\n".join(summary_lines),
                    "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            except Exception as exc:
                mark = {
                    "bias": "中性",
                    "action": "等待",
                    "summary": f"生成失败：{exc}",
                    "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            self.root.after(0, lambda: apply_result(mark))

        threading.Thread(target=worker, daemon=True).start()

        bar = tk.Frame(dialog, bg=PANEL)
        bar.pack(fill="x", padx=12, pady=12)
        tk.Button(bar, text="关闭", command=dialog.destroy).pack(side="right")
        self.center_dialog(dialog)

    def open_selected_site(self):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("打开股票", "请先选择一只股票。")
            return
        market = stock_item.get("market") or infer_market(stock_item["symbol"])
        webbrowser.open(f"https://gu.qq.com/{market}{stock_item['symbol']}", new=2)

    def open_donate_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("赞赏作者")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text="如果这个软件对你有帮助，欢迎赞赏支持。", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=16, pady=(16, 12))
        content = tk.Frame(dialog, bg=PANEL)
        content.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.render_donate_card(content, "支付宝", DONATE_ALIPAY)
        self.render_donate_card(content, "微信支付", DONATE_WECHAT)
        footer = tk.Frame(dialog, bg=PANEL)
        footer.pack(fill="x", padx=16, pady=(0, 16))
        tk.Button(footer, text="关闭", command=dialog.destroy).pack(side="right")
        self.center_dialog(dialog)

    def render_donate_card(self, parent, title, image_path):
        card = tk.Frame(parent, bg=BG, padx=12, pady=12, highlightthickness=1, highlightbackground=BORDER)
        card.pack(side="left", padx=(0, 12), fill="both", expand=True)
        tk.Label(card, text=title, fg=TEXT, bg=BG, font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        if image_path.exists() and Image and ImageTk:
            image = Image.open(image_path)
            image.thumbnail((220, 320))
            photo = ImageTk.PhotoImage(image)
            label = tk.Label(card, image=photo, bg=BG)
            label.image = photo
            label.pack(anchor="center")
        else:
            tk.Label(card, text=f"缺少图片：{image_path.name}", fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8)).pack(anchor="w")
    def open_add_dialog(self):
        self.open_stock_dialog()

    def open_edit_dialog(self):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("编辑股票", "请先选择一只股票。")
            return
        self.open_stock_dialog(stock_item)

    def open_stock_dialog(self, current=None):
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑股票" if current else "新增股票")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()
        symbol_var = tk.StringVar(value=current["symbol"] if current else "")
        label_var = tk.StringVar(value=current.get("label", "") if current else "")
        cost_var = tk.StringVar(value=f"{float(current['cost_price']):.3f}" if current and current.get("cost_price") not in (None, "") else "")
        lots_var = tk.StringVar(value=str(current.get("lots", 0)) if current and current.get("lots", 0) else "")
        levels_var = tk.StringVar(value=", ".join(str(level) for level in current.get("levels", [])) if current else "")
        status_value = current.get("status", "holding" if current and current.get("lots", 0) else "favorite") if current else ("holding" if self.active_tab == "holding" else self.active_tab)
        status_text_by_key = {key: text for text, key in STATUS_OPTIONS}
        key_by_status_text = {text: key for text, key in STATUS_OPTIONS}
        status_var = tk.StringVar(value=status_text_by_key.get(status_value, "收藏"))
        fields = (("代码", symbol_var), ("名称", label_var), ("成本价", cost_var), ("持仓手数", lots_var), ("提醒位", levels_var))
        for idx, (label, variable) in enumerate(fields):
            tk.Label(dialog, text=label, fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=idx, column=0, sticky="w", padx=12, pady=(12 if idx == 0 else 8, 0))
            tk.Entry(dialog, textvariable=variable, width=28).grid(row=idx, column=1, sticky="ew", padx=12, pady=(12 if idx == 0 else 8, 0))
        tk.Label(dialog, text="分组", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=5, column=0, sticky="w", padx=12, pady=(8, 0))
        tk.OptionMenu(dialog, status_var, *key_by_status_text.keys()).grid(row=5, column=1, sticky="ew", padx=12, pady=(8, 0))
        tk.Label(dialog, text="提醒位示例：7.6, 7.2；持仓手数按 1 手 = 100 股计算", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))
        def on_save():
            symbol = symbol_var.get().strip()
            label = label_var.get().strip()
            cost_text = cost_var.get().strip()
            lots_text = lots_var.get().strip()
            level_text = levels_var.get().strip()
            if not symbol:
                messagebox.showerror("保存股票", "股票代码不能为空。")
                return
            try:
                normalized = re.sub(r"[，、；;\s]+", ",", level_text)
                levels = [float(part.strip()) for part in normalized.split(",") if part.strip()]
            except ValueError:
                messagebox.showerror("保存股票", "提醒位必须是数字，并使用逗号分隔。")
                return
            if not levels:
                messagebox.showerror("保存股票", "至少需要一个提醒位。")
                return
            try:
                cost_price = float(cost_text) if cost_text else None
            except ValueError:
                messagebox.showerror("保存股票", "成本价格式不正确。")
                return
            try:
                lots = int(lots_text) if lots_text else 0
            except ValueError:
                messagebox.showerror("保存股票", "持仓手数必须是整数。")
                return
            status = key_by_status_text.get(status_var.get(), "favorite")
            if lots > 0 and status != "closed":
                status = "holding"
            if lots <= 0 and status == "holding":
                status = "favorite"
            item = {"symbol": symbol, "market": infer_market(symbol), "label": label or symbol, "cost_price": cost_price, "lots": lots, "levels": sorted(set(levels), reverse=True), "status": status, "trades": current.get("trades", []).copy() if current else []}
            if current:
                for idx, existing in enumerate(self.all_stocks()):
                    if existing["symbol"] == current["symbol"]:
                        self.config["stocks"][idx] = item
                        break
            else:
                if any(existing["symbol"] == symbol for existing in self.all_stocks()):
                    messagebox.showerror("保存股票", "这只股票已经存在。")
                    return
                self.config["stocks"].append(item)
            self.active_tab = status if status in TAB_LABELS else self.active_tab
            self.selected_symbol = symbol
            self.save_and_reload()
            dialog.destroy()
        button_bar = tk.Frame(dialog, bg=PANEL)
        button_bar.grid(row=7, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        tk.Button(button_bar, text="取消", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(button_bar, text="保存", command=on_save).pack(side="right")
        dialog.grid_columnconfigure(1, weight=1)
        self.center_dialog(dialog)

    def open_trade_dialog(self, action):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("持仓操作", "请先选择一只股票。")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("加仓" if action == "add" else "减仓")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()
        price_var = tk.StringVar()
        lots_var = tk.StringVar()
        note_var = tk.StringVar()
        tk.Label(dialog, text=f"{stock_item.get('label', stock_item['symbol'])}（{stock_item['symbol']}）", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 8))
        for idx, (label, variable) in enumerate((("成交价", price_var), ("手数", lots_var), ("备注", note_var)), start=1):
            tk.Label(dialog, text=label, fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=idx, column=0, sticky="w", padx=12, pady=(8, 0))
            tk.Entry(dialog, textvariable=variable, width=28).grid(row=idx, column=1, sticky="ew", padx=12, pady=(8, 0))
        if action == "reduce":
            tk.Label(dialog, text=f"当前持有 {int(stock_item.get('lots', 0) or 0)} 手", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).grid(row=4, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))
        def on_save():
            try:
                price = float(price_var.get().strip())
                lots = int(lots_var.get().strip())
            except ValueError:
                messagebox.showerror("持仓操作", "成交价和手数格式不正确。")
                return
            if lots <= 0:
                messagebox.showerror("持仓操作", "手数必须大于 0。")
                return
            current_lots = int(stock_item.get("lots", 0) or 0)
            current_cost = float(stock_item["cost_price"]) if stock_item.get("cost_price") not in (None, "") else None
            if action == "add":
                new_lots = current_lots + lots
                new_cost = price if current_cost is None or current_lots <= 0 else ((current_cost * current_lots) + (price * lots)) / new_lots
                stock_item["lots"] = new_lots
                stock_item["cost_price"] = round(new_cost, 3)
                stock_item["status"] = "holding"
            else:
                if lots > current_lots:
                    messagebox.showerror("持仓操作", "减仓手数不能大于当前持仓。")
                    return
                new_lots = current_lots - lots
                stock_item["lots"] = new_lots
                stock_item["status"] = "closed" if new_lots == 0 else "holding"
            trades = stock_item.setdefault("trades", [])
            trades.append({"time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": action if current_lots > 0 else "create", "price": round(price, 3), "lots": lots, "note": note_var.get().strip()})
            self.active_tab = "closed" if stock_item["status"] == "closed" else "holding"
            self.selected_symbol = stock_item["symbol"]
            self.save_and_reload()
            dialog.destroy()
        bar = tk.Frame(dialog, bg=PANEL)
        bar.grid(row=5, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        tk.Button(bar, text="取消", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(bar, text="保存", command=on_save).pack(side="right")
        dialog.grid_columnconfigure(1, weight=1)
        self.center_dialog(dialog)

    def center_dialog(self, dialog):
        dialog.update_idletasks()
        root_x, root_y = self.root.winfo_x(), self.root.winfo_y()
        root_w, root_h = self.root.winfo_width(), self.root.winfo_height()
        dialog_w, dialog_h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = root_x + max(0, (root_w - dialog_w) // 2)
        y = root_y + max(0, (root_h - dialog_h) // 2)
        dialog.geometry(f"+{x}+{y}")
    def delete_selected(self):
        stock_item = self.find_stock(self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("删除股票", "请先选择一只股票。")
            return
        if not messagebox.askyesno("删除股票", f"确认删除 {stock_item['symbol']} 吗？"):
            return
        self.config["stocks"] = [item for item in self.all_stocks() if item["symbol"] != stock_item["symbol"]]
        self.selected_symbol = None
        self.save_and_reload()

    def fetch_quotes_async(self):
        snapshot = self.current_quote_targets()
        def worker():
            results = {}
            for item in snapshot:
                symbol = item["symbol"]
                try:
                    quote = fetch_quote(symbol, item["market"])
                    results[symbol] = ("ok", quote)
                except (urllib.error.URLError, ValueError):
                    results[symbol] = ("error", None)
            self.root.after(0, lambda: self.apply_quote_updates(results))
        threading.Thread(target=worker, daemon=True).start()

    def apply_quote_updates(self, results):
        self.fetch_inflight = False
        for symbol, result in results.items():
            if symbol not in self.rows:
                continue
            status, payload = result
            stock_item = self.find_stock(symbol)
            if status == "ok" and payload is not None:
                self.runtime_quotes[symbol] = payload
                color = color_for_change(payload["change"])
                self.append_history(symbol, payload["time"], payload["price"], payload["prev_close"])
                self.runtime_scores[symbol] = self.recommendation_score(stock_item, payload) if stock_item else 0
                configured = stock_item.get("label", symbol) if stock_item else symbol
                title_text = f"{configured} / {payload['name']}" if configured and configured != payload["name"] else (payload["name"] or configured)
                lots = int(stock_item.get("lots", 0) or 0) if stock_item else 0
                cost_price = stock_item.get("cost_price") if stock_item else None
                if cost_price is not None and lots > 0:
                    profit = (payload["price"] - float(cost_price)) * lots * 100
                    profit_text = f"盈亏 {profit:+.2f}"
                    profit_color = color_for_change(profit)
                else:
                    profit_text = "盈亏 --"
                    profit_color = MUTED
                self.rows[symbol]["title"].configure(text=title_text)
                self.rows[symbol]["code"].configure(text=symbol)
                self.rows[symbol]["price"].configure(text=f"{payload['price']:.2f}", fg=color)
                self.rows[symbol]["change"].configure(text=f"{payload['change']:+.2f}\n{payload['change_pct']:+.2f}%", fg=color)
                self.rows[symbol]["position"].configure(text=self.position_text(stock_item), fg=MUTED)
                trade_text = self.recommendation_summary(stock_item) if self.active_tab == "recommended" else self.trade_summary(stock_item)
                self.rows[symbol]["trade"].configure(text=trade_text, fg=MUTED)
                self.render_level_chips(self.rows[symbol]["chips"], stock_item)
                self.render_risk_chips(self.rows[symbol]["risk_chips"], stock_item)
                self.rows[symbol]["plan"].configure(text=self.next_day_summary(stock_item))
                manual_action = (stock_item.get("manual_mark") or {}).get("action")
                ai_action = (stock_item.get("ai_mark") or {}).get("action")
                manual_badge_text, manual_badge_bg, manual_badge_fg = self.action_badge_style(manual_action)
                ai_badge_text, ai_badge_bg, ai_badge_fg = self.action_badge_style(ai_action)
                self.rows[symbol]["manual"].configure(text=f"笔记  {self.manual_mark_summary(stock_item)}", fg=self.action_color(manual_action))
                self.rows[symbol]["ai"].configure(text=f"新闻  {self.ai_mark_summary(stock_item)}", fg=self.action_color(ai_action))
                self.rows[symbol]["manual_badge"].configure(text=manual_badge_text, bg=manual_badge_bg, fg=manual_badge_fg)
                self.rows[symbol]["ai_badge"].configure(text=ai_badge_text, bg=ai_badge_bg, fg=ai_badge_fg)
                self.rows[symbol]["profit"].configure(text=profit_text, fg=profit_color)
            else:
                self.runtime_quotes.pop(symbol, None)
                self.runtime_scores.pop(symbol, None)
                self.rows[symbol]["price"].configure(text="...", fg=MUTED)
                self.rows[symbol]["change"].configure(text="等待数据", fg=MUTED)
                if stock_item:
                    self.rows[symbol]["position"].configure(text=self.position_text(stock_item), fg=MUTED)
                    trade_text = self.recommendation_summary(stock_item) if self.active_tab == "recommended" else self.trade_summary(stock_item)
                    self.rows[symbol]["trade"].configure(text=trade_text, fg=MUTED)
                    self.render_level_chips(self.rows[symbol]["chips"], stock_item)
                    self.render_risk_chips(self.rows[symbol]["risk_chips"], stock_item)
                    self.rows[symbol]["plan"].configure(text=self.next_day_summary(stock_item))
                    manual_action = (stock_item.get("manual_mark") or {}).get("action")
                    ai_action = (stock_item.get("ai_mark") or {}).get("action")
                    manual_badge_text, manual_badge_bg, manual_badge_fg = self.action_badge_style(manual_action)
                    ai_badge_text, ai_badge_bg, ai_badge_fg = self.action_badge_style(ai_action)
                    self.rows[symbol]["manual"].configure(text=f"笔记  {self.manual_mark_summary(stock_item)}", fg=self.action_color(manual_action))
                    self.rows[symbol]["ai"].configure(text=f"新闻  {self.ai_mark_summary(stock_item)}", fg=self.action_color(ai_action))
                    self.rows[symbol]["manual_badge"].configure(text=manual_badge_text, bg=manual_badge_bg, fg=manual_badge_fg)
                    self.rows[symbol]["ai_badge"].configure(text=ai_badge_text, bg=ai_badge_bg, fg=ai_badge_fg)
                self.rows[symbol]["profit"].configure(text="盈亏 --", fg=MUTED)
            if symbol == self.selected_symbol:
                self.update_chart()
        if self.sort_by != "default":
            self.build_rows()

    def refresh(self):
        self.time_label.configure(text=dt.datetime.now().strftime("%H:%M:%S"))
        if not self.fetch_inflight and self.all_stocks():
            self.fetch_inflight = True
            self.fetch_quotes_async()
        elif not self.all_stocks():
            self.fetch_inflight = False
        self.root.after(self.interval_ms, self.refresh)

    def run(self):
        self.root.mainloop()

def parse_args():
    parser = argparse.ArgumentParser(description="显示可拖动吸附的股票盯盘小窗。")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="JSON 配置文件路径")
    return parser.parse_args()

def main():
    args = parse_args()
    widget = StockWidget(pathlib.Path(args.config))
    widget.run()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
