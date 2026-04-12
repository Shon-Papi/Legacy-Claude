"""
NewsBiasAgent — establishes the directional market bias for the trading session.

Runs at market open and every NEWS_BIAS_INTERVAL minutes. Uses Claude's
server-side web_search tool to scan:
  - Pre-market futures and sentiment
  - Scheduled economic releases today (CPI, PPI, FOMC minutes, NFP, etc.)
  - Overnight news and major headlines
  - Sector rotation and institutional flow signals

Returns BULLISH / BEARISH / NEUTRAL with a confidence score that the
orchestrator uses to filter which confluence signals it acts on.
"""
import json
import logging
import re
from datetime import datetime

import anthropic

from config import config
from core.trading_state import trading_state

logger = logging.getLogger(__name__)

_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

_SYSTEM = """You are a senior macro analyst and market strategist responsible for setting
the directional bias that governs a day-trading system.

Your job is to synthesise today's news, economic data, and market conditions into ONE
clear directional view: BULLISH, BEARISH, or NEUTRAL.

Sources to weight (in order of importance):
1. Scheduled high-impact economic releases (CPI, PPI, FOMC, NFP, GDP, ISM) — did they beat/miss?
2. Pre-market S&P 500 / Nasdaq futures direction and magnitude
3. Federal Reserve communications (speeches, minutes, rate expectations)
4. Geopolitical risk (tariffs, trade wars, military conflict, sanctions)
5. Major corporate earnings surprises (especially mega-caps: AAPL, NVDA, MSFT, AMZN, META)
6. Credit markets: VIX level and direction, HY spreads
7. Currency and commodities (DXY strength, oil, gold as risk proxies)

Output rules:
- BULLISH: clear tailwinds, beats on data, constructive futures, risk-on conditions
- BEARISH: headwinds, misses on data, negative futures, risk-off conditions
- NEUTRAL: mixed signals, no strong edge, or major uncertainty ahead

You MUST use web_search to gather CURRENT information. Do NOT rely on training data for today's news.

After gathering information, respond ONLY with this JSON block:
```json
{
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<2-3 sentences explaining the bias>",
  "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
  "upcoming_events": ["<event1 with time>", "<event2 with time>"],
  "risk_level": "LOW" | "MEDIUM" | "HIGH"
}
```
Be decisive. Confidence < 0.5 should default to NEUTRAL."""


def _call_with_websearch(user_message: str) -> str:
    """Call Claude with web_search tool, handling pause_turn continuations."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    for _ in range(6):  # max continuations for server-side tool loops
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            tools=[_WEB_SEARCH_TOOL],
            messages=messages,
        )

        text = "".join(b.text for b in response.content if b.type == "text")

        if response.stop_reason == "end_turn":
            return text

        if response.stop_reason == "pause_turn":
            # Server-side tool loop hit iteration limit — re-send to continue
            messages.append({"role": "assistant", "content": response.content})
            continue

        # tool_use or anything else — keep going
        messages.append({"role": "assistant", "content": response.content})

    return text


def _parse_bias_response(text: str) -> dict:
    """Extract the JSON block from the LLM response."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: scan for bare JSON object
    match = re.search(r'\{[^{}]*"bias"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse bias JSON; defaulting to NEUTRAL")
    return {
        "bias": "NEUTRAL",
        "confidence": 0.4,
        "reasoning": "Unable to parse structured response from news scan.",
        "key_factors": [],
        "upcoming_events": [],
        "risk_level": "MEDIUM",
    }


def run_news_bias_check() -> None:
    """
    Perform a full news scan and update TradingState with today's market bias.
    Called by the orchestrator at the start of each session and every
    NEWS_BIAS_INTERVAL minutes thereafter.
    """
    now = datetime.now()
    print(f"\n📰 [NewsBiasAgent] Running market bias scan at {now.strftime('%H:%M:%S')}...")

    user_message = (
        f"Today is {now.strftime('%A, %B %d, %Y')}. Current time: {now.strftime('%H:%M')} ET.\n\n"
        "Search for:\n"
        "1. US stock market futures right now (S&P 500, Nasdaq, Dow pre-market)\n"
        "2. Any economic data released today or scheduled in the next 2 hours "
        "(CPI, PPI, NFP, FOMC, GDP, ISM, retail sales, jobless claims)\n"
        "3. Major market-moving news from the last 12 hours\n"
        "4. Current VIX level and whether it's elevated\n"
        "5. Any Federal Reserve speeches or communications today\n\n"
        "Based on ALL of this, set the market bias for today's trading session."
    )

    try:
        raw = _call_with_websearch(user_message)
        data = _parse_bias_response(raw)

        bias = data.get("bias", "NEUTRAL")
        confidence = float(data.get("confidence", 0.5))
        reasoning = data.get("reasoning", "")
        key_factors = data.get("key_factors", [])
        upcoming = data.get("upcoming_events", [])
        risk = data.get("risk_level", "MEDIUM")

        trading_state.update_bias(bias, confidence, reasoning, key_factors)

        # Log upcoming events for the event guard to pick up
        for event in upcoming:
            trading_state.log_event(f"UPCOMING: {event}")

        print(
            f"   Bias:      {bias} ({confidence:.0%} confidence)\n"
            f"   Risk:      {risk}\n"
            f"   Reasoning: {reasoning[:120]}\n"
            f"   Factors:   {', '.join(key_factors[:3])}"
        )
        if upcoming:
            print(f"   Upcoming:  {' | '.join(upcoming[:3])}")

    except Exception as e:
        logger.error(f"NewsBiasAgent error: {e}", exc_info=True)
        trading_state.update_bias("NEUTRAL", 0.3, f"Bias scan failed: {e}", [])
