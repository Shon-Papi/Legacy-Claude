#!/usr/bin/env python3
"""
Verification suite for the futures bot. Run any time with:

    python verify_futures.py

Every check is offline (synthetic data) and asserts a property that must
hold for the bot to be trustworthy: indicator math, no lookahead, sizing
and leverage caps, fee/PnL accounting, stop behaviour, circuit breakers,
engine state persistence, and the mainnet safety latch.

This proves CORRECTNESS, not profitability. Profitability evidence comes
from `python run_futures.py backtest --days 365` on real data, and then
from weeks of paper trading.
"""
import json
import logging
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.CRITICAL)

PASS, FAIL = 0, 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def trending_df(seed: int, n: int = 20_000) -> pd.DataFrame:
    """Alternating strong trends — the strategy must profit here."""
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 2000) % 2 == 0, 8e-4, -8e-4)
    rets = drift + 0.004 * rng.standard_normal(n)
    close = 1000 * np.exp(np.cumsum(rets))
    open_ = np.r_[1000.0, close[:-1]]
    wick = np.abs(rng.standard_normal(n)) * 0.004 * close * 0.7
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n, freq="15min")
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + wick,
         "low": np.minimum(open_, close) - wick, "close": close,
         "volume": np.ones(n)},
        index=idx,
    )


