#!/usr/bin/env python3
"""
Futures Trading Bot — trend-filtered Donchian breakout on crypto perpetuals.

The required workflow, in order. Do not skip steps:

  1. Backtest on real data (needs internet, no API key):
       python run_futures.py backtest --days 365

  2. Paper trade on live market data (no API key, simulated fills):
       python run_futures.py paper

  3. Testnet trade (real orders on the exchange TESTNET, fake money):
       FUTURES_API_KEY=... FUTURES_API_SECRET=... python run_futures.py live

  4. Real money — only after 1-3 look good for weeks, and only with money
     you can afford to lose:
       FUTURES_TESTNET=false FUTURES_LIVE_CONFIRM=YES python run_futures.py live

Other commands:
  python run_futures.py backtest --synthetic     # offline mechanics check
  python run_futures.py backtest --csv-dir DIR   # backtest your own CSVs
  python run_futures.py fetch --days 365         # pre-download data cache
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_futures")


def cmd_backtest(args) -> None:
    from futures.backtest import Backtester
    from futures.config import fconfig
    from futures.data import generate_synthetic, get_data, load_csv, _cache_path

    symbols = args.symbols.split(",") if args.symbols else fconfig.SYMBOLS
    data = {}
    for i, sym in enumerate(symbols):
        sym = sym.strip()
        if args.synthetic:
            data[sym] = generate_synthetic(sym, fconfig.TIMEFRAME, args.days, seed=i)
        elif args.csv_dir:
            import os
            path = os.path.join(args.csv_dir, os.path.basename(_cache_path(sym, fconfig.TIMEFRAME)))
            data[sym] = load_csv(path)
        else:
            data[sym] = get_data(sym, fconfig.TIMEFRAME, args.days)

    if args.synthetic:
        print(
            "\nNOTE: --synthetic exercises the bot's mechanics on random data.\n"
            "Expect roughly breakeven-minus-fees. It says NOTHING about real\n"
            "profitability — run against real data for that.\n"
        )

    result = Backtester(data, fconfig).run()
    print(result.summary())

    trades = result.trades_df()
    if not trades.empty:
        out = args.output or "backtest_trades.csv"
        trades.to_csv(out, index=False)
        print(f"  Trade log written to {out}")
        by_reason = trades.groupby("reason")["pnl"].agg(["count", "sum"]).round(2)
        print(f"\n  Exits by reason:\n{by_reason.to_string()}\n")


def cmd_fetch(args) -> None:
    from futures.config import fconfig
    from futures.data import get_data

    for sym in fconfig.SYMBOLS:
        df = get_data(sym, fconfig.TIMEFRAME, args.days, use_cache=False)
        print(f"  {sym}: {len(df)} bars cached")


def cmd_run(mode: str) -> None:
    from futures.engine import TradingEngine

    engine = TradingEngine(mode=mode)
    engine.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_bt = sub.add_parser("backtest", help="Backtest the strategy")
    p_bt.add_argument("--days", type=int, default=365)
    p_bt.add_argument("--symbols", type=str, help="Comma-separated symbol override")
    p_bt.add_argument("--synthetic", action="store_true", help="Offline mechanics check on random data")
    p_bt.add_argument("--csv-dir", type=str, help="Backtest from CSV files in this directory")
    p_bt.add_argument("--output", type=str, help="Trade log CSV path")

    p_fetch = sub.add_parser("fetch", help="Download and cache historical data")
    p_fetch.add_argument("--days", type=int, default=365)

    sub.add_parser("paper", help="Paper trade on live data (no API key needed)")
    sub.add_parser("live", help="Trade on the exchange (testnet unless explicitly confirmed)")

    args = parser.parse_args()
    if args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "fetch":
        cmd_fetch(args)
    elif args.command in ("paper", "live"):
        cmd_run(args.command)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
