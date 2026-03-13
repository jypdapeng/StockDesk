import argparse
import pathlib
import threading

from stock_common import DEFAULT_CONFIG
from stock_monitor import run_monitor
from stock_widget import StockWidget


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the stock monitor widget and alert service together.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to JSON config file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = pathlib.Path(args.config)

    worker = threading.Thread(target=run_monitor, args=(config_path,), kwargs={"once": False}, daemon=True)
    worker.start()

    widget = StockWidget(config_path)
    widget.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
