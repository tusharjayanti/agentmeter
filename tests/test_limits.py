import datetime as dt
import json
import os

import pytest

from agentmeter import claude_settings, limits
from agentmeter.prices import split

NOW = dt.datetime(2026, 11, 12, 16, 30, tzinfo=dt.timezone.utc).astimezone()


@pytest.fixture(autouse=True)
def own_status_file(tmp_path, monkeypatch):
    """Never read or write the real saved status line reading."""
    monkeypatch.setattr(limits, "STATUS_FILE", str(tmp_path / "sl" / "claude.json"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))     # nor the real /usage copy


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
    assert got[0]["as_of"].startswith("2026-11-12") and limits.short(got[0], NOW).startswith("reset at ")


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


def _sl(five, week=None, five_reset=1794600000, week_reset=1795000000):
    rl = {"five_hour": {"used_percentage": five, "resets_at": five_reset}}
    if week is not None:
        rl["seven_day"] = {"used_percentage": week, "resets_at": week_reset}
    return {"session_id": "x", "rate_limits": rl}


def test_status_line_reading_is_kept_and_used():
    assert limits.record_statusline(_sl(23.5, 41.2), NOW)
    got = limits.claude(NOW)
    assert [(x["name"], x["percent"], x["stale"]) for x in got] == [("5-hour", 24, False), ("week", 41, False)]
    assert limits.source(NOW) == "statusline"
    # a later reading without the weekly window (Claude Code drops a window once it resets) keeps the old one
    later = NOW + dt.timedelta(minutes=5)
    assert limits.record_statusline(_sl(30.0), later)
    got = limits.claude(later)
    assert [(x["name"], x["percent"]) for x in got] == [("5-hour", 30), ("week", 41)]


def test_status_line_input_without_limits_writes_nothing():
    assert not limits.record_statusline({"session_id": "x"}, NOW)       # API-key users: no rate_limits
    assert not limits.record_statusline("not a dict", NOW)
    assert not limits.record_statusline({"rate_limits": {"five_hour": "odd"}}, NOW)
    assert limits.claude(NOW) == [] or limits.source(NOW) != "statusline"


def test_newer_reading_wins(tmp_path):
    _claude(tmp_path, {"limits": [{"kind": "session", "percent": 90, "resets_at": "2026-11-12T20:00:00+00:00"}]})
    try:
        limits.record_statusline(_sl(10.0), NOW)                         # status line reading: now
        assert limits.claude(NOW)[0]["percent"] == 10 and limits.source(NOW) == "statusline"
        limits.record_statusline(_sl(10.0), dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))   # older than /usage copy
        assert limits.claude(NOW)[0]["percent"] == 90 and limits.source(NOW) == "usage"
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR")


def test_reset_window_says_when():
    past = int((NOW - dt.timedelta(hours=1)).timestamp())
    limits.record_statusline(_sl(80.0, five_reset=past), NOW - dt.timedelta(hours=2))
    (row,) = limits.claude(NOW)
    assert row["stale"] and limits.short(row, NOW) == f"reset at {(NOW - dt.timedelta(hours=1)):%H:%M}"


def test_claude_settings_status_line(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(ls)"]}}))
    assert claude_settings.status() == ""
    assert claude_settings.install().startswith("on")
    d = json.loads(f.read_text())
    assert d["model"] == "opus" and d["permissions"] == {"allow": ["Bash(ls)"]}          # everything else kept
    assert d["statusLine"]["type"] == "command" and d["statusLine"]["command"].endswith("agentmeter statusline")
    assert claude_settings.status() == "agentmeter" and claude_settings.install() == "already on"
    assert claude_settings.remove().startswith("off") and "statusLine" not in json.loads(f.read_text())
    f.write_text(json.dumps({"statusLine": {"type": "command", "command": "~/my-line.sh"}}))
    assert claude_settings.status() == "other" and claude_settings.install().startswith("not changed")
    assert json.loads(f.read_text())["statusLine"]["command"] == "~/my-line.sh"           # someone else's is never replaced
    assert claude_settings.remove() == "nothing to remove"
    f.write_text("{broken")
    assert claude_settings.status() == "unreadable" and claude_settings.install().startswith("not changed")
