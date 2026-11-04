"""Reports kept on disk, one per measurement window: <start>.md to read, <start>.json for scripts.
<start> is the date the window starts on (config `period`), e.g. 2026-11-06.

A report is written once, after its window has ended, and never rewritten (unless
forced). Tools prune their own logs (Claude Code deletes transcripts after 30
days by default), so recomputing an old window later would quietly undercount it.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .core import Periods

DEFAULT_DIR = "~/.local/share/agentmeter/reports"
FOOTNOTE = ("Tokens are fresh tokens: input + cache writes + output. Cache reads (the model re-reading the "
            "conversation so far, billed at a fraction of the price) are shown separately.")


def _fmt(n):
    n = float(n)
    return f"{n/1e9:.2f}B" if n >= 1e9 else f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.0f}k" if n >= 1e3 else str(int(n))


def _change(cur, prev) -> str:
    if not prev:
        return "new" if cur else "–"
    return f"{100 * (cur - prev) / prev:+.0f}%"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def summary(rows: list[dict]) -> dict:
    return {"fresh": sum(r["fresh"] for r in rows), "total": sum(r["total"] for r in rows),
            "cache_read": sum(r["cache_read"] for r in rows), "auto_tokens": sum(r["auto_tokens"] for r in rows)}


def n_sessions(sessions: list[dict]) -> int:
    """Distinct sessions; one that used two models appears once per model in the session rows."""
    return len({(x["tool"], x["session"]) for x in sessions if not x["auto"]})


def previous(d: Path, pk: str, rows_all: list[dict]):
    """(rows, source) for the window before: its saved report if there is one (frozen, so pruned logs
    don't shrink it), else what the logs still hold, else nothing."""
    f = d / f"{pk}.json"
    if f.exists():
        try:
            return json.loads(f.read_text()).get("periods") or [], "report"
        except ValueError:
            pass
    rows = [r for r in rows_all if r["period"] == pk]
    return rows, ("logs" if rows else None)


def render_md(wk: str, rows: list[dict], sessions: list[dict], periods: Periods, prev_rows=(), n_prompts: int = 5) -> str:
    rows = sorted(rows, key=lambda r: -r["fresh"])
    s, p = summary(rows), summary(list(prev_rows))
    pk, name = periods.previous(wk), periods.name
    out = [f"# agentmeter: {periods.label(wk)}", "",
           f"**{_fmt(s['fresh'])} tokens** this {name} · {n_sessions(sessions)} session{'s' * (n_sessions(sessions) != 1)}", ""]
    if prev_rows:
        out += [f"Previous {name} ({periods.label(pk)}): {_fmt(p['fresh'])} · **{_change(s['fresh'], p['fresh'])}**", ""]
    else:
        out += [f"Previous {name} ({periods.label(pk)}): no data", ""]
    prev_by = {}
    for r in prev_rows:
        prev_by[(r["tool"], r["model"])] = prev_by.get((r["tool"], r["model"]), 0) + r["fresh"]
    out += [f"| model | tool | tokens | previous {name} | change | sessions | turns |", "|---|---|--:|--:|--:|--:|--:|"]
    for r in rows:
        pv = prev_by.pop((r["tool"], r["model"]), 0)
        out.append(f"| {r['model']} | {r['tool']} | {_fmt(r['fresh'])} | {_fmt(pv) if prev_rows else '–'} | "
                   f"{_change(r['fresh'], pv) if prev_rows else '–'} | {r['sessions']} | {r['turns']} |")
    for (tool, model), pv in sorted(prev_by.items(), key=lambda x: -x[1]):   # used last time, not this time
        out.append(f"| {model} | {tool} | 0 | {_fmt(pv)} | -100% | 0 | 0 |")
    out += ["", f"Including cache reads: {_fmt(s['total'])} this {name}"
            + (f", {_fmt(p['total'])} the previous {name}" if prev_rows else "") + "."]
    if s["auto_tokens"]:
        out[-1] += f" Subagents account for {_fmt(s['auto_tokens'])} of the total."
    big = sorted((x for x in sessions if not x["auto"]), key=lambda x: -x["fresh"])[:n_prompts]
    if big:
        out += ["", "## Largest sessions", ""]
        out += [f"- {_fmt(x['fresh'])} · {x['project']} · {x['model']}: {_cell(x['prompt'][:120])}" for x in big]
    out += ["", "---", f"_{FOOTNOTE}_", ""]
    return "\n".join(out)


def render_json(wk: str, rows: list[dict], sessions: list[dict], meta: dict, periods: Periods,
                prev_rows=(), prev_source=None) -> str:
    s, p = summary(rows), summary(list(prev_rows))
    prev = {"period": periods.previous(wk), "source": prev_source,
            "fresh": p["fresh"] if prev_rows else None, "total": p["total"] if prev_rows else None,
            "change_pct": round(100 * (s["fresh"] - p["fresh"]) / p["fresh"], 1) if prev_rows and p["fresh"] else None}
    return json.dumps({"period": wk, "start": wk, "end": periods.end(wk).isoformat(),
                       "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                       "summary": {**s, "sessions": n_sessions(sessions)}, "previous": prev, "config": meta, "periods": rows, "sessions": sessions}, indent=1)


def save(directory, rows_all, sessions, meta, keys, periods: Periods, today=None, n_prompts=5, force=False) -> list[str]:
    """Write <start>.md and <start>.json for each window in `keys` that has ended, starts on or after
    the collection begin date, has data, and has no report yet. Returns the windows written.
    Meant to run often (the job runs hourly): a report appears the first run after its window ends."""
    d = Path(directory or DEFAULT_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    current = periods.current(today)
    written = []
    for wk in sorted(keys):
        if wk >= current:                       # not over yet
            continue
        if periods.begins and wk < periods.begins.isoformat():   # before collection begins
            continue
        if (d / f"{wk}.json").exists() and not force:
            continue
        rows = [r for r in rows_all if r["period"] == wk]
        if not rows:                            # no data: maybe idle, maybe logs already pruned; don't freeze a zero
            continue
        ss = [s for s in sessions if s["period"] == wk]
        prev_rows, source = previous(d, periods.previous(wk), rows_all)
        (d / f"{wk}.md").write_text(render_md(wk, rows, ss, periods, prev_rows, n_prompts))
        (d / f"{wk}.json").write_text(render_json(wk, rows, ss, meta, periods, prev_rows, source))
        written.append(wk)
    return written
