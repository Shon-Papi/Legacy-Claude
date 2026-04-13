"""
Alpaca broker integration — live order execution via Alpaca REST API v2.

Uses the `requests` library (already in requirements.txt) so no extra
dependency is needed.  Supports both paper and live endpoints depending
on ALPACA_BASE_URL in .env:

  Paper:  https://paper-api.alpaca.markets
  Live:   https://api.alpaca.markets

Docs: https://docs.alpaca.markets/reference/

Public interface
----------------
  get_account()                    → dict   account info (equity, cash, …)
  is_market_open()                 → bool   live clock check via Alpaca
  get_position(symbol)             → dict | None
  get_all_positions()              → list[dict]
  submit_market_order(sym, qty, side)
  submit_bracket_order(sym, qty, side, stop_loss, take_profit)
  close_position(symbol)
  cancel_all_orders()
"""
import logging
from typing import Optional

import requests

from config import config

logger = logging.getLogger(__name__)

_BASE    = config.ALPACA_BASE_URL.rstrip("/")
_HEADERS = {
    "APCA-API-KEY-ID":     config.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    "Content-Type":        "application/json",
}
_TIMEOUT = 10  # seconds


# ------------------------------------------------------------------
# Low-level HTTP helpers
# ------------------------------------------------------------------

def _get(path: str) -> dict | list:
    url = f"{_BASE}{path}"
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict:
    url = f"{_BASE}{path}"
    resp = requests.post(url, headers=_HEADERS, json=body, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _delete(path: str) -> dict | list:
    url = f"{_BASE}{path}"
    resp = requests.delete(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


# ------------------------------------------------------------------
# Account / clock
# ------------------------------------------------------------------

def get_account() -> dict:
    """Return Alpaca account info (equity, cash, buying_power, status, …)."""
    return _get("/v2/account")


def is_market_open() -> bool:
    """Ask Alpaca's live clock whether the market is currently open."""
    try:
        clock = _get("/v2/clock")
        return bool(clock.get("is_open", False))
    except Exception as e:
        logger.warning(f"Alpaca clock check failed: {e}")
        return False


def get_equity() -> float:
    """Return current account equity as float."""
    try:
        return float(get_account().get("equity", 0.0))
    except Exception as e:
        logger.warning(f"Could not fetch equity: {e}")
        return 0.0


# ------------------------------------------------------------------
# Positions
# ------------------------------------------------------------------

def get_position(symbol: str) -> Optional[dict]:
    """
    Return the current open position for *symbol*, or None if flat.
    """
    try:
        return _get(f"/v2/positions/{symbol}")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise


def get_all_positions() -> list[dict]:
    """Return all currently open positions."""
    return _get("/v2/positions")


# ------------------------------------------------------------------
# Orders
# ------------------------------------------------------------------

def submit_market_order(symbol: str, qty: float, side: str) -> dict:
    """
    Submit a day market order.

    Parameters
    ----------
    symbol : ticker, e.g. "AAPL"
    qty    : number of shares (fractional allowed for paper)
    side   : "buy" or "sell"

    Returns
    -------
    Alpaca order object dict.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")

    body = {
        "symbol":        symbol,
        "qty":           str(round(qty, 4)),
        "side":          side,
        "type":          "market",
        "time_in_force": "day",
    }
    logger.info(f"[Alpaca] Market {side.upper()} {qty:.4f} {symbol}")
    return _post("/v2/orders", body)


def submit_bracket_order(
    symbol:      str,
    qty:         float,
    side:        str,
    stop_loss:   Optional[float] = None,
    take_profit: Optional[float] = None,
) -> dict:
    """
    Submit a bracket order (entry + optional stop loss + optional take profit).

    Falls back to a plain market order when neither SL nor TP is provided.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")

    body: dict = {
        "symbol":        symbol,
        "qty":           str(round(qty, 4)),
        "side":          side,
        "type":          "market",
        "time_in_force": "day",
    }

    if stop_loss and take_profit:
        body["order_class"] = "bracket"
        body["stop_loss"]   = {"stop_price": str(round(stop_loss, 2))}
        body["take_profit"] = {"limit_price": str(round(take_profit, 2))}
    elif stop_loss:
        body["order_class"] = "oto"
        body["stop_loss"]   = {"stop_price": str(round(stop_loss, 2))}
    elif take_profit:
        body["order_class"] = "oto"
        body["take_profit"] = {"limit_price": str(round(take_profit, 2))}

    logger.info(
        f"[Alpaca] Bracket {side.upper()} {qty:.4f} {symbol} "
        f"SL={stop_loss} TP={take_profit}"
    )
    return _post("/v2/orders", body)


def close_position(symbol: str) -> dict:
    """
    Close the entire open position for *symbol* at market price.
    Raises HTTPError with 404 if no position exists.
    """
    logger.info(f"[Alpaca] Closing position: {symbol}")
    return _delete(f"/v2/positions/{symbol}")


def cancel_all_orders() -> list:
    """Cancel all open (pending/new) orders."""
    logger.info("[Alpaca] Cancelling all open orders")
    result = _delete("/v2/orders")
    return result if isinstance(result, list) else []


# ------------------------------------------------------------------
# Position sizing helper
# ------------------------------------------------------------------

def calculate_shares(
    price: float,
    portfolio_value: float,
    position_size_pct: float,
) -> float:
    """
    Calculate the number of shares to buy given a position-size percentage.

    Parameters
    ----------
    price              : current ask/last price
    portfolio_value    : total account equity
    position_size_pct  : fraction of portfolio per trade, e.g. 0.05 for 5%

    Returns
    -------
    Number of shares (rounded to 2 dp).
    """
    if price <= 0:
        return 0.0
    allocated = portfolio_value * position_size_pct
    return round(allocated / price, 2)