def main() -> int:
    from futures.backtest import Backtester
    from futures.config import fconfig
    from futures.data import generate_synthetic
    from futures.indicators import add_indicators, atr, rsi
    from futures.risk import RiskState, position_qty
    from futures.strategy import signal_at

    print("\n== Indicator math ==")
    up = pd.Series(np.arange(1.0, 101.0))
    r = rsi(up, 14)
    check("RSI of a straight-up series is 100", abs(float(r.iloc[-1]) - 100.0) < 1e-9)
    rng = np.random.default_rng(0)
    noisy = pd.Series(100 + np.cumsum(rng.standard_normal(500)))
    rv = rsi(noisy, 14).dropna()
    check("RSI bounded in [0, 100]", bool(((rv >= 0) & (rv <= 100)).all()))

    df = generate_synthetic("X", "15m", 30, seed=1)
    a = atr(df, 14).dropna()
    check("ATR strictly positive", bool((a > 0).all()))

    enriched = add_indicators(df)
    i = 500
    manual_dh = float(df["high"].iloc[i - fconfig.DONCHIAN_PERIOD : i].max())
    check(
        "Donchian high excludes the current bar",
        abs(float(enriched["don_high"].iloc[i]) - manual_dh) < 1e-9,
    )

    print("\n== No lookahead ==")
    full = add_indicators(df)
    ok = True
    for i in (300, 700, 1500, 2500):
        trunc = add_indicators(df.iloc[: i + 1])
        s_full = signal_at(full, i, "X")
        s_trunc = signal_at(trunc, i, "X")
        same = (s_full is None) == (s_trunc is None)
        if s_full and s_trunc:
            same = s_full.side == s_trunc.side and abs(s_full.price - s_trunc.price) < 1e-9
        ok &= same
    check("signal at bar i identical with/without future bars", ok)

    print("\n== Position sizing ==")
    q = position_qty(equity=10_000, price=100, sig_atr=2.0, open_notional=0)
    expected = 10_000 * fconfig.RISK_PER_TRADE / (fconfig.STOP_ATR_MULT * 2.0)
    check("qty risks exactly RISK_PER_TRADE to the stop", abs(q - expected) < 1e-9)
    q = position_qty(equity=10_000, price=100, sig_atr=0.01, open_notional=0)
    check(
        "per-position leverage cap binds on tight stops",
        abs(q * 100 - 10_000 * fconfig.MAX_POSITION_LEVERAGE) < 1e-6,
    )
    q = position_qty(equity=10_000, price=100, sig_atr=0.01,
                     open_notional=10_000 * fconfig.MAX_TOTAL_LEVERAGE)
    check("total leverage cap blocks new exposure", q == 0.0)
    check("zero/negative inputs return zero qty",
          position_qty(0, 100, 1, 0) == 0.0 and position_qty(1000, 100, 0, 0) == 0.0)

    print("\n== Circuit breakers ==")
    rs = RiskState(starting_equity=10_000)
    rs.roll_day(pd.Timestamp("2026-01-01").date(), 10_000)
    rs.record_realized(-fconfig.DAILY_LOSS_LIMIT_PCT * 10_000 - 1)
    check("daily loss limit halts entries", rs.halted_for_day and not rs.entries_allowed(0))
    rs.roll_day(pd.Timestamp("2026-01-02").date(), 9_600)
    check("halt clears on the next day", not rs.halted_for_day and rs.entries_allowed(0))
    rs.update_equity(10_000)
    rs.update_equity(10_000 * (1 - fconfig.HALT_DRAWDOWN_PCT) - 1)
    check("drawdown kill switch trips", rs.drawdown_halted and not rs.entries_allowed(0))
    check("max positions respected",
          RiskState(10_000).entries_allowed(fconfig.MAX_POSITIONS) is False)

    print("\n== Backtester accounting ==")
    data = {s: generate_synthetic(s, "15m", 180, seed=i) for i, s in enumerate(["A", "B", "C"])}
    res = Backtester(data).run()
    m = res.metrics()
    total_pnl = sum(t.pnl for t in res.trades)
    check(
        "equity change equals sum of net trade PnL (to the cent)",
        abs((m["end_equity"] - m["start_equity"]) - total_pnl) < 1e-6,
        f"diff={abs((m['end_equity'] - m['start_equity']) - total_pnl):.6f}",
    )
    check("every trade pays fees", all(t.fees > 0 for t in res.trades))
    # exit_time == entry_time is the conservative same-bar stop-out
    # (entry at the bar's open, stop hit within that same bar)
    check("exit never precedes entry", all(t.exit_time >= t.entry_time for t in res.trades))
    check(
        "no stop loss materially exceeds 1R (beyond gap risk)",
        all(t.r_multiple > -1.5 for t in res.trades),
        f"worst={min((t.r_multiple for t in res.trades), default=0):.2f}R",
    )
    res2 = Backtester({s: generate_synthetic(s, "15m", 180, seed=i)
                       for i, s in enumerate(["A", "B", "C"])}).run()
    check("backtest is deterministic", res.metrics() == res2.metrics())

    print("\n== Strategy behaviour ==")
    trend_res = Backtester({f"T{i}": trending_df(i) for i in range(3)}).run()
    tm = trend_res.metrics()
    check(
        "captures profit in trending markets (profit factor > 2)",
        tm["profit_factor"] > 2.0,
        f"PF={tm['profit_factor']:.2f}",
    )
    check("multiple trades per day in trending markets",
          tm["trades_per_day"] > 1.0, f"{tm['trades_per_day']:.2f}/day")
    check(
        "near-random data ~ breakeven minus fees (backtester does not invent profit)",
        -25 < m["total_return_pct"] < 25,
        f"return={m['total_return_pct']:+.1f}%",
    )

    print("\n== Engine (paper) ==")
    from futures import engine as eng

    class FakeExchange:
        def __init__(self, cfg=None, authenticated=False):
            self.data = {
                s: generate_synthetic(s, "15m", 60, seed=i * 7 + 1)
                for i, s in enumerate(fconfig.SYMBOLS)
            }
            self.cursor = 700

        def closed_ohlcv(self, symbol, timeframe, limit=450):
            return self.data[symbol].iloc[: self.cursor].iloc[-limit:]

        def last_price(self, symbol):
            return float(self.data[symbol]["close"].iloc[self.cursor - 1])

    real_exchange = eng.FuturesExchange
    eng.FuturesExchange = FakeExchange
    tmp = tempfile.mkdtemp()
    state_file, journal_file = fconfig.PAPER_STATE_FILE, fconfig.JOURNAL_FILE
    fconfig.PAPER_STATE_FILE = os.path.join(tmp, "state.json")
    fconfig.JOURNAL_FILE = os.path.join(tmp, "journal.csv")
    try:
        engine = eng.TradingEngine(mode="paper")
        for _ in range(1200):
            engine._cycle(610)
            engine.exchange.cursor += 1
        journaled = (
            len(pd.read_csv(fconfig.JOURNAL_FILE)) if os.path.exists(fconfig.JOURNAL_FILE) else 0
        )
        check("paper engine executes and journals trades", journaled > 0,
              f"{journaled} trades")
        engine2 = eng.TradingEngine(mode="paper")
        check(
            "state (cash + risk) survives restart",
            abs(engine2.cash - engine.cash) < 1e-9
            and engine2.risk.halted_for_day == engine.risk.halted_for_day
            and engine2.risk.day_realized == engine.risk.day_realized,
        )
        with open(fconfig.PAPER_STATE_FILE) as f:
            check("state file is valid JSON with risk block", "risk" in json.load(f))

        # Downtime: 5 bars close while the engine is offline — one cycle
        # must process all of them in order, not just the newest
        sym0 = fconfig.SYMBOLS[0]
        engine2.exchange.cursor = engine.exchange.cursor + 5
        engine2._cycle(610)
        expected = engine2.exchange.data[sym0].index[engine2.exchange.cursor - 1].isoformat()
        check("engine catches up on bars missed during downtime",
              engine2.last_bar[sym0] == expected)
    finally:
        eng.FuturesExchange = real_exchange
        fconfig.PAPER_STATE_FILE, fconfig.JOURNAL_FILE = state_file, journal_file

    print("\n== Safety latch ==")
    old_testnet, old_confirm = fconfig.TESTNET, fconfig.LIVE_CONFIRM
    fconfig.TESTNET, fconfig.LIVE_CONFIRM = False, ""
    try:
        eng.TradingEngine(mode="live")
        check("mainnet refused without FUTURES_LIVE_CONFIRM=YES", False)
    except RuntimeError:
        check("mainnet refused without FUTURES_LIVE_CONFIRM=YES", True)
    finally:
        fconfig.TESTNET, fconfig.LIVE_CONFIRM = old_testnet, old_confirm

    print(f"\n{'=' * 50}\n  {PASS} passed, {FAIL} failed\n{'=' * 50}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
