import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import config
from data.fetcher import fetch_ohlcv, fetch_current_price
from indicators.calculator import compute_all, get_snapshot
from agents.trend_following import TrendFollowingAgent
from agents.momentum import MomentumAgent
from agents.breakout import BreakoutAgent
from agents.mean_reversion import MeanReversionAgent
from agents.vwap_scalper import VWAPScalperAgent
from agents.base_agent import AgentSignal, Signal
from core.confluence import detect_confluence, ConfluenceResult
from core.notifier import send_notification
from paper_trading.portfolio import PaperPortfolio

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """
    Central coordinator for the multi-agent trading bot.

    Workflow per scan cycle:
    1. Fetch market data for each symbol
    2. Compute all technical indicators
    3. Run all 5 strategy agents in parallel
    4. Aggregate signals via confluence detection
    5. Execute paper trade or send notification if threshold met
    """

    def __init__(self) -> None:
        self.agents = [
            TrendFollowingAgent(),
            MomentumAgent(),
            BreakoutAgent(),
            MeanReversionAgent(),
            VWAPScalperAgent(),
        ]
        self.portfolio = PaperPortfolio()
        self._scan_count = 0

        logger.info(f"Initialized TradingOrchestrator with {len(self.agents)} agents")
        logger.info(f"Watching {len(config.WATCH_SYMBOLS)} symbols: {', '.join(config.WATCH_SYMBOLS)}")
        logger.info(f"Confluence threshold: {config.CONFLUENCE_THRESHOLD}/{len(self.agents)} agents")
        logger.info(f"Trading mode: {config.TRADING_MODE.upper()}")

    def scan_symbol(self, symbol: str) -> ConfluenceResult | None:
        """Run a full analysis cycle for one symbol."""
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning {symbol}...")

            # 1. Fetch and compute indicators
            df = fetch_ohlcv(symbol)
            df = compute_all(df)
            snapshot = get_snapshot(df)
            print(f"  Price: ${snapshot['price']} | RSI: {snapshot['rsi']:.1f} | "
                  f"MACD Hist: {snapshot['macd_hist']:.4f} | RelVol: {snapshot['rel_volume']:.1f}x")

            # 2. Run agents in parallel
            signals = self._run_agents_parallel(symbol, snapshot)

            # 3. Detect confluence
            result = detect_confluence(symbol, signals)
            print(f"  Votes → BUY:{result.vote_breakdown['BUY']} "
                  f"SELL:{result.vote_breakdown['SELL']} "
                  f"HOLD:{result.vote_breakdown['HOLD']} | "
                  f"Score:{result.confluence_score:.0%} | "
                  f"Threshold:{'✓' if result.threshold_met else '✗'}")

            # 4. Act on confluence
            if result.threshold_met and result.final_signal != Signal.HOLD:
                self._handle_signal(result, snapshot)

            return result

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
            return None

    def _run_agents_parallel(self, symbol: str, snapshot: dict) -> list[AgentSignal]:
        """Run all agents concurrently and collect signals."""
        signals: list[AgentSignal] = []

        with ThreadPoolExecutor(max_workers=len(self.agents)) as executor:
            futures = {executor.submit(agent.analyze, symbol, snapshot): agent for agent in self.agents}
            for future in as_completed(futures):
                agent = futures[future]
                try:
                    signal = future.result(timeout=30)
                    signals.append(signal)
                    print(f"  [{signal.strategy_name[:25]:<25}] → {signal.signal.value} ({signal.confidence:.0%})")
                except Exception as e:
                    logger.warning(f"Agent {agent.__class__.__name__} failed for {symbol}: {e}")

        return signals

    def _handle_signal(self, result: ConfluenceResult, snapshot: dict) -> None:
        """Handle a confirmed confluence signal: trade and/or notify."""
        send_notification(result)

        if config.TRADING_MODE == "paper":
            best = result.top_signals[0] if result.top_signals else None
            self.portfolio.execute_signal(
                symbol=result.symbol,
                signal=result.final_signal,
                price=snapshot["price"],
                stop_loss=best.stop_loss if best else None,
                take_profit=best.take_profit if best else None,
                strategy=result.top_signals[0].strategy_name if result.top_signals else "",
                reason=result.summary[:200],
            )

    def run_scan_cycle(self) -> list[ConfluenceResult]:
        """Run a full scan of all symbols."""
        self._scan_count += 1
        print(f"\n{'#'*60}")
        print(f"SCAN CYCLE #{self._scan_count} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#'*60}")

        results = []
        for symbol in config.WATCH_SYMBOLS:
            result = self.scan_symbol(symbol)
            if result:
                results.append(result)
                # Check exits for paper positions
                if config.TRADING_MODE == "paper" and symbol in self.portfolio.positions:
                    try:
                        current = fetch_current_price(symbol)
                        self.portfolio.check_exits(symbol, current)
                    except Exception as e:
                        logger.warning(f"Could not check exits for {symbol}: {e}")

        # Print portfolio summary every 5 cycles
        if config.TRADING_MODE == "paper" and self._scan_count % 5 == 0:
            self.portfolio.print_summary()

        return results

    def run_forever(self) -> None:
        """Main loop: scan all symbols on a fixed interval."""
        print(f"\n{'='*60}")
        print("MULTI-AGENT TRADING BOT STARTED")
        print(f"{'='*60}")
        print(f"Symbols:   {', '.join(config.WATCH_SYMBOLS)}")
        print(f"Agents:    {', '.join(a.__class__.__name__ for a in self.agents)}")
        print(f"Mode:      {config.TRADING_MODE.upper()}")
        print(f"Interval:  {config.SCAN_INTERVAL}s")
        print(f"Threshold: {config.CONFLUENCE_THRESHOLD}/{len(self.agents)} agents")
        print(f"{'='*60}\n")

        while True:
            try:
                self.run_scan_cycle()
                print(f"\nNext scan in {config.SCAN_INTERVAL}s... (Ctrl+C to stop)")
                time.sleep(config.SCAN_INTERVAL)
            except KeyboardInterrupt:
                print("\n\nBot stopped by user.")
                if config.TRADING_MODE == "paper":
                    self.portfolio.print_summary()
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(30)
