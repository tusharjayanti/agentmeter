"""Tool-agnostic core: normalised session model, work classification,
tier policy, weekly aggregation."""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------- model


@dataclass
class Turn:
    ts: str              # ISO 8601
    model: str           # raw model id as the tool reports it
    input: int = 0       # fresh (uncached) input tokens
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0      # includes reasoning/thinking tokens where the tool counts them separately
    auto: bool = False   # model chosen by the harness (subagent, sidechain), not the user: counted, never judged

    @property
    def total(self) -> int:
        return self.input + self.cache_write + self.cache_read + self.output

    @property
    def fresh(self) -> int:
        """Tokens the model actually processed or produced; excludes cheap cache reads."""
        return self.input + self.cache_write + self.output


@dataclass
class Session:
    tool: str            # adapter name: claude-code, codex, gemini, aider, ...
    id: str
    project: str         # usually basename of cwd
    prompts: list[str] = field(default_factory=list)   # real user prompts, in order
    turns: list[Turn] = field(default_factory=list)


# ---------------------------------------------------------------- config

DEFAULT_CONFIG = {
    # model-name regex (case-insensitive) -> tier. First match wins.
    "tiers": {
        "economy":  ["haiku", "(^|-)mini\\b", "(^|-)nano\\b", "flash-lite", "flash-8b"],
        "premium":  ["fable", "mythos", "gpt-5(\\.\\d)?-pro", "o3-pro", "deepthink", "codex-max"],
        "strong":   ["opus", "gemini-.*-pro", "gpt-5(\\.\\d)?-codex$", "o3$"],
        "standard": ["sonnet", "gpt-5", "gpt-4", "o4", "gemini-.*-flash", "codex"],
    },
    # tier -> work categories it is meant for
    "policy": {
        "premium":  ["design", "research"],
        "strong":   ["build", "refactor"],
        "standard": ["fix", "test", "docs", "ops", "explain"],
        "economy":  ["trivial"],
    },
    # ordered [category, regex]; a category scores one point per distinct match in each prompt,
    # earlier wins ties, so keep narrow patterns first and catch-alls last
    "categories": [
        ["trivial",  r"\b(typo|format|lint|one[- ]liner|quick|small change|rename variable|what does this do|explain this)\b"],
        ["docs",     r"\b(readme|docs?|documentation|comment|docstring|changelog|write ?up)\b"],
        ["ops",      r"\b(deploy|ci|cd|pipeline|docker|k8s|kubernetes|terraform|fly\.io|vercel|github actions|release|tag v?\d)\b"],
        ["test",     r"\b(test|tests|unit test|integration test|coverage|pytest|jest|junit|spec)\b"],
        ["design",   r"\b(architect|architecture|design (the|a|an)|system design|high[- ]level|trade[- ]?offs?|schema design|data model|roadmap|rfc|adr)\b"],
        ["research", r"\b(research|compare|comparison|evaluate|investigate|survey|options|pros and cons|which (library|framework|approach|db|database)|should (i|we) use)\b"],
        ["refactor", r"\b(refactor|clean ?up|restructure|rename|extract|simplify|migrate)\b"],
        ["fix",      r"\b(fix|bug|error|fail(s|ing|ed)?|broken|crash|exception|stack ?trace|not working|debug|why (does|is|isn't|doesn't))\b"],
        ["build",    r"\b(implement|build|create|add (a|an|the|support)|scaffold|new (feature|endpoint|service|module|page|component)|wire up|integrate|set up)\b"],
        ["explain",  r"\b(how (do|does|can|should|would) (i|we|you|it|this)|what (is|are|does|do)|why|explain|understand|walk me through)\b|\?\s*$"],
    ],
    "prompts_for_classification": 5,
    # measurement windows: back-to-back, `length` long ("7d", "2w", "1m"), the first starting on `start`
    # (YYYY-MM-DD). start null = weeks starting Monday, no begin date. Windows are labelled by their start date.
    "period": {"start": None, "length": "1w"},
    # also judge which model did which kind of work (tiers, policy, off-policy sessions). Off by default:
    # token counts don't need it.
    "routing": False,
    "roots": {},     # adapter name -> custom log root
    "tools": [],     # adapters to run; empty = every adapter whose logs exist
}


