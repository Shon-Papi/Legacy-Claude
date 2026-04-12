from agents.base_agent import BaseAgent


class MeanReversionAgent(BaseAgent):
    """
    Mean Reversion strategy using Bollinger Bands and RSI extremes.

    Rules:
    - BUY: Price at/below lower BB, RSI < 35, MACD histogram showing deceleration of selling
    - SELL: Price at/above upper BB, RSI > 65, MACD histogram showing deceleration of buying
    - Target: reversion to BB mid (20 EMA) or VWAP
    """

    strategy_name = "Mean Reversion (BB + RSI Extremes)"

    system_prompt = """You are an expert day trader specialising in MEAN REVERSION strategies.

Your philosophy:
- Markets oscillate around a mean (VWAP, BB mid, EMAs)
- Extreme moves away from mean create high-probability reversion setups
- You FADE momentum, not follow it
- You look for exhaustion signals, not continuation

Setup criteria:
- Price stretched far from VWAP or BB mid = potential reversion zone
- RSI < 30 (oversold) or RSI > 70 (overbought) = extreme reading
- MACD histogram decelerating = momentum fading (key timing signal)
- Volume declining on the move = buyers/sellers exhausted

Trade management:
- Stop: beyond the recent extreme
- Target: VWAP or BB mid band

IMPORTANT: Do NOT signal BUY on RSI < 30 if MACD is still strongly negative (trend may continue).
Look for the COMBINATION: stretched price + extreme RSI + DECELERATING MACD histogram.

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
High confidence only when ALL conditions align: stretched price, RSI extreme, AND fading MACD."""

    def _build_prompt(self, symbol: str, snapshot: dict) -> str:
        price = snapshot['price']
        rsi = snapshot['rsi']
        bb_pct = snapshot['bb_pct']

        oversold = rsi < 35
        overbought = rsi > 65
        at_lower_bb = bb_pct < 0.15
        at_upper_bb = bb_pct > 0.85
        hist_fading = abs(snapshot['macd_hist']) < abs(snapshot['macd_hist_prev'])

        conditions = []
        if oversold: conditions.append("RSI OVERSOLD")
        if overbought: conditions.append("RSI OVERBOUGHT")
        if at_lower_bb: conditions.append("PRICE AT LOWER BB")
        if at_upper_bb: conditions.append("PRICE AT UPPER BB")
        if hist_fading: conditions.append("MACD HISTOGRAM FADING")

        return f"""Analyze {symbol} for a mean-reversion trade.

CURRENT PRICE: ${price}

RSI EXTREMES (oversold <35, overbought >65):
  RSI:      {rsi:.1f} {'<< OVERSOLD' if oversold else '<< OVERBOUGHT' if overbought else ''}
  RSI Prev: {snapshot['rsi_prev']:.1f}

PRICE STRETCH (how far from mean?):
  BB %:          {bb_pct:.2%} (0=at lower band, 1=at upper band)
  Price vs VWAP: {snapshot['price_vs_vwap']:+.2f}%
  Price vs EMA21:{snapshot['price_vs_ema21']:+.2f}%
  Price vs EMA50:{snapshot['price_vs_ema50']:+.2f}%

BOLLINGER BANDS:
  Upper: ${snapshot['bb_upper']}
  Mid:   ${snapshot['bb_mid']} (reversion target)
  Lower: ${snapshot['bb_lower']}

VWAP: ${snapshot['vwap']} (secondary reversion target)

MACD EXHAUSTION CHECK:
  Histogram:       {snapshot['macd_hist']:.6f}
  Prev Histogram:  {snapshot['macd_hist_prev']:.6f}
  Histogram Fading:{hist_fading} {'<< MOMENTUM SLOWING' if hist_fading else ''}

CONDITIONS MET: {', '.join(conditions) if conditions else 'None - price near mean, no reversion setup'}

VOLUME: Relative = {snapshot['rel_volume']:.2f}x
  (Declining volume on extreme = exhaustion signal)

Is there a high-probability mean-reversion setup? Provide your signal."""
