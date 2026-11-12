"""What the tokens would cost at each vendor's published API prices.

This is an estimate of "API-equivalent" cost. On a subscription (Claude Pro/Max, ChatGPT Plus/Pro,
a Google login) it is not your bill; it is what the same tokens would cost on pay-as-you-go.

Prices are US dollars per million tokens, copied from the vendors' pricing pages on AS_OF:
  Anthropic  https://platform.claude.com/docs/en/about-claude/pricing
  OpenAI     https://developers.openai.com/api/docs/pricing
  Google     https://aistudio.google.com/docs/pricing
A model id is matched exactly (after dropping date suffixes and platform prefixes), so a model
missing here has no price rather than a wrong one. Add or correct prices in config:

  "prices": {"gpt-5.1-codex": {"input": 1.25, "cache_read": 0.125, "output": 10}}

Fields: input, output, cache_read, cache_write (5-minute cache), cache_write_1h. Missing
cache fields default to the input price (cache_read) and the input price (cache_write).
"""
from __future__ import annotations

import re

AS_OF = "2026-11-12"


def _claude(inp, out, read):
    # Anthropic: 5-minute cache writes cost 1.25x input, 1-hour writes 2x
    return {"input": inp, "output": out, "cache_read": read, "cache_write": inp * 1.25, "cache_write_1h": inp * 2}


def _cached(inp, out, read):
    # OpenAI and Google bill no cache writes; cached input is the cache read
    return {"input": inp, "output": out, "cache_read": read, "cache_write": inp, "cache_write_1h": inp}


def _long(base, over, inp, out):
    """A higher price for turns whose prompt (input incl. cached) is above `over` tokens.
    Only input and output prices are published for some of these; cache prices scale with input."""
    k = inp / base["input"]
    return {**base, "long": (over, {**base, "input": inp, "output": out, "cache_read": base["cache_read"] * k,
                                    "cache_write": base["cache_write"] * k, "cache_write_1h": base["cache_write_1h"] * k})}


_HAIKU_55 = _claude(0.10, 0.50, 0.01)

BUILTIN = {
    # Anthropic (Claude Code). Cache reads per the pricing page; they differ by model.
    "claude-fable-5-2": _claude(8, 40, 0.20),
    "claude-mythos-5-2": _claude(8, 40, 0.20),
    "claude-fable-5-1": _claude(10, 50, 0.25),
    "claude-mythos-5-1": _claude(10, 50, 0.25),
    "claude-fable-5": _claude(10, 50, 1.00),
    "claude-mythos-5": _claude(10, 50, 1.00),
    "claude-opus-5-5": _claude(4, 20, 0.20),
    "claude-opus-5": _claude(5, 25, 0.50),
    "claude-opus-4-8": _claude(5, 25, 0.50),
    "claude-opus-4-7": _claude(5, 25, 0.50),
    "claude-opus-4-6": _claude(5, 25, 0.50),
    "claude-sonnet-5-5": _claude(2, 10, 0.10),
    "claude-sonnet-5": _claude(2, 10, 0.20),
    "claude-sonnet-4-6": _claude(3, 15, 0.30),
    "claude-haiku-5-5": _long(_HAIKU_55, 100_000, 0.50, 2.50),
    "claude-haiku-4-5": _claude(1, 5, 0.10),
    # OpenAI (Codex CLI). Long context = more than 272K input tokens.
    "gpt-5.6-sol": _long(_cached(4, 20, 0.40), 272_000, 8, 30),
    "gpt-5.6-terra": _long(_cached(2, 12, 0.20), 272_000, 4, 18),
    "gpt-5.6-luna": _long(_cached(0.20, 1.20, 0.02), 272_000, 0.40, 1.80),
    "gpt-5.5": _long(_cached(5, 30, 0.50), 272_000, 10, 45),
    "gpt-5.5-pro": _long(_cached(30, 180, 30), 272_000, 60, 270),
    "gpt-5.4": _long(_cached(2.50, 15, 0.25), 272_000, 5, 22.50),
    "gpt-5.4-pro": _long(_cached(30, 180, 30), 272_000, 60, 270),
    "gpt-5.4-mini": _cached(0.75, 4.50, 0.075),
    "gpt-5.4-nano": _cached(0.20, 1.25, 0.02),
    "gpt-5.3-codex": _cached(1.75, 14, 0.175),
    "gpt-5.2": _cached(1.75, 14, 0.175),
    "gpt-5.2-pro": _cached(21, 168, 21),
    "gpt-5.1": _cached(1.25, 10, 0.125),
    "gpt-5": _cached(1.25, 10, 0.125),
    "gpt-5-mini": _cached(0.25, 2, 0.025),
    "gpt-5-nano": _cached(0.05, 0.40, 0.005),
    "gpt-5-pro": _cached(15, 120, 15),
    # Google (Gemini CLI). Pro models cost more above 200K prompt tokens.
    "gemini-3.8-flash": _cached(0.75, 3.75, 0.075),
    "gemini-3.6-flash": _cached(0.75, 3.75, 0.075),
    "gemini-3.5-flash-lite": _cached(0.30, 2.50, 0.03),
    "gemini-3.1-pro-preview": {**_cached(2, 12, 0.20), "long": (200_000, _cached(4, 18, 0.40))},
    "gemini-3.1-flash-lite": _cached(0.25, 1.50, 0.025),
    "gemini-3-flash-preview": _cached(0.50, 3, 0.05),
    "gemini-2.5-pro": {**_cached(1.25, 10, 0.125), "long": (200_000, _cached(2.50, 15, 0.25))},
    "gemini-2.5-flash": _cached(0.30, 2.50, 0.03),
    "gemini-2.5-flash-lite": _cached(0.10, 0.40, 0.01),
}