def config_path() -> Path:
    return Path(os.environ.get("AGENTMETER_CONFIG", "~/.config/agentmeter/config.json")).expanduser()


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text())
        except ValueError as e:
            sys.exit(f"bad config {p}: {e}")
        for k in ("tiers", "policy", "categories", "prompts_for_classification", "period", "week_start", "routing", "roots", "tools"):
            if k in user:
                cfg[k] = user[k]
        if isinstance(user.get("period"), dict):
            cfg["period"] = {**DEFAULT_CONFIG["period"], **user["period"]}
    return cfg


def validate(cfg: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a config. Errors stop a run; warnings explain silent n/a results."""
    errors, warnings = [], []
    for tier, pats in (cfg.get("tiers") or {}).items():
        if not isinstance(pats, list):
            errors.append(f"tiers.{tier} must be a list of regexes")
            continue
        for p in pats:
            try:
                re.compile(p)
            except re.error as e:
                errors.append(f"tiers.{tier}: bad regex {p!r}: {e}")
    names = []
    for item in cfg.get("categories") or []:
        if not (isinstance(item, list) and len(item) == 2):
            errors.append(f"categories: expected [name, regex], got {item!r}")
            continue
        names.append(item[0])
        try:
            re.compile(item[1])
        except re.error as e:
            errors.append(f"categories.{item[0]}: bad regex: {e}")
    tiers, policy = set(cfg.get("tiers") or {}), cfg.get("policy") or {}
    for tier, cats in policy.items():
        if tier not in tiers:
            warnings.append(f"policy.{tier}: no such tier in 'tiers', so it never applies")
        for c in cats:
            if c not in names:
                warnings.append(f"policy.{tier}: category {c!r} is not in 'categories', so it never matches")
    for tier in sorted(tiers - set(policy)):
        warnings.append(f"tier {tier!r} has no policy entry: its sessions are never judged")
    if not isinstance(cfg.get("prompts_for_classification", 5), int):
        errors.append("prompts_for_classification must be an integer")
    if "week_start" in cfg and str(cfg["week_start"]).lower() not in DAYS:
        errors.append(f"week_start must be one of {', '.join(DAYS)}, got {cfg.get('week_start')!r}")
    per = cfg.get("period") or {}
    if not isinstance(per, dict):
        errors.append('period must be an object like {"start": "2026-11-06", "length": "1w"}')
    else:
        try:
            parse_length(per.get("length", "1w"))
        except ValueError as e:
            errors.append(f"period.length: {e}")
        if per.get("start"):
            try:
                dt.date.fromisoformat(str(per["start"]))
            except ValueError:
                errors.append(f"period.start must be a date (YYYY-MM-DD), got {per['start']!r}")
            if "week_start" in cfg:
                warnings.append("week_start is ignored because period.start is set")
    return errors, warnings


class Policy:
    def __init__(self, cfg: dict):
        self.tiers = [(tier, re.compile(p, re.I)) for tier, pats in cfg["tiers"].items() for p in pats]
        self.allowed = {t: set(c) for t, c in cfg["policy"].items()}
        self.categories = [(c, re.compile(p, re.I)) for c, p in cfg["categories"]]
        self.order = [c for c, _ in cfg["categories"]]
        self.n_prompts = int(cfg.get("prompts_for_classification", 5))

    def tier(self, model: str) -> str:
        for tier, rx in self.tiers:
            if rx.search(model or ""):
                return tier
        return "unknown"

    def classify(self, prompts: Iterable[str]) -> str:
        # distinct matches per prompt, so a pasted stack trace full of "error" counts once
        prompts = list(prompts)[: self.n_prompts]
        scores = {c: sum(len({m.group(0).lower() for m in rx.finditer(p)}) for p in prompts) for c, rx in self.categories}
        if not scores or max(scores.values()) == 0:
            return "unclassified"
        return max(scores, key=lambda c: (scores[c], -self.order.index(c)))

    def on_policy(self, tier: str, category: str):
        """True / False / None (unknown tier or unclassified work)."""
        if tier not in self.allowed or category == "unclassified":
            return None
        return category in self.allowed[tier]


# ---------------------------------------------------------------- helpers

def family(model: str) -> str:
    """Short display name: 'claude-opus-5-5' -> 'opus', 'gpt-5.1-codex' -> 'gpt-5.1-codex'."""
    m = re.search(r"(fable|mythos|opus|sonnet|haiku)", model or "", re.I)
    return m.group(1).lower() if m else (model or "unknown")


# Measurement windows. A window is keyed by the local date it starts on ("2026-11-06"), so keys
# sort chronologically and work for any start date and length.

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_LENGTH = re.compile(r"\s*(\d+)\s*(d|days?|w|wks?|weeks?|m|mo|mons?|months?)\s*")
_DURATION = re.compile(r"\s*(\d+)\s*(h|hours?|d|days?|w|weeks?)\s*")


def parse_length(s) -> tuple[int, str]:
    """'7d' -> (7, 'd'), '2w' -> (14, 'd'), '1m' -> (1, 'm'). Units: days, weeks, calendar months."""
    m = _LENGTH.fullmatch(str(s).lower())
    if not m or int(m.group(1)) < 1:
        raise ValueError(f"expected a length like 7d, 2w or 1m, got {s!r}")
    n, unit = int(m.group(1)), m.group(2)[0]
    return (7 * n, "d") if unit == "w" else (n, unit)


def add_months(d: dt.date, n: int) -> dt.date:
    """Same day n months later, clamped to the month's end (31 Jan + 1 -> 28/29 Feb)."""
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return d.replace(year=y, month=m + 1, day=min(d.day, calendar.monthrange(y, m + 1)[1]))


def local(ts: str) -> dt.datetime:
    """An ISO timestamp as an aware local datetime; naive timestamps are taken as UTC."""
    d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone()


class Periods:
    """Back-to-back windows of one length, aligned to an anchor date.

    `begins` is the date collection starts: windows before it are never saved as reports
    (they can still be viewed). None means no begin date."""

    def __init__(self, anchor: dt.date, length: str = "1w", begins: dt.date | None = None):
        self.anchor, self.length, self.begins = anchor, str(length), begins
        self.n, self.unit = parse_length(length)

    @classmethod
    def from_config(cls, cfg: dict) -> "Periods":
        per = cfg.get("period") or {}
        length = per.get("length") or "1w"
        if per.get("start"):
            d = dt.date.fromisoformat(str(per["start"]))
            return cls(d, length, begins=d)
        # no begin date: weeks start on Monday, or on the legacy `week_start` day
        day = DAYS.index(str(cfg.get("week_start", "monday")).lower())
        return cls(dt.date(2024, 1, 1) + dt.timedelta(days=day), length)

    def _start(self, i: int) -> dt.date:
        if self.unit == "d":
            return self.anchor + dt.timedelta(days=i * self.n)
        return add_months(self.anchor, i * self.n)

    def _index(self, d: dt.date) -> int:
        if self.unit == "d":
            return (d - self.anchor).days // self.n
        i = ((d.year - self.anchor.year) * 12 + d.month - self.anchor.month) // self.n
        while self._start(i) > d:
            i -= 1
        while self._start(i + 1) <= d:
            i += 1
        return i

    def key(self, d: dt.date) -> str:
        return self._start(self._index(d)).isoformat()

    def end(self, key: str) -> dt.date:
        """Last day (inclusive) of the window starting on `key`."""
        return self._start(self._index(dt.date.fromisoformat(key)) + 1) - dt.timedelta(days=1)

    def previous(self, key: str) -> str:
        """Start of the window before the one starting on `key`."""
        return self._start(self._index(dt.date.fromisoformat(key)) - 1).isoformat()

    def current(self, today: dt.date | None = None) -> str:
        return self.key(today or dt.date.today())

    def back(self, n: int, today: dt.date | None = None) -> list[str]:
        """The current window and the n-1 before it, oldest first."""
        i = self._index(today or dt.date.today())
        return [self._start(j).isoformat() for j in range(i - n + 1, i + 1)]

    def covering(self, frm: dt.date, today: dt.date | None = None) -> list[str]:
        """Every window from the one holding `frm` to the current one, oldest first."""
        i, j = self._index(frm), self._index(today or dt.date.today())
        return [self._start(k).isoformat() for k in range(i, j + 1)]

    def parse(self, s: str, today: dt.date | None = None) -> str:
        """'this', 'last', any date in the window (YYYY-MM-DD), or an ISO week (2026-W45, read as its Monday)."""
        if s in ("this", "last"):
            return self.back(2, today)[1 if s == "this" else 0]
        m = re.fullmatch(r"(\d{4})-W(\d{1,2})", s)
        d = dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1) if m else dt.date.fromisoformat(s)
        return self.key(d)

    def label(self, key: str) -> str:
        """'2026-11-06' -> 'Fri 6 Nov – Thu 12 Nov 2026'."""
        return span_label(dt.date.fromisoformat(key), self.end(key))

    @property
    def name(self) -> str:
        """What to call one window in prose."""
        return {(1, "d"): "day", (7, "d"): "week", (14, "d"): "fortnight", (1, "m"): "month"}.get((self.n, self.unit), "period")

    def describe(self) -> str:
        n, u = self.n, self.unit
        size = (f"{n // 7} week{'s' * (n > 7)}" if u == "d" and n % 7 == 0 else
                f"{n} day{'s' * (n > 1)}" if u == "d" else f"{n} month{'s' * (n > 1)}")
        frm = f"starting {self.begins:%a} {self.begins.day} {self.begins:%b %Y}" if self.begins else \
            f"aligned to {self.anchor:%A}s"
        return f"{size} windows, {frm}"


