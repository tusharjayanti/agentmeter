from agentmeter.core import Turn
from agentmeter.prices import Prices, money, normalise

P = Prices()
T = "2026-11-04T10:00:00Z"


def test_normalise_ids():
    assert normalise("us.anthropic.claude-opus-5-5-20260401[1m]") == "claude-opus-5-5"
    assert normalise("models/gemini-2.5-pro") == "gemini-2.5-pro"
    assert normalise("claude-sonnet-5-5@20260101") == "claude-sonnet-5-5"


def test_claude_turn_prices_each_kind_of_token():
    # Opus 5.5: $4 in, $20 out, $0.20 cache read, 5-minute writes 1.25x input, 1-hour writes 2x
    t = Turn(T, "claude-opus-5-5", input=1_000_000, cache_write=1_000_000, cache_read=1_000_000, output=1_000_000)
    assert P.cost(t) == 4 + 5 + 0.20 + 20
    t.cache_write_1h = 1_000_000
    assert P.cost(t) == 4 + 8 + 0.20 + 20


def test_long_prompts_cost_more_where_the_vendor_says_so():
    short = Turn(T, "gemini-2.5-pro", input=100_000, output=1_000_000)
    long = Turn(T, "gemini-2.5-pro", input=300_000, output=1_000_000)
    assert P.cost(short) == 0.125 + 10 and P.cost(long) == 0.75 + 15


def test_no_price_is_none_not_zero():
    assert P.cost(Turn(T, "mystery-1", input=10)) is None
    assert P.cost(Turn(T, "gpt-5.1-codex", input=10)) is None      # not on OpenAI's page, so no guess
    assert P.cost(Turn(T, "ollama_chat/qwen2.5-coder:7b", input=10)) == 0
    assert P.cost(Turn(T, "mystery-1", input=10, cost=0.5)) == 0.5   # a logged cost wins


def test_config_adds_and_overrides_prices():
    p = Prices({"gpt-5.1-codex": {"input": 1.25, "output": 10}, "claude-opus-5-5": {"input": 1, "output": 1}})
    assert p.cost(Turn(T, "gpt-5.1-codex", input=1_000_000, cache_read=1_000_000)) == 1.25 + 1.25   # cache_read defaults to input
    assert p.cost(Turn(T, "claude-opus-5-5", input=1_000_000)) == 1


def test_money():
    assert [money(x) for x in (None, 0, 0.004, 41.2, 1234.5)] == ["–", "$0", "<$0.01", "$41.20", "$1,234"]
