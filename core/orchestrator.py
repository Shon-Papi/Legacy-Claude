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
from core.market_hours import is_market_open, session_status, minutes_to_open
from core.journal import journal
from core.risk_manager import risk_manager
from paper_trading.portfolio import PaperPortfolio

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """
    Central coordinator for the multi-agent trading bot.

    Scan cycle
    ----------
    1. Market-hours gate  — skip if ONLY_TRADE_MARKET_HOURS and market is closed
    2. EventGuardAgent    — check for high-impact news; may halt trading
    3. NewsBiasAgent      — refresh directional bias every NEWS_BIAS_INTERVAL min
    4. For each symbol:
         a. Fetch OHLCV → compute indicators → get snapshot
         b. Run 5 strategy agents in parallel
         c. Detect confluence (vote aggregation)
         d. Bias filter  — suppress signals opposing a high-confidence bias
         e. Risk checks  — daily-loss / drawdown / trade-count guards
         f. Execute trade (paper or live) and journal the result
    5. Between cycles, run the event guard every EVENT_GUARD_INTERVAL seconds

    New modules wired in
    --------------------
    - core.market_hours  : only trade during NYSE regular session (configurable)
    - core.journal       : append-only JSONL log of every signal and trade
    - core.risk_manager  : daily-loss / drawdown / trade-count guardrails
    - live_trading.broker: Alpaca REST API for live order execution
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
        # Track portfolio peak for drawdown calculations
        self._peak_value: float = config.PAPER_STARTING_CAPITAL

        # Lazy-import live broker only when needed
        self._broker = None
        if config.TRADING_MODE == "live":
            self._init_live_broker()

        logger.info(
            f"TradingOrchestrator ready — {len(self.strategy_agents)} agents | "
            f"{len(config.WATCH_SYMBOLS)} symbols | "
            f"mode={config.TRADING_MODE.upper()} | "
            f"threshold={config.CONFLUENCE_THRESHOLD}/{len(self.strategy_agents)}"
        )

    def _init_live_broker(self) -> None:
        """Verify Alpaca credentials and print account info."""
        if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
            logger.error(
                "TRADING_MODE=live but ALPACA_API_KEY / ALPACA_SECRET_KEY are not set. "
                "Falling back to paper mode."
            )
            return
        try:
            from live_trading.broker import get_account
            acct = get_account()
            equity = float(acct.get("equity", 0))
            cash   = float(acct.get("cash", 0))
            status = acct.get("status", "unknown")
            print(
                f"\n[Alpaca LIVE] Account: {status} | "
                f"Equity: ${equity:,.2f} | Cash: ${cash:,.2f}"
            )
            self._broker = True  # sentinel — actual calls go through live_trading.broker
        except Exception as e:
            logger.error(f"Alpaca init failed: {e}. Continuing in paper mode.")
            self._broker = None

    # ------------------------------------------------------------------
    # Market-hours gate
    # ------------------------------------------------------------------

    def _check_market_hours(self) -> bool:
        """
        Returns False (skip this cycle) when the market is closed and
        ONLY_TRADE_MARKET_HOURS is enabled.
        """
        if not config.ONLY_TRADE_MARKET_HOURS:
            return True

        status = session_status()
        if status == "OPEN":
            return True

        mins = minutes_to_open()
        print(
            f"  🕐  Market {status} — next open in {mins} min. "
            f"Set ONLY_TRADE_MARKET_HOURS=false to scan outside hours."
        )
        return False

    # ------------------------------------------------------------------
    # News / guard scheduling
    # ------------------------------------------------------------------

    def _maybe_run_event_guard(self) -> bool:
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
        now = datetime.now()
        elapsed_minutes = (now - self._last_bias_check).total_seconds() / 60
        if elapsed_minutes >= config.NEWS_BIAS_INTERVAL:
            run_news_bias_check()
            self._last_bias_check = now

    # ------------------------------------------------------------------
    # Bias filtering
    # ------------------------------------------------------------------

    def _signal_passes_bias_filter(self, signal: Signal) -> bool:
        if signal == Signal.HOLD:
            return True

        bias = trading_state.market_bias
        confidence = trading_state.bias_confidence

        if confidence < config.BIAS_FILTER_THRESHOLD:
            return True

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
    # Portfolio peak tracking
    # ------------------------------------------------------------------

    def _update_peak(self) -> None:
        """Keep _peak_value at the highest portfolio value seen."""
        current = self._portfolio_value()
        if current > self._peak_value:
            self._peak_value = current

    def _portfolio_value(self) -> float:
        """Portfolio value — uses paper portfolio or Alpaca equity."""
        if config.TRADING_MODE == "live" and self._broker:
            try:
                from live_trading.broker import get_equity
                return get_equity()
            except Exception:
                pass
        return self.portfolio.portfolio_value

    # ------------------------------------------------------------------
    # Symbol scan
    # ------------------------------------------------------------------

    def scan_symbol(self, symbol: str) -> ConfluenceResult | None:
        """Run a full analysis cycle for one symbol."""
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

            # Determine whether a trade will be taken
            will_trade = (
                result.threshold_met
                and result.final_signal != Signal.HOLD
                and self._signal_passes_bias_filter(result.final_signal)
                and risk_manager.is_trade_allowed(
                    self._portfolio_value(), self._peak_value
                )
            )

            # Always journal the signal
            journal.log_signal(
                symbol=symbol,
                signal=result.final_signal.value,
                confluence_score=result.confluence_score,
                vote_breakdown=result.vote_breakdown,
                market_bias=trading_state.market_bias,
                bias_confidence=trading_state.bias_confidence,
                snapshot=snapshot,
                top_strategies=[s.strategy_name for s in result.top_signals[:3]],
                threshold_met=result.threshold_met,
                action_taken=will_trade,
            )

            if will_trade:
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
        """Execute a confirmed confluence signal: trade + notify + journal."""
        send_notification(result)

        best = result.top_signals[0] if result.top_signals else None
        stop_loss   = best.stop_loss   if best else None
        take_profit = best.take_profit if best else None
        strategy    = best.strategy_name if best else ""

        if config.TRADING_MODE == "paper":
            trade = self.portfolio.execute_signal(
                symbol=result.symbol,
                signal=result.final_signal,
                price=snapshot["price"],
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy=strategy,
                reason=result.summary[:200],
            )
            if trade:
                journal.log_trade(
                    symbol=trade.symbol,
                    action=trade.action,
                    shares=trade.shares,
                    price=trade.price,
                    strategy=trade.strategy,
                    reason=trade.reason,
                    pnl=trade.pnl,
                    mode="paper",
                )
                self._update_peak()

        elif config.TRADING_MODE == "live" and self._broker:
            self._execute_live_order(result, snapshot, stop_loss, take_profit, strategy)

    def _execute_live_order(
        self,
        result: ConfluenceResult,
        snapshot: dict,
        stop_loss: float | None,
        take_profit: float | None,
        strategy: str,
    ) -> None:
        """Submit a live Alpaca order for the confluence signal."""
        from live_trading.broker import (
            get_position, submit_bracket_order, close_position,
            calculate_shares, get_equity,
        )

        symbol = result.symbol
        price  = snapshot["price"]
        signal = result.final_signal

        try:
            if signal == Signal.BUY:
                existing = get_position(symbol)
                if existing:
                    logger.info(f"[Live] Already long {symbol} — skipping BUY")
                    return

                equity = get_equity()
                qty = calculate_shares(price, equity, config.PAPER_POSITION_SIZE)
                if qty <= 0:
                    logger.warning(f"[Live] Calculated 0 shares for {symbol} — skipping")
                    return

                order = submit_bracket_order(
                    symbol=symbol, qty=qty, side="buy",
                    stop_loss=stop_loss, take_profit=take_profit,
                )
                order_id = order.get("id", "")
                print(f"  📈 LIVE BUY  {symbol}: {qty:.2f} shares @ ~${price:.2f} | order={order_id}")
                journal.log_trade(
                    symbol=symbol, action="BUY", shares=qty,
                    price=price, strategy=strategy,
                    reason=result.summary[:200],
                    mode="live", order_id=order_id,
                )

            elif signal == Signal.SELL:
                existing = get_position(symbol)
                if not existing:
                    logger.info(f"[Live] No position in {symbol} — skipping SELL")
                    return

                order = close_position(symbol)
                order_id = order.get("id", "")
                print(f"  📉 LIVE SELL {symbol}: closed @ ~${price:.2f} | order={order_id}")
                journal.log_trade(
                    symbol=symbol, action="SELL",
                    shares=float(existing.get("qty", 0)),
                    price=price, strategy=strategy,
                    reason=result.summary[:200],
                    mode="live", order_id=order_id,
                )

            self._update_peak()

        except Exception as e:
            logger.error(f"[Live] Order failed for {symbol}: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Scan cycle
    # ------------------------------------------------------------------

    def run_scan_cycle(self) -> list[ConfluenceResult]:
        """Run one complete scan of all symbols, with all guards."""
        self._scan_count += 1
        print(f"\n{'#'*60}")
        print(f"SCAN CYCLE #{self._scan_count} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'#'*60}")

        # Step 1: Market hours gate
        if not self._check_market_hours():
            return []

        # Step 2: Event guard (highest trading priority)
        self._maybe_run_event_guard()

        # Step 3: Refresh market bias if needed
        self._maybe_refresh_bias()

        # Print current state
        bias      = trading_state.market_bias
        bias_conf = trading_state.bias_confidence
        pv        = self._portfolio_value()
        print(
            f"Bias: {bias} ({bias_conf:.0%}) | "
            f"Trading: {trading_state.halt_status_line} | "
            f"Session: {session_status()} | "
            f"{risk_manager.status_line(pv, self._peak_value)}"
        )

        if trading_state.is_halted:
            print("⏸️  All symbol scans skipped — trading is halted.")
            return []

        # Step 4: Scan each symbol
        results = []
        for symbol in config.WATCH_SYMBOLS:
            result = self.scan_symbol(symbol)
            if result:
                results.append(result)
                if config.TRADING_MODE == "paper" and symbol in self.portfolio.positions:
                    try:
                        current = fetch_current_price(symbol)
                        trade = self.portfolio.check_exits(symbol, current)
                        if trade:
                            journal.log_trade(
                                symbol=trade.symbol, action=trade.action,
                                shares=trade.shares, price=trade.price,
                                strategy=trade.strategy, reason=trade.reason,
                                pnl=trade.pnl, mode="paper",
                            )
                            self._update_peak()
                    except Exception as e:
                        logger.warning(f"Could not check exits for {symbol}: {e}")

        if config.TRADING_MODE == "paper" and self._scan_count % 5 == 0:
            self.portfolio.print_summary()
            journal.print_daily_summary()

        return results

    # ------------------------------------------------------------------
    # Inter-cycle guard loop
    # ------------------------------------------------------------------

    def _run_inter_cycle_guard(self, wait_seconds: int) -> None:
        """
        Sleep between main scan cycles while running the event guard at
        EVENT_GUARD_INTERVAL intervals so the bot reacts faster than the
        full scan period.
        """
        end_time = datetime.now() + timedelta(seconds=wait_seconds)

        while datetime.now() < end_time:
            remaining  = (end_time - datetime.now()).total_seconds()
            next_guard = max(0.0, min(config.EVENT_GUARD_INTERVAL, remaining))

            if next_guard > 0:
                time.sleep(next_guard)

            if datetime.now() >= end_time:
                break

            elapsed_since = (datetime.now() - self._last_guard_check).total_seconds()
            if elapsed_since >= config.EVENT_GUARD_INTERVAL:
                run_event_guard_check()
                self._last_guard_check = datetime.now()

                if trading_state.is_halted:
                    print(
                        f"  ⏸️  Trading halted mid-sleep: "
                        f"{trading_state.halt_status_line}"
                    )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Bootstrap → event guard → bias check → continuous scan loop."""
        print(f"\n{'='*60}")
        print("MULTI-AGENT TRADING BOT STARTED")
        print(f"{'='*60}")
        print(f"Symbols:        {', '.join(config.WATCH_SYMBOLS)}")
        print(f"Strategies:     {', '.join(a.__class__.__name__ for a in self.strategy_agents)}")
        print(f"Mode:           {config.TRADING_MODE.upper()}")
        print(f"Session gate:   {'ON' if config.ONLY_TRADE_MARKET_HOURS else 'OFF'}")
        print(f"Scan interval:  {config.SCAN_INTERVAL}s")
        print(f"Guard interval: {config.EVENT_GUARD_INTERVAL}s")
        print(f"Bias refresh:   {config.NEWS_BIAS_INTERVAL}min")
        print(f"Threshold:      {config.CONFLUENCE_THRESHOLD}/{len(self.strategy_agents)} agents")
        print(f"Risk:           loss≤{config.MAX_DAILY_LOSS_PCT:.0%} | dd≤{config.MAX_DRAWDOWN_PCT:.0%} | ≤{config.DAILY_TRADE_LIMIT} trades/day")
        print(f"Journal:        trades_journal.jsonl")
        print(f"{'='*60}")

        # Bootstrap: run bias + guard immediately before first scan
        print("\n🔄 Bootstrapping news state before first scan...")
        run_news_bias_check()
        run_event_guard_check()
        self._last_bias_check  = datetime.now()
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
                journal.print_daily_summary()
                trading_state.print_status()
                break

            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(30)