def change_label(cur: float, prev: float) -> str:
    """'↑25%', '↓19%', 'no change', or 'new' when there was nothing before."""
    if not prev:
        return "new" if cur else "–"
    p = round(100 * (cur - prev) / prev)
    return "no change" if p == 0 else f"{'↑' if p > 0 else '↓'}{abs(p)}%"


def span_label(a: dt.date, b: dt.date) -> str:
    if a == b:
        return f"{a:%a} {a.day} {a:%b %Y}"
    return f"{a:%a} {a.day} {a:%b} – {b:%a} {b.day} {b:%b %Y}"


def parse_since(s: str, now: dt.datetime | None = None) -> dt.datetime:
    """'6h', '3d', '2w' back from now, 'today' (local midnight), or a date / ISO datetime. Returns aware local."""
    now = now or dt.datetime.now().astimezone()
    if s == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    m = _DURATION.fullmatch(s.lower())
    if m:
        n, u = int(m.group(1)), m.group(2)[0]
        return now - dt.timedelta(hours=n) if u == "h" else now - dt.timedelta(days=n * (7 if u == "w" else 1))
    d = dt.datetime.fromisoformat(s)
    return d.astimezone() if d.tzinfo else d.replace(tzinfo=now.tzinfo)


def since(keys: Iterable[str]) -> float:
    """Epoch seconds a log file must have been modified after to hold turns in windows `keys`.
    Logs are append-only, so an older mtime means nothing in range; a day of slack covers timezones."""
    start = dt.datetime.combine(dt.date.fromisoformat(min(keys)), dt.time())
    return start.timestamp() - 86400


