import datetime as dt
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.parse
import urllib.request

from ai_provider import extract_holdings_from_images, extract_watchlist_from_images
from stock_common import infer_market


BG = "#0f172a"
PANEL = "#111827"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
SINA_SUGGEST_URL = "https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key={keyword}"


def _normalize_symbol(symbol: str) -> str:
    value = "".join(ch for ch in str(symbol or "") if ch.isdigit())
    return value[:6]


def _find_existing_by_name(config: dict, name: str) -> dict | None:
    target = str(name or "").strip()
    if not target:
        return None
    for item in config.get("stocks", []):
        label = str(item.get("label", "")).strip()
        symbol = str(item.get("symbol", "")).strip()
        if target == label or target == symbol:
            return item
    return None


def _lookup_symbol_by_name(name: str) -> tuple[str, str] | None:
    keyword = str(name or "").strip()
    if not keyword:
        return None
    url = SINA_SUGGEST_URL.format(keyword=urllib.parse.quote(keyword))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read().decode("gbk", errors="replace")
    if '"' not in content:
        return None
    payload = content.split('"', 1)[1].rsplit('"', 1)[0].strip()
    if not payload:
        return None
    for raw_item in payload.split(";"):
        parts = raw_item.split(",")
        if len(parts) < 4:
            continue
        stock_name = parts[0].strip()
        stock_code = _normalize_symbol(parts[2])
        market_code = parts[3].strip().lower()
        if not stock_code:
            continue
        if stock_name == keyword or keyword in stock_name:
            market = market_code[:2] if market_code.startswith(("sh", "sz")) else infer_market(stock_code)
            return stock_code, market
    return None


def _resolve_symbol_and_market(config: dict, symbol: str, name: str) -> tuple[str, str | None, bool]:
    normalized = _normalize_symbol(symbol)
    if normalized:
        return normalized, infer_market(normalized), False
    existing = _find_existing_by_name(config, name)
    if existing and str(existing.get("symbol", "")).isdigit():
        return existing["symbol"], existing.get("market") or infer_market(existing["symbol"]), False
    lookup = _lookup_symbol_by_name(name)
    if lookup:
        return lookup[0], lookup[1], True
    return "", None, False


def _find_or_create_stock(config: dict, symbol: str, name: str) -> tuple[dict, bool]:
    existing = None
    if symbol:
        for item in config.get("stocks", []):
            if item.get("symbol") == symbol:
                existing = item
                break
    if not existing and name:
        existing = _find_existing_by_name(config, name)

    if existing:
        if name and (not existing.get("label") or existing.get("label") == existing.get("symbol")):
            existing["label"] = name
        if symbol and not str(existing.get("symbol", "")).isdigit():
            existing["symbol"] = symbol
            existing["market"] = infer_market(symbol)
        return existing, False

    item = {
        "symbol": symbol or name,
        "market": infer_market(symbol) if symbol else "sz",
        "label": name or symbol,
        "cost_price": None,
        "lots": 0,
        "levels": [],
        "status": "favorite",
        "trades": [],
    }
    config.setdefault("stocks", []).append(item)
    return item, True


