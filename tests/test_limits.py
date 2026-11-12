import datetime as dt
import json
import os

from agentmeter import limits
from agentmeter.prices import split

NOW = dt.datetime(2026, 11, 12, 16, 30, tzinfo=dt.timezone.utc).astimezone()


def _claude(tmp_path, util):
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"secret": "not read"},
                                                       "cachedUsageUtilization": {"fetchedAtMs": 1794479411771, "utilization": util}}))
    os.environ["CLAUDE_CONFIG_DIR"] = str(tmp_path)


def test_claude_limits_from_its_cached_reading(tmp_path):
    _claude(tmp_path, {"limits": [
        {"kind": "session", "percent": 4, "resets_at": "2026-11-12T14:59:59+00:00"},
        {"kind": "weekly_all", "percent": 1, "resets_at": "2026-11-17T03:59:59+00:00"},
        {"kind": "weekly_scoped", "percent": 0, "resets_at": "2026-11-17T04:00:00+00:00",
         "scope": {"model": {"display_name": "Fable"}}}]})
    try:
        got = limits.claude(NOW)
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR")
    assert [(x["name"], x["percent"], x["stale"]) for x in got] == [("5-hour", 4, True), ("week", 1, False), ("week (Fable)", 0, False)]
    assert got[0]["as_of"].startswith("2026-11-12") and limits.short(got[0], NOW) == "reset since"


def test_claude_older_shape_and_bad_files(tmp_path):
    _claude(tmp_path, {"five_hour": {"utilization": 62, "resets_at": "2026-11-12T20:00:00+00:00"},
                       "seven_day": {"utilization": 81, "resets_at": "2026-11-17T04:00:00+00:00"}})
    try:
        assert [(x["name"], x["percent"]) for x in limits.claude(NOW)] == [("5-hour", 62), ("week", 81)]
        (tmp_path / ".claude.json").write_text("{not json")
        assert limits.claude(NOW) == []
        (tmp_path / ".claude.json").write_text('{"cachedUsageUtilization": "changed format"}')
        assert limits.claude(NOW) == []
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR")


def test_codex_limits_from_its_session_log(tmp_path):
    d = tmp_path / "2026" / "11" / "12"; d.mkdir(parents=True)
    ev = lambda ts, p, s: {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": None, "rate_limits": {
        "primary": {"used_percent": p, "window_minutes": 300, "resets_at": 1794500000},
        "secondary": {"used_percent": s, "window_minutes": 10080, "resets_at": 1795000000}}}}
    d.joinpath("rollout-2026-11-12T10-00-00-abc.jsonl").write_text(
        json.dumps(ev("2026-11-12T10:00:00Z", 10.0, 20.0)) + "\n" + json.dumps(ev("2026-11-12T11:00:00Z", 35.5, 41.0)) + "\n")
    got = limits.codex(tmp_path, NOW)
    assert [(x["tool"], x["name"], x["percent"]) for x in got] == [("Codex", "5-hour", 36), ("Codex", "week", 41)]
    assert got[0]["as_of"].startswith("2026-11-12") and limits.codex(tmp_path / "none", NOW) == []


def test_cost_split_largest_first():
    assert split({"output": 2.37, "cache_read": 5.4, "cache_write": 2.68, "input": 0.001}) == \
        "cache reads $5.40 · cache writes $2.68 · output $2.37"