def by_period(periods: Periods, wanted: Iterable[str]):
    """Bucket function for aggregate(): a turn's window key, or None outside `wanted`."""
    wanted = set(wanted)

    def bucket(t: dt.datetime):
        k = periods.key(t.date())
        return k if k in wanted else None
    return bucket


def by_range(frm: dt.datetime, to: dt.datetime | None = None):
    """Bucket function for aggregate(): one window, keyed by its start date, from `frm` up to `to` (exclusive)."""
    key = frm.date().isoformat()

    def bucket(t: dt.datetime):
        return key if t >= frm and (to is None or t < to) else None
    return bucket


def on_policy_pct(weekly_rows: Iterable[dict]):
    """Token-weighted on-policy share of judged work, or None if nothing was judged."""
    rows = list(weekly_rows)
    judged = sum(r["judged_tokens"] for r in rows)
    return 100 * sum(r["on_policy_tokens"] for r in rows) / judged if judged else None


# ---------------------------------------------------------------- aggregation

def aggregate(sessions: Iterable[Session], policy: Policy, bucket):
    """Returns (period_rows, session_rows) as lists of dicts.

    `bucket(local_datetime) -> key | None` puts each turn in a window (see by_period, by_range) or drops it.
    Period rows are keyed by (period, tool, model). Session rows are one per (session, period, model, auto);
    subagent slices carry category "subagent" and are never judged against the policy."""
    tok = defaultdict(lambda: defaultdict(int))   # (week, tool, model) -> field
    per = defaultdict(list)                       # (week, tool, model) -> session rows
    for s in sessions:
        if not s.turns:
            continue
        cat = policy.classify(s.prompts)
        by = defaultdict(lambda: defaultdict(int))
        for t in s.turns:
            wk = bucket(local(t.ts))
            if wk is None:
                continue
            b = by[(wk, t.model, t.auto)]
            b["input"] += t.input; b["cache_write"] += t.cache_write
            b["cache_read"] += t.cache_read; b["output"] += t.output; b["turns"] += 1
        for (wk, model, auto), b in by.items():
            agg = tok[(wk, s.tool, model)]
            for k, v in b.items():
                agg[k] += v
            tier = policy.tier(model)
            on = None if auto else policy.on_policy(tier, cat)
            per[(wk, s.tool, model)].append({
                "period": wk, "tool": s.tool, "session": s.id, "model": model, "family": family(model), "tier": tier,
                "project": s.project, "category": "subagent" if auto else cat, "auto": auto,
                "prompt": (s.prompts[0].strip().splitlines()[0][:140] if s.prompts else ""),
                "tokens": b["input"] + b["cache_write"] + b["cache_read"] + b["output"],
                "fresh": b["input"] + b["cache_write"] + b["output"], "turns": b["turns"],
                "on_policy": "n/a" if on is None else ("yes" if on else "no"),
            })

    weekly, session_rows = [], []
    for key in sorted(tok):
        wk, tool, model = key
        t, rows = tok[key], per[key]
        inp = t["input"] + t["cache_write"] + t["cache_read"]
        off = [r for r in rows if r["on_policy"] == "no"]
        mix = defaultdict(int)
        for r in rows:
            mix[r["category"]] += r["tokens"]
        weekly.append({
            "period": wk, "tool": tool, "model": model,
            "family": family(model), "tier": policy.tier(model),
            "sessions": len({r["session"] for r in rows}), "turns": t["turns"],
            "input": t["input"], "cache_write": t["cache_write"], "cache_read": t["cache_read"],
            "output": t["output"], "total": inp + t["output"], "fresh": t["input"] + t["cache_write"] + t["output"],
            "cache_pct": round(100 * t["cache_read"] / inp, 1) if inp else 0.0,
            "off_policy_sessions": len(off), "off_policy_tokens": sum(r["tokens"] for r in off),
            "on_policy_tokens": sum(r["tokens"] for r in rows if r["on_policy"] == "yes"),
            "judged_tokens": sum(r["tokens"] for r in rows if r["on_policy"] != "n/a"),
            "auto_tokens": sum(r["tokens"] for r in rows if r["auto"]),
            "top_category": max(mix, key=mix.get) if mix else "",
            "mix": dict(mix),
        })
        session_rows.extend(rows)
    return weekly, session_rows
