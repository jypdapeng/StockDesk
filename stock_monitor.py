import argparse
import datetime as dt
import pathlib
import subprocess
import sys
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
    ps = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = "{title.replace('"', '`"')}"
$notify.BalloonTipText = "{message.replace('"', '`"').replace(chr(10), ' ')}"
$notify.Visible = $true
$notify.ShowBalloonTip(5000)
Start-Sleep -Seconds 6
$notify.Dispose()
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "-"],
        input=ps,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    error_text = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0, error_text


def toast(title: str, message: str, log_file: pathlib.Path | None) -> None:
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    ok, error_text = show_windows_notification(title, message)
    if not ok:
        log(f"notification failed: {error_text or 'unknown error'}", log_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor one or more A-share quotes and show Windows notifications when price levels are crossed."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to JSON config file")
    parser.add_argument("--interval", type=int, help="override poll interval in seconds")
    parser.add_argument("--once", action="store_true", help="fetch one round of quotes and exit")
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
        return config, last_mtime, state, pathlib.Path(config["log_file"]) if config.get("log_file") else None

    config = load_config(config_path)
    next_log_file = pathlib.Path(config["log_file"]) if config.get("log_file") else None
    next_state = sync_state(state, config)
    if last_mtime is not None:
        log(
            f"config reloaded: symbols={', '.join(item['symbol'] for item in config['stocks'])}",
            next_log_file or log_file,
        )
    return config, mtime, next_state, next_log_file


def check_crossings(state: dict, quote: dict, log_file: pathlib.Path | None) -> None:
    symbol = quote["symbol"]
    price = quote["price"]
    stock_state = state[symbol]
    levels = stock_state["levels"]

    # If the app starts while price is already outside the configured range,
    # notify once instead of waiting for a future crossing.
    if not stock_state.get("initialized"):
        if len(levels) >= 2:
            top_level = max(levels)
            bottom_level = min(levels)
            if price > top_level:
                title = f"{quote['name']} 价格提醒"
                message = (
                    f"{quote['name']}({symbol}) 当前已高于设定区间上限 {top_level:.2f}\n"
                    f"当前价格: {price:.2f}\n时间: {now_text()}"
                )
                log(
                    f"ALERT {quote['name']}({symbol}) above range top={top_level:.2f}, current={price:.2f}",
                    log_file,
                )
                toast(title, message, log_file)
            elif price < bottom_level:
                title = f"{quote['name']} 价格提醒"
                message = (
                    f"{quote['name']}({symbol}) 当前已低于设定区间下限 {bottom_level:.2f}\n"
                    f"当前价格: {price:.2f}\n时间: {now_text()}"
                )
                log(
                    f"ALERT {quote['name']}({symbol}) below range bottom={bottom_level:.2f}, current={price:.2f}",
                    log_file,
                )
                toast(title, message, log_file)
        stock_state["initialized"] = True

    for level in levels:
        previous_side = stock_state["sides"].get(level)
        current_side = side_of(price, level)

        if previous_side is None:
            stock_state["sides"][level] = current_side
            continue

        crossed_up = previous_side in {"below", "equal"} and current_side == "above"
        crossed_down = previous_side in {"above", "equal"} and current_side == "below"

        if crossed_up or crossed_down:
            direction_text = "向上突破" if crossed_up else "向下跌破"
            title = f"{quote['name']} 价格提醒"
            message = (
                f"{quote['name']}({symbol}) 已{direction_text} {level:.2f}\n"
                f"当前价格: {price:.2f}\n时间: {now_text()}"
            )
            log(
                f"ALERT {quote['name']}({symbol}) {direction_text} {level:.2f}, current={price:.2f}",
                log_file,
            )
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
        f"stock monitor started, interval={interval}s, symbols={', '.join(item['symbol'] for item in config['stocks'])}",
        log_file,
    )

    while True:
        if interval_override is None:
            config, last_mtime, state, log_file = maybe_reload_config(config_path, last_mtime, state, log_file)
            interval = config["interval"]

        for item in config["stocks"]:
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
    return run_monitor(pathlib.Path(args.config), interval_override=args.interval, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
