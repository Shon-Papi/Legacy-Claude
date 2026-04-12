from agents.base_agent import BaseAgent


class VWAPScalperAgent(BaseAgent):
    """
    VWAP Scalping strategy - uses VWAP as the anchor price level.

    Rules:
    - BUY: Price dips below VWAP then reclaims it, with MACD turning positive
    - SELL: Price rallies above VWAP then loses it, with MACD turning negative
    - VWAP acts as dynamic S/R, combined with EMA9 for short-term momentum
    """

    strategy_name = "VWAP Scalper (VWAP + EMA9 + MACD)"

    system_prompt = """You are an expert day trader specialising in VWAP-based SCALPING strategies.

Your core belief:
- VWAP is the fair value price institutions use as a benchmark
- Price hovering above VWAP = institutional buying; below = institutional selling
- The best trades occur when price RECLAIMS or LOSES VWAP with conviction

Setup types:
1. VWAP Reclaim (BUY): Price was below VWAP, pushes back above it, EMA9 turning up, MACD going positive
2. VWAP Rejection (SELL): Price was above VWAP, falls back below, EMA9 turning down, MACD going negative
3. VWAP Bounce (BUY): Price touches VWAP from above and bounces, RSI not overbought
4. VWAP Rejection from below (SELL): Price tries to break VWAP from below and fails

Key filters:
- Only take VWAP setups when MACD confirms direction
- EMA9 relative to VWAP confirms intraday trend
- Avoid trades when price is far from VWAP (>0.5%) - too risky

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
HOLD if price is not near VWAP. SCALP setups require precision - only signal when setup is clear."""

    def _build_prompt(self, symbol: str, snapshot: dict) -> str:
        price = snapshot['price']
        vwap = snapshot['vwap']
        pct_vs_vwap = snapshot['price_vs_vwap']
        ema9_vs_vwap = round((snapshot['ema9'] - vwap) / vwap * 100, 3)

        near_vwap = abs(pct_vs_vwap) < 0.5

        # Determine VWAP relative position over recent bars
        recent_closes = snapshot['recent_closes']
        prices_above_vwap = sum(1 for p in recent_closes if p > vwap)
        vwap_relationship = f"{prices_above_vwap}/5 recent bars above VWAP"

        return f"""Analyze {symbol} for a VWAP scalp trade.

CURRENT PRICE: ${price}
VWAP: ${vwap}
PRICE VS VWAP: {pct_vs_vwap:+.3f}% {'<< NEAR VWAP - SETUP POSSIBLE' if near_vwap else '<< FAR FROM VWAP - LOW PRIORITY'}

VWAP CONTEXT:
  EMA9 vs VWAP: {ema9_vs_vwap:+.3f}%
  {vwap_relationship}
  Recent Closes: {recent_closes}

MACD CONFIRMATION:
  Histogram:       {snapshot['macd_hist']:.6f}
  Prev Histogram:  {snapshot['macd_hist_prev']:.6f}
  MACD > Signal:   {snapshot['macd_above_signal']}
  Histogram Rising:{snapshot['macd_hist_rising']}

EMA INTRADAY TREND:
  EMA9:  ${snapshot['ema9']}
  EMA21: ${snapshot['ema21']}
  Price vs EMA9: {snapshot['price_vs_ema9']:+.2f}%

RSI: {snapshot['rsi']:.1f}

VOLUME:
  Relative Volume: {snapshot['rel_volume']:.2f}x average

Is there a clear VWAP reclaim, rejection, or bounce setup? Provide your scalp signal."""
