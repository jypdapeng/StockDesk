import argparse
import datetime as dt
import pathlib
import re
import threading
import tkinter as tk
from tkinter import messagebox
import urllib.error
import webbrowser

from stock_common import DEFAULT_CONFIG, fetch_quote, infer_market, load_config, save_config


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
        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.on_move)

        self.drag_x = 0
        self.drag_y = 0
        self.selected_symbol: str | None = None
        self.rows: dict[str, dict[str, tk.Widget]] = {}
        self.fetch_inflight = False
        self.hide_job: str | None = None
        self.hidden = False
        self.visible_strip = 14

        frame = tk.Frame(
            self.root,
            bg=PANEL,
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        frame.pack(fill="both", expand=True)

        header = tk.Frame(frame, bg=PANEL)
        header.pack(fill="x")
        tk.Label(header, text="股票盯盘", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self.time_label = tk.Label(header, text="--:--:--", fg=MUTED, bg=PANEL, font=("Consolas", 9))
        self.time_label.pack(side="left", padx=(8, 0))

        for text, command, bg in (
            ("新增", self.open_add_dialog, "#2563eb"),
            ("编辑", self.open_edit_dialog, "#374151"),
            ("打开", self.open_selected_site, "#065f46"),
            ("删除", self.delete_selected, "#7f1d1d"),
            ("关闭", self.root.destroy, PANEL),
        ):
            tk.Button(
                header,
                text=text,
                command=command,
                fg=TEXT if text != "关闭" else MUTED,
                bg=bg,
                activebackground=bg,
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                font=("Microsoft YaHei UI", 8, "bold"),
                padx=8 if text != "关闭" else 4,
                pady=2 if text != "关闭" else 0,
            ).pack(side="right", padx=(4, 0))

        tk.Label(
            frame,
            text="点击一行后可编辑、打开或删除",
            fg=MUTED,
            bg=PANEL,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(4, 8))

        self.empty_label = tk.Label(
            frame,
            text="暂无股票，点击“新增”开始添加",
            fg=MUTED,
            bg=PANEL,
            font=("Microsoft YaHei UI", 9),
        )

        self.list_container = tk.Frame(frame, bg=PANEL)
        self.list_container.pack(fill="both", expand=True)
        self.build_rows()

        self.bind_hover_events()
        self.place_bottom_right()
        self.hide_to_right_edge()
        self.refresh()

    def bind_hover_events(self) -> None:
        widgets = [self.root]
        widgets.extend(self.root.winfo_children())
        for child in self.root.winfo_children():
            widgets.extend(child.winfo_children())
        for widget in widgets:
            widget.bind("<Enter>", self.on_mouse_enter, add="+")
            widget.bind("<Leave>", self.on_mouse_leave, add="+")

    def build_rows(self) -> None:
        for child in self.list_container.winfo_children():
            child.destroy()
        self.rows.clear()

        if not self.config["stocks"]:
            self.selected_symbol = None
            self.empty_label.pack(anchor="w", pady=(0, 4))
            self.bind_hover_events()
            return

        self.empty_label.pack_forget()

        for item in self.config["stocks"]:
            symbol = item["symbol"]
            row = tk.Frame(
                self.list_container,
                bg=BG,
                padx=8,
                pady=6,
                highlightthickness=2,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
            )
            row.pack(fill="x", pady=4)

            title = tk.Label(row, text=item["label"], fg=TEXT, bg=BG, font=("Microsoft YaHei UI", 10, "bold"))
            title.grid(row=0, column=0, sticky="w")
            code = tk.Label(row, text=symbol, fg=MUTED, bg=BG, font=("Consolas", 9))
            code.grid(row=1, column=0, sticky="w")
            price = tk.Label(row, text="--", fg=TEXT, bg=BG, font=("Consolas", 18, "bold"))
            price.grid(row=0, column=1, rowspan=2, sticky="e", padx=(20, 0))
            change = tk.Label(row, text="--", fg=MUTED, bg=BG, font=("Consolas", 10))
            change.grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 0))

            levels = ", ".join(f"{level:.2f}" for level in item["levels"]) or "-"
            level_label = tk.Label(row, text=f"提醒位 {levels}", fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8))
            level_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
            position_label = tk.Label(row, text="成本 --  持仓 --", fg=MUTED, bg=BG, font=("Microsoft YaHei UI", 8))
            position_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))
            profit_label = tk.Label(row, text="盈亏 --", fg=MUTED, bg=BG, font=("Consolas", 9, "bold"))
            profit_label.grid(row=3, column=2, sticky="e", pady=(2, 0))
            row.grid_columnconfigure(1, weight=1)

            widgets = [row, title, code, price, change, level_label, position_label, profit_label]
            for widget in widgets:
                widget.bind("<Button-1>", lambda event, s=symbol: self.select_symbol(s))

            self.rows[symbol] = {
                "frame": row,
                "title": title,
                "code": code,
                "price": price,
                "change": change,
                "position": position_label,
                "profit": profit_label,
                "widgets": widgets,
            }

        available = {item["symbol"] for item in self.config["stocks"]}
        if self.selected_symbol not in available:
            self.selected_symbol = self.config["stocks"][0]["symbol"]
        self.select_symbol(self.selected_symbol)
        self.bind_hover_events()

    def select_symbol(self, symbol: str | None) -> None:
        self.selected_symbol = symbol
        for row_symbol, parts in self.rows.items():
            is_selected = row_symbol == symbol
            bg = SELECTED if is_selected else BG
            border = ACCENT if is_selected else BORDER
            parts["frame"].configure(bg=bg, highlightbackground=border, highlightcolor=border)
            for widget in parts["widgets"]:
                widget.configure(bg=bg)

    def place_bottom_right(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = screen_width - width - 24
        y = screen_height - height - 64
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def hide_to_right_edge(self) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_screenwidth() - self.visible_strip
        y = self.root.winfo_y()
        self.root.geometry(f"+{x}+{y}")
        self.hidden = True

    def show_from_right_edge(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width() or self.root.winfo_reqwidth()
        x = self.root.winfo_screenwidth() - width
        y = self.root.winfo_y()
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def schedule_hide(self) -> None:
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
        self.hide_job = self.root.after(250, self.hide_if_pointer_outside)

    def hide_if_pointer_outside(self) -> None:
        self.hide_job = None
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        left = self.root.winfo_x()
        top = self.root.winfo_y()
        right = left + self.root.winfo_width()
        bottom = top + self.root.winfo_height()
        if left <= pointer_x <= right and top <= pointer_y <= bottom:
            return
        self.hide_to_right_edge()

    def on_mouse_enter(self, _event=None) -> None:
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if self.hidden:
            self.show_from_right_edge()

    def on_mouse_leave(self, _event=None) -> None:
        self.schedule_hide()

    def start_move(self, event) -> None:
        self.drag_x = event.x
        self.drag_y = event.y

    def on_move(self, event) -> None:
        x = event.x_root - self.drag_x
        y = event.y_root - self.drag_y
        self.root.geometry(f"+{x}+{y}")
        self.hidden = False

    def save_and_reload(self) -> None:
        save_config(self.config_path, self.config)
        self.config = load_config(self.config_path)
        self.interval_ms = max(1000, int(self.config["interval"]) * 1000)
        self.build_rows()
        if self.hidden:
            self.hide_to_right_edge()
        else:
            self.show_from_right_edge()

    def open_add_dialog(self) -> None:
        self.open_stock_dialog()

    def open_selected_site(self) -> None:
        if not self.selected_symbol:
            messagebox.showinfo("打开股票", "请先选择一只股票。")
            return
        current = next((item for item in self.config["stocks"] if item["symbol"] == self.selected_symbol), None)
        if not current:
            return
        market = current.get("market") or infer_market(self.selected_symbol)
        webbrowser.open(f"https://gu.qq.com/{market}{self.selected_symbol}", new=2)

    def open_edit_dialog(self) -> None:
        if not self.selected_symbol:
            messagebox.showinfo("编辑股票", "请先选择一只股票。")
            return
        current = next((item for item in self.config["stocks"] if item["symbol"] == self.selected_symbol), None)
        if current:
            self.open_stock_dialog(current)

    def open_stock_dialog(self, current: dict | None = None) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑股票" if current else "新增股票")
        dialog.configure(bg=PANEL)
        dialog.attributes("-topmost", True)
        dialog.transient(self.root)
        dialog.grab_set()

        symbol_var = tk.StringVar(value=current["symbol"] if current else "")
        label_var = tk.StringVar(value=current.get("label", "") if current else "")
        cost_var = tk.StringVar(
            value=f"{float(current['cost_price']):.3f}" if current and current.get("cost_price") not in (None, "") else ""
        )
        lots_var = tk.StringVar(value=str(current.get("lots", 0)) if current and current.get("lots", 0) else "")
        levels_var = tk.StringVar(
            value=", ".join(str(level) for level in current.get("levels", [])) if current else ""
        )

        fields = (
            ("代码", symbol_var),
            ("名称", label_var),
            ("成本价", cost_var),
            ("持仓手数", lots_var),
            ("提醒位", levels_var),
        )
        for idx, (label, variable) in enumerate(fields):
            tk.Label(dialog, text=label, fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 9)).grid(
                row=idx, column=0, sticky="w", padx=12, pady=(12 if idx == 0 else 8, 0)
            )
            tk.Entry(dialog, textvariable=variable, width=28).grid(
                row=idx, column=1, sticky="ew", padx=12, pady=(12 if idx == 0 else 8, 0)
            )

        tk.Label(
            dialog,
            text="提醒位示例：7.6, 7.2；持仓手数按 1 手 = 100 股计算",
            fg=MUTED,
            bg=PANEL,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))

        def on_save() -> None:
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
            if not levels:
                messagebox.showerror("保存股票", "至少需要一个提醒位。")
                return

            item = {
                "symbol": symbol,
                "market": infer_market(symbol),
                "label": label or symbol,
                "cost_price": cost_price,
                "lots": lots,
                "levels": sorted(set(levels), reverse=True),
            }

            if current:
                for idx, existing in enumerate(self.config["stocks"]):
                    if existing["symbol"] == current["symbol"]:
                        self.config["stocks"][idx] = item
                        break
            else:
                if any(existing["symbol"] == symbol for existing in self.config["stocks"]):
                    messagebox.showerror("保存股票", "这只股票已经存在。")
                    return
                self.config["stocks"].append(item)

            self.selected_symbol = symbol
            self.save_and_reload()
            dialog.destroy()

        button_bar = tk.Frame(dialog, bg=PANEL)
        button_bar.grid(row=6, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        tk.Button(button_bar, text="取消", command=dialog.destroy).pack(side="right", padx=(8, 0))
        tk.Button(button_bar, text="保存", command=on_save).pack(side="right")
        dialog.grid_columnconfigure(1, weight=1)
        dialog.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        dialog_w = dialog.winfo_reqwidth()
        dialog_h = dialog.winfo_reqheight()
        x = root_x + max(0, (root_w - dialog_w) // 2)
        y = root_y + max(0, (root_h - dialog_h) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.bind("<Enter>", self.on_mouse_enter, add="+")

    def delete_selected(self) -> None:
        if not self.selected_symbol:
            messagebox.showinfo("删除股票", "请先选择一只股票。")
            return
        if not messagebox.askyesno("删除股票", f"确认删除 {self.selected_symbol} 吗？"):
            return
        self.config["stocks"] = [item for item in self.config["stocks"] if item["symbol"] != self.selected_symbol]
        self.selected_symbol = None
        self.save_and_reload()

    def fetch_quotes_async(self) -> None:
        snapshot = [{"symbol": item["symbol"], "market": item["market"]} for item in self.config["stocks"]]

        def worker() -> None:
            results: dict[str, tuple[str, dict | None]] = {}
            for item in snapshot:
                symbol = item["symbol"]
                try:
                    quote = fetch_quote(symbol, item["market"])
                    results[symbol] = ("ok", quote)
                except (urllib.error.URLError, ValueError):
                    results[symbol] = ("error", None)
            self.root.after(0, lambda: self.apply_quote_updates(results))

        threading.Thread(target=worker, daemon=True).start()

    def apply_quote_updates(self, results: dict[str, tuple[str, dict | None]]) -> None:
        self.fetch_inflight = False
        for symbol, result in results.items():
            if symbol not in self.rows:
                continue
            status, payload = result
            stock_item = next((item for item in self.config["stocks"] if item["symbol"] == symbol), None)
            if status == "ok" and payload is not None:
                color = color_for_change(payload["change"])
                configured = stock_item.get("label", symbol) if stock_item else symbol
                if configured and configured != payload["name"]:
                    title_text = f"{configured} / {payload['name']}"
                else:
                    title_text = payload["name"] or configured
                cost_price = stock_item.get("cost_price") if stock_item else None
                lots = int(stock_item.get("lots", 0)) if stock_item else 0
                shares = lots * 100
                if cost_price is not None and lots > 0:
                    profit = (payload["price"] - float(cost_price)) * shares
                    profit_color = color_for_change(profit)
                    self.rows[symbol]["position"].configure(
                        text=f"成本 {float(cost_price):.3f}  持仓 {lots} 手",
                        fg=MUTED,
                    )
                    self.rows[symbol]["profit"].configure(text=f"盈亏 {profit:+.2f}", fg=profit_color)
                else:
                    self.rows[symbol]["position"].configure(text="成本 --  持仓 --", fg=MUTED)
                    self.rows[symbol]["profit"].configure(text="盈亏 --", fg=MUTED)
                self.rows[symbol]["title"].configure(text=title_text)
                self.rows[symbol]["code"].configure(text=symbol)
                self.rows[symbol]["price"].configure(text=f"{payload['price']:.2f}", fg=color)
                self.rows[symbol]["change"].configure(
                    text=f"{payload['change']:+.2f}\n{payload['change_pct']:+.2f}%",
                    fg=color,
                )
            else:
                self.rows[symbol]["price"].configure(text="ERR", fg=MUTED)
                self.rows[symbol]["change"].configure(text="获取失败", fg=MUTED)
                if stock_item and stock_item.get("cost_price") is not None and int(stock_item.get("lots", 0)) > 0:
                    self.rows[symbol]["position"].configure(
                        text=f"成本 {float(stock_item['cost_price']):.3f}  持仓 {int(stock_item['lots'])} 手",
                        fg=MUTED,
                    )
                else:
                    self.rows[symbol]["position"].configure(text="成本 --  持仓 --", fg=MUTED)
                self.rows[symbol]["profit"].configure(text="盈亏 --", fg=MUTED)

    def refresh(self) -> None:
        self.time_label.configure(text=dt.datetime.now().strftime("%H:%M:%S"))
        if not self.fetch_inflight and self.config["stocks"]:
            self.fetch_inflight = True
            self.fetch_quotes_async()
        elif not self.config["stocks"]:
            self.fetch_inflight = False

        self.root.after(self.interval_ms, self.refresh)

    def run(self) -> None:
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="显示右下角股票实时小窗。")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="JSON 配置文件路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    widget = StockWidget(pathlib.Path(args.config))
    widget.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
