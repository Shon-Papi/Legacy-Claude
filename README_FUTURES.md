# Futures Trading Bot

A standalone, deterministic trading bot for **crypto perpetual futures**
(Binance USDT-M by default). No LLM, no API key needed for backtesting or
paper trading — just market data and rules.

## The honest part, first

**No trading bot can be guaranteed profitable.** Anyone who promises that is
selling something. What this bot gives you instead:

- A strategy class (trend-filtered breakout) with decades of documented
  out-of-sample persistence in futures markets — not a guarantee, an edge
  that exists in trending regimes and bleeds in chop.
- A backtester that *cannot* flatter the strategy: signals fill at the next
  bar's open, every fill pays taker fees + slippage, stops are checked
  against intrabar lows/highs, and gaps fill at the open, not at your stop.
- The **same** risk and strategy code in the backtest and the live engine,
  so the rules you tested are the rules you trade.
- Risk controls that cap how wrong things can go: fixed-fractional sizing,
  leverage caps, a daily loss halt, and a max-drawdown kill switch.

Futures are leveraged instruments. You can lose more than you expect, fast.
Only trade money you can fully afford to lose.

## Strategy

Trend-filtered Donchian breakout on 15m bars across BTC, ETH and SOL
perpetuals (24/7 market → multiple signals per day):

| | Long (short is the mirror) |
|---|---|
| Trend filter | EMA50 > EMA200 and close > EMA200 |
| Entry | Close breaks the prior 20-bar high |
| Sanity filter | RSI < 75 (don't chase blow-off tops) |
| Initial stop | Entry − 2.0 × ATR(14) |
| Breakeven | Stop to entry after +1R |
| Trailing | Chandelier: highest high − 2.5 × ATR |
| Time stop | Out after 96 bars (1 day) |
| Flip | Opposite signal closes the position |

### Risk limits (defaults)

- **0.75% of equity risked per trade** (sized to the initial stop)
- Max 2× leverage per position, 3× total, max 3 concurrent positions
- **Daily loss halt:** −3% realized in a UTC day stops new entries until tomorrow
- **Kill switch:** −15% from peak equity halts the bot entirely
- Halts survive restarts (state is persisted)

## The required workflow — in order

### 1. Backtest on real data

```bash
pip install -r requirements.txt
python run_futures.py backtest --days 365
```

Reads a year of 15m candles from Binance (public API, no key) and prints
return, max drawdown, Sharpe, win rate, profit factor, trades/day, and fees,
plus a full trade log in `backtest_trades.csv`.

**Gate: do not proceed unless profit factor > 1.2 and the max drawdown is
something you could genuinely sit through.**

### 2. Paper trade on live data

```bash
python run_futures.py paper
```

Real-time data, simulated fills with the same fees/slippage as the backtest.
State persists in `futures_paper_state.json`; every closed trade is appended
to `futures_trades.csv`. **Run this for at least 4 weeks.**

### 3. Exchange testnet

```bash
FUTURES_API_KEY=... FUTURES_API_SECRET=... python run_futures.py live
```

Real orders, fake money (testnet is the default). Verifies order placement,
stop handling, and position reconciliation against a real exchange.

### 4. Real money (only after 1–3 look good)

```bash
FUTURES_TESTNET=false FUTURES_LIVE_CONFIRM=YES python run_futures.py live
```

The bot refuses to start on mainnet without the explicit confirm latch.
Start with a small account. The daily-loss halt and drawdown kill switch
remain active at all times.

## Other commands

```bash
python run_futures.py backtest --synthetic        # offline mechanics check (random data)
python run_futures.py backtest --csv-dir data/    # backtest your own CSVs
python run_futures.py backtest --symbols "BTC/USDT:USDT" --days 730
python run_futures.py fetch --days 365            # pre-download the data cache
```

`--synthetic` runs the whole pipeline on regime-switching random data. It
exists to prove the *mechanics* are correct (accounting, stops, halts) — on
random data the expected result is roughly breakeven minus fees, and that is
exactly what it shows. Real-data backtests are the only performance evidence
that counts.

## Configuration

Everything is overridable via environment variables / `.env` — see the
`FUTURES BOT` section of `.env.example`. If you change strategy parameters,
re-run the backtest *and* the paper period before trading them.

## Layout

```
futures/
  config.py      all tunables (env-overridable)
  indicators.py  EMA / RSI / ATR / Donchian (pure pandas)
  strategy.py    signal + stop logic (shared by backtest and live)
  risk.py        position sizing + circuit breakers (shared)
  data.py        ccxt history fetch, CSV cache, synthetic generator
  backtest.py    event-driven portfolio backtester
  exchange.py    ccxt order/data wrapper (testnet-aware)
  engine.py      paper/live trading loop with persistent state
run_futures.py   CLI entrypoint
```
