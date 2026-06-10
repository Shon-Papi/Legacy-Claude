"""
Market data for the futures bot.

  - fetch_ohlcv():       paginated history from the exchange via ccxt
  - get_data():          fetch with a local CSV cache (data_cache/)
  - load_csv():          backtest from your own CSV files
  - generate_synthetic(): regime-switching random walk, used ONLY to test
                          that the bot's mechanics are correct. Synthetic
                          results say nothing about real-market profits.
"""
import logging
import os
import time

import numpy as np
import pandas as pd

from futures.config import fconfig

logger = logging.getLogger(__name__)

_TIMEFRAME_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "1d": 86_400_000,
}

COLUMNS = ["open", "high", "low", "close", "volume"]


def timeframe_ms(timeframe: str) -> int:
    if timeframe not in _TIMEFRAME_MS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return _TIMEFRAME_MS[timeframe]


def fetch_ohlcv(symbol: str, timeframe: str, days: int, cfg=fconfig) -> pd.DataFrame:
    """Fetch `days` of OHLCV history from the exchange, paginating as needed."""
    import ccxt  # imported lazily so offline use (CSV/synthetic) needs no ccxt

    exchange = getattr(ccxt, cfg.EXCHANGE_ID)({"enableRateLimit": True})
    tf_ms = timeframe_ms(timeframe)
    since = exchange.milliseconds() - days * 86_400_000

    all_rows: list[list] = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < 1000:
            break
        since = batch[-1][0] + tf_ms
        time.sleep(exchange.rateLimit / 1000.0)

    if not all_rows:
        raise ValueError(f"No OHLCV data returned for {symbol} {timeframe}")

    df = pd.DataFrame(all_rows, columns=["ts", *COLUMNS])
    df = df.drop_duplicates(subset="ts").sort_values("ts")
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.index.name = "time"
    # Drop the final row: it is the still-forming (unclosed) candle
    return df[COLUMNS].iloc[:-1].astype(float)


def _cache_path(symbol: str, timeframe: str, cfg=fconfig) -> str:
    safe = symbol.replace("/", "-").replace(":", "_")
    return os.path.join(cfg.DATA_CACHE_DIR, f"{safe}_{timeframe}.csv")


def get_data(
    symbol: str, timeframe: str, days: int, use_cache: bool = True, cfg=fconfig
) -> pd.DataFrame:
    """Fetch OHLCV with a local CSV cache so repeated backtests are instant."""
    path = _cache_path(symbol, timeframe, cfg)
    if use_cache and os.path.exists(path):
        df = load_csv(path)
        span_days = (df.index[-1] - df.index[0]).total_seconds() / 86_400
        age_min = (pd.Timestamp.now(tz="UTC") - df.index[-1]).total_seconds() / 60
        if span_days >= days * 0.95 and age_min < 24 * 60:
            logger.info("Using cached data for %s (%d rows)", symbol, len(df))
            # Trim to the requested window (the cache may hold a longer span)
            return df[df.index >= df.index[-1] - pd.Timedelta(days=days)]

    df = fetch_ohlcv(symbol, timeframe, days, cfg)
    os.makedirs(cfg.DATA_CACHE_DIR, exist_ok=True)
    df.to_csv(path)
    logger.info("Fetched %d rows for %s %s", len(df), symbol, timeframe)
    return df


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLCV from CSV: a datetime index column plus open/high/low/close/volume."""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df[COLUMNS].astype(float).sort_index()


def generate_synthetic(
    symbol: str, timeframe: str, days: int, seed: int | None = None
) -> pd.DataFrame:
    """
    Regime-switching geometric random walk with OHLC bars.

    Exists so the engine and backtester can be exercised end-to-end without
    network access. NOT a substitute for real data.
    """
    rng = np.random.default_rng(seed if seed is not None else abs(hash(symbol)) % 2**32)
    tf_ms = timeframe_ms(timeframe)
    n = int(days * 86_400_000 / tf_ms)

    # Markov regimes: trend up / chop / trend down, avg duration ~250 bars
    drift_by_regime = {0: 4e-4, 1: 0.0, 2: -4e-4}
    regime = 1
    drifts = np.empty(n)
    for i in range(n):
        if rng.random() < 1 / 250:
            regime = rng.integers(0, 3)
        drifts[i] = drift_by_regime[regime]

    vol = 0.004 * np.exp(0.3 * np.sin(np.arange(n) / 500) + 0.2 * rng.standard_normal(n))
    rets = drifts + vol * rng.standard_normal(n)
    close = 1000.0 * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = 1000.0
    open_[1:] = close[:-1]

    wick = np.abs(rng.standard_normal(n)) * vol * close * 0.7
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = 1000 * np.exp(rng.standard_normal(n) * 0.5)

    end = pd.Timestamp.now(tz="UTC").floor("h")
    idx = pd.date_range(end=end, periods=n, freq=pd.Timedelta(milliseconds=tf_ms))
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    df.index.name = "time"
    return df
