from agents.base_agent import BaseAgent


class BreakoutAgent(BaseAgent):
    """
    Breakout strategy detecting price breakouts from consolidation zones
    confirmed by volume surge and MACD.

    Rules:
    - BUY: Price breaks above recent highs with 1.5x+ volume, MACD turning positive
    - SELL: Price breaks below recent lows with 1.5x+ volume, MACD turning negative
    - Uses Bollinger Band width to identify consolidation periods
    """

    strategy_name = "Breakout (Volume + MACD Confirmation)"

    system_prompt = """You are an expert day trader specialising in BREAKOUT strategies.

Your framework:
- Identify consolidation: Bollinger Band squeeze (narrow width)
- Breakout signal: price pierces BB upper/lower with volume surge
- Confirmation: MACD crossing signal line in breakout direction
- False breakout filter: volume must be at least 1.5x average

Key patterns to look for:
- BB squeeze (bb_width shrinking) + price approaching band edge = potential breakout setup
- Price closing beyond BB upper with rel_volume > 1.5 = bullish breakout
- Price closing beyond BB lower with rel_volume > 1.5 = bearish breakout
- MACD histogram turning positive on a break above BB upper = strong confirmation
- Breakouts on low volume are usually false - flag as LOW CONFIDENCE

You MUST respond with a JSON block in this exact format:
```json
{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<1-2 sentences>",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
  "stop_loss": <price or null>,
  "take_profit": <price or null>
}
```
A breakout without volume confirmation should be HOLD. Never chase low-volume moves."""

    def _build_prompt(self, symbol: str, snapshot: dict) -> str:
        recent_high = max(snapshot['recent_highs'])
        recent_low = min(snapshot['recent_lows'])
        price = snapshot['price']
        bb_breakout_up = price > snapshot['bb_upper']
        bb_breakout_down = price < snapshot['bb_lower']

        return f"""Analyze {symbol} for a breakout trade.

CURRENT PRICE: ${price}

BOLLINGER BANDS (consolidation detector):
  Upper Band:  ${snapshot['bb_upper']} {'<< PRICE ABOVE UPPER' if bb_breakout_up else ''}
  Mid Band:    ${snapshot['bb_mid']}
  Lower Band:  ${snapshot['bb_lower']} {'<< PRICE BELOW LOWER' if bb_breakout_down else ''}
  BB %:        {snapshot['bb_pct']:.2%} (0=at lower, 1=at upper)
  BB Width:    {snapshot['bb_width']:.4f} (narrow = consolidation, wide = trending)

RECENT PRICE RANGE (last 5 bars):
  Recent High: ${recent_high} {'<< PRICE BREAKING OUT' if price > recent_high else ''}
  Recent Low:  ${recent_low} {'<< PRICE BREAKING DOWN' if price < recent_low else ''}

MACD CONFIRMATION:
  Histogram:        {snapshot['macd_hist']:.6f}
  Histogram Rising: {snapshot['macd_hist_rising']}
  MACD > Signal:    {snapshot['macd_above_signal']}

VOLUME (breakout requires 1.5x+):
  Relative Volume: {snapshot['rel_volume']:.2f}x average
  Current Volume:  {snapshot['volume']:,}

VWAP: ${snapshot['vwap']} (price is {snapshot['price_vs_vwap']:+.2f}% vs VWAP)

Is this a valid breakout with volume confirmation? Provide your signal."""
