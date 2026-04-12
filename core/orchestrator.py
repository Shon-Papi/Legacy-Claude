import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from config import config
from data.fetcher import fetch_ohlcv, fetch_current_price
from indicators.calculator import compute_all, get_snapshot
from agents.trend_following import TrendFollowingAgent
from agents.momentum import MomentumAgent
from agents.breakout import BreakoutAgent
from agents.mean_reversion import MeanReversionAgent
from agents.vwap_scalper import VWAPScalperAgent
from agents.news_bias import run_news_bias_check
from agents.event_guard import run_event_guard_check
from agents.base_agent import AgentSignal, Signal
from core.confluence import detect_confluence, ConfluenceResult
from core.notifier import send_notification
from core.trading_state import trading_state
from paper_trading.portfolio import PaperPortfolio

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """
    Central coordinator for the multi-agent trading bot.

    Scan cycle:
    1. EventGuardAgent checks for high-impact events → may halt trading
    2. If trading is halted, skip all strategy work
    3. NewsBiasAgent refreshes daily directional bias (every N minutes)
    4. For each symbol: fetch data → compute indicators → run 5 strategy
       agents in parallel → detect confluence
    5. Bias filter: if strong directional bias, suppress signals that go
       against it (e.g. don't BUY into a HIGH-confidence BEARISH day)
    6. If confluence threshold met and signal passes bias filter → execute
       paper trade and/or send notification

    Between main scan cycles the orchestrator also runs a lightweight
    event guard check every EVENT_GUARD_INTERVAL seconds so the bot can
    react to breaking news faster than the full scan interval.
    """

    def __init__(self) -> None:
        self.strategy_agents = [
            TrendFollowingAgent(),
            MomentumAgent(),
            BreakoutAgent(),
            MeanReversionAgent(),
            VWAPScalperAgent(),
        ]
        self.portfolio = PaperPortfolio()
        self._scan_count = 0
        self._last_guard_check: datetime = datetime.min
        self._last_bias_check: datetime = datetime.min

        logger.info(f"Initialized TradingOrchestrator with {len(self.strategy_agents)} strategy agents")
        logger.info(f"Watching {len(config.WATCH_SYMBOLS)} symbols: {', '.join(config.WATCH_SYMBOLS)}")
        logger.info(f"Confluence threshold: {config.CONFLUENCE_THRESHOLD}/{len(self.strategy_agents)} agents")
        logger.info(f"Trading mode: {config.TRADING_MODE.upper()}")

    # ------------------------------------------------------------------
    # News / guard scheduling
    # ------------------------------------------------------------------

    def _maybe_run_event_guard(self) -> bool:
        """
        Run event guard if its interval has elapsed.
        Returns True if trading is safe to continue, False if halted.
        """
        if trading_state.is_halted:
            return False

        now = datetime.now()
        elapsed = (now - self._last_guard_check).total_seconds()
        if elapsed >= config.EVENT_GUARD_INTERVAL:
            safe = run_event_guard_check()
            self._last_guard_check = now
            return safe

        return not trading_state.is_halted

    def _maybe_refresh_bias(self) -> None:
        """Run bias refresh if the interval has elapsed or it's never run."""
        now = datetime.now()
        elapsed_minutes = (now - self._last_bias_check).total_seconds() / 60
        if elapsed_minutes >= config.NEWS_BIAS_INTERVAL:
            run_news_bias_check()
            self._last_bias_check = now

    # ------------------------------------------------------------------
    # Bias filtering
    # ------------------------------------------------------------------

    def _signal_passes_bias_filter(self, signal: Signal) -> bool:
        """
        Return False if the signal contradicts a high-confidence directional bias.

        Only suppresses when:
        - Bias confidence >= BIAS_FILTER_THRESHOLD
        - Signal is directly opposed to bias direction (BUY vs BEARISH, SELL vs BULLISH)
        - HOLD always passes — never blocked
        """
        if signal == Signal.HOLD:
            return True

        bias = trading_state.market_bias
        confidence = trading_state.bias_confidence

        if confidence < config.BIAS_FILTER_THRESHOLD:
            return True  # Bias too uncertain to filter

        if bias == "BEARISH" and signal == Signal.BUY:
            print(
                f"  ⚠️  Signal BLOCKED by bias filter: "
                f"BUY suppressed (BEARISH bias, {confidence:.0%} confidence)"
            )
            return False

        if bias == "BULLISH" and signal == Signal.SELL:
            print(
                f"  ⚠️  Signal BLOCKED by bias filter: "
                f"SELL suppressed (BULLISH bias, {confidence:.0%} confidence)"
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Symbol scan
    # ------------------------------------------------------------------

    def scan_symbol(self, symbol: str) -> ConfluenceResult | None:
        """Run a full analysis cycle for one symbol."""
        # Check halt before doing any work for this symbol
        if trading_state.is_halted:
            print(f"  ⏸️  {symbol} skipped — {trading_state.halt_status_line}")
            return None

        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning {symbol}...")

            df = fetch_ohlcv(symbol)
            df = compute_all(df)
            snapshot = get_snapshot(df)
            print(
                f"  Price: ${snapshot['price']} | RSI: {snapshot['rsi']:.1f} | "
                f"MACD Hist: {snapshot['macd_hist']:.4f} | RelVol: {snapshot['rel_volume']:.1f}x"
            )

            signals = self._run_agents_parallel(symbol, snapshot)
            result = detect_confluence(symbol, signals)

            print(
                f"  Votes → BUY:{result.vote_breakdown['BUY']} "
                f"SELL:{result.vote_breakdown['SELL']} "
                f"HOLD:{result.vote_breakdown['HOLD']} | "
                f"Score:{result.confluence_score:.0%} | "
                f"Threshold:{'✓' if result.threshold_met else '✗'}"
            )

            if (
                result.threshold_met
                and result.final_signal != Signal.HOLD
                and self._signal_passes_bias_filter(result.final_signal)
            ):
                self._handle_signal(result, snapshot)

            return result

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
            return None

    def _run_agents_parallel(self, symbol: str, snapshot: dict) -> list[AgentSignal]:
        """Run all strategy agents concurrently and collect signals."""
        signals: list[AgentSignal] = []

        with ThreadPoolExecutor(max_workers=len(self.strategy_agents)) as executor:
            futures = {
                executor.submit(agent.analyze, symbol, snapshot): agent
                for agent in self.strategy_agents
            }
            for future in as_completed(futures):
                agent = futures[future]
                try:
                    signal = future.result(timeout=30)
                    signals.append(signal)
                    print(
                        f"  [{signal.strategy_name[:25]:<25}] → "
                        f"{signal.signal.value} ({signal.confidence:.0%})"
                    )
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

    # ------------------------------------------------------------------
    # Scan cycle
    # ------------------------------------------------------------------

    def run_scan_cycle(self) -> list[ConfluenceResult]:
        """Run one complete scan of all symbols, with news checks."""
        self._scan_count += 1
        print(f"\n{'#'*60}")
        print(f"SCAN CYCLE #{self._scan_count} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#'*60}")

        # Step 1: Event guard (highest priority)
        self._maybe_run_event_guard()

        # Step 2: Refresh market bias if needed
        self._maybe_refresh_bias()

        # Print current news state for visibility
        bias = trading_state.market_bias
        bias_conf = trading_state.bias_confidence
        halt_line = trading_state.halt_status_line
        print(
            f"Bias: {bias} ({bias_conf:.0%}) | Trading: {halt_line}"
        )

        if trading_state.is_halted:
            print("⏸️  All symbol scans skipped — trading is halted.")
            return []

        # Step 3: Scan each symbol
        results = []
        for symbol in config.WATCH_SYMBOLS:
            result = self.scan_symbol(symbol)
            if result:
                results.append(result)
                if config.TRADING_MODE == "paper" and symbol in self.portfolio.positions:
                    try:
                        current = fetch_current_price(symbol)
                        self.portfolio.check_exits(symbol, current)
                    except Exception as e:
                        logger.warning(f"Could not check exits for {symbol}: {e}")

        if config.TRADING_MODE == "paper" and self._scan_count % 5 == 0:
            self.portfolio.print_summary()

        return results

    # ------------------------------------------------------------------
    # Inter-cycle guard loop
    # ------------------------------------------------------------------

    def _run_inter_cycle_guard(self, wait_seconds: int) -> None:
        """
        During the sleep between main scan cycles, run the event guard
        every EVENT_GUARD_INTERVAL seconds so we react faster than the
        full scan period.
        """
        end_time = datetime.now() + timedelta(seconds=wait_seconds)

        while datetime.now() < end_time:
            remaining = (end_time - datetime.now()).total_seconds()
            next_guard = max(0.0, min(config.EVENT_GUARD_INTERVAL, remaining))

            if next_guard > 0:
                time.sleep(next_guard)

            if datetime.now() >= end_time:
                break

            # Only run guard if we haven't already run it recently
            elapsed_since_last = (datetime.now() - self._last_guard_check).total_seconds()
            if elapsed_since_last >= config.EVENT_GUARD_INTERVAL:
                run_event_guard_check()
                self._last_guard_check = datetime.now()

                if trading_state.is_halted:
                    print(
                        f"  ⏸️  Trading halted mid-sleep. "
                        f"Halt: {trading_state.halt_status_line}"
                    )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Main loop: news check → scan all symbols → guard between cycles."""
        print(f"\n{'='*60}")
        print("MULTI-AGENT TRADING BOT STARTED")
        print(f"{'='*60}")
        print(f"Symbols:      {', '.join(config.WATCH_SYMBOLS)}")
        print(f"Strategy:     {', '.join(a.__class__.__name__ for a in self.strategy_agents)}")
        print(f"Mode:         {config.TRADING_MODE.upper()}")
        print(f"Scan interval:{config.SCAN_INTERVAL}s")
        print(f"Guard interval:{config.EVENT_GUARD_INTERVAL}s")
        print(f"Bias refresh: {config.NEWS_BIAS_INTERVAL}min")
        print(f"Threshold:    {config.CONFLUENCE_THRESHOLD}/{len(self.strategy_agents)} agents")
        print(f"{'='*60}")

        # Bootstrap: run bias check and initial guard immediately
        print("\n🔄 Bootstrapping news state before first scan...")
        run_news_bias_check()
        run_event_guard_check()
        self._last_bias_check = datetime.now()
        self._last_guard_check = datetime.now()

        while True:
            try:
                self.run_scan_cycle()
                print(f"\nNext scan in {config.SCAN_INTERVAL}s... (Ctrl+C to stop)")
                self._run_inter_cycle_guard(config.SCAN_INTERVAL)

            except KeyboardInterrupt:
                print("\n\nBot stopped by user.")
                if config.TRADING_MODE == "paper":
                    self.portfolio.print_summary()
                trading_state.print_status()
                break

            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(30)
