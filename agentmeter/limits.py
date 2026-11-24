"""Plan limits (5-hour and weekly), read from what the tools already keep on disk. No network.

Claude Code, two sources; the newer reading wins:
  1. Its status line (documented: https://code.claude.com/docs/en/statusline.md). With `agentmeter
     statusline` set as the status line command (agentmeter setup offers it), Claude Code passes
     `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}` after every reply, and
     record_statusline() keeps the last reading in ~/.local/share/agentmeter/limits/claude.json.
  2. ~/.claude.json (or $CLAUDE_CONFIG_DIR/.claude.json), key `cachedUsageUtilization`: the copy /usage
     saves, with `fetchedAtMs`. Internal to Claude Code and only refreshed when /usage is opened, so it is
     the fallback. Only these fields are read; the rest of that file (account settings) is ignored.
  Anything unexpected in either gives no limits rather than an error.
Codex CLI: the newest rollout file's last `event_msg` / `token_count` event with `rate_limits`
  {primary, secondary: {used_percent, window_minutes, resets_at (unix seconds)}}, as defined in
  codex-rs/protocol (RateLimitSnapshot). Its time is the event's timestamp.

Each reading is only as fresh as the tool's last fetch, so it carries `as_of`; a window whose reset
time has passed is marked stale: its percentage no longer applies, and it is shown as "reset at …".
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from .adapters import codex as codex_adapter
from .adapters import read_jsonl


def _when(x) -> dt.datetime | None:
    """ISO string, unix seconds or unix milliseconds -> aware local datetime."""
    try:
        if isinstance(x, (int, float)):
            return dt.datetime.fromtimestamp(x / 1000 if x > 1e11 else x, dt.timezone.utc).astimezone()
        if isinstance(x, str) and x:
            d = dt.datetime.fromisoformat(x.replace("Z", "+00:00"))
            return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).astimezone()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _row(tool, name, pct, resets, as_of, now):
    resets = _when(resets) if not isinstance(resets, dt.datetime) else resets
    return {"tool": tool, "name": name, "percent": round(float(pct)), "resets_at": resets.isoformat() if resets else None,
            "as_of": as_of.isoformat(timespec="seconds") if as_of else None,
            "stale": bool(resets and resets <= now)}


STATUS_FILE = "~/.local/share/agentmeter/limits/claude.json"
_WINDOWS = (("five_hour", "5-hour"), ("seven_day", "week"))


def status_file() -> Path:
    return Path(STATUS_FILE).expanduser()


def record_statusline(data, now: dt.datetime | None = None) -> bool:
    """Keep the plan limits from Claude Code's status line input. A window missing from this reading
    (Claude Code drops one once its reset time passes) keeps its previous value, which is then stale.
    Returns whether anything was written. Never raises."""
    try:
        rl = data.get("rate_limits") if isinstance(data, dict) else None
        got = {k: rl[k] for k, _ in _WINDOWS if isinstance(rl, dict) and isinstance(rl.get(k), dict)
               and rl[k].get("used_percentage") is not None}
        if not got:
            return False
        f = status_file()
        try:
            old = json.loads(f.read_text()).get("windows") or {}
        except (OSError, ValueError, AttributeError):
            old = {}
        now = now or dt.datetime.now().astimezone()
        windows = {**old, **{k: {"used_percentage": w["used_percentage"], "resets_at": w.get("resets_at"),
                                 "as_of": now.isoformat(timespec="seconds")} for k, w in got.items()}}
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"as_of": now.isoformat(timespec="seconds"), "windows": windows}))
        tmp.replace(f)                       # atomic: a reader never sees half a file
        return True
    except (OSError, TypeError, ValueError, AttributeError):
        return False


def _from_statusline(now: dt.datetime) -> list[dict]:
    try:
        w = json.loads(status_file().read_text()).get("windows") or {}
    except (OSError, ValueError, AttributeError):
        return []
    return [_row("Claude", name, w[k]["used_percentage"], w[k].get("resets_at"), _when(w[k].get("as_of")), now)
            for k, name in _WINDOWS if isinstance(w.get(k), dict) and w[k].get("used_percentage") is not None]


def claude(now: dt.datetime | None = None) -> list[dict]:
    """The newer of the status line reading and Claude Code's /usage copy. Never raises."""
    now = now or dt.datetime.now().astimezone()
    got = []
    for read in (_from_statusline, _claude):
        try:
            rows = read(now)
        except (AttributeError, TypeError, KeyError, ValueError):
            rows = []
        if rows:
            got.append(rows)
    newest = lambda rows: max((r["as_of"] or "") for r in rows)
    return max(got, key=newest) if got else []