FREE = re.compile(r"^(ollama|ollama_chat|lm_studio|lmstudio|llamacpp|local)/", re.I)   # runs on your machine


def normalise(model: str) -> str:
    """'us.anthropic.claude-opus-5-5-20260401[1m]' -> 'claude-opus-5-5'; 'models/gemini-2.5-pro' -> 'gemini-2.5-pro'."""
    m = (model or "").strip().lower()
    m = re.sub(r"\[.*?\]$", "", m)
    m = re.sub(r"^(models/|openai/|anthropic/|google/|gemini/|(\w+\.)?anthropic\.)", "", m)
    m = re.sub(r"(-\d{8}|@\d{8}|-v\d+(:\d+)?)$", "", m)
    return m


class Prices:
    def __init__(self, overrides: dict | None = None):
        self.table = dict(BUILTIN)
        for name, p in (overrides or {}).items():
            inp = float(p.get("input", 0))
            self.table[normalise(name)] = {"input": inp, "output": float(p.get("output", 0)),
                                           "cache_read": float(p.get("cache_read", inp)),
                                           "cache_write": float(p.get("cache_write", inp)),
                                           "cache_write_1h": float(p.get("cache_write_1h", p.get("cache_write", inp)))}

    def rates(self, model: str) -> dict | None:
        if FREE.match(model or ""):
            return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cache_write_1h": 0}
        return self.table.get(normalise(model))

    def cost(self, turn) -> float | None:
        """Dollars for one turn, or None when the model has no price. A cost the tool logged itself wins."""
        if turn.cost is not None:
            return turn.cost
        r = self.rates(turn.model)
        if r is None:
            return None
        prompt = turn.input + turn.cache_write + turn.cache_read
        if "long" in r and prompt > r["long"][0]:
            r = r["long"][1]
        w1h = min(turn.cache_write_1h, turn.cache_write)
        return (turn.input * r["input"] + (turn.cache_write - w1h) * r["cache_write"] + w1h * r["cache_write_1h"]
                + turn.cache_read * r["cache_read"] + turn.output * r["output"]) / 1e6


def money(x) -> str:
    """'$41.20', '$1,234', '<$0.01', or '–' for no price."""
    if x is None:
        return "–"
    if x == 0:
        return "$0"
    if x < 0.01:
        return "<$0.01"
    return f"${x:,.0f}" if x >= 1000 else f"${x:,.2f}"
