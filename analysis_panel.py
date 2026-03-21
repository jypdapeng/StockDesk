import threading
import tkinter as tk
from tkinter import scrolledtext

from ai_provider import get_ai_explanation
from analysis_engine import analyze_stock


BG = "#0f172a"
PANEL = "#111827"
CARD = "#1f2937"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
UP = "#ef4444"
DOWN = "#22c55e"
AMBER = "#f59e0b"
BORDER = "#334155"


def _color_for_score(score: int) -> str:
    if score >= 70:
        return DOWN
    if score >= 45:
        return AMBER
    return UP


def _lines(items: list[str]) -> str:
    return "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, start=1)) if items else "暂无。"


def open_analysis_panel(parent: tk.Tk, stock_item: dict, on_mouse_enter=None, center_dialog=None) -> None:
    dialog = tk.Toplevel(parent)
    dialog.title("AI 分析面板")
    dialog.configure(bg=BG)
    dialog.attributes("-topmost", True)
    dialog.transient(parent)

    container = tk.Frame(dialog, bg=BG, padx=14, pady=14)
    container.pack(fill="both", expand=True)

    display_name = stock_item.get("label") or stock_item.get("symbol", "")
    title = tk.Label(
        container,
        text=f"{display_name} · AI 分析面板",
        fg=TEXT,
        bg=BG,
        font=("Microsoft YaHei UI", 12, "bold"),
    )
    title.pack(anchor="w")

    subtitle = tk.Label(
        container,
        text="规则分析 + AI 解释",
        fg=MUTED,
        bg=BG,
        font=("Microsoft YaHei UI", 9),
    )
    subtitle.pack(anchor="w", pady=(2, 10))

    cards = tk.Frame(container, bg=BG)
    cards.pack(fill="x")

    score_card = tk.Frame(cards, bg=CARD, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER)
    score_card.pack(side="left", fill="both", expand=True, padx=(0, 8))
    plan_card = tk.Frame(cards, bg=CARD, padx=12, pady=10, highlightthickness=1, highlightbackground=BORDER)
    plan_card.pack(side="left", fill="both", expand=True, padx=(8, 0))

    score_title = tk.Label(score_card, text="量价评分", fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9))
    score_title.pack(anchor="w")
    score_value = tk.Label(score_card, text="--", fg=TEXT, bg=CARD, font=("Consolas", 22, "bold"))
    score_value.pack(anchor="w", pady=(6, 0))
    score_desc = tk.Label(score_card, text="分析中...", fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9))
    score_desc.pack(anchor="w", pady=(4, 0))

    plan_title = tk.Label(plan_card, text="次日预案", fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9))
    plan_title.pack(anchor="w")
    plan_value = tk.Label(plan_card, text="--", fg=TEXT, bg=CARD, font=("Microsoft YaHei UI", 16, "bold"))
    plan_value.pack(anchor="w", pady=(6, 0))
    plan_desc = tk.Label(plan_card, text="分析中...", fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9), justify="left", anchor="w")
    plan_desc.pack(anchor="w", pady=(4, 0))

    body = tk.Frame(container, bg=BG)
    body.pack(fill="both", expand=True, pady=(12, 0))

    left = tk.Frame(body, bg=BG)
    left.pack(side="left", fill="both", expand=True, padx=(0, 6))
    right = tk.Frame(body, bg=BG)
    right.pack(side="left", fill="both", expand=True, padx=(6, 0))

    rule_box = scrolledtext.ScrolledText(
        left,
        wrap="word",
        width=46,
        height=20,
        bg=PANEL,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        font=("Microsoft YaHei UI", 9),
    )
    rule_box.pack(fill="both", expand=True)

    ai_box = scrolledtext.ScrolledText(
        right,
        wrap="word",
        width=46,
        height=20,
        bg=PANEL,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        font=("Microsoft YaHei UI", 9),
    )
    ai_box.pack(fill="both", expand=True)

    rule_box.insert("1.0", "正在生成规则分析...")
    ai_box.insert("1.0", "正在调用 AI 解释...")
    rule_box.configure(state="disabled")
    ai_box.configure(state="disabled")

    footer = tk.Frame(container, bg=BG)
    footer.pack(fill="x", pady=(10, 0))
    tk.Button(footer, text="关闭", command=dialog.destroy).pack(side="right")

    if center_dialog:
        center_dialog(dialog)
    if on_mouse_enter:
        dialog.bind("<Enter>", on_mouse_enter, add="+")

    def worker() -> None:
        try:
            analysis = analyze_stock(stock_item)
            ai = get_ai_explanation(stock_item, analysis)
        except Exception as exc:
            analysis = None
            ai = {"enabled": False, "provider": None, "content": f"分析失败：{exc}"}
        parent.after(0, lambda: _apply(dialog, analysis, ai))

    def _apply(dialog_ref: tk.Toplevel, analysis: dict | None, ai_result: dict) -> None:
        if not dialog_ref.winfo_exists():
            return
        rule_box.configure(state="normal")
        ai_box.configure(state="normal")
        rule_box.delete("1.0", "end")
        ai_box.delete("1.0", "end")

        if analysis is None:
            score_value.configure(text="--", fg=TEXT)
            score_desc.configure(text="规则分析失败")
            plan_value.configure(text="--", fg=TEXT)
            plan_desc.configure(text="规则分析失败")
            rule_box.insert("1.0", "规则分析失败。")
            ai_box.insert("1.0", ai_result["content"])
        else:
            score = analysis["score"]
            next_day_plan = analysis.get("next_day_plan", []) or []
            score_value.configure(text=f"{score['score']}", fg=_color_for_score(score["score"]))
            score_desc.configure(text=f"风险级别：{score['risk']}")

            plan_status = "等待确认" if not next_day_plan else "重点观察"
            plan_lines = next_day_plan if next_day_plan else ["等待更多分时和关键位信息。"]
            plan_value.configure(text=plan_status, fg=TEXT)
            plan_desc.configure(text="\n".join(plan_lines[:2]))

            rule_text = (
                "最新事实\n"
                f"{_lines(analysis['facts'])}\n\n"
                "方法观察\n"
                f"{_lines(analysis['observations'])}\n\n"
                "风险提示\n"
                f"{_lines(analysis['risks'])}\n\n"
                "保守建议\n"
                f"{_lines(analysis['suggestions'])}"
            )
            rule_box.insert("1.0", rule_text)

            provider_label = ai_result.get("provider") or "规则模式"
            ai_text = f"提供方：{provider_label}\n\n{ai_result.get('content', '暂无 AI 解读。')}"
            ai_box.insert("1.0", ai_text)

        rule_box.configure(state="disabled")
        ai_box.configure(state="disabled")

    threading.Thread(target=worker, daemon=True).start()