def source(now: dt.datetime | None = None) -> str:
    """Which Claude reading is in use: 'statusline', 'usage' (the /usage copy) or ''."""
    rows = claude(now)
    if not rows:
        return ""
    try:
        sl = _from_statusline(now or dt.datetime.now().astimezone())
    except (AttributeError, TypeError, KeyError, ValueError):
        sl = []
    return "statusline" if sl and rows == sl else "usage"


def _claude(now: dt.datetime) -> list[dict]:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    f = Path(base).expanduser() / ".claude.json" if base else Path("~/.claude.json").expanduser()
    try:
        c = json.loads(f.read_text()).get("cachedUsageUtilization") or {}
    except (OSError, ValueError, AttributeError):
        return []
    as_of, u = _when(c.get("fetchedAtMs")), c.get("utilization") or {}
    out = []
    names = {"session": "5-hour", "weekly_all": "week"}
    for lim in u.get("limits") or []:
        if not isinstance(lim, dict) or lim.get("percent") is None:
            continue
        name = names.get(lim.get("kind"))
        if name is None:
            model = (((lim.get("scope") or {}).get("model")) or {}).get("display_name")
            if not model:
                continue
            name = f"week ({model})"
        out.append(_row("Claude", name, lim["percent"], lim.get("resets_at"), as_of, now))
    if not out:   # older shape: five_hour / seven_day / seven_day_<model>
        for key, name in (("five_hour", "5-hour"), ("seven_day", "week"), ("seven_day_opus", "week (Opus)"),
                          ("seven_day_sonnet", "week (Sonnet)")):
            w = u.get(key)
            if isinstance(w, dict) and w.get("utilization") is not None:
                out.append(_row("Claude", name, w["utilization"], w.get("resets_at"), as_of, now))
    return out


def _window_name(minutes) -> str:
    if not minutes:
        return "limit"
    if minutes <= 24 * 60:
        return f"{round(minutes / 60)}-hour"
    return "week" if abs(minutes - 7 * 24 * 60) < 24 * 60 else f"{round(minutes / 1440)}-day"


def codex(root: Path | None = None, now: dt.datetime | None = None) -> list[dict]:
    try:
        return _codex(root, now or dt.datetime.now().astimezone())
    except (AttributeError, TypeError, KeyError, ValueError):
        return []


def _codex(root: Path | None, now: dt.datetime) -> list[dict]:
    root = root or codex_adapter.default_root()
    try:
        files = sorted(root.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    except OSError:
        return []
    for path in files:                       # newest file that has a reading
        last = None
        for e in read_jsonl(path):
            p = e.get("payload") or {}
            if e.get("type") == "event_msg" and p.get("type") == "token_count" and isinstance(p.get("rate_limits"), dict):
                last = (e.get("timestamp"), p["rate_limits"])
        if not last:
            continue
        ts, rl = last
        as_of = _when(ts)
        out = []
        for key in ("primary", "secondary"):
            w = rl.get(key)
            if not isinstance(w, dict) or w.get("used_percent") is None:
                continue
            resets = w.get("resets_at")
            if resets is None and w.get("resets_in_seconds") is not None and as_of:   # older Codex versions
                resets = as_of + dt.timedelta(seconds=w["resets_in_seconds"])
            out.append(_row("Codex", _window_name(w.get("window_minutes")), w["used_percent"], resets, as_of, now))
        return out
    return []


def all_limits(now: dt.datetime | None = None, codex_root: Path | None = None) -> list[dict]:
    return claude(now) + codex(codex_root, now)


def short(lim: dict, now: dt.datetime | None = None) -> str:
    """'resets 20:29' today, 'resets Tue 17 Nov' later; once passed, 'reset at 07:38' or 'reset Tue 24 Nov'."""
    now = now or dt.datetime.now().astimezone()
    r = _when(lim["resets_at"])
    if not r:
        return ""
    if lim["stale"]:
        return f"reset at {r:%H:%M}" if r.date() == now.date() else f"reset {r:%a} {r.day} {r:%b}"
    return f"resets {r:%H:%M}" if r.date() == now.date() else f"resets {r:%a} {r.day} {r:%b}"


def age(lim: dict, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now().astimezone()
    a = _when(lim["as_of"])
    if not a:
        return ""
    return f"as of {a:%H:%M}" if a.date() == now.date() else f"as of {a:%a} {a.day} {a:%b} {a:%H:%M}"
