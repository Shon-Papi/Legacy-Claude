import yfinance as yf
import pandas as pd
from config import config


def fetch_ohlcv(symbol: str, period: str = None, interval: str = None) -> pd.DataFrame:
    """Fetch OHLCV data for a symbol using yfinance."""
    period = period or config.DATA_PERIOD
    interval = interval or config.DATA_INTERVAL

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    df.index = pd.to_datetime(df.index)
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def fetch_current_price(symbol: str) -> float:
    """Fetch the latest price for a symbol."""
    ticker = yf.Ticker(symbol)
    data = ticker.history(period="1d", interval="1m")
    if data.empty:
        raise ValueError(f"No price data for {symbol}")
    return float(data["Close"].iloc[-1])


def fetch_info(symbol: str) -> dict:
    """Fetch basic symbol info."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    return {
        "symbol": symbol,
        "name": info.get("shortName", symbol),
        "sector": info.get("sector", "Unknown"),
        "market_cap": info.get("marketCap", 0),
        "avg_volume": info.get("averageVolume", 0),
    }
