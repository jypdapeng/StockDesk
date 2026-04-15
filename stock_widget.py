import argparse
import datetime as dt
import os
import pathlib
import re
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext
import urllib.error
import webbrowser

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    win32api = None
    win32con = None
    win32gui = None

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

from ai_provider import (
    analyze_news_with_ai,
    explain_runtime_event,
    load_ai_settings,
    provider_choices,
    save_ai_settings,
    test_provider_connection,
)
from ai_chat_panel import open_ai_chat_panel
from analysis_panel import open_analysis_panel
from dashboard_panel import open_dashboard_panel
from image_import_panel import open_image_import_dialog
from market_recommend import generate_recommendations
from market_state import get_market_state
from news_panel import open_news_panel
from recommend_chat_panel import open_recommend_chat_panel
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
WINDOW_TOP_MARGIN = 10
DONATE_ALIPAY = RESOURCE_DIR / "assets" / "donate_alipay.jpg"
DONATE_WECHAT = RESOURCE_DIR / "assets" / "donate_wechat.jpg"
TAB_LABELS = {"recommended": "推荐", "favorite": "收藏", "holding": "持有", "closed": "清仓"}
STATUS_OPTIONS = [("推荐", "recommended"), ("收藏", "favorite"), ("持有", "holding"), ("清仓", "closed")]
FAVORITE_FILTER_LABELS = {"全部": "all", "有代码": "with_code", "无代码": "without_code", "有提醒位": "with_levels", "无提醒位": "without_levels"}
FAVORITE_FILTER_KEYS = {value: key for key, value in FAVORITE_FILTER_LABELS.items()}


