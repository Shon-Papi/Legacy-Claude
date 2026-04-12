from dataclasses import dataclass, field
from agents.base_agent import AgentSignal, Signal
from config import config


@dataclass
class ConfluenceResult:
    symbol: str
    final_signal: Signal
    confluence_score: float      # 0.0 to 1.0
    vote_breakdown: dict         # signal -> count
    weighted_score: float        # net directional score (-1 to +1)
    top_signals: list[AgentSignal] = field(default_factory=list)
    all_signals: list[AgentSignal] = field(default_factory=list)
    threshold_met: bool = False
    summary: str = ""

    def __repr__(self) -> str:
        votes = " | ".join(f"{k}:{v}" for k, v in self.vote_breakdown.items())
        return (
            f"[{self.symbol}] {self.final_signal.value} "
            f"(score={self.confluence_score:.0%}, votes={votes}, "
            f"threshold={'MET' if self.threshold_met else 'NOT MET'})"
        )


def detect_confluence(symbol: str, signals: list[AgentSignal]) -> ConfluenceResult:
    """
    Aggregate agent signals into a confluence result.

    Scoring:
    - Each BUY contributes +confidence to a positive score
    - Each SELL contributes -confidence to a score
    - HOLD contributes 0
    - Weighted score normalized to [-1, +1]
    - Confluence score = |weighted_score| when threshold is met
    """
    if not signals:
        return ConfluenceResult(
            symbol=symbol,
            final_signal=Signal.HOLD,
            confluence_score=0.0,
            vote_breakdown={"BUY": 0, "SELL": 0, "HOLD": 0},
            weighted_score=0.0,
            threshold_met=False,
            summary="No signals available.",
        )

    vote_breakdown = {"BUY": 0, "SELL": 0, "HOLD": 0}
    for s in signals:
        vote_breakdown[s.signal.value] += 1

    buy_signals = [s for s in signals if s.signal == Signal.BUY]
    sell_signals = [s for s in signals if s.signal == Signal.SELL]

    buy_score = sum(s.confidence for s in buy_signals)
    sell_score = sum(s.confidence for s in sell_signals)

    total_possible = sum(s.confidence for s in signals)
    weighted_score = (buy_score - sell_score) / max(total_possible, 1e-9)

    # Determine dominant direction
    if buy_score > sell_score:
        final_signal = Signal.BUY
        dominant_signals = buy_signals
        confluence_score = buy_score / total_possible if total_possible > 0 else 0.0
        agreement_count = len(buy_signals)
    elif sell_score > buy_score:
        final_signal = Signal.SELL
        dominant_signals = sell_signals
        confluence_score = sell_score / total_possible if total_possible > 0 else 0.0
        agreement_count = len(sell_signals)
    else:
        final_signal = Signal.HOLD
        dominant_signals = []
        confluence_score = 0.0
        agreement_count = 0

    threshold_met = agreement_count >= config.CONFLUENCE_THRESHOLD

    # Sort dominant signals by confidence for display
    top_signals = sorted(dominant_signals, key=lambda s: s.confidence, reverse=True)

    summary = _build_summary(symbol, final_signal, vote_breakdown, confluence_score, threshold_met, top_signals)

    return ConfluenceResult(
        symbol=symbol,
        final_signal=final_signal,
        confluence_score=confluence_score,
        vote_breakdown=vote_breakdown,
        weighted_score=weighted_score,
        top_signals=top_signals,
        all_signals=signals,
        threshold_met=threshold_met,
        summary=summary,
    )


def _build_summary(
    symbol: str,
    signal: Signal,
    votes: dict,
    score: float,
    threshold_met: bool,
    top_signals: list[AgentSignal],
) -> str:
    lines = [
        f"{'='*60}",
        f"CONFLUENCE ANALYSIS: {symbol}",
        f"{'='*60}",
        f"Final Signal:    {signal.value}",
        f"Confluence Score:{score:.0%}",
        f"Threshold Met:   {'YES ✓' if threshold_met else 'NO ✗'} (need {config.CONFLUENCE_THRESHOLD}+ agents)",
        f"Votes:           BUY={votes['BUY']} | SELL={votes['SELL']} | HOLD={votes['HOLD']}",
        "",
        "AGENT SIGNALS:",
    ]
    for s in top_signals:
        lines.append(f"  [{s.strategy_name}] → {s.signal.value} ({s.confidence:.0%})")
        lines.append(f"    Reason: {s.reasoning[:100]}...")
    lines.append(f"{'='*60}")
    return "\n".join(lines)
