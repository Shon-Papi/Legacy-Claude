"""
Live/paper trading engine.

Runs the exact strategy + risk code that the backtester runs:
on every newly CLOSED bar it (1) manages open positions against that bar,
(2) evaluates the entry signal, and (3) executes at the current market
price (which is the open of the next bar — same as the backtest fill).

Modes
  paper  Real market data, simulated fills with fees+slippage, state kept
         in futures_paper_state.json. Needs no API key.
  live   Real orders via ccxt with a reduce-only STOP_MARKET resting on
         the exchange. Testnet by default; mainnet requires
         FUTURES_TESTNET=false AND FUTURES_LIVE_CONFIRM=YES.
"""
import csv
import json
import logging
import os
import time
from dataclasses import asdict

import numpy as np
import pandas as pd

from futures.backtest import Position
from futures.config import fconfig
from futures.exchange import FuturesExchange
from futures.indicators import add_indicators
from futures.risk import RiskState, position_qty
from futures.strategy import LONG, Signal, initial_stop, signal_at, update_stop

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, mode: str = "paper", cfg=fconfig):
        if mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        self.mode = mode
        self.cfg = cfg

        if mode == "live":
            if not cfg.TESTNET and cfg.LIVE_CONFIRM != "YES":
                raise RuntimeError(
                    "Refusing to trade real money: set FUTURES_LIVE_CONFIRM=YES "
                    "only after the strategy is profitable in your own backtest "
                    "AND in >=4 weeks of paper/testnet trading."
                )
            self.exchange = FuturesExchange(cfg, authenticated=True)
            for sym in cfg.SYMBOLS:
                self.exchange.set_leverage(sym, int(cfg.MAX_POSITION_LEVERAGE) or 1)
        else:
            self.exchange = FuturesExchange(cfg, authenticated=False)

        self.cash = cfg.STARTING_EQUITY
        self.risk = RiskState(starting_equity=cfg.STARTING_EQUITY)
        self.positions: dict[str, Position] = {}
        self.last_bar: dict[str, str] = {}  # symbol -> isoformat of last processed bar
        self._load_state()

    # ------------------------------------------------------------------
    # Persistence + journal
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        path = self.cfg.PAPER_STATE_FILE
        if self.mode != "paper" or not os.path.exists(path):
            return
        with open(path) as f:
            s = json.load(f)
        self.cash = s["cash"]
        self.last_bar = s.get("last_bar", {})
        risk = s.get("risk", {})
        self.risk.peak_equity = risk.get("peak_equity", self.cash)
        self.risk.drawdown_halted = risk.get("drawdown_halted", False)
        if risk.get("day"):
            self.risk.day = pd.Timestamp(risk["day"]).date()
            self.risk.day_start_equity = risk.get("day_start_equity", self.cash)
            self.risk.day_realized = risk.get("day_realized", 0.0)
            self.risk.halted_for_day = risk.get("halted_for_day", False)
        for sym, p in s.get("positions", {}).items():
            p["entry_time"] = pd.Timestamp(p["entry_time"])
            self.positions[sym] = Position(**p)
        logger.info("Resumed paper state: cash=%.2f, %d open positions", self.cash, len(self.positions))

    def _save_state(self) -> None:
        if self.mode != "paper":
            return
        positions = {}
        for sym, p in self.positions.items():
            d = asdict(p)
            d["entry_time"] = p.entry_time.isoformat()
            positions[sym] = d
        state = {
            "cash": self.cash,
            "last_bar": self.last_bar,
            "positions": positions,
            "risk": {
                "peak_equity": self.risk.peak_equity,
                "drawdown_halted": self.risk.drawdown_halted,
                "day": self.risk.day.isoformat() if self.risk.day else None,
                "day_start_equity": self.risk.day_start_equity,
                "day_realized": self.risk.day_realized,
                "halted_for_day": self.risk.halted_for_day,
            },
        }
        tmp = self.cfg.PAPER_STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.cfg.PAPER_STATE_FILE)

    def _journal(self, row: dict) -> None:
        path = self.cfg.JOURNAL_FILE
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
            w.writerow(row)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _mark_equity(self, prices: dict[str, float]) -> float:
        unrealized = sum(
            p.side * (prices.get(s, p.entry_price) - p.entry_price) * p.qty
            for s, p in self.positions.items()
        )
        return self.cash + unrealized

    def _open_notional(self, prices: dict[str, float]) -> float:
        return sum(prices.get(s, p.entry_price) * p.qty for s, p in self.positions.items())

    def _enter(self, sig: Signal, price: float, prices: dict[str, float]) -> None:
        fill = price * (1 + sig.side * self.cfg.SLIPPAGE)
        qty = position_qty(self.cash, fill, sig.atr, self._open_notional(prices), self.cfg)
        if self.mode == "live":
            qty = self.exchange.round_qty(sig.symbol, qty)
        if qty <= 0:
            return

        if self.mode == "live":
            order = self.exchange.market_order(sig.symbol, sig.side, qty)
            fill = float(order.get("average") or order.get("price") or fill)

        fee = fill * qty * self.cfg.TAKER_FEE
        self.cash -= fee
        stop = initial_stop(sig.side, fill, sig.atr, self.cfg)
        self.positions[sig.symbol] = Position(
            symbol=sig.symbol,
            side=sig.side,
            qty=qty,
            entry_price=fill,
            entry_time=pd.Timestamp.now(tz="UTC"),
            stop=stop,
            init_risk=abs(fill - stop),
            extreme=fill,
            entry_fee=fee,
        )
        if self.mode == "live":
            self.exchange.place_stop_market(sig.symbol, sig.side, qty, stop)

        logger.info(
            "ENTER %s %s qty=%.6f @ %.4f stop=%.4f (%s)",
            sig.direction, sig.symbol, qty, fill, stop, sig.reason,
        )

    def _exit(self, pos: Position, raw_price: float, reason: str) -> None:
        exit_price = raw_price * (1 - pos.side * self.cfg.SLIPPAGE)

        if self.mode == "live":
            self.exchange.cancel_all_orders(pos.symbol)
            if reason != "exchange_stop" and self.exchange.position_qty(pos.symbol) != 0:
                order = self.exchange.market_order(
                    pos.symbol, -pos.side, pos.qty, reduce_only=True
                )
                exit_price = float(order.get("average") or order.get("price") or exit_price)

        exit_fee = exit_price * pos.qty * self.cfg.TAKER_FEE
        gross = pos.side * (exit_price - pos.entry_price) * pos.qty
        net = gross - pos.entry_fee - exit_fee
        self.cash += gross - exit_fee
        del self.positions[pos.symbol]
        self.risk.record_realized(net)

        self._journal({
            "exit_time": pd.Timestamp.now(tz="UTC").isoformat(),
            "symbol": pos.symbol,
            "side": "LONG" if pos.side == LONG else "SHORT",
            "qty": pos.qty,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "pnl_net": round(net, 4),
            "reason": reason,
            "mode": self.mode,
        })
        logger.info("EXIT %s @ %.4f pnl=%.2f (%s)", pos.symbol, exit_price, net, reason)

    # ------------------------------------------------------------------
    # Per-bar logic (mirrors the backtester)
    # ------------------------------------------------------------------

    def _process_bar(self, sym: str, df: pd.DataFrame, prices: dict[str, float]) -> None:
        bar = df.iloc[-1]
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        pos = self.positions.get(sym)

        if pos is not None:
            if self.mode == "live" and self.exchange.position_qty(sym) == 0:
                # Exchange-side stop already closed it; book it at the stop price
                self._exit(pos, pos.stop, "exchange_stop")
                pos = None
            elif pos.side == LONG and (o <= pos.stop or l <= pos.stop):
                self._exit(pos, min(o, pos.stop), "stop")
                pos = None
            elif pos.side != LONG and (o >= pos.stop or h >= pos.stop):
                self._exit(pos, max(o, pos.stop), "stop")
                pos = None
            else:
                pos.bars_held += 1
                pos.extreme = max(pos.extreme, h) if pos.side == LONG else min(pos.extreme, l)
                cur_atr = float(bar["atr"])
                if np.isfinite(cur_atr) and cur_atr > 0:
                    new_stop = update_stop(
                        pos.side, pos.stop, pos.entry_price, pos.init_risk,
                        pos.extreme, cur_atr, c, self.cfg,
                    )
                    if new_stop != pos.stop:
                        pos.stop = new_stop
                        if self.mode == "live":
                            self.exchange.cancel_all_orders(sym)
                            self.exchange.place_stop_market(sym, pos.side, pos.qty, new_stop)
                if pos.bars_held >= self.cfg.MAX_HOLD_BARS:
                    self._exit(pos, prices.get(sym, c), "time_stop")
                    pos = None

        sig = signal_at(df, len(df) - 1, sym, self.cfg)
        if sig is None:
            return
        if pos is not None:
            if pos.side != sig.side:
                self._exit(pos, prices.get(sym, c), "signal_flip")
            else:
                return
        if self.risk.entries_allowed(len(self.positions), self.cfg):
            self._enter(sig, prices.get(sym, c), prices)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        cfg = self.cfg
        logger.info(
            "Engine starting: mode=%s symbols=%s timeframe=%s equity=%.2f",
            self.mode, cfg.SYMBOLS, cfg.TIMEFRAME, self.cash,
        )
        # 3x the slowest EMA so its value matches a long-history backtest computation
        warmup = max(cfg.EMA_SLOW * 3, cfg.DONCHIAN_PERIOD + cfg.ATR_PERIOD + 50)

        while True:
            try:
                self._cycle(warmup)
            except KeyboardInterrupt:
                logger.info("Stopped by user. State saved.")
                self._save_state()
                return
            except Exception:  # noqa: BLE001 - keep the loop alive on transient errors
                logger.exception("Cycle failed; retrying after poll interval")
            time.sleep(cfg.POLL_SECONDS)

    def _cycle(self, warmup: int) -> None:
        prices: dict[str, float] = {}
        frames: dict[str, pd.DataFrame] = {}
        for sym in self.cfg.SYMBOLS:
            df = self.exchange.closed_ohlcv(sym, self.cfg.TIMEFRAME, limit=warmup + 50)
            frames[sym] = add_indicators(df, self.cfg)
            prices[sym] = float(df["close"].iloc[-1])

        equity = self._mark_equity(prices)
        self.risk.roll_day(pd.Timestamp.now(tz="UTC").date(), equity)
        self.risk.update_equity(equity, self.cfg)

        for sym, df in frames.items():
            newest = df.index[-1].isoformat()
            if self.last_bar.get(sym) == newest:
                continue  # no new closed bar yet
            self.last_bar[sym] = newest
            self._process_bar(sym, df, prices)

        self._save_state()
        logger.info(
            "equity=%.2f open=%s day_pnl=%.2f%s",
            equity,
            {s: ("L" if p.side == LONG else "S") for s, p in self.positions.items()} or "{}",
            self.risk.day_realized,
            " [HALTED]" if (self.risk.halted_for_day or self.risk.drawdown_halted) else "",
        )
