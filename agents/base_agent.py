import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import anthropic
from config import config


def extract_json_block(text: str, fallback_key: str = "") -> dict:
    """
    Extract the first JSON code block from an LLM response.
    Falls back to scanning for a bare JSON object containing *fallback_key*.
    Returns an empty dict if nothing parseable is found.
    """
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    if fallback_key:
        pattern = rf'\{{[^{{}}]*"{re.escape(fallback_key)}"[^{{}}]*\}}'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class AgentSignal:
    agent_name: str
    strategy_name: str
    signal: Signal
    confidence: float        # 0.0 to 1.0
    reasoning: str
    key_factors: list[str]
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def __repr__(self) -> str:
        return (
            f"[{self.agent_name}] {self.signal.value} "
            f"(confidence={self.confidence:.0%}) | {self.reasoning[:80]}..."
        )


class BaseAgent:
    """Base class for all strategy agents powered by Claude."""

    strategy_name: str = "Base Strategy"
    system_prompt: str = "You are a trading agent."

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def analyze(self, symbol: str, snapshot: dict) -> AgentSignal:
        """Analyze market data and return a trading signal."""
        user_message = self._build_prompt(symbol, snapshot)

        response = self._client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        # Extract text from response (skip thinking blocks)
        text = ""
        for block in response.content:
            if block.type == "text":
                text = block.text
                break

        return self._parse_response(text, symbol, snapshot)

    def _build_prompt(self, symbol: str, snapshot: dict) -> str:
        raise NotImplementedError

    def _parse_response(self, text: str, symbol: str, snapshot: dict) -> AgentSignal:
        """Parse the LLM response into a structured AgentSignal."""
        data = extract_json_block(text, fallback_key="signal")
        if data:
            try:
                return AgentSignal(
                    agent_name=self.__class__.__name__,
                    strategy_name=self.strategy_name,
                    signal=Signal(data.get("signal", "HOLD").upper()),
                    confidence=float(data.get("confidence", 0.5)),
                    reasoning=data.get("reasoning", ""),
                    key_factors=data.get("key_factors", []),
                    stop_loss=data.get("stop_loss"),
                    take_profit=data.get("take_profit"),
                )
            except (KeyError, ValueError):
                pass

        # Fallback: parse signal keyword from raw text
        text_upper = text.upper()
        if "BUY" in text_upper and "SELL" not in text_upper:
            signal = Signal.BUY
        elif "SELL" in text_upper and "BUY" not in text_upper:
            signal = Signal.SELL
        else:
            signal = Signal.HOLD

        conf_match = re.search(r"confidence[:\s]+([0-9.]+)", text, re.IGNORECASE)
        confidence = float(conf_match.group(1)) if conf_match else 0.5
        if confidence > 1.0:
            confidence /= 100.0

        return AgentSignal(
            agent_name=self.__class__.__name__,
            strategy_name=self.strategy_name,
            signal=signal,
            confidence=min(max(confidence, 0.0), 1.0),
            reasoning=text[:300],
            key_factors=[],
        )
