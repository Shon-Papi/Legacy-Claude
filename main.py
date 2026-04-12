#!/usr/bin/env python3
"""
Multi-Agent Day Trading Bot
===========================
Uses MACD + EMA indicators with 5 Claude-powered strategy agents:
  1. Trend Following  — EMA crossover + MACD direction
  2. Momentum         — MACD histogram acceleration + RSI
  3. Breakout         — BB squeeze breakout + volume surge
  4. Mean Reversion   — BB extremes + RSI oversold/overbought
  5. VWAP Scalper     — VWAP reclaim/rejection + EMA9

Trades are executed (paper) or notifications sent when
CONFLUENCE_THRESHOLD agents agree on the same direction.

Usage:
  python main.py              # run continuous loop
  python main.py --once       # single scan and exit
  python main.py --symbol AAPL  # scan a specific symbol once
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Agent Day Trading Bot")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit")
    parser.add_argument("--symbol", type=str, help="Scan a single symbol and exit")
    args = parser.parse_args()

    from config import config

    if not config.ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    from core.orchestrator import TradingOrchestrator
    bot = TradingOrchestrator()

    if args.symbol:
        # Single symbol scan
        result = bot.scan_symbol(args.symbol.upper())
        if result:
            print(result.summary)
    elif args.once:
        # One full cycle across all configured symbols
        bot.run_scan_cycle()
        if config.TRADING_MODE == "paper":
            bot.portfolio.print_summary()
    else:
        # Continuous loop
        bot.run_forever()


if __name__ == "__main__":
    main()
