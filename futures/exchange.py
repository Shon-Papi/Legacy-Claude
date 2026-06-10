"""
Thin ccxt wrapper for the futures exchange (default: Binance USDT-M perps).

Public-data calls need no API key. Trading calls require FUTURES_API_KEY /
FUTURES_API_SECRET, and run against the exchange testnet unless
FUTURES_TESTNET=false AND FUTURES_LIVE_CONFIRM=YES.
"""
import logging

import pandas as pd

from futures.config import fconfig
from futures.data import COLUMNS
from futures.strategy import LONG

logger = logging.getLogger(__name__)


class FuturesExchange:
    def __init__(self, cfg=fconfig, authenticated: bool = False):
        import ccxt

        self.cfg = cfg
        params = {"enableRateLimit": True, "options": {"defaultType": "swap"}}
        if authenticated:
            if not cfg.API_KEY or not cfg.API_SECRET:
                raise RuntimeError(
                    "FUTURES_API_KEY / FUTURES_API_SECRET are required for live trading"
                )
            params["apiKey"] = cfg.API_KEY
            params["secret"] = cfg.API_SECRET

        self.x = getattr(ccxt, cfg.EXCHANGE_ID)(params)
        if authenticated and cfg.TESTNET:
            self.x.set_sandbox_mode(True)
            logger.info("Exchange running in TESTNET/sandbox mode")
        self.x.load_markets()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def closed_ohlcv(self, symbol: str, timeframe: str, limit: int = 450) -> pd.DataFrame:
        """Most recent CLOSED candles (the still-forming candle is dropped)."""
        rows = self.x.fetch_ohlcv(symbol, timeframe, limit=limit)
        if len(rows) < 2:
            raise ValueError(f"Not enough candles for {symbol}")
        df = pd.DataFrame(rows, columns=["ts", *COLUMNS])
        df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df.index.name = "time"
        return df[COLUMNS].iloc[:-1].astype(float)

    def last_price(self, symbol: str) -> float:
        return float(self.x.fetch_ticker(symbol)["last"])

    # ------------------------------------------------------------------
    # Trading (authenticated)
    # ------------------------------------------------------------------

    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self.x.set_leverage(leverage, symbol)
        except Exception as e:  # noqa: BLE001 - non-fatal, exchange may already be set
            logger.warning("set_leverage(%s) failed: %s", symbol, e)

    def round_qty(self, symbol: str, qty: float) -> float:
        return float(self.x.amount_to_precision(symbol, qty))

    def market_order(self, symbol: str, side: int, qty: float, reduce_only: bool = False) -> dict:
        order_side = "buy" if side == LONG else "sell"
        params = {"reduceOnly": True} if reduce_only else {}
        order = self.x.create_order(symbol, "market", order_side, qty, params=params)
        logger.info("Market %s %s %.6f -> order %s", order_side, symbol, qty, order.get("id"))
        return order

    def place_stop_market(self, symbol: str, pos_side: int, qty: float, stop_price: float) -> dict:
        """Reduce-only stop that closes a position of side `pos_side`."""
        order_side = "sell" if pos_side == LONG else "buy"
        order = self.x.create_order(
            symbol,
            "market",
            order_side,
            qty,
            params={
                "stopPrice": self.x.price_to_precision(symbol, stop_price),
                "reduceOnly": True,
                "type": "STOP_MARKET",
            },
        )
        logger.info("Stop for %s @ %.6f -> order %s", symbol, stop_price, order.get("id"))
        return order

    def cancel_all_orders(self, symbol: str) -> None:
        try:
            self.x.cancel_all_orders(symbol)
        except Exception as e:  # noqa: BLE001
            logger.warning("cancel_all_orders(%s) failed: %s", symbol, e)

    def position_qty(self, symbol: str) -> float:
        """Signed position size on the exchange (0.0 when flat)."""
        for p in self.x.fetch_positions([symbol]):
            contracts = float(p.get("contracts") or 0)
            if contracts != 0:
                sign = 1 if p.get("side") == "long" else -1
                return sign * contracts
        return 0.0