class WindowsTrayIcon:
    WM_TRAYICON = 0x0401
    ID_RESTORE = 1001
    ID_EXIT = 1002

    def __init__(self, title, icon_path, on_restore, on_exit):
        self.title = title
        self.icon_path = str(icon_path)
        self.on_restore = on_restore
        self.on_exit = on_exit
        self.thread = None
        self.hwnd = None
        self.class_name = f"StockDeskTray_{os.getpid()}"
        self._running = False

    @property
    def available(self):
        return all(module is not None for module in (win32api, win32con, win32gui))

    def show(self):
        if not self.available or self._running:
            return
        self._running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def hide(self):
        if not self.available:
            self._running = False
            return
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                self._running = False

    def _run(self):
        message_map = {
            win32con.WM_DESTROY: self._on_destroy,
            win32con.WM_COMMAND: self._on_command,
            self.WM_TRAYICON: self._on_tray_notify,
        }
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = self.class_name
        wc.lpfnWndProc = message_map
        try:
            win32gui.RegisterClass(wc)
        except Exception:
            pass

        self.hwnd = win32gui.CreateWindow(
            self.class_name,
            self.class_name,
            0,
            0,
            0,
            win32con.CW_USEDEFAULT,
            win32con.CW_USEDEFAULT,
            0,
            0,
            wc.hInstance,
            None,
        )
        try:
            hicon = win32gui.LoadImage(
                0,
                self.icon_path,
                win32con.IMAGE_ICON,
                0,
                0,
                win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
            )
        except Exception:
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        notify_id = (self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP, self.WM_TRAYICON, hicon, self.title)
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, notify_id)
        win32gui.PumpMessages()

    def _on_tray_notify(self, hwnd, msg, wparam, lparam):
        if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
            self.on_restore()
        elif lparam == win32con.WM_RBUTTONUP:
            self._show_menu()
        return 0

    def _show_menu(self):
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_RESTORE, "恢复窗口")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.ID_EXIT, "退出")
        pos_x, pos_y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos_x, pos_y, 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def _on_command(self, hwnd, msg, wparam, lparam):
        command_id = win32api.LOWORD(wparam)
        if command_id == self.ID_RESTORE:
            self.on_restore()
        elif command_id == self.ID_EXIT:
            self.on_exit()
        return 0

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
        except Exception:
            pass
        self.hwnd = None
        self._running = False
        win32gui.PostQuitMessage(0)
        return 0

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
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.96)
        self.base_tk_scaling = float(self.root.tk.call("tk", "scaling"))
        widget_cfg = self.config.get("widget", {})
        self.always_on_top = bool(widget_cfg.get("always_on_top", False))
        self.root.attributes("-topmost", self.always_on_top)
        self.show_title = bool(widget_cfg.get("show_title", False))
        self.ui_scale = self.normalize_ui_scale(widget_cfg.get("ui_scale", 1.0))
        self.root.tk.call("tk", "scaling", self.base_tk_scaling * self.ui_scale)
        self.intraday_runtime_reminder = bool(widget_cfg.get("intraday_runtime_reminder", True))
        self.intraday_strong_reminder = bool(widget_cfg.get("intraday_strong_reminder", True))
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
                "allow_kcb": False,
                "avoid_limit_up": True,
                "max_chase_pct": 7.5,
            },
        )
        self.dragging = False
        self.resizing = False
        self.resize_edge = None
        self.resize_origin = {}
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
        self.runtime_events = []
        self.runtime_event_hints = {}
        self.event_seen = {}
        self.event_hint_fetching = set()
        self.event_popup_seen = {}
        self.event_popup_symbol_seen = {}
        self.max_live_quotes = 10
        self.last_recommend_result = None
        self.market_state_data = None
        self.market_state_fetching = False
        self.market_state_updated_at = None
        self.hide_job = None
        self.hidden = False
        self.visible_strip = 14
        self.tray_icon = WindowsTrayIcon(
            "股票盯盘",
            RESOURCE_DIR / "assets" / "stock_app.ico",
            on_restore=lambda: self.root.after(0, self.restore_from_tray),
            on_exit=lambda: self.root.after(0, self.on_close_request),
        )
        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.on_move)
        self.root.bind("<ButtonRelease-1>", self.end_move)
        self.root.bind("<Motion>", self.on_pointer_motion, add="+")
        self.root.bind("<Control-MouseWheel>", self.on_ctrl_mousewheel, add="+")
        self.root.bind("<Control-plus>", lambda _e: self.change_ui_scale(0.1), add="+")
        self.root.bind("<Control-equal>", lambda _e: self.change_ui_scale(0.1), add="+")
        self.root.bind("<Control-minus>", lambda _e: self.change_ui_scale(-0.1), add="+")
        self.root.bind("<Control-0>", lambda _e: self.reset_ui_scale(), add="+")
        self.frame = tk.Frame(self.root, bg=PANEL, padx=self.scale_px(12), pady=self.scale_px(10), highlightthickness=1, highlightbackground=BORDER)
        self.frame.pack(fill="both", expand=True)
        self.header = tk.Frame(self.frame, bg=PANEL)
        self.header.pack(fill="x")
        self.title_label = tk.Label(self.header, text="股票盯盘", fg=TEXT, bg=PANEL, font=self.ui_font("Microsoft YaHei UI", 11, "bold"))
        if self.show_title:
            self.title_label.pack(side="left")
        self.time_label = tk.Label(self.header, text="--:--:--", fg=MUTED, bg=PANEL, font=self.ui_font("Consolas", 9))
        self.time_label.pack(side="left", padx=(self.scale_px(8), 0))
        self.make_header_button("退出", self.on_close_request, PANEL, fg=MUTED)
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
            font=self.ui_font("Microsoft YaHei UI", 8, "bold"),
            padx=self.scale_px(8),
            pady=self.scale_px(2),
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
            font=self.ui_font("Microsoft YaHei UI", 8, "bold"),
            padx=self.scale_px(8),
            pady=self.scale_px(2),
        )
        self.tip_label = tk.Label(self.frame, text="可拖动到桌面任意位置，松手后自动吸附左侧或右侧", fg=MUTED, bg=PANEL, font=self.ui_font("Microsoft YaHei UI", 8))
        self.tip_label.pack(anchor="w", pady=(self.scale_px(4), self.scale_px(8)))
        self.tab_bar = tk.Frame(self.frame, bg=PANEL)
        self.tab_bar.pack(fill="x", pady=(0, self.scale_px(8)))
        self.tab_buttons = {}
        for key, text in TAB_LABELS.items():
            button = tk.Button(self.tab_bar, text=text, command=lambda tab=key: self.switch_tab(tab), fg=TEXT, bg=BG, activebackground=BG, activeforeground=TEXT, relief="flat", bd=0, font=self.ui_font("Microsoft YaHei UI", 9, "bold"), padx=self.scale_px(10), pady=self.scale_px(4))
            button.pack(side="left", padx=(0, self.scale_px(6)))
            self.tab_buttons[key] = button
        self.favorite_filter_bar = tk.Frame(self.frame, bg=PANEL)
        tk.Label(self.favorite_filter_bar, text="搜索", fg=MUTED, bg=PANEL, font=self.ui_font("Microsoft YaHei UI", 8)).pack(side="left")
        favorite_search_entry = tk.Entry(self.favorite_filter_bar, textvariable=self.favorite_search_var, width=16)
        favorite_search_entry.pack(side="left", padx=(self.scale_px(6), self.scale_px(8)))
        favorite_search_entry.bind("<KeyRelease>", lambda _event: self.on_favorite_filter_change())
        tk.Label(self.favorite_filter_bar, text="过滤", fg=MUTED, bg=PANEL, font=self.ui_font("Microsoft YaHei UI", 8)).pack(side="left")
        tk.OptionMenu(self.favorite_filter_bar, self.favorite_filter_var, *FAVORITE_FILTER_LABELS.keys(), command=lambda _value: self.on_favorite_filter_change()).pack(side="left", padx=(self.scale_px(6), self.scale_px(8)))
        tk.Button(self.favorite_filter_bar, text="清空", command=self.clear_favorite_filters).pack(side="left")
        self.empty_label = tk.Label(self.frame, text="暂无股票，点击“新增”开始添加", fg=MUTED, bg=PANEL, font=self.ui_font("Microsoft YaHei UI", 9))
        self.list_wrapper = tk.Frame(self.frame, bg=PANEL, height=self.scale_px(5 * 136))
        self.list_wrapper.pack(fill="both", expand=False)
        self.list_wrapper.pack_propagate(False)
        self.list_canvas = tk.Canvas(self.list_wrapper, bg=PANEL, highlightthickness=0, bd=0, height=self.scale_px(5 * 136))
        self.list_scrollbar = tk.Scrollbar(self.list_wrapper, orient="vertical", command=self.on_list_scrollbar)
        self.list_canvas.configure(yscrollcommand=self.list_scrollbar.set)
        self.list_canvas.pack(side="left", fill="both", expand=True)
        self.list_scrollbar.pack(side="right", fill="y")
        self.list_container = tk.Frame(self.list_canvas, bg=PANEL)
        self.list_canvas_window = self.list_canvas.create_window((0, 0), window=self.list_container, anchor="nw")
        self.list_container.bind("<Configure>", lambda _e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.bind("<Configure>", self.on_list_canvas_configure)
        self.list_canvas.bind_all("<MouseWheel>", self.on_list_mousewheel, add="+")
        self.chart_frame = tk.Frame(self.frame, bg=BG, padx=self.scale_px(8), pady=self.scale_px(8), highlightthickness=1, highlightbackground=BORDER)
        self.chart_title = tk.Label(self.chart_frame, text="分时图", fg=TEXT, bg=BG, font=self.ui_font("Microsoft YaHei UI", 9, "bold"))
        self.chart_title.pack(anchor="w")
        self.chart_meta = tk.Label(self.chart_frame, text="启动后实时采样", fg=MUTED, bg=BG, font=self.ui_font("Microsoft YaHei UI", 8))
        self.chart_meta.pack(anchor="w", pady=(self.scale_px(2), self.scale_px(6)))
        self.chart_canvas = tk.Canvas(self.chart_frame, width=self.scale_px(280), height=self.scale_px(88), bg=BG, highlightthickness=0, bd=0)
        self.chart_canvas.pack(fill="x", expand=True)
        self.chart_canvas.bind("<Motion>", self.on_chart_hover, add="+")
        self.chart_canvas.bind("<Leave>", self.on_chart_leave, add="+")
        self.build_rows()
        self.bind_hover_events()
        self.place_initial_position()
        self.tray_icon.show()
        if self.all_stocks() and self.visible_stocks():
            self.hide_to_edge()
        self.refresh()

    def make_header_button(self, text, command, bg, fg=TEXT):
        compact = text in {"关闭", "退出"}
        button = tk.Button(self.header, text=text, command=command, fg=fg, bg=bg, activebackground=bg, activeforeground=TEXT, relief="flat", bd=0, font=self.ui_font("Microsoft YaHei UI", 8, "bold"), padx=self.scale_px(8 if not compact else 4), pady=self.scale_px(2 if not compact else 0))
        button.pack(side="right", padx=(self.scale_px(4), 0))

    def normalize_ui_scale(self, value):
        try:
            scale = float(value)
        except Exception:
            scale = 1.0
        return max(0.8, min(1.8, round(scale, 2)))

    def scale_px(self, value):
        return max(1, int(round(float(value) * self.ui_scale)))

    def ui_font(self, family, size, *styles):
        return (family, max(7, int(round(size * self.ui_scale))), *styles)

    def apply_ui_scale(self):
        self.root.tk.call("tk", "scaling", self.base_tk_scaling * self.ui_scale)
        if hasattr(self, "frame"):
            self.frame.configure(padx=self.scale_px(12), pady=self.scale_px(10))
            self.title_label.configure(font=self.ui_font("Microsoft YaHei UI", 11, "bold"))
            self.time_label.configure(font=self.ui_font("Consolas", 9))
            self.tip_label.configure(font=self.ui_font("Microsoft YaHei UI", 8))
            self.tip_label.pack_configure(pady=(self.scale_px(4), self.scale_px(8)))
            self.tab_bar.pack_configure(pady=(0, self.scale_px(8)))
            for button in self.tab_buttons.values():
                button.configure(font=self.ui_font("Microsoft YaHei UI", 9, "bold"), padx=self.scale_px(10), pady=self.scale_px(4))
                button.pack_configure(padx=(0, self.scale_px(6)))
            self.list_wrapper.configure(height=self.scale_px(5 * 136))
            self.list_canvas.configure(height=self.scale_px(5 * 136))
            self.chart_frame.configure(padx=self.scale_px(8), pady=self.scale_px(8))
            self.chart_title.configure(font=self.ui_font("Microsoft YaHei UI", 9, "bold"))
            self.chart_meta.configure(font=self.ui_font("Microsoft YaHei UI", 8))
            self.chart_meta.pack_configure(pady=(self.scale_px(2), self.scale_px(6)))
            self.chart_canvas.configure(width=self.scale_px(280), height=self.scale_px(88))
            self.build_rows()
            self.refresh_chart()

    def change_ui_scale(self, delta):
        self.ui_scale = self.normalize_ui_scale(self.ui_scale + delta)
        self.apply_ui_scale()
        self.save_widget_preferences()

    def reset_ui_scale(self):
        self.ui_scale = 1.0
        self.apply_ui_scale()
        self.save_widget_preferences()

    def on_ctrl_mousewheel(self, event):
        self.change_ui_scale(0.1 if event.delta > 0 else -0.1)
        return "break"

    def resize_border_size(self):
        return self.scale_px(8)

    def min_window_width(self):
        return self.scale_px(280)

    def min_window_height(self):
        return self.scale_px(280)

    def clamp_y(self, y):
        self.root.update_idletasks()
        height = self.root.winfo_height() or self.root.winfo_reqheight()
        screen_height = self.root.winfo_screenheight()
        return max(WINDOW_TOP_MARGIN, min(int(y), max(WINDOW_TOP_MARGIN, screen_height - height - 60)))

    def current_resize_zone(self, x_root, y_root):
        if self.hidden:
            return None
        left = self.root.winfo_x()
        top = self.root.winfo_y()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        height = self.root.winfo_height() or self.root.winfo_reqheight()
        right = left + width
        bottom = top + height
        border = self.resize_border_size()
        near_left = abs(x_root - left) <= border
        near_right = abs(x_root - right) <= border
        near_top = abs(y_root - top) <= border
        near_bottom = abs(y_root - bottom) <= border
        if near_left and near_top:
            return "top_left"
        if near_right and near_top:
            return "top_right"
        if near_left and near_bottom:
            return "bottom_left"
        if near_right and near_bottom:
            return "bottom_right"
        if near_left:
            return "left"
        if near_right:
            return "right"
        if near_top:
            return "top"
        if near_bottom:
            return "bottom"
        return None

    def cursor_for_resize_zone(self, zone):
        mapping = {
            "left": "sb_h_double_arrow",
            "right": "sb_h_double_arrow",
            "top": "sb_v_double_arrow",
            "bottom": "sb_v_double_arrow",
            "top_left": "size_nw_se",
            "bottom_right": "size_nw_se",
            "top_right": "size_ne_sw",
            "bottom_left": "size_ne_sw",
        }
        return mapping.get(zone, "")

    def on_pointer_motion(self, event=None):
        if self.dragging or self.resizing:
            return
        zone = self.current_resize_zone(self.root.winfo_pointerx(), self.root.winfo_pointery())
        try:
            self.root.configure(cursor=self.cursor_for_resize_zone(zone))
        except Exception:
            pass

    def resize_window(self, event):
        if not self.resizing or not self.resize_edge:
            return
        start = self.resize_origin
        dx = event.x_root - start["pointer_x"]
        dy = event.y_root - start["pointer_y"]
        new_x = start["x"]
        new_y = start["y"]
        new_width = start["width"]
        new_height = start["height"]
        min_width = self.min_window_width()
        min_height = self.min_window_height()
        if "left" in self.resize_edge:
            new_width = max(min_width, start["width"] - dx)
            new_x = start["x"] + (start["width"] - new_width)
        if "right" in self.resize_edge:
            new_width = max(min_width, start["width"] + dx)
        if "top" in self.resize_edge:
            new_height = max(min_height, start["height"] - dy)
            new_y = start["y"] + (start["height"] - new_height)
        if "bottom" in self.resize_edge:
            new_height = max(min_height, start["height"] + dy)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        new_x = max(0, min(int(new_x), max(0, screen_width - int(new_width))))
        new_y = max(WINDOW_TOP_MARGIN, min(int(new_y), max(WINDOW_TOP_MARGIN, screen_height - int(new_height) - 60)))
        self.saved_y = new_y
        self.root.geometry(f"{int(new_width)}x{int(new_height)}+{new_x}+{new_y}")

    def on_close_request(self):
        if not messagebox.askyesno("退出确认", "确认退出股票盯盘和提醒服务吗？"):
            return
        self.tray_icon.hide()
        self.root.destroy()

    def open_actions_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=TEXT, activebackground=BUTTON_BLUE, activeforeground=TEXT)
        menu.add_command(label="指挥台", command=self.open_dashboard_panel)
        menu.add_separator()
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
        menu.add_command(label="买入", command=self.buy_selected_from_favorite)
        menu.add_command(label="加收藏", command=self.add_selected_to_favorite)
        menu.add_command(label="置顶/取消置顶", command=self.toggle_pin_selected)
        menu.add_separator()
        menu.add_command(label="打开网页", command=self.open_selected_site)
        menu.add_command(label="相关新闻", command=self.open_news_panel)
        menu.add_command(label="AI对话", command=self.open_ai_chat_panel)
        menu.add_command(label="推荐对话", command=self.open_recommend_chat_panel)
        menu.add_command(label="AI设置", command=self.open_ai_settings_dialog)
        menu.add_command(label="版本信息", command=self.show_version_info)
        if self.active_tab == "favorite":
            menu.add_separator()
            menu.add_command(label="批量删除当前筛选", command=self.batch_delete_filtered_favorites)
            menu.add_command(label="清空导入结果", command=self.clear_imported_favorites)
        menu.add_separator()
        zoom_menu = tk.Menu(menu, tearoff=0, bg=PANEL, fg=TEXT, activebackground=BUTTON_BLUE, activeforeground=TEXT)
        zoom_menu.add_command(label="放大界面", command=lambda: self.change_ui_scale(0.1))
        zoom_menu.add_command(label="缩小界面", command=lambda: self.change_ui_scale(-0.1))
        zoom_menu.add_command(label="恢复 100%", command=self.reset_ui_scale)
        menu.add_cascade(label=f"界面缩放 {int(self.ui_scale * 100)}%", menu=zoom_menu)
        menu.add_command(label="显示/隐藏标题", command=self.toggle_title_visibility)
        menu.add_command(
            label="关闭盘中提醒" if self.intraday_runtime_reminder else "开启盘中提醒",
            command=self.toggle_intraday_runtime_reminder,
        )
        menu.add_command(
            label="关闭盘中强提醒" if self.intraday_strong_reminder else "开启盘中强提醒",
            command=self.toggle_intraday_strong_reminder,
        )
        menu.add_command(
            label="关闭窗口置顶" if self.always_on_top else "开启窗口置顶",
            command=self.toggle_always_on_top,
        )
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
            widget.bind("<Motion>", self.on_pointer_motion, add="+")

    def toggle_title_visibility(self):
        self.show_title = not self.show_title
        if self.show_title:
            self.title_label.pack(side="left", before=self.time_label)
        else:
            self.title_label.pack_forget()
        self.save_widget_preferences()

    def toggle_always_on_top(self):
        self.always_on_top = not self.always_on_top
        self.root.attributes("-topmost", self.always_on_top)
        self.save_widget_preferences()

    def toggle_intraday_strong_reminder(self):
        self.intraday_strong_reminder = not self.intraday_strong_reminder
        self.save_widget_preferences()
        self.build_rows()

    def toggle_intraday_runtime_reminder(self):
        self.intraday_runtime_reminder = not self.intraday_runtime_reminder
        if not self.intraday_runtime_reminder:
            self.runtime_events = []
            self.runtime_event_hints = {}
            self.event_popup_seen = {}
            self.event_popup_symbol_seen = {}
        self.save_widget_preferences()
        self.build_rows()

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
        visible = sorted(visible, key=lambda item: (0 if item.get("pinned") else 1, str(item.get("label", item.get("symbol", "")))))
        if self.sort_by != "default":
            visible = sorted(visible, key=lambda item: (0 if item.get("pinned") else 1, -self._item_sort_value(item) if self.sort_desc else self._item_sort_value(item)))
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
        widget_cfg["always_on_top"] = self.always_on_top
        widget_cfg["ui_scale"] = self.ui_scale
        widget_cfg["intraday_runtime_reminder"] = self.intraday_runtime_reminder
        widget_cfg["intraday_strong_reminder"] = self.intraday_strong_reminder
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
            row = tk.Frame(self.list_container, bg=BG, padx=self.scale_px(8), pady=self.scale_px(6), highlightthickness=2, highlightbackground=BORDER, highlightcolor=ACCENT)
            row.pack(fill="x", pady=self.scale_px(4))
            header_left = tk.Frame(row, bg=BG)
            header_left.grid(row=0, column=0, sticky="w")
            title = tk.Label(header_left, text=item.get("label", symbol), fg=TEXT, bg=BG, font=self.ui_font("Microsoft YaHei UI", 10, "bold"))
            title.pack(side="left")
            if item.get("pinned"):
                tk.Label(header_left, text="置顶", fg="#fef3c7", bg="#92400e", font=self.ui_font("Microsoft YaHei UI", 7, "bold"), padx=self.scale_px(6), pady=self.scale_px(1)).pack(side="left", padx=(self.scale_px(6), 0))
            manual_btn = tk.Button(header_left, text="✎", command=lambda s=symbol: self.open_manual_mark_dialog(s), fg=TEXT, bg=BORDER, activebackground=BUTTON_BLUE, activeforeground=TEXT, relief="flat", bd=0, padx=self.scale_px(4), pady=0, font=self.ui_font("Microsoft YaHei UI", 8, "bold"), cursor="hand2")
            manual_btn.pack(side="left", padx=(self.scale_px(6), self.scale_px(4)))
            ai_btn = tk.Button(header_left, text="!", command=lambda s=symbol: self.open_ai_news_mark_dialog(s), fg=TEXT, bg=BUTTON_RED, activebackground=BUTTON_RED, activeforeground=TEXT, relief="flat", bd=0, padx=self.scale_px(6), pady=0, font=self.ui_font("Microsoft YaHei UI", 8, "bold"), cursor="hand2")
            ai_btn.pack(side="left")
            action_bar = tk.Frame(row, bg=BG)
            action_bar.grid(row=1, column=0, sticky="w", pady=(self.scale_px(3), 0))
            chat_btn = tk.Button(action_bar, text="AI", command=lambda s=symbol: self.open_ai_chat_panel(s), fg=TEXT, bg=BUTTON_PURPLE, activebackground=BUTTON_PURPLE, activeforeground=TEXT, relief="flat", bd=0, padx=self.scale_px(6), pady=0, font=self.ui_font("Microsoft YaHei UI", 7, "bold"), cursor="hand2")
            chat_btn.pack(side="left")
            pin_btn = tk.Button(action_bar, text="置顶" if not item.get("pinned") else "取消", command=lambda s=symbol: self.toggle_pin_selected(s), fg=TEXT, bg="#92400e", activebackground="#92400e", activeforeground=TEXT, relief="flat", bd=0, padx=self.scale_px(6), pady=0, font=self.ui_font("Microsoft YaHei UI", 7, "bold"), cursor="hand2")
            pin_btn.pack(side="left", padx=(self.scale_px(6), 0))
            if self.active_tab == "recommended":
                fav_btn = tk.Button(action_bar, text="收藏", command=lambda s=symbol: self.add_selected_to_favorite(s), fg=TEXT, bg="#065f46", activebackground="#065f46", activeforeground=TEXT, relief="flat", bd=0, padx=self.scale_px(6), pady=0, font=self.ui_font("Microsoft YaHei UI", 7, "bold"), cursor="hand2")
                fav_btn.pack(side="left", padx=(self.scale_px(6), 0))
            elif self.active_tab == "favorite":
                buy_btn = tk.Button(action_bar, text="买入", command=lambda s=symbol: self.buy_selected_from_favorite(s), fg=TEXT, bg="#1d4ed8", activebackground="#1d4ed8", activeforeground=TEXT, relief="flat", bd=0, padx=self.scale_px(6), pady=0, font=self.ui_font("Microsoft YaHei UI", 7, "bold"), cursor="hand2")
                buy_btn.pack(side="left", padx=(self.scale_px(6), 0))
            code = tk.Label(row, text=symbol, fg=MUTED, bg=BG, font=self.ui_font("Consolas", 9))
            code.grid(row=2, column=0, sticky="w", pady=(self.scale_px(2), 0))
            right_panel = tk.Frame(row, bg=BG)
            right_panel.grid(row=0, column=1, rowspan=5, sticky="ne", padx=(self.scale_px(20), 0))
            price_change_box = tk.Frame(right_panel, bg=BG)
            price_change_box.pack(anchor="e")
            price = tk.Label(price_change_box, text="...", fg=TEXT, bg=BG, font=self.ui_font("Consolas", 18, "bold"))
            price.pack(side="left", anchor="n")
            change = tk.Label(price_change_box, text="加载中", fg=MUTED, bg=BG, font=self.ui_font("Consolas", 10))
            change.pack(side="left", anchor="n", padx=(self.scale_px(10), 0))
            badge_box = tk.Frame(right_panel, bg=BG)
            badge_box.pack(anchor="e", pady=(self.scale_px(6), 0))
            levels = ", ".join(f"{level:.2f}" for level in item.get("levels", [])) or "-"
            level_label = tk.Label(row, text=f"提醒位 {levels}", fg=MUTED, bg=BG, font=self.ui_font("Microsoft YaHei UI", 8), wraplength=self.scale_px(240), justify="left", anchor="w")
            level_label.grid(row=3, column=0, sticky="ew", pady=(self.scale_px(4), 0))
            position_label = tk.Label(row, text=self.position_text(item), fg=MUTED, bg=BG, font=self.ui_font("Microsoft YaHei UI", 8), wraplength=self.scale_px(240), justify="left", anchor="w")
            position_label.grid(row=4, column=0, sticky="ew", pady=(self.scale_px(2), 0))
            trade_text = self.recommendation_summary(item) if self.active_tab == "recommended" else self.trade_summary(item)
            trade_label = tk.Label(row, text=trade_text, fg=MUTED, bg=BG, font=self.ui_font("Microsoft YaHei UI", 8), wraplength=self.scale_px(240), justify="left", anchor="w")
            trade_label.grid(row=5, column=0, sticky="ew", pady=(self.scale_px(2), 0))
            manual_mark = item.get("manual_mark", {}) if isinstance(item.get("manual_mark"), dict) else {}
            ai_mark = item.get("ai_mark", {}) if isinstance(item.get("ai_mark"), dict) else {}
            manual_badge_text, manual_badge_bg, manual_badge_fg = self.action_badge_style(manual_mark.get("action"))
            ai_badge_text, ai_badge_bg, ai_badge_fg = self.action_badge_style(ai_mark.get("action"))
            manual_badge = tk.Label(badge_box, text=manual_badge_text, fg=manual_badge_fg, bg=manual_badge_bg, font=self.ui_font("Microsoft YaHei UI", 8, "bold"), padx=self.scale_px(8), pady=self.scale_px(2))
            manual_badge.pack(anchor="e", pady=(0, self.scale_px(4)))
            ai_badge = tk.Label(badge_box, text=ai_badge_text, fg=ai_badge_fg, bg=ai_badge_bg, font=self.ui_font("Microsoft YaHei UI", 8, "bold"), padx=self.scale_px(8), pady=self.scale_px(2))
            ai_badge.pack(anchor="e")
            profit_label = tk.Label(right_panel, text="盈亏 --", fg=MUTED, bg=BG, font=self.ui_font("Consolas", 9, "bold"))
            profit_label.pack(anchor="e", pady=(self.scale_px(10), 0))
            chip_bar = tk.Frame(row, bg=BG)
            chip_bar.grid(row=6, column=0, columnspan=2, sticky="w", pady=(self.scale_px(6), 0))
            self.render_level_chips(chip_bar, item)
            risk_bar = tk.Frame(row, bg=BG)
            risk_bar.grid(row=7, column=0, columnspan=2, sticky="w", pady=(self.scale_px(4), 0))
            self.render_risk_chips(risk_bar, item)
            event_tag = tk.Label(
                row,
                text=self.runtime_event_summary(item),
                fg="#fde68a",
                bg="#3f3112",
                font=self.ui_font("Microsoft YaHei UI", 8, "bold"),
                padx=self.scale_px(8),
                pady=self.scale_px(4),
                anchor="w",
                justify="left",
                wraplength=self.scale_px(320),
            )
            event_tag.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(self.scale_px(4), 0))
            plan_tag = tk.Label(
                row,
                text=self.next_day_summary(item),
                fg="#93c5fd",
                bg="#0f2747",
                font=self.ui_font("Microsoft YaHei UI", 8, "bold"),
                padx=self.scale_px(8),
                pady=self.scale_px(4),
                anchor="w",
                justify="left",
                wraplength=self.scale_px(320),
            )
            plan_tag.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(self.scale_px(4), 0))
            sell_tag = tk.Label(
                row,
                text=self.sell_plan_summary(item),
                fg="#fcd34d",
                bg="#3f2a13",
                font=self.ui_font("Microsoft YaHei UI", 8, "bold"),
                padx=self.scale_px(8),
                pady=self.scale_px(4),
                anchor="w",
                justify="left",
                wraplength=self.scale_px(320),
            )
            sell_tag.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(self.scale_px(4), 0))
            manual_tag = tk.Label(row, text=f"笔记  {self.manual_mark_summary(item)}", fg=self.action_color(manual_mark.get("action")), bg="#172554", font=self.ui_font("Microsoft YaHei UI", 8, "bold"), padx=self.scale_px(8), pady=self.scale_px(4), anchor="w", justify="left", wraplength=self.scale_px(320))
            manual_tag.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(self.scale_px(4), 0))
            ai_tag = tk.Label(row, text=f"新闻  {self.ai_mark_summary(item)}", fg=self.action_color(ai_mark.get("action")), bg="#3f1d2e", font=self.ui_font("Microsoft YaHei UI", 8, "bold"), padx=self.scale_px(8), pady=self.scale_px(4), anchor="w", justify="left", wraplength=self.scale_px(320))
            ai_tag.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(self.scale_px(4), 0))
            row.grid_columnconfigure(0, weight=1)
            widgets = [row, header_left, title, action_bar, code, right_panel, price_change_box, price, change, level_label, position_label, trade_label, badge_box, manual_badge, ai_badge, chip_bar, risk_bar, event_tag, plan_tag, sell_tag, manual_tag, ai_tag, profit_label]
            for widget in widgets:
                widget.bind("<Button-1>", lambda event, s=symbol: self.select_symbol(s), add="+")
            self.rows[symbol] = {"frame": row, "title": title, "code": code, "price": price, "change": change, "position": position_label, "trade": trade_label, "chips": chip_bar, "risk_chips": risk_bar, "event": event_tag, "plan": plan_tag, "sell": sell_tag, "manual": manual_tag, "ai": ai_tag, "manual_badge": manual_badge, "ai_badge": ai_badge, "profit": profit_label, "widgets": widgets}
        available = {item["symbol"] for item in visible}
        if self.selected_symbol not in available:
            self.selected_symbol = visible[0]["symbol"]
        self.select_symbol(self.selected_symbol)
        self.list_canvas.yview_moveto(0)
        self.chart_frame.pack(fill="x", pady=(self.scale_px(8), 0))
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

    def build_dashboard(self):
        wrapper = tk.Frame(self.list_container, bg=PANEL)
        wrapper.pack(fill="both", expand=True)

        state = self.market_state_data
        if state is None:
            state = {
                "mood": "等待刷新",
                "tactic": "正在获取市场状态",
                "risk_bias": "--",
                "score": 0,
                "summary": "正在拉取指数、样本涨跌分布和市场情绪，请稍候。",
                "indices": [],
                "breadth": {"up": 0, "down": 0, "flat": 0, "sample_size": 0},
            }
            if not self.market_state_fetching:
                self.fetch_market_state_async()

        self._dashboard_card(
            wrapper,
            "今日市场状态",
            [
                f"情绪：{state.get('mood', '未知')}",
                f"策略：{state.get('tactic', '等待确认')}",
                f"风险：{state.get('risk_bias', '中等')}",
                f"评分：{state.get('score', 0)}/100",
                state.get("summary", ""),
            ],
            accent=BUTTON_PURPLE,
        )

        breadth = state.get("breadth", {})
        index_lines = [
            f"{item.get('label', item.get('symbol', ''))}  {item.get('price', '--')}  {item.get('change_pct', 0):+.2f}%"
            for item in state.get("indices", [])
        ]
        index_lines.append(
            f"样本上涨 {breadth.get('up', 0)}  下跌 {breadth.get('down', 0)}  平盘 {breadth.get('flat', 0)}"
        )
        self._dashboard_card(wrapper, "指数与样本分布", index_lines, accent="#1d4ed8")
        self._dashboard_card(wrapper, "账户概览", self.dashboard_holding_summary(), accent="#065f46")
        self._dashboard_card(wrapper, "今日重点盯盘", self.dashboard_focus_candidates(), accent="#92400e")

    def _dashboard_card(self, parent, title, lines, accent):
        card = tk.Frame(parent, bg=BG, padx=10, pady=10, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=4)
        head = tk.Frame(card, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=title, fg=TEXT, bg=BG, font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Frame(head, bg=accent, width=10, height=10).pack(side="right")
        for index, line in enumerate(lines):
            tk.Label(
                card,
                text=line,
                fg=MUTED if index == len(lines) - 1 and len(lines) > 1 else TEXT,
                bg=BG,
                font=("Microsoft YaHei UI", 8 if index == len(lines) - 1 and len(lines) > 1 else 9),
                justify="left",
                anchor="w",
                wraplength=300,
            ).pack(fill="x", anchor="w", pady=(6 if index == 0 else 2, 0))

    def dashboard_holding_summary(self):
        holdings = [item for item in self.all_stocks() if item.get("status") == "holding"]
        if not holdings:
            return ["当前没有持仓。", "建议：先看市场状态和候选池，再决定是否出手。"]
        total_cost = 0.0
        total_market = 0.0
        watched = 0
        largest_symbol = None
        largest_value = 0.0
        for item in holdings:
            lots = int(item.get("lots", 0) or 0)
            cost = float(item.get("cost_price") or 0)
            quote = self.runtime_quotes.get(item["symbol"], {})
            price = float(quote.get("price") or 0)
            if lots > 0:
                total_cost += cost * lots * 100
                if price > 0:
                    market_value = price * lots * 100
                    total_market += market_value
                    watched += 1
                    if market_value > largest_value:
                        largest_value = market_value
                        largest_symbol = item.get("label", item["symbol"])
        profit = total_market - total_cost if total_market else 0.0
        concentration = (largest_value / total_market) if total_market and largest_value else 0.0
        return [
            f"持仓数量：{len(holdings)} 只",
            f"已刷新行情：{watched} 只",
            f"持仓成本：{total_cost:,.2f}",
            f"最新市值：{total_market:,.2f}" if total_market else "最新市值：等待行情刷新",
            f"浮动盈亏：{profit:+,.2f}" if total_market else "浮动盈亏：等待行情刷新",
            f"持仓数量阈值：{'偏高' if len(holdings) > 5 else '正常'}",
            f"集中度阈值：{'偏高' if concentration >= 0.35 else '正常'}",
            f"最大单票：{largest_symbol}  占比 {concentration * 100:.1f}%" if largest_symbol else "最大单票：等待行情刷新",
        ]

    def dashboard_focus_candidates(self):
        candidates = []
        for item in self.all_stocks():
            if item.get("status") not in {"holding", "recommended", "favorite"}:
                continue
            score = self.runtime_scores.get(item["symbol"], 0)
            quote = self.runtime_quotes.get(item["symbol"], {})
            change_pct = float(quote.get("change_pct", 0) or 0)
            candidates.append((score, change_pct, item))
        candidates.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        top = candidates[:5]
        if not top:
            return ["等待行情刷新后生成重点盯盘名单。"]
        return [
            f"{item.get('label', item['symbol'])}  评分 {score}  涨跌 {change_pct:+.2f}%  预案：{self.next_day_summary(item).replace('次日预案  ', '')}"
            for score, change_pct, item in top
        ]

    def dashboard_risk_summary(self):
        holdings = [item for item in self.all_stocks() if item.get("status") == "holding"]
        if not holdings:
            return ["当前没有持仓，先看市场状态和重点候选。"]
        lines = []
        state = self.market_state_data or {}
        mood = state.get("mood", "未知")
        if mood in {"偏弱", "震荡偏弱"}:
            lines.append(f"市场当前 {mood}，短线成功率会打折，优先控制仓位和节奏。")
        elif mood == "偏强":
            lines.append("市场整体偏强，但尾盘一致性过高时仍要防止回落。")
        else:
            lines.append("市场仍偏震荡，重点看关键位确认，不在模糊区间乱追。")

        risky = []
        underwater = 0
        total = 0
        total_cost = 0.0
        total_market = 0.0
        for item in holdings:
            quote = self.runtime_quotes.get(item["symbol"], {})
            change_pct = float(quote.get("change_pct", 0) or 0)
            lots = int(item.get("lots", 0) or 0)
            cost = float(item.get("cost_price") or 0)
            price = float(quote.get("price") or 0)
            if lots > 0 and cost > 0 and price > 0:
                total += 1
                total_cost += cost * lots * 100
                total_market += price * lots * 100
                if price < cost:
                    underwater += 1
            if change_pct <= -3:
                risky.append(f"{item.get('label', item['symbol'])} 跌幅较大，先防守。")
            elif change_pct >= 4:
                risky.append(f"{item.get('label', item['symbol'])} 涨幅偏高，注意冲高回落。")
        if total:
            underwater_ratio = underwater / total
            pnl_ratio = (total_market - total_cost) / total_cost if total_cost else 0
            if underwater_ratio >= 0.6:
                lines.append(f"账户风险：{underwater}/{total} 持仓处于浮亏，优先降低主观激进度。")
            if pnl_ratio <= -0.03:
                lines.append(f"账户风险：整体浮亏 {pnl_ratio * 100:.2f}% ，先做减压和防守。")
            elif pnl_ratio >= 0.03:
                lines.append(f"账户状态：整体浮盈 {pnl_ratio * 100:.2f}% ，别在强势里追高放大回撤。")
        if len(holdings) > 5:
            lines.append("账户风险：持仓数量偏多，容易分散注意力，建议聚焦核心标的。")
        largest_holding = None
        largest_ratio = 0.0
        if total_market > 0:
            for item in holdings:
                quote = self.runtime_quotes.get(item["symbol"], {})
                lots = int(item.get("lots", 0) or 0)
                price = float(quote.get("price") or 0)
                market_value = price * lots * 100 if lots > 0 and price > 0 else 0
                ratio = market_value / total_market if total_market else 0.0
                if ratio > largest_ratio:
                    largest_ratio = ratio
                    largest_holding = item.get("label", item["symbol"])
        if largest_holding and largest_ratio >= 0.35:
            lines.append(f"账户风险：{largest_holding} 占仓 {largest_ratio * 100:.1f}% ，集中度偏高。")
        lines.extend(risky[:4])
        recent_events = [item for item in self.runtime_events[:3]]
        if recent_events:
            lines.append("")
            lines.append("最近盘中事件：")
            lines.extend(f"- {item['text']}" for item in recent_events)

        if not risky:
            lines.append("当前持仓没有明显极端波动，重点盯承接和关键位。")
        lines.append("纪律提醒：先计划高开、平开、低开的处理，再决定是否隔夜。")
        return lines

    def dashboard_action_plan(self):
        state = self.market_state_data or {}
        mood = state.get("mood", "未知")
        tactic = state.get("tactic", "等待确认")
        execution_focus = state.get("execution_focus", "")
        focus = self.dashboard_focus_candidates()
        lines = [f"今天的市场节奏：{mood}，更适合 {tactic}。"]
        if execution_focus:
            lines.append(f"执行重点：{execution_focus}")
        if mood in {"偏弱", "震荡偏弱"}:
            lines.append("行动建议 1：少做追涨，优先看防守位和承接，不要把弱反弹当反转。")
            lines.append("行动建议 2：如果已有浮亏持仓，先减压，再考虑新开仓。")
        elif mood == "偏强":
            lines.append("行动建议 1：可以顺主线跟随，但尾盘一致性过高时不要接最后一棒。")
            lines.append("行动建议 2：优先挑尾盘不弱、次日更容易有承接的标的。")
        else:
            lines.append("行动建议 1：现在更适合做确认，不适合在模糊区间频繁试错。")
            lines.append("行动建议 2：只有关键位、量能和尾盘强弱同时对上，再考虑出手。")
        if focus:
            lines.append("")
            lines.append("当前最值得先看的 3 只：")
            lines.extend(f"- {line}" for line in focus[:3])
        return lines

    def dashboard_should_do(self):
        state = self.market_state_data or {}
        mood = state.get("mood", "未知")
        items = []
        urgent_events = [event for event in self.runtime_events if event.get("priority", 2) <= 0]
        escalated_events = [event for event in urgent_events if event.get("escalate")]
        if mood == "偏强":
            items.extend(
                [
                    "顺主线，优先看尾盘不弱且次日更容易有承接的标的",
                    "先看关键位是否站稳，再考虑小仓跟随",
                ]
            )
        elif mood in {"偏弱", "震荡偏弱"}:
            items.extend(
                [
                    "优先处理持仓风险，先减压再考虑新开仓",
                    "只看防守位和承接，不把弱反弹当反转",
                ]
            )
        else:
            items.extend(
                [
                    "只做确认，不在模糊区间频繁试错",
                    "优先看有承接的主线，不做情绪后排",
                ]
            )
        if escalated_events:
            items.insert(0, f"先处理 {len(escalated_events)} 条强提醒，再考虑新机会。")
        elif urgent_events:
            items.insert(0, f"先处理 {len(urgent_events)} 条立即事项，再看新的推荐和机会。")
        elif self.runtime_events:
            items.append("先看盘中触发事件，再决定是否继续出手。")
        focus = state.get("execution_focus", "")
        if focus:
            items.append(focus)
        return items[:4]

    def dashboard_should_avoid(self):
        state = self.market_state_data or {}
        mood = state.get("mood", "未知")
        items = ["没有计划的隔夜单", "冲高回落后的情绪追单"]
        urgent_events = [event for event in self.runtime_events if event.get("priority", 2) <= 0]
        escalated_events = [event for event in urgent_events if event.get("escalate")]
        if mood in {"偏弱", "震荡偏弱"}:
            items.extend(["弱市追涨", "浮亏状态下继续摊平"])
        else:
            items.extend(["尾盘一致性过高时接最后一棒", "只凭单一消息或单一信号冲动下单"])
        if escalated_events:
            items.insert(0, "强提醒未处理前，不新增主观仓位。")
        elif urgent_events:
            items.insert(0, "立即事项未处理前，不新增主观仓位。")
        chase_risk = state.get("chase_risk", "")
        if chase_risk:
            items.append(chase_risk)
        return items[:4]

    def dashboard_todo_list(self):
        todo = []
        for event in self.runtime_events[:5]:
            hint = self.runtime_event_hints.get(event.get("fingerprint", ""), "")
            action = event.get("action", "")
            prefix = "【强提醒】" if event.get("escalate") else ""
            if hint:
                text = f"[持仓事件] {prefix}{event.get('text', '')}｜{hint}"
            else:
                text = f"[持仓事件] {prefix}{event.get('text', '')}"
            if action:
                text = f"{text}｜处理：{action}"
            todo.append((event.get("priority", 0), text))
        holdings = [item for item in self.all_stocks() if item.get("status") == "holding"]
        recommendations = [item for item in self.all_stocks() if item.get("status") == "recommended"]

        for item in holdings[:]:
            quote = self.runtime_quotes.get(item.get("symbol", ""), {})
            if not quote:
                continue
            action_text = self.sell_plan_summary(item).replace("操作计划  ", "")
            next_text = self.next_day_summary(item).replace("次日预案  ", "")
            hold_priority = 2
            if "减半" in action_text or "失守" in action_text:
                hold_priority = 0
            elif "卖" in action_text or "锁盈" in action_text:
                hold_priority = 1
            todo.append(
                (
                    hold_priority,
                    f"[持仓计划] {item.get('label', item.get('symbol', ''))}：{action_text}；{next_text}",
                )
            )

        for item in recommendations[:]:
            quote = self.runtime_quotes.get(item.get("symbol", ""), {})
            score = self.runtime_scores.get(item.get("symbol", ""), 0)
            change_pct = float(quote.get("change_pct", 0) or 0)
            if score < 45:
                continue
            todo.append(
                (
                    2,
                    f"[推荐观察] {item.get('label', item.get('symbol', ''))}：观察为主，评分 {score}，涨跌 {change_pct:+.2f}%，{self.next_day_summary(item).replace('次日预案  ', '')}",
                )
            )

        if not todo:
            return ["暂无待执行动作，先观察市场与关键位。"]

        todo.sort(key=lambda entry: entry[0])
        groups = {0: [], 1: [], 2: []}
        for priority, text in todo[:10]:
            groups[priority if priority in groups else 2].append(text)
        lines = []
        labels = {0: "立即处理", 1: "继续关注", 2: "观察队列"}
        for priority in (0, 1, 2):
            if not groups[priority]:
                continue
            lines.append(f"{labels[priority]}（{len(groups[priority])}）：")
            for index, text in enumerate(groups[priority], start=1):
                lines.append(f"{index}. {text}")
            lines.append("")
        return lines

    def record_runtime_event(self, symbol, key, text, priority=0):
        if not self.intraday_runtime_reminder:
            return
        fingerprint = f"{symbol}:{key}"
        now = dt.datetime.now()
        last_seen = self.event_seen.get(fingerprint)
        if last_seen and (now - last_seen).total_seconds() < 300:
            return
        self.event_seen[fingerprint] = now
        action = self.runtime_event_action_text(text, priority)
        escalate = self.should_escalate_runtime_event(text, priority) if self.intraday_strong_reminder else False
        interrupt_reason = self.runtime_event_interrupt_reason(text, priority, escalate)
        self.runtime_events.insert(
            0,
            {
                "time": now.strftime("%H:%M:%S"),
                "symbol": symbol,
                "priority": priority,
                "fingerprint": fingerprint,
                "text": text,
                "action": action,
                "escalate": escalate,
                "interrupt_reason": interrupt_reason,
            },
        )
        self.runtime_events = self.runtime_events[:20]
        self.fetch_runtime_event_hint_async(symbol, fingerprint, text)
        self.maybe_popup_runtime_event(symbol, fingerprint, text, priority, escalate)

    def runtime_event_priority_text(self, priority):
        if priority <= 0:
            return "立即处理"
        if priority == 1:
            return "继续关注"
        return "观察跟踪"

    def runtime_event_action_text(self, text, priority):
        lowered = str(text or "")
        if "跌幅扩大" in lowered:
            return "先看防守计划，必要时先减半。"
        if "涨幅扩大" in lowered:
            return "先看是否按计划锁盈，别让浮盈回吐。"
        if "触发防守位" in lowered or "失守防守位" in lowered:
            return "先按防守减仓计划处理，别再硬扛。"
        if "触发止盈位" in lowered or "锁盈位" in lowered:
            return "先锁一部分利润，再看冲高能否延续。"
        if "触发跟踪位" in lowered or "跌回跟踪位" in lowered:
            return "先看跟踪止盈位是否失守，必要时兑现。"
        if "接近关键位" in lowered or "贴近关键位" in lowered:
            return "先看承接和分时重心，不急着补仓。"
        if "涨幅来到" in lowered or "冲高" in lowered:
            return "优先锁定部分利润，防冲高回落。"
        if priority <= 0:
            return "先处理这条，再看新的机会。"
        if priority == 1:
            return "继续跟踪，不急着立刻动作。"
        return "先放观察队列里。"

    def should_escalate_runtime_event(self, text, priority):
        lowered = str(text or "")
        if "跌幅扩大到" in lowered:
            return True
        if "涨幅扩大到" in lowered:
            return True
        return False

    def runtime_event_interrupt_reason(self, text, priority, escalate):
        lowered = str(text or "")
        if "跌幅扩大到" in lowered:
            return "跌幅已经进入高风险区，优先保住主动权。"
        if "涨幅扩大到" in lowered:
            return "涨幅已经明显放大，先确认是否按计划锁盈。"
        if escalate:
            return "这条事件已经满足打断条件，应该先处理。"
        if priority <= 0:
            return "优先级很高，但还需要结合分时承接确认动作。"
        return "先放入队列持续跟踪，不用立刻被打断。"

    def evaluate_runtime_events(self, stock_item, payload):
        if not stock_item or stock_item.get("status") != "holding":
            return
        symbol = stock_item.get("symbol", "")
        label = stock_item.get("label", symbol)
        price = float(payload.get("price", 0) or 0)
        change_pct = float(payload.get("change_pct", 0) or 0)
        levels = sorted(stock_item.get("levels", []) or [])
        plan = self.sell_plan_data(stock_item, payload)
        if price > 0:
            for level in levels:
                if level <= 0:
                    continue
                gap = abs(price - level) / level
                if gap <= 0.0015:
                    self.record_runtime_event(
                        symbol,
                        f"level-tight:{level:.2f}",
                        f"{label} 已贴近关键位 {level:.2f}，先看承接再决定是否动作。",
                        priority=0,
                    )
                elif gap <= 0.003:
                    self.record_runtime_event(
                        symbol,
                        f"level:{level:.2f}",
                        f"{label} 接近关键位 {level:.2f}，优先按计划观察承接。",
                        priority=1,
                    )
            defense = plan.get("defense_price")
            if defense and defense > 0:
                defense_gap = abs(price - float(defense)) / max(float(defense), 0.01)
                if price <= float(defense) or defense_gap <= 0.0015:
                    self.record_runtime_event(
                        symbol,
                        f"plan-defense-hit:{float(defense):.2f}",
                        f"{label} 触发防守位 {float(defense):.2f}，优先按{plan.get('sell_step', '防守减仓')}处理。",
                        priority=0,
                    )
                elif defense_gap <= 0.003:
                    self.record_runtime_event(
                        symbol,
                        f"plan-defense-near:{float(defense):.2f}",
                        f"{label} 接近防守位 {float(defense):.2f}，先准备防守动作。",
                        priority=1,
                    )
            take_profit = plan.get("take_profit_price")
            if take_profit and take_profit > 0:
                take_gap = abs(price - float(take_profit)) / max(float(take_profit), 0.01)
                if price >= float(take_profit) and "卖" in str(plan.get("sell_step", "")):
                    self.record_runtime_event(
                        symbol,
                        f"plan-take-hit:{float(take_profit):.2f}",
                        f"{label} 触发止盈位 {float(take_profit):.2f}，可先按{plan.get('sell_step', '锁盈')}执行。",
                        priority=1,
                    )
                elif take_gap <= 0.003 and "卖" in str(plan.get("sell_step", "")):
                    self.record_runtime_event(
                        symbol,
                        f"plan-take-near:{float(take_profit):.2f}",
                        f"{label} 接近止盈位 {float(take_profit):.2f}，先准备锁盈动作。",
                        priority=2,
                    )
            trailing = plan.get("trailing_stop_price")
            if trailing and trailing > 0:
                trailing_gap = abs(price - float(trailing)) / max(float(trailing), 0.01)
                if price <= float(trailing):
                    self.record_runtime_event(
                        symbol,
                        f"plan-trailing-hit:{float(trailing):.2f}",
                        f"{label} 跌回跟踪位 {float(trailing):.2f}，优先兑现已浮盈部分。",
                        priority=0,
                    )
                elif trailing_gap <= 0.003:
                    self.record_runtime_event(
                        symbol,
                        f"plan-trailing-near:{float(trailing):.2f}",
                        f"{label} 接近跟踪位 {float(trailing):.2f}，继续看是否失守。",
                        priority=1,
                    )
        if change_pct <= -9.5:
            pass
        elif change_pct <= -5:
            self.record_runtime_event(
                symbol,
                "drawdown",
                f"{label} 跌幅扩大到 {change_pct:+.2f}% ，先按防守计划处理。",
                priority=0,
            )
        elif change_pct <= -3:
            self.record_runtime_event(
                symbol,
                "soft-drawdown",
                f"{label} 跌幅来到 {change_pct:+.2f}% ，继续关注承接与防守位。",
                priority=1,
            )
        elif change_pct >= 9.5:
            pass
        elif change_pct >= 6:
            self.record_runtime_event(
                symbol,
                "hard-surge",
                f"{label} 涨幅扩大到 {change_pct:+.2f}% ，先确认是否按计划锁盈。",
                priority=0,
            )
        elif change_pct >= 4:
            self.record_runtime_event(
                symbol,
                "surge",
                f"{label} 涨幅来到 {change_pct:+.2f}% ，注意锁盈和冲高回落风险。",
                priority=2,
            )

    def runtime_event_summary(self, item):
        symbol = item.get("symbol", "")
        for event in self.runtime_events:
            if event.get("symbol") == symbol:
                hint = self.runtime_event_hints.get(event.get("fingerprint", ""), "")
                prefix = "强提醒｜" if event.get("escalate") else ""
                summary = f"事件  {prefix}{self.runtime_event_priority_text(event.get('priority', 2))}｜{event.get('time', '--')}｜{event.get('text', '')}"
                if hint:
                    summary += f"｜{hint}"
                return summary
        return "事件  暂无盘中触发"

    def fetch_runtime_event_hint_async(self, symbol, fingerprint, event_text):
        if fingerprint in self.event_hint_fetching:
            return
        stock_item = self.find_stock(symbol)
        quote = self.runtime_quotes.get(symbol)
        if not stock_item or not quote:
            return
        self.event_hint_fetching.add(fingerprint)

        def worker():
            try:
                state = self.market_state_data or get_market_state()
                result = explain_runtime_event(stock_item, quote, state, event_text)
                content = str(result.get("content", "")).strip()
            except Exception:
                content = ""
            self.root.after(0, lambda: self.apply_runtime_event_hint(fingerprint, content))

        threading.Thread(target=worker, daemon=True).start()

    def apply_runtime_event_hint(self, fingerprint, content):
        self.event_hint_fetching.discard(fingerprint)
        if content:
            self.runtime_event_hints[fingerprint] = content[:48]
            self.build_rows()

    def maybe_popup_runtime_event(self, symbol, fingerprint, event_text, priority, escalate=False):
        if not self.intraday_strong_reminder:
            return
        if not escalate:
            return
        now = dt.datetime.now()
        last_popup = self.event_popup_seen.get(fingerprint)
        if last_popup and (now - last_popup).total_seconds() < 600:
            return
        last_symbol_popup = self.event_popup_symbol_seen.get(symbol)
        if last_symbol_popup and (now - last_symbol_popup).total_seconds() < 180 and not escalate:
            return
        self.event_popup_seen[fingerprint] = now
        self.event_popup_symbol_seen[symbol] = now
        stock_item = self.find_stock(symbol)
        if not stock_item:
            return
        self.root.after(0, lambda: self.show_runtime_event_popup(stock_item, fingerprint, event_text))

    def show_runtime_event_popup(self, stock_item, fingerprint, event_text):
        dialog = tk.Toplevel(self.root)
        event = next((item for item in self.runtime_events if item.get("fingerprint") == fingerprint), {})
        dialog.title("盘中强提醒" if event.get("escalate") else "盘中事件提醒")
        dialog.configure(bg=BG)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        frame = tk.Frame(dialog, bg=BG, padx=18, pady=16, highlightthickness=1, highlightbackground=BORDER)
        frame.pack(fill="both", expand=True)

        head = tk.Frame(frame, bg=BG)
        head.pack(fill="x")
        tk.Label(
            head,
            text="盘中强提醒" if event.get("escalate") else "盘中事件提醒",
            fg=TEXT,
            bg=BG,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(side="left")
        priority = event.get("priority", 0)
        action_text = event.get("action", "")
        priority_label = self.runtime_event_priority_text(priority)
        priority_fg = "#fecaca" if priority <= 0 or event.get("escalate") else "#fde68a"
        interrupt_reason = event.get("interrupt_reason", "")
        tk.Label(
            head,
            text=stock_item.get("label", stock_item.get("symbol", "")),
            fg=MUTED,
            bg=BG,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")
        tk.Label(
            frame,
            text=f"优先级：{priority_label}{'｜请先处理' if event.get('escalate') else ''}",
            fg=priority_fg,
            bg=BG,
            justify="left",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w", pady=(8, 4))

        tk.Label(
            frame,
            text=event_text,
            fg="#fde68a",
            bg=BG,
            justify="left",
            wraplength=380,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w", pady=(12, 8))

        if interrupt_reason:
            tk.Label(
                frame,
                text=f"打断原因：{interrupt_reason}",
                fg="#fca5a5" if event.get("escalate") else "#fde68a",
                bg=BG,
                justify="left",
                wraplength=380,
                font=("Microsoft YaHei UI", 9),
            ).pack(anchor="w", pady=(0, 8))

        if action_text:
            tk.Label(
                frame,
                text=f"建议动作：{action_text}",
                fg="#86efac",
                bg=BG,
                justify="left",
                wraplength=380,
                font=("Microsoft YaHei UI", 9, "bold"),
            ).pack(anchor="w", pady=(0, 8))

        hint = self.runtime_event_hints.get(fingerprint, "")
        hint_var = tk.StringVar(value=hint or "正在生成盘中处理提示...")
        hint_label = tk.Label(
            frame,
            textvariable=hint_var,
            fg="#d1d5db",
            bg=BG,
            justify="left",
            wraplength=380,
            font=("Microsoft YaHei UI", 9),
        )
        hint_label.pack(anchor="w")

        btn_bar = tk.Frame(frame, bg=BG)
        btn_bar.pack(fill="x", pady=(14, 0))
        tk.Button(
            btn_bar,
            text="AI对话",
            command=lambda: (dialog.destroy(), self.open_ai_chat_panel(stock_item.get("symbol"))),
            bg=BUTTON_PURPLE,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left")
        tk.Button(
            btn_bar,
            text="关闭弹窗",
            command=dialog.destroy,
            bg=BORDER,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right")

        self.position_runtime_event_popup(dialog)

        def refresh_hint():
            latest = self.runtime_event_hints.get(fingerprint, "")
            if latest:
                hint_var.set(latest)
                return
            if dialog.winfo_exists():
                dialog.after(600, refresh_hint)

        dialog.after(600, refresh_hint)

    def build_dashboard_payload(self):
        return {
            "market": self.market_state_data or {
                "generated_at": "等待刷新",
                "mood": "等待刷新",
                "tactic": "正在获取市场状态",
                "risk_bias": "--",
                "score": 0,
                "summary": "正在拉取指数、样本涨跌分布和市场情绪，请稍候。",
                "indices": [],
                "breadth": {"up": 0, "down": 0, "flat": 0, "sample_size": 0},
            },
            "account": self.dashboard_holding_summary(),
            "focus": self.dashboard_focus_candidates(),
            "risks": self.dashboard_risk_summary(),
            "actions": self.dashboard_action_plan(),
            "do_list": self.dashboard_should_do(),
            "avoid_list": self.dashboard_should_avoid(),
            "todo": self.dashboard_todo_list(),
        }

    def open_dashboard_panel(self):
        if self.market_state_data is None and not self.market_state_fetching:
            self.fetch_market_state_async()
        open_dashboard_panel(
            self.root,
            self.build_dashboard_payload,
            on_mouse_enter=self.on_mouse_enter,
            center_dialog=self.center_dialog,
        )

    def fetch_market_state_async(self):
        if self.market_state_fetching:
            return
        self.market_state_fetching = True

        def worker():
            try:
                state = get_market_state()
            except Exception as exc:
                state = {
                    "mood": "未知",
                    "tactic": "等待确认",
                    "risk_bias": "中等",
                    "score": 0,
                    "summary": f"市场状态获取失败：{exc}",
                    "indices": [],
                    "breadth": {"up": 0, "down": 0, "flat": 0, "sample_size": 0},
                }
            self.root.after(0, lambda: self.apply_market_state(state))

        threading.Thread(target=worker, daemon=True).start()

    def apply_market_state(self, state):
        self.market_state_fetching = False
        self.market_state_data = state
        self.market_state_updated_at = dt.datetime.now()
        if self.active_tab == "dashboard":
            self.build_rows()

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

    def toggle_pin_selected(self, symbol=None):
        stock_item = self.find_stock(symbol or self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("置顶", "请先选择一只股票。")
            return
        stock_item["pinned"] = not bool(stock_item.get("pinned", False))
        self.save_and_reload()

    def add_selected_to_favorite(self, symbol=None):
        stock_item = self.find_stock(symbol or self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("加收藏", "请先选择一只股票。")
            return
        current_status = str(stock_item.get("status", "favorite"))
        if current_status == "favorite":
            messagebox.showinfo("加收藏", "这只股票已经在收藏里了。")
            return
        if current_status == "holding":
            messagebox.showinfo("加收藏", "这只股票当前在持有中，无需再加收藏。")
            return
        if current_status == "closed":
            stock_item["status"] = "favorite"
        elif current_status == "recommended":
            stock_item["status"] = "favorite"
        stock_item.setdefault("manual_mark", {})
        stock_item["manual_mark"]["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.active_tab = "favorite"
        self.selected_symbol = stock_item["symbol"]
        self.save_and_reload()

    def buy_selected_from_favorite(self, symbol=None):
        stock_item = self.find_stock(symbol or self.selected_symbol)
        if not stock_item:
            messagebox.showinfo("买入", "请先选择一只股票。")
            return
        self.selected_symbol = stock_item["symbol"]
        self.open_trade_dialog("add")

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

    def sell_plan_data(self, item, quote=None):
        quote = quote or self.runtime_quotes.get(item.get("symbol", ""))
        lots = int(item.get("lots", 0) or 0)
        cost_price = item.get("cost_price")
        levels = sorted(item.get("levels", []) or [], reverse=True)
        if not quote or lots <= 0 or cost_price in (None, ""):
            buy_trigger = f"站上 {levels[0]:.2f} 试 1-2 手" if levels else "暂无持仓，先观察"
            return {
                "action": "继续观察",
                "summary": f"操作计划  {buy_trigger}",
                "defense_price": levels[-1] if levels else None,
                "take_profit_price": levels[0] if levels else None,
                "trailing_stop_price": None,
                "sell_step": "暂无持仓",
                "sell_size": "0%",
                "buy_trigger": buy_trigger,
                "buy_size": "试仓 1-2 手",
            }

        price = float(quote.get("price", 0) or 0)
        cost = float(cost_price)
        change_pct = float(quote.get("change_pct", 0) or 0)
        profit_pct = ((price - cost) / max(cost, 0.01)) * 100
        above = [level for level in levels if level >= price]
        below = sorted([level for level in levels if level <= price], reverse=True)
        defense = below[0] if below else round(cost * 0.98, 2)
        take_profit = above[0] if above else round(max(price, cost) * 1.03, 2)
        trailing = None
        action = "继续观察"
        sell_step = "先观察"
        sell_size = "0%"

        if profit_pct >= 6:
            action = "分批止盈"
            trailing = round(max(price * 0.985, cost * 1.02), 2)
            sell_step = "先卖 1/3，余下看跟踪位"
            sell_size = "33%"
            summary = f"操作计划  先卖 1/3｜跟踪 {trailing:.2f}"
        elif profit_pct >= 3:
            action = "冲高减仓"
            trailing = round(max(price * 0.99, cost), 2)
            sell_step = "冲高先卖 1/4，失守防守位减半"
            sell_size = "25%"
            summary = f"操作计划  冲高卖 1/4｜失守 {defense:.2f} 减半"
        elif change_pct <= -4 or price <= defense:
            action = "防守减仓"
            sell_step = "失守防守位先减半"
            sell_size = "50%"
            summary = f"操作计划  失守 {defense:.2f} 先减半"
        elif price > cost and change_pct > 0:
            action = "持有观察"
            sell_step = "暂不卖，冲压力位再锁盈"
            summary = f"操作计划  先拿住｜冲 {take_profit:.2f} 再锁盈"
        else:
            action = "继续观察"
            sell_step = "先等站回压力位再看"
            summary = f"操作计划  先观察｜站回 {take_profit:.2f} 再看"

        return {
            "action": action,
            "summary": summary,
            "defense_price": defense,
            "take_profit_price": take_profit,
            "trailing_stop_price": trailing,
            "sell_step": sell_step,
            "sell_size": sell_size,
            "buy_trigger": "不急着加仓，先看关键位确认",
            "buy_size": "若要加，只加 1-2 手或不超过当前仓位 1/3",
        }

    def sell_plan_summary(self, item):
        return self.sell_plan_data(item).get("summary", "操作计划  暂无持仓，先观察")

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
        self.saved_y = self.clamp_y(self.saved_y)
        self.snap_to_edge(self.anchor_side, persist=False)

    def snap_to_edge(self, side, persist=True):
        self.root.update_idletasks()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        screen_width = self.root.winfo_screenwidth()
        y = self.clamp_y(self.saved_y)
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
        y = self.clamp_y(self.saved_y)
        x = -(width - self.visible_strip) if self.anchor_side == "left" else self.root.winfo_screenwidth() - self.visible_strip
        self.root.geometry(f"+{x}+{y}")
        self.hidden = True
        self.tray_icon.show()

    def show_from_edge(self):
        self.root.update_idletasks()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        y = self.clamp_y(self.saved_y)
        x = 0 if self.anchor_side == "left" else self.root.winfo_screenwidth() - width
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def restore_from_tray(self):
        self.show_from_edge()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.root.after(250, lambda: self.root.attributes("-topmost", self.always_on_top))

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
        zone = self.current_resize_zone(event.x_root, event.y_root)
        if zone:
            self.resizing = True
            self.resize_edge = zone
            self.resize_origin = {
                "pointer_x": event.x_root,
                "pointer_y": event.y_root,
                "x": self.root.winfo_x(),
                "y": self.root.winfo_y(),
                "width": self.root.winfo_width() or self.root.winfo_reqwidth(),
                "height": self.root.winfo_height() or self.root.winfo_reqheight(),
            }
        else:
            if event.widget.winfo_class() in {"Button", "Entry", "Text", "Scrollbar"}:
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
        if self.resizing:
            self.resize_window(event)
            return
        if not self.dragging:
            return
        x = event.x_root - self.drag_x
        y = event.y_root - self.drag_y
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        height = self.root.winfo_height() or self.root.winfo_reqheight()
        x = max(-width + self.visible_strip, min(x, screen_width - self.visible_strip))
        y = max(WINDOW_TOP_MARGIN, min(y, screen_height - height - 60))
        self.saved_y = y
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def end_move(self, _event=None):
        if self.resizing:
            self.resizing = False
            self.resize_edge = None
            self.resize_origin = {}
            self.saved_y = self.clamp_y(self.root.winfo_y())
            self.anchor_side = "left" if self.root.winfo_x() < self.root.winfo_screenwidth() // 2 else "right"
            self.save_widget_preferences()
            self.on_pointer_motion()
            return
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
        self.always_on_top = bool(widget_cfg.get("always_on_top", self.always_on_top))
        self.ui_scale = self.normalize_ui_scale(widget_cfg.get("ui_scale", self.ui_scale))
        self.intraday_runtime_reminder = bool(widget_cfg.get("intraday_runtime_reminder", self.intraday_runtime_reminder))
        self.intraday_strong_reminder = bool(widget_cfg.get("intraday_strong_reminder", self.intraday_strong_reminder))
        self.root.attributes("-topmost", self.always_on_top)
        self.root.tk.call("tk", "scaling", self.base_tk_scaling * self.ui_scale)
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

        provider_var = tk.StringVar(value=settings.get("provider", "auto"))
        router_enabled = tk.BooleanVar(value=bool(settings.get("router", {}).get("enabled", False)))
        local_enabled = tk.BooleanVar(value=bool(settings["local"].get("enabled", False)))
        deepseek_enabled = tk.BooleanVar(value=bool(settings["deepseek"].get("enabled", True)))
        bailian_enabled = tk.BooleanVar(value=bool(settings["bailian"].get("enabled", True)))
        custom_providers = [dict(item) for item in settings.get("custom_providers", [])]
        fields = {
            "router_base": tk.StringVar(value=settings.get("router", {}).get("base_url", "")),
            "router_model": tk.StringVar(value=settings.get("router", {}).get("model", "")),
            "router_key": tk.StringVar(value=settings.get("router", {}).get("api_key", "")),
            "local_base": tk.StringVar(value=settings["local"].get("base_url", "")),
            "local_model": tk.StringVar(value=settings["local"].get("model", "")),
            "local_key": tk.StringVar(value=settings["local"].get("api_key", "")),
            "deepseek_base": tk.StringVar(value=settings["deepseek"].get("base_url", "")),
            "deepseek_model": tk.StringVar(value=settings["deepseek"].get("model", "")),
            "deepseek_key": tk.StringVar(value=settings["deepseek"].get("api_key", "")),
            "bailian_base": tk.StringVar(value=settings["bailian"].get("base_url", "")),
            "bailian_model": tk.StringVar(value=settings["bailian"].get("model", "")),
            "bailian_key": tk.StringVar(value=settings["bailian"].get("api_key", "")),
        }
        custom_name_var = tk.StringVar()
        custom_enabled_var = tk.BooleanVar(value=True)
        custom_base_var = tk.StringVar()
        custom_model_var = tk.StringVar()
        custom_key_var = tk.StringVar()
        selected_custom_index: dict[str, int | None] = {"value": None}

        row = 0
        tk.Label(dialog, text="默认AI来源", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9, "bold")).grid(row=row, column=0, sticky="w", padx=12, pady=(12, 0))
        provider_menu = tk.OptionMenu(dialog, provider_var, *provider_choices(settings))
        provider_menu.grid(row=row, column=1, sticky="ew", padx=12, pady=(12, 0))
        row += 1

        def refresh_provider_menu() -> None:
            menu = provider_menu["menu"]
            menu.delete(0, "end")
            choices = provider_choices({"custom_providers": custom_providers})
            current = provider_var.get().strip() or "auto"
            for choice in choices:
                menu.add_command(label=choice, command=lambda value=choice: provider_var.set(value))
            if current not in choices:
                provider_var.set("auto")

        for name, enabled_var, prefix, title in (
            ("router", router_enabled, "router", "路由网关（LiteLLM / OpenAI 兼容代理）"),
            ("local", local_enabled, "local", "本地模型（Ollama / 本地 OpenAI 兼容）"),
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

        tk.Label(dialog, text="自定义 AI（OpenAI 兼容）", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9, "bold")).grid(row=row, column=0, sticky="w", padx=12, pady=(12, 0))
        row += 1
        custom_wrap = tk.Frame(dialog, bg=PANEL)
        custom_wrap.grid(row=row, column=0, columnspan=2, sticky="nsew", padx=12, pady=(6, 0))
        custom_wrap.grid_columnconfigure(1, weight=1)
        custom_list = tk.Listbox(custom_wrap, height=5, exportselection=False)
        custom_list.grid(row=0, column=0, rowspan=7, sticky="nsw", padx=(0, 12))
        detail = tk.Frame(custom_wrap, bg=PANEL)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.grid_columnconfigure(1, weight=1)
        tk.Label(detail, text="名称", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w")
        tk.Entry(detail, textvariable=custom_name_var, width=28).grid(row=0, column=1, sticky="ew", pady=(0, 6))
        tk.Label(detail, text="Base URL", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w")
        tk.Entry(detail, textvariable=custom_base_var, width=28).grid(row=1, column=1, sticky="ew", pady=(0, 6))
        tk.Label(detail, text="Model", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w")
        tk.Entry(detail, textvariable=custom_model_var, width=28).grid(row=2, column=1, sticky="ew", pady=(0, 6))
        tk.Label(detail, text="API Key", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, sticky="w")
        tk.Entry(detail, textvariable=custom_key_var, width=28, show="*").grid(row=3, column=1, sticky="ew", pady=(0, 6))
        tk.Checkbutton(detail, text="启用", variable=custom_enabled_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=4, column=0, columnspan=2, sticky="w")
        custom_bar = tk.Frame(detail, bg=PANEL)
        custom_bar.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1

        def refresh_custom_list() -> None:
            custom_list.delete(0, "end")
            for item in custom_providers:
                label = str(item.get("name", "")).strip() or "未命名"
                if not item.get("enabled", True):
                    label = f"{label}（停用）"
                custom_list.insert("end", label)
            refresh_provider_menu()

        def load_custom_form(index: int | None) -> None:
            selected_custom_index["value"] = index
            if index is None or index < 0 or index >= len(custom_providers):
                custom_name_var.set("")
                custom_base_var.set("")
                custom_model_var.set("")
                custom_key_var.set("")
                custom_enabled_var.set(True)
                return
            item = custom_providers[index]
            custom_name_var.set(str(item.get("name", "")))
            custom_base_var.set(str(item.get("base_url", "")))
            custom_model_var.set(str(item.get("model", "")))
            custom_key_var.set(str(item.get("api_key", "")))
            custom_enabled_var.set(bool(item.get("enabled", True)))

        def on_custom_select(event=None) -> None:
            selection = custom_list.curselection()
            load_custom_form(selection[0] if selection else None)

        def save_custom_provider(show_message: bool = True) -> bool:
            name = custom_name_var.get().strip()
            if not name:
                if show_message:
                    messagebox.showwarning("AI设置", "请先填写自定义 AI 名称。")
                return False
            if name.lower() in {"auto", "router", "local", "deepseek", "bailian"}:
                if show_message:
                    messagebox.showwarning("AI设置", "名称不能与内置 AI 重名。")
                return False
            payload = {
                "name": name,
                "enabled": bool(custom_enabled_var.get()),
                "base_url": custom_base_var.get().strip(),
                "model": custom_model_var.get().strip(),
                "api_key": custom_key_var.get().strip(),
            }
            current_index = selected_custom_index["value"]
            for idx, item in enumerate(custom_providers):
                if idx == current_index:
                    continue
                if str(item.get("name", "")).strip().lower() == name.lower():
                    if show_message:
                        messagebox.showwarning("AI设置", "已存在同名自定义 AI。")
                    return False
            if current_index is None or current_index >= len(custom_providers):
                custom_providers.append(payload)
                current_index = len(custom_providers) - 1
            else:
                custom_providers[current_index] = payload
            refresh_custom_list()
            custom_list.selection_clear(0, "end")
            custom_list.selection_set(current_index)
            load_custom_form(current_index)
            if show_message:
                messagebox.showinfo("AI设置", "自定义 AI 已保存。")
            return True

        def add_custom_provider() -> None:
            custom_list.selection_clear(0, "end")
            load_custom_form(None)

        def delete_custom_provider() -> None:
            index = selected_custom_index["value"]
            if index is None or index >= len(custom_providers):
                return
            deleted_name = str(custom_providers[index].get("name", "")).strip()
            custom_providers.pop(index)
            if provider_var.get().strip() == deleted_name:
                provider_var.set("auto")
            refresh_custom_list()
            load_custom_form(None)

        def test_selected_provider() -> None:
            provider_name = provider_var.get().strip() or "auto"
            test_settings = {
                "provider": provider_name,
                "router": {
                    "enabled": bool(router_enabled.get()),
                    "base_url": fields["router_base"].get().strip(),
                    "model": fields["router_model"].get().strip(),
                    "api_key": fields["router_key"].get().strip(),
                },
                "local": {
                    "enabled": bool(local_enabled.get()),
                    "base_url": fields["local_base"].get().strip(),
                    "model": fields["local_model"].get().strip(),
                    "api_key": fields["local_key"].get().strip(),
                },
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
                "custom_providers": list(custom_providers),
            }
            if provider_name not in {"auto", "router", "local", "deepseek", "bailian"}:
                save_custom_provider(show_message=False)
                test_settings["custom_providers"] = list(custom_providers)
            if provider_name == "auto":
                messagebox.showinfo("AI设置", "请先切换到一个具体 AI，再测试连接。")
                return
            ok, msg = test_provider_connection(test_settings, provider_name)
            if ok:
                messagebox.showinfo("测试连接", msg)
            else:
                messagebox.showwarning("测试连接", msg)

        tk.Button(custom_bar, text="新增 AI", command=add_custom_provider).pack(side="left")
        tk.Button(custom_bar, text="保存 AI", command=save_custom_provider).pack(side="left", padx=(8, 0))
        tk.Button(custom_bar, text="删除 AI", command=delete_custom_provider).pack(side="left", padx=(8, 0))
        tk.Button(custom_bar, text="测试连接", command=test_selected_provider).pack(side="left", padx=(8, 0))
        custom_list.bind("<<ListboxSelect>>", on_custom_select)
        refresh_custom_list()
        load_custom_form(0 if custom_providers else None)

        tk.Label(dialog, text="Router 适合接 LiteLLM 等本地网关；本地模型通常不需要 API Key；云模型不填时，会继续尝试读取你本机已有配置。", fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 0))
        row += 1

        def on_save():
            if custom_name_var.get().strip():
                save_custom_provider(show_message=False)
            new_settings = {
                "provider": provider_var.get().strip() or "auto",
                "router": {
                    "enabled": bool(router_enabled.get()),
                    "base_url": fields["router_base"].get().strip(),
                    "model": fields["router_model"].get().strip(),
                    "api_key": fields["router_key"].get().strip(),
                },
                "local": {
                    "enabled": bool(local_enabled.get()),
                    "base_url": fields["local_base"].get().strip(),
                    "model": fields["local_model"].get().strip(),
                    "api_key": fields["local_key"].get().strip(),
                },
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
                "custom_providers": list(custom_providers),
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
        allow_kcb_var = tk.BooleanVar(value=bool(self.recommend_filter.get("allow_kcb", False)))
        avoid_limit_up_var = tk.BooleanVar(value=bool(self.recommend_filter.get("avoid_limit_up", True)))
        max_chase_pct_var = tk.StringVar(value=str(self.recommend_filter.get("max_chase_pct", 7.5)))

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
        tk.Label(dialog, text="最大追涨幅(%)", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(row=5, column=0, sticky="w", padx=12, pady=(8, 0))
        tk.Entry(dialog, textvariable=max_chase_pct_var, width=24).grid(row=5, column=1, sticky="ew", padx=12, pady=(8, 0))
        tk.Checkbutton(dialog, text="排除涨停/接近涨停", variable=avoid_limit_up_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))
        tk.Checkbutton(dialog, text="要求有提醒位", variable=require_levels_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=7, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 0))
        tk.Checkbutton(dialog, text="只优先正向新闻", variable=prefer_positive_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=8, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 0))
        tk.Checkbutton(dialog, text="已开通科创板（允许推荐科创股）", variable=allow_kcb_var, fg=TEXT, bg=PANEL, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).grid(row=9, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 0))

        def on_save():
            try:
                max_chase_pct_value = float(max_chase_pct_var.get().strip() or 7.5)
            except Exception:
                messagebox.showerror("推荐条件", "最大追涨幅必须是数字。")
                return
            self.recommend_filter = {
                "min_price": min_price_var.get().strip(),
                "max_price": max_price_var.get().strip(),
                "min_score": int(min_score_var.get().strip() or 45),
                "max_quant_risk": max_risk_var.get().strip() or "中等",
                "max_chase_pct": max_chase_pct_value,
                "avoid_limit_up": bool(avoid_limit_up_var.get()),
                "require_levels": bool(require_levels_var.get()),
                "prefer_positive_news": bool(prefer_positive_var.get()),
                "allow_kcb": bool(allow_kcb_var.get()),
            }
            self.save_widget_preferences()
            dialog.destroy()
            messagebox.showinfo("推荐条件", "推荐条件已保存。")

        bar = tk.Frame(dialog, bg=PANEL)
        bar.grid(row=10, column=0, columnspan=2, sticky="e", padx=12, pady=12)
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
        follow_button = None

        def apply_result(result):
            self.last_recommend_result = result
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
            if follow_button is not None:
                follow_button.configure(state="normal" if picks or result.get("content") else "disabled")
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
        follow_button = tk.Button(bar, text="继续追问", state="disabled", command=self.open_recommend_chat_panel)
        follow_button.pack(side="left")
        tk.Button(bar, text="关闭", command=dialog.destroy).pack(side="right")
        self.center_dialog(dialog)

    def open_recommend_chat_panel(self):
        if not isinstance(self.last_recommend_result, dict):
            messagebox.showinfo("推荐对话", "请先生成一次 AI 推荐。")
            return
        open_recommend_chat_panel(
            self.root,
            self.last_recommend_result,
            on_mouse_enter=self.on_mouse_enter,
            center_dialog=self.center_dialog,
        )

    def open_ai_chat_panel(self, symbol=None):
        target_symbol = symbol or self.selected_symbol
        if symbol:
            self.selected_symbol = symbol
        stock_item = self.find_stock(target_symbol)
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
        dialog_w, dialog_h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - dialog_w) // 2)
        y = max(0, (screen_h - dialog_h) // 2 - 20)
        dialog.geometry(f"+{x}+{y}")

    def position_runtime_event_popup(self, dialog):
        dialog.update_idletasks()
        dialog_w, dialog_h = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        margin_x = 28
        margin_y = 56
        x = max(0, screen_w - dialog_w - margin_x)
        y = max(0, screen_h - dialog_h - margin_y)
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
                self.evaluate_runtime_events(stock_item, payload)
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
                self.rows[symbol]["event"].configure(text=self.runtime_event_summary(stock_item))
                self.rows[symbol]["plan"].configure(text=self.next_day_summary(stock_item))
                self.rows[symbol]["sell"].configure(text=self.sell_plan_summary(stock_item))
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
                    self.rows[symbol]["event"].configure(text=self.runtime_event_summary(stock_item))
                    self.rows[symbol]["plan"].configure(text=self.next_day_summary(stock_item))
                    self.rows[symbol]["sell"].configure(text=self.sell_plan_summary(stock_item))
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
        if self.market_state_updated_at is None or (dt.datetime.now() - self.market_state_updated_at).total_seconds() >= max(60, int(self.config["interval"]) * 4):
            self.fetch_market_state_async()
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