def open_image_import_dialog(parent, config: dict, on_import_complete, center_dialog=None, on_mouse_enter=None) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("图片导入")
    dialog.configure(bg=PANEL)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)
    dialog.grab_set()

    mode_var = tk.StringVar(value="holdings")
    selected_files: list[str] = []

    tk.Label(dialog, text="图片导入", fg=TEXT, bg=PANEL, font=("Microsoft YaHei UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 4))
    tk.Label(
        dialog,
        text="支持持仓截图和自选截图。没有代码时会先用现有数据匹配，再按股票名称动态补代码。成交记录导入暂时隐藏，避免长图识别不稳定。",
        fg=MUTED,
        bg=PANEL,
        wraplength=520,
        justify="left",
        font=("Microsoft YaHei UI", 9),
    ).grid(row=1, column=0, columnspan=3, sticky="w", padx=14)

    mode_bar = tk.Frame(dialog, bg=PANEL)
    mode_bar.grid(row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 6))
    tk.Radiobutton(mode_bar, text="导入持仓", value="holdings", variable=mode_var, bg=PANEL, fg=TEXT, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).pack(side="left", padx=(0, 12))
    tk.Radiobutton(mode_bar, text="导入自选", value="favorites", variable=mode_var, bg=PANEL, fg=TEXT, selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).pack(side="left")

    file_text = tk.Text(dialog, height=8, width=70, bg=BG, fg=TEXT, relief="flat", bd=0, font=("Consolas", 9))
    file_text.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=14, pady=(4, 0))
    file_text.insert("1.0", "尚未选择图片。")
    file_text.configure(state="disabled")

    status_var = tk.StringVar(value="请选择截图后再导入。")
    tk.Label(dialog, textvariable=status_var, fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8)).grid(row=4, column=0, columnspan=3, sticky="w", padx=14, pady=(8, 0))

    def refresh_file_text():
        file_text.configure(state="normal")
        file_text.delete("1.0", "end")
        if not selected_files:
            file_text.insert("1.0", "尚未选择图片。")
        else:
            for path in selected_files:
                file_text.insert("end", f"{path}\n")
        file_text.configure(state="disabled")

    def choose_files():
        nonlocal selected_files
        files = filedialog.askopenfilenames(
            parent=dialog,
            title="选择截图文件",
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("All Files", "*.*")],
        )
        if files:
            selected_files = list(files)
            status_var.set(f"已选择 {len(selected_files)} 张图片。")
            refresh_file_text()

    def merge_holdings(result: dict) -> tuple[int, list[str]]:
        imported = 0
        unresolved: list[str] = list(result.get("notes", []))
        for row in result.get("holdings", []):
            name = str(row.get("name", "")).strip()
            symbol, market, matched_by_name = _resolve_symbol_and_market(config, row.get("symbol", ""), name)
            if not symbol and not name:
                continue
            stock, _ = _find_or_create_stock(config, symbol, name)
            if symbol:
                stock["symbol"] = symbol
                stock["market"] = market or infer_market(symbol)
            if name:
                stock["label"] = name
            lots = int(float(row.get("lots") or 0))
            if not lots:
                shares = int(float(row.get("shares") or 0))
                lots = shares // 100 if shares > 0 else 0
            stock["lots"] = lots
            cost = float(row.get("cost_price") or 0)
            if cost > 0:
                stock["cost_price"] = round(cost, 3)
            stock["status"] = "holding" if lots > 0 else stock.get("status", "favorite")
            stock["last_import_source"] = "image-holdings"
            stock["last_import_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            imported += 1
            if not symbol:
                unresolved.append(f"未识别代码：{name}")
            elif matched_by_name:
                unresolved.append(f"已按名称匹配代码：{name} -> {symbol}")
        return imported, unresolved

    def merge_favorites(result: dict) -> tuple[int, list[str]]:
        imported = 0
        unresolved: list[str] = list(result.get("notes", []))
        for row in result.get("favorites", []):
            name = str(row.get("name", "")).strip()
            symbol, market, matched_by_name = _resolve_symbol_and_market(config, row.get("symbol", ""), name)
            if not symbol and not name:
                continue
            stock, created = _find_or_create_stock(config, symbol, name)
            if symbol:
                stock["symbol"] = symbol
                stock["market"] = market or infer_market(symbol)
            if name:
                stock["label"] = name
            if int(stock.get("lots", 0) or 0) <= 0:
                stock["status"] = "favorite"
            stock["import_source"] = "image"
            stock["imported_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            imported += 1 if created or stock.get("status") == "favorite" else 0
            if not symbol:
                unresolved.append(f"未识别代码：{name}")
            elif matched_by_name:
                unresolved.append(f"已按名称匹配代码：{name} -> {symbol}")
        return imported, unresolved

    def run_import():
        if not selected_files:
            messagebox.showinfo("图片导入", "请先选择截图。")
            return
        status_var.set("正在识别图片，请稍候...")
        import_button.configure(state="disabled")
        choose_button.configure(state="disabled")

        def worker():
            try:
                if mode_var.get() == "holdings":
                    result = extract_holdings_from_images(selected_files)
                    imported, unresolved = merge_holdings(result)
                    summary = f"已导入/更新 {imported} 条持仓。"
                else:
                    result = extract_watchlist_from_images(selected_files)
                    imported, unresolved = merge_favorites(result)
                    summary = f"已导入/更新 {imported} 条自选。"

                def finish_success():
                    on_import_complete()
                    dialog.destroy()
                    extra = ""
                    if unresolved:
                        deduped = []
                        for item in unresolved:
                            if item not in deduped:
                                deduped.append(item)
                        extra = "\n\n待确认：\n- " + "\n- ".join(deduped[:10])
                    messagebox.showinfo("图片导入", summary + extra)

                parent.after(0, finish_success)
            except Exception as exc:
                parent.after(0, lambda: messagebox.showerror("图片导入", f"导入失败：{exc}"))
                parent.after(0, lambda: status_var.set("导入失败，请检查截图清晰度或 AI 配置。"))
                parent.after(0, lambda: import_button.configure(state="normal"))
                parent.after(0, lambda: choose_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    button_bar = tk.Frame(dialog, bg=PANEL)
    button_bar.grid(row=5, column=0, columnspan=3, sticky="e", padx=14, pady=14)
    choose_button = tk.Button(button_bar, text="选择图片", command=choose_files)
    choose_button.pack(side="left", padx=(0, 8))
    import_button = tk.Button(button_bar, text="开始导入", command=run_import)
    import_button.pack(side="left", padx=(0, 8))
    tk.Button(button_bar, text="关闭", command=dialog.destroy).pack(side="left")

    dialog.grid_columnconfigure(0, weight=1)
    dialog.grid_columnconfigure(1, weight=1)
    dialog.grid_columnconfigure(2, weight=1)
    dialog.grid_rowconfigure(3, weight=1)

    if center_dialog:
        center_dialog(dialog)
    if on_mouse_enter:
        dialog.bind("<Enter>", on_mouse_enter, add="+")
