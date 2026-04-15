import json
import pathlib
import threading
import tkinter as tk

from ai_provider import chat_with_stock_context
from analysis_engine import analyze_stock
from stock_common import USER_DATA_DIR


BG = "#0f172a"
PANEL = "#111827"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
USER_BUBBLE = "#2563eb"
AI_BUBBLE = "#1f2937"
BUTTON = "#2563eb"
BORDER = "#334155"
CHAT_HISTORY_PATH = USER_DATA_DIR / "ai_chat_history.json"
LEGACY_CHAT_HISTORY_PATH = pathlib.Path(__file__).resolve().parent / "ai_chat_history.json"


def _load_history_map() -> dict:
    if not CHAT_HISTORY_PATH.exists() and LEGACY_CHAT_HISTORY_PATH.exists():
        try:
            CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            CHAT_HISTORY_PATH.write_text(LEGACY_CHAT_HISTORY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    if not CHAT_HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(CHAT_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_history_map(data: dict) -> None:
    CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAT_HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def open_ai_chat_panel(parent: tk.Tk, stock_item: dict, on_mouse_enter=None, center_dialog=None) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("AI 对话")
    dialog.configure(bg=BG)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)

    symbol = stock_item["symbol"]
    history_map = _load_history_map()
    history: list[dict] = history_map.get(symbol, [])
    state = {"analysis": None}

    container = tk.Frame(dialog, bg=BG, padx=14, pady=14)
    container.pack(fill="both", expand=True)

    title = stock_item.get("label") or stock_item.get("name") or symbol
    tk.Label(
        container,
        text=f"{title} · AI 对话",
        fg=TEXT,
        bg=BG,
        font=("Microsoft YaHei UI", 12, "bold"),
    ).pack(anchor="w")
    tk.Label(
        container,
        text="围绕当前股票继续追问，例如：支撑位怎么看、明天观察什么、减仓节奏怎么定。",
        fg=MUTED,
        bg=BG,
        font=("Microsoft YaHei UI", 9),
    ).pack(anchor="w", pady=(2, 10))

    chat_outer = tk.Frame(container, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
    chat_outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(chat_outer, bg=PANEL, highlightthickness=0, bd=0)
    scrollbar = tk.Scrollbar(chat_outer, orient="vertical", command=canvas.yview)
    messages_frame = tk.Frame(canvas, bg=PANEL)
    messages_frame.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    frame_window = canvas.create_window((0, 0), window=messages_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    def sync_width(_event=None) -> None:
        width = max(220, canvas.winfo_width() - 6)
        canvas.itemconfigure(frame_window, width=width)
        for outer in messages_frame.winfo_children():
            for child in outer.winfo_children():
                if isinstance(child, tk.Label) and getattr(child, "_is_bubble", False):
                    child.configure(wraplength=max(180, width - 90))

    def on_mousewheel(event):
        if event.delta:
            canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def on_linux_scroll_up(_event):
        canvas.yview_scroll(-1, "units")
        return "break"

    def on_linux_scroll_down(_event):
        canvas.yview_scroll(1, "units")
        return "break"

    canvas.bind("<Configure>", sync_width, add="+")
    canvas.bind("<MouseWheel>", on_mousewheel, add="+")
    canvas.bind("<Button-4>", on_linux_scroll_up, add="+")
    canvas.bind("<Button-5>", on_linux_scroll_down, add="+")
    messages_frame.bind("<MouseWheel>", on_mousewheel, add="+")
    messages_frame.bind("<Button-4>", on_linux_scroll_up, add="+")
    messages_frame.bind("<Button-5>", on_linux_scroll_down, add="+")

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    input_bar = tk.Frame(container, bg=BG)
    input_bar.pack(fill="x", pady=(10, 0))
    input_text = tk.Text(
        input_bar,
        height=4,
        bg=PANEL,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        font=("Microsoft YaHei UI", 9),
    )
    input_text.pack(side="left", fill="both", expand=True)

    footer = tk.Frame(container, bg=BG)
    footer.pack(fill="x", pady=(10, 0))
    status_label = tk.Label(
        footer,
        text="会在发送前刷新最新行情。",
        fg=MUTED,
        bg=BG,
        font=("Microsoft YaHei UI", 8),
    )
    status_label.pack(side="left")

    def persist_history() -> None:
        history_map[symbol] = history[-40:]
        _save_history_map(history_map)

    def scroll_to_bottom() -> None:
        canvas.update_idletasks()
        canvas.yview_moveto(1.0)

    def append_bubble(role: str, content: str) -> None:
        outer = tk.Frame(messages_frame, bg=PANEL)
        outer.pack(fill="x", padx=10, pady=6)

        align = "e" if role == "user" else "w"
        bubble_bg = USER_BUBBLE if role == "user" else AI_BUBBLE
        title_text = "你" if role == "user" else "AI"

        header = tk.Label(outer, text=title_text, fg=MUTED, bg=PANEL, font=("Microsoft YaHei UI", 8, "bold"))
        header.pack(anchor=align, padx=4, pady=(0, 2))

        bubble = tk.Label(
            outer,
            text=content,
            justify="left",
            wraplength=max(180, canvas.winfo_width() - 90),
            anchor="w",
            padx=12,
            pady=10,
            fg=TEXT,
            bg=bubble_bg,
            font=("Microsoft YaHei UI", 9),
        )
        bubble._is_bubble = True
        bubble.pack(anchor=align)
        scroll_to_bottom()

    if history:
        for item in history:
            append_bubble(item.get("role", "assistant"), item.get("content", ""))
    else:
        append_bubble("assistant", "AI 已准备好，你可以开始提问。")

    def send_message() -> None:
        message = input_text.get("1.0", "end").strip()
        if not message:
            return
        input_text.delete("1.0", "end")
        append_bubble("user", message)
        history.append({"role": "user", "content": message})
        persist_history()
        status_label.configure(text="正在刷新最新行情和分析...", fg=MUTED)

        waiting_holder = {"shown": False}

        def show_waiting() -> None:
            if waiting_holder["shown"]:
                return
            waiting_holder["shown"] = True
            append_bubble("assistant", "正在刷新最新行情并思考中...")

        parent.after(400, show_waiting)

        def worker() -> None:
            try:
                latest_analysis = analyze_stock(stock_item)
                state["analysis"] = latest_analysis
                result = chat_with_stock_context(stock_item, latest_analysis, history, message)
                answer = result["content"]
            except Exception as exc:
                answer = f"AI 对话暂时不可用：{exc}"

            def render_answer() -> None:
                if waiting_holder["shown"]:
                    children = messages_frame.winfo_children()
                    if children:
                        children[-1].destroy()
                append_bubble("assistant", answer)
                history.append({"role": "assistant", "content": answer})
                persist_history()

                latest_time = ""
                if isinstance(state.get("analysis"), dict):
                    latest_time = str(state["analysis"].get("quote", {}).get("time", "")).strip()
                if latest_time:
                    status_label.configure(text=f"已按最新行情回答（{latest_time}）。", fg=MUTED)
                else:
                    status_label.configure(text="已按最新行情回答。", fg=MUTED)

            parent.after(0, render_answer)

        threading.Thread(target=worker, daemon=True).start()

    send_button = tk.Button(
        input_bar,
        text="发送",
        command=send_message,
        bg=BUTTON,
        fg=TEXT,
        activebackground=BUTTON,
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        padx=12,
    )
    send_button.pack(side="left", padx=(8, 0), fill="y")

    def close_dialog() -> None:
        dialog.destroy()

    tk.Button(footer, text="关闭", command=close_dialog).pack(side="right")

    input_text.bind("<Control-Return>", lambda _e: (send_message(), "break"))
    input_text.bind("<Return>", lambda _e: (send_message(), "break"))

    if center_dialog:
        center_dialog(dialog)
    if on_mouse_enter:
        dialog.bind("<Enter>", on_mouse_enter, add="+")
