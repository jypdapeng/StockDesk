import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import winsound

from stock_common import DEFAULT_CONFIG, fetch_quote, load_config


def now_text() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str, log_file: pathlib.Path | None) -> None:
    line = f"[{now_text()}] {message}"
    print(line)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def show_windows_notification(title: str, message: str) -> tuple[bool, str]:
    pythonw = pathlib.Path(sys.executable).with_name("pythonw.exe")
    temp_dir = pathlib.Path(tempfile.gettempdir()) / "stockdesk_notifications"
    temp_dir.mkdir(parents=True, exist_ok=True)
    popup_code = r"""
import json
import tkinter as tk
from pathlib import Path

payload = json.loads(Path(__PAYLOAD__).read_text(encoding="utf-8"))
TITLE = payload["title"]
MESSAGE = payload["message"]

root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg="#111827")

frame = tk.Frame(root, bg="#111827", highlightthickness=1, highlightbackground="#374151", padx=16, pady=14)
frame.pack(fill="both", expand=True)

header = tk.Frame(frame, bg="#111827")
header.pack(fill="x")
tk.Label(
    header,
    text=TITLE,
    fg="#f9fafb",
    bg="#111827",
    font=("Microsoft YaHei UI", 11, "bold"),
).pack(side="left", anchor="w")
tk.Button(
    header,
    text="关闭",
    command=root.destroy,
    fg="#d1d5db",
    bg="#1f2937",
    activebackground="#374151",
    activeforeground="#ffffff",
    relief="flat",
    bd=0,
    padx=8,
    pady=2,
    font=("Microsoft YaHei UI", 8, "bold"),
).pack(side="right")

tk.Label(
    frame,
    text=MESSAGE,
    fg="#d1d5db",
    bg="#111827",
    justify="left",
    font=("Microsoft YaHei UI", 9),
).pack(anchor="w", pady=(10, 0))

root.update_idletasks()
width = max(360, root.winfo_reqwidth())
height = root.winfo_reqheight()
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
margin_x = 28
margin_y = 56
x = max(0, int(screen_width - width - margin_x))
y = max(0, int(screen_height - height - margin_y))
root.geometry(f"{width}x{height}+{x}+{y}")
root.mainloop()
"""
    stamp = str(int(time.time() * 1000))
    payload_path = temp_dir / f"{stamp}.json"
    popup_path = temp_dir / f"{stamp}.py"
    payload_path.write_text(
        json.dumps({"title": title, "message": message}, ensure_ascii=False),
        encoding="utf-8",
    )
    popup_path.write_text(
        popup_code.replace("__PAYLOAD__", repr(str(payload_path))),
        encoding="utf-8",
    )

    result = subprocess.Popen(
        [str(pythonw), str(popup_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.poll() is None, ""


def toast(title: str, message: str, log_file: pathlib.Path | None) -> None:
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    ok, error_text = show_windows_notification(title, message)
    if not ok:
        log(f"notification failed: {error_text or 'unknown error'}", log_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor A-share quotes and show alert popups when levels are reached."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to JSON config file")
    parser.add_argument("--interval", type=int, help="override poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="fetch one round of quotes and exit")
    parser.add_argument(
        "--test-notification",
        action="store_true",
        help="show a built-in Chinese notification test and exit",
    )
    return parser.parse_args()


def side_of(price: float, level: float) -> str:
    if price > level:
        return "above"
    if price < level:
        return "below"
    return "equal"


def sync_state(state: dict, config: dict) -> dict:
    next_state: dict[str, dict] = {}
    for item in config["stocks"]:
        if str(item.get("status", "")).strip().lower() == "closed":
            continue
        symbol = item["symbol"]
        existing = state.get(symbol, {})
        old_sides = existing.get("sides", {})
        next_state[symbol] = {
            "levels": item["levels"],
            "sides": {level: old_sides.get(level) for level in item["levels"]},
            "market": item["market"],
            "initialized": existing.get("initialized", False),
        }
    return next_state


def maybe_reload_config(
    config_path: pathlib.Path,
    last_mtime: float | None,
    state: dict,
    log_file: pathlib.Path | None,
) -> tuple[dict, float | None, dict, pathlib.Path | None]:
    try:
        mtime = config_path.stat().st_mtime
    except FileNotFoundError:
        return load_config(config_path), last_mtime, state, log_file

    if last_mtime is not None and mtime == last_mtime:
        config = load_config(config_path)
        next_log_file = pathlib.Path(config["log_file"]) if config.get("log_file") else None
        return config, last_mtime, state, next_log_file

    config = load_config(config_path)
    next_log_file = pathlib.Path(config["log_file"]) if config.get("log_file") else None
    next_state = sync_state(state, config)
    if last_mtime is not None:
        log(
            f"config reloaded: symbols={', '.join(item['symbol'] for item in config['stocks'])}",
            next_log_file or log_file,
        )
    return config, mtime, next_state, next_log_file


def maybe_notify_initial_state(quote: dict, levels: list[float], log_file: pathlib.Path | None) -> None:
    price = quote["price"]
    symbol = quote["symbol"]

    exact_levels = [level for level in levels if abs(price - level) < 0.0001]
    if exact_levels:
        for level in exact_levels:
            title = f"{quote['name']} 价格提醒"
            message = (
                f"{quote['name']}({symbol}) 当前已到达提醒位 {level:.2f}\n"
                f"当前价格: {price:.2f}\n时间: {now_text()}"
            )
            log(f"ALERT {quote['name']}({symbol}) reached {level:.2f}, current={price:.2f}", log_file)
            toast(title, message, log_file)
        return

    if len(levels) >= 2:
        top_level = max(levels)
        bottom_level = min(levels)
        if price > top_level:
            title = f"{quote['name']} 价格提醒"
            message = (
                f"{quote['name']}({symbol}) 当前已高于设定区间上沿 {top_level:.2f}\n"
                f"当前价格: {price:.2f}\n时间: {now_text()}"
            )
            log(f"ALERT {quote['name']}({symbol}) above range top={top_level:.2f}, current={price:.2f}", log_file)
            toast(title, message, log_file)
        elif price < bottom_level:
            title = f"{quote['name']} 价格提醒"
            message = (
                f"{quote['name']}({symbol}) 当前已低于设定区间下沿 {bottom_level:.2f}\n"
                f"当前价格: {price:.2f}\n时间: {now_text()}"
            )
            log(
                f"ALERT {quote['name']}({symbol}) below range bottom={bottom_level:.2f}, current={price:.2f}",
                log_file,
            )
            toast(title, message, log_file)


def check_crossings(state: dict, quote: dict, log_file: pathlib.Path | None) -> None:
    symbol = quote["symbol"]
    price = quote["price"]
    stock_state = state[symbol]
    levels = stock_state["levels"]

    if not stock_state.get("initialized"):
        maybe_notify_initial_state(quote, levels, log_file)
        stock_state["initialized"] = True

    for level in levels:
        previous_side = stock_state["sides"].get(level)
        current_side = side_of(price, level)

        if previous_side is None:
            stock_state["sides"][level] = current_side
            continue

        reached_up = previous_side == "below" and current_side in {"equal", "above"}
        reached_down = previous_side == "above" and current_side in {"equal", "below"}

        if reached_up or reached_down:
            direction_text = "向上到达/突破" if reached_up else "向下到达/跌破"
            title = f"{quote['name']} 价格提醒"
            message = (
                f"{quote['name']}({symbol}) 已{direction_text} {level:.2f}\n"
                f"当前价格: {price:.2f}\n时间: {now_text()}"
            )
            log(f"ALERT {quote['name']}({symbol}) {direction_text} {level:.2f}, current={price:.2f}", log_file)
            toast(title, message, log_file)

        stock_state["sides"][level] = current_side


def run_monitor(config_path: pathlib.Path, interval_override: int | None = None, once: bool = False) -> int:
    try:
        config = load_config(pathlib.Path(config_path))
    except Exception as exc:
        print(f"failed to load config: {exc}", file=sys.stderr)
        return 1

    config_path = pathlib.Path(config_path)
    last_mtime = config_path.stat().st_mtime if config_path.exists() else None
    interval = interval_override or config["interval"]
    log_file = pathlib.Path(config["log_file"]) if config.get("log_file") else None
    state = sync_state({}, config)

    log(
        f"stock monitor started, interval={interval}s, symbols={', '.join(item['symbol'] for item in config['stocks'] if str(item.get('status', '')).strip().lower() != 'closed')}",
        log_file,
    )

    while True:
        if interval_override is None:
            config, last_mtime, state, log_file = maybe_reload_config(config_path, last_mtime, state, log_file)
            interval = config["interval"]

        for item in config["stocks"]:
            if str(item.get("status", "")).strip().lower() == "closed":
                continue
            try:
                quote = fetch_quote(item["symbol"], item["market"])
                log(
                    f"{quote['name']}({quote['market']}{quote['symbol']}) current={quote['price']:.2f} prev_close={quote['prev_close']:.2f}",
                    log_file if once else None,
                )
                check_crossings(state, quote, log_file)
            except (urllib.error.URLError, ValueError) as exc:
                log(f"fetch failed for {item['symbol']}: {exc}", log_file)

        if once:
            return 0

        time.sleep(interval)


def main() -> int:
    args = parse_args()
    if args.test_notification:
        ok, error_text = show_windows_notification(
            "股票盯盘测试提醒",
            "这是一条程序内置的中文测试提醒。\n现在的提醒窗不会自动关闭，必须手动点击“关闭”。",
        )
        print(f"ok={ok}")
        if error_text:
            print(error_text)
        return 0 if ok else 1
    return run_monitor(pathlib.Path(args.config), interval_override=args.interval, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
