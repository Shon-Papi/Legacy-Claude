"""Shared Claude web-search helper for EventGuardAgent and NewsBiasAgent."""
import anthropic
from config import config

_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


def call_with_websearch(user_message: str, system: str, max_tokens: int = 1024) -> str:
    """Call Claude with the web_search tool, handling pause_turn continuations."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": user_message}]

    for _ in range(6):
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            tools=[_WEB_SEARCH_TOOL],
            messages=messages,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason == "end_turn":
            return text
        messages.append({"role": "assistant", "content": response.content})

    return text
