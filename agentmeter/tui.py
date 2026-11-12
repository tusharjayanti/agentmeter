"""`agentmeter tui`: a full-screen view that stays open, in the style of htop.

Built on curses from the Python standard library, so it needs nothing installed. Keys:
  ↑↓ (j/k) pick a model or report   ←→ (h/l) previous / next window   tab switch view
  enter open the selected report    r reload logs   q quit
It reloads the logs every minute while open.

All drawing goes through frame(), which returns plain lines of (text, style) segments for a
given size; curses only paints them. Tests call frame() directly.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from . import report
from .cli import collect, fmt, load_policy
from .core import Periods, aggregate, by_period, by_range, change_label, load_config, since, span_label
from .prices import AS_OF, Prices, money

SPARK = "▁▂▃▄▅▆▇█"
HUES = ["c1", "c2", "c3", "c4", "ok"]
REFRESH = 60


class Data:
    """Sessions parsed once from the logs; every view aggregates from them in memory."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.policy = load_policy(cfg)
        self.prices = Prices(cfg.get("prices"))
        self.per = Periods.from_config(cfg)
        self.tools = cfg.get("tools") or None
        self.roots = cfg.get("roots", {})
        self.sessions, self.loaded_from, self.loaded_at = [], None, 0.0

    def load(self, frm: str | None = None):
        """(Re)read the logs, far enough back to cover the window starting on `frm` and the one before it."""
        frm = min(x for x in (frm, self.loaded_from, self.per.back(6)[0]) if x)
        frm = self.per.previous(frm)
        self.sessions = list(collect(self.tools, self.roots, since([frm]), quiet=True))
        self.loaded_from, self.loaded_at = frm, time.time()

    def need(self, key: str):
        if self.loaded_from is None or self.per.previous(key) < self.loaded_from:
            self.load(key)

    def window(self, key: str):
        """(rows, sessions, previous rows) for one window."""
        self.need(key)
        pk = self.per.previous(key)
        rows, ss = aggregate(self.sessions, self.policy, by_period(self.per, [key, pk]), self.prices)
        return ([r for r in rows if r["period"] == key], [s for s in ss if s["period"] == key],
                [r for r in rows if r["period"] == pk])

    def span(self, frm: dt.datetime, to: dt.datetime | None = None):
        rows, ss = aggregate(self.sessions, self.policy, by_range(frm, to), self.prices)
        return rows, ss, None

    def series(self, frm: dt.datetime, to: dt.datetime, step: dt.timedelta) -> list[int]:
        """Fresh tokens per `step` from `frm` to `to`, for the small chart."""
        n = max(1, -int(-(to - frm) // step))          # round up: the current, partial slot counts
        out = [0] * n

        def bucket(t):
            i = int((t - frm) / step)
            return i if t >= frm and i < n else None
        rows, _ = aggregate(self.sessions, self.policy, bucket, self.prices)
        for r in rows:
            out[r["period"]] += r["fresh"]
        return out

    def reports(self) -> list[dict]:
        d = Path(report.DEFAULT_DIR).expanduser()
        out = []
        for f in sorted(d.glob("????-??-??.json"), reverse=True):
            try:
                j = json.loads(f.read_text())
            except ValueError:
                continue
            s = j.get("summary") or {}
            try:
                lab = span_label(dt.date.fromisoformat(j.get("start") or f.stem), dt.date.fromisoformat(j["end"]))
            except (KeyError, ValueError):
                lab = f.stem
            out.append({"key": f.stem, "label": lab, "md": f.with_suffix(".md"), "fresh": s.get("fresh", 0), "cost": s.get("cost"),
                        "change": (j.get("previous") or {}).get("change_pct"), "sessions": s.get("sessions", 0)})
        return out


class State:
    def __init__(self, data: Data):
        self.data = data
        self.tabs = [data.per.name.title(), "Today", "Last 5h", "Reports"]
        self.tab, self.sel, self.key = 0, 0, data.per.current()
        self.message = ""


# ---------------------------------------------------------------- drawing

def _len(segs) -> int:
    return sum(len(t) for t, _ in segs)


def _fit(segs, w):
    """Clip or pad segments to exactly w columns."""
    out, n = [], 0
    for t, s in segs:
        if n >= w:
            break
        t = t[: w - n]
        out.append((t, s)); n += len(t)
    if n < w:
        out.append((" " * (w - n), None))
    return out


def _row(W, *cols):
    """│ col │ col │ … with each col = (width, segments); widths add up to W."""
    out = [("│", "dim")]
    for i, (w, segs) in enumerate(cols):
        out += _fit([(" ", None)] + segs, w)
        out.append(("│", "dim"))
    return out


def _rule(W, a, b, splits=(), mid="┬"):
    line = "─" * (W - 2)
    for x in splits:
        line = line[:x - 1] + mid + line[x:]
    return [(a + line + b, "dim")]


def _clean(s: str) -> str:
    return "".join(c if c.isprintable() else " " for c in s)


def _pad(s, n, right=False):
    s = s if len(s) <= n else s[: n - 1] + "…"
    return s.rjust(n) if right else s.ljust(n)


def _chg(cur, prev):
    if prev is None:
        return ("–", "dim")
    lab = change_label(cur, prev)
    return (lab, "ok" if lab.startswith("↑") else "bad" if lab.startswith("↓") else "dim")


def _spark(vals, width):
    if not vals:
        return ""
    if len(vals) > width:                 # squeeze: sum neighbours
        k = -(-len(vals) // width)
        vals = [sum(vals[i:i + k]) for i in range(0, len(vals), k)]
    top = max(vals) or 1
    return "".join(SPARK[min(7, int(7 * v / top + 0.999))] if v else " " for v in vals)


def view(st: State, now: dt.datetime | None = None):
    """What the current tab shows: title, rows, sessions, previous rows, chart values and labels."""
    d, per = st.data, st.data.per
    now = now or dt.datetime.now().astimezone()
    if st.tab == 0:
        rows, ss, prev = d.window(st.key)
        a = dt.datetime.combine(dt.date.fromisoformat(st.key), dt.time()).astimezone()
        end = dt.datetime.combine(per.end(st.key) + dt.timedelta(days=1), dt.time()).astimezone()
        days = d.series(a, min(end, now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)),
                        dt.timedelta(days=1))
        lab = [(a + dt.timedelta(days=i)).strftime("%a") for i in range(len(days))]
        return per.label(st.key), rows, ss, prev, days, lab, f"vs last {per.name}", "TOKENS PER DAY"
    d.need(per.current())
    if st.tab == 1:
        a = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows, ss, _ = d.span(a)
        prev_rows, _ = aggregate(d.sessions, d.policy, by_range(a - dt.timedelta(days=1), a), d.prices)
        hours = d.series(a, now, dt.timedelta(hours=1))
        lab = [f"{h:02d}:00" for h in range(len(hours))]
        return f"Today, {now:%a} {now.day} {now:%b}", rows, ss, prev_rows, hours, lab, "vs yesterday", "TOKENS PER HOUR"
    a = now - dt.timedelta(hours=5)
    rows, ss, _ = d.span(a)
    quarters = d.series(a, now, dt.timedelta(minutes=15))
    lab = [f"{a + dt.timedelta(minutes=15 * i):%H:%M}" for i in range(len(quarters))]
    return f"Last 5 hours, since {a:%H:%M}", rows, ss, None, quarters, lab, "", "TOKENS PER 15 MIN"


def frame(st: State, W: int, H: int, now: dt.datetime | None = None):
    """The whole screen as H lines of (text, style) segments."""
    W = max(W, 60)
    lines = [[("┌─ ", "dim"), ("agentmeter", "b"), (" ", None)] + [("─" * (W - 15), "dim"), ("┐", "dim")]]
    tabs = []
    for i, t in enumerate(st.tabs):
        tabs += [(f" {t} ", "sel" if i == st.tab else None), ("  ", None)]
    if st.tab == 3:
        return _reports(st, W, H, lines, tabs)
    title, rows, ss, prev, chart, chart_lab, vs, chart_name = view(st, now)
    nav = [(f"◀ {title} ▶" if st.tab == 0 else title, "dim")]
    lines.append(_row(W, (W - 2, tabs + [(" " * max(1, W - 4 - _len(tabs) - _len(nav)), None)] + nav)))

    L = max(30, int(W * 0.44))
    R = W - 3 - L
    lines.append(_rule(W, "├", "┤", [L + 1]))
    rows = sorted(rows, key=lambda r: -r["fresh"])
    fresh = sum(r["fresh"] for r in rows)
    priced = [r["cost"] for r in rows if r.get("cost") is not None]
    cost = sum(priced) if priced else None
    pf = sum(r["fresh"] for r in prev) if prev else None
    pc = [r["cost"] for r in prev if r.get("cost") is not None] if prev else []
    n = len({(s["tool"], s["session"]) for s in ss if not s["auto"]})
    total = sum(r["total"] for r in rows)
    left = [[("TOKENS", "dim"), (" " * 10, None), ("COST (API prices)", "dim")],
            [(f"{fmt(fresh):<7}", "b"), (" ", None), _chg(fresh, pf) if prev else ("", None), (" " * (9 - len(_chg(fresh, pf)[0] if prev else "")), None),
             (f"{money(cost):<8}", "b"), (" ", None), _chg(cost or 0, sum(pc)) if pc and cost is not None else ("", None)],
            [(f"{n} session{'s' * (n != 1)} · {fmt(total)} incl. cache", "dim")]]
    spark = _spark(chart, R - 2)
    busiest = ""
    if chart and max(chart):
        i = chart.index(max(chart))
        busiest = f"busiest: {chart_lab[i] if i < len(chart_lab) else '#' + str(i + 1)}, {fmt(chart[i])}"
    axis = st.tab == 0 and chart_lab and len(chart_lab) * 3 <= R - 2   # day letters under the bars
    right = [[(chart_name, "dim")], [(spark if not axis else "  ".join(spark), "c1")],
             [(" ".join(x[:2] for x in chart_lab) if axis else "", "dim")]]
    right[2] = right[2] + [("  " if right[2][0][0] else "", None), (busiest, "dim")]
    for a, b in zip(left, right):
        lines.append(_row(W, (L, a), (R, b)))
    lines.append(_rule(W, "├", "┤", [L + 1], mid="┴"))

    # model table
    mw = min(24, max([5] + [len(r["model"]) for r in rows]))
    tw = min(12, max([4] + [len(r["tool"]) for r in rows]))
    bw = max(6, min(24, W - (mw + tw + 8 + 9 + 10 + 14)))
    head = f"{'MODEL':<{mw}}  {'TOOL':<{tw}}  {'TOKENS':>7}  {'SHARE':<{bw}}  {'COST':>8}  {vs.upper()}"
    lines.append(_row(W, (W - 2, [(head, "dim")])))
    prev_by = defaultdict(int)
    for r in prev or []:
        prev_by[(r["tool"], r["model"])] += r["fresh"]
    budget = H - len(lines) - 4        # lines left once the bottom border, keys, divider and session title are drawn
    st.sel = max(0, min(st.sel, len(rows) - 1))
    if not rows:
        lines.append(_row(W, (W - 2, [("no sessions here; ←/→ for other windows, tab for other views", "dim")])))
    fits = max(1, min(len(rows), budget - 3))        # every model if it fits; keep three lines for sessions
    first = max(0, st.sel - fits + 1)
    shown = rows[first: first + fits]
    for i, r in enumerate(shown, start=first):
        share = r["fresh"] / fresh if fresh else 0
        k = round(share * bw)
        sel = i == st.sel
        segs = [(f"{_pad(r['model'], mw)}  {_pad(r['tool'], tw)}  {fmt(r['fresh']):>7}  ", "sel" if sel else None),
                ("█" * k, "sel" if sel else HUES[i % len(HUES)]), ("░" * (bw - k), "sel" if sel else "dim"),
                (f"  {money(r.get('cost')):>8}  ", "sel" if sel else None)]
        if prev is not None:
            lab, sty = _chg(r["fresh"], prev_by.get((r["tool"], r["model"]), 0))
            segs.append((lab, "sel" if sel else sty))
        out = _row(W, (W - 2, segs))
        if sel:   # highlight the whole row
            out = [out[0]] + [(t, "sel") for t, _ in out[1:-1]] + [out[-1]]
        lines.append(out)

    # sessions of the selected model
    lines.append(_rule(W, "├", "┤"))
    if rows:
        r = rows[st.sel]
        mine = sorted((s for s in ss if s["tool"] == r["tool"] and s["model"] == r["model"] and not s["auto"]),
                      key=lambda s: -s["fresh"])
        lines.append(_row(W, (W - 2, [(f"{r['model']} · {len(mine)} session{'s' * (len(mine) != 1)}", "dim")])))
        pw = max(10, W - 2 - 2 - 14 - 7 - 9 - 12 - 4)
        for s in mine[: max(0, H - len(lines) - 3)]:
            when = dt.datetime.fromisoformat(s["start"]) if s.get("start") else None
            lines.append(_row(W, (W - 2, [(f"  {_pad(_clean(s['project']), 12)}  ", "c1"),
                                          (_pad(_clean(s["prompt"]), pw), None),
                                          (f" {fmt(s['fresh']):>7} {money(s.get('cost')):>8}  ", None),
                                          (f"{when:%a} {when.day} {when:%b}" if when else "", "dim")])))
    while len(lines) < H - 2:
        lines.append(_row(W, (W - 2, [])))
    lines = lines[: H - 2]
    lines.append(_rule(W, "└", "┘"))
    lines.append(_fit(_keys(st, f"API prices of {AS_OF}"), W))
    return lines


def _keys(st: State, note=""):
    keys = [("↑↓", "model" if st.tab != 3 else "report"), ("←→", st.data.per.name), ("tab", "view")]
    if st.tab == 3:
        keys = [("↑↓", "report"), ("enter", "open"), ("tab", "view")]
    keys += [("r", "reload"), ("q", "quit")]
    out = [(" ", None)]
    for k, v in keys:
        out += [(f" {k} ", "key"), (f" {v}  ", None)]
    if st.message or note:
        out.append((st.message or note, "dim"))
    return out


def _reports(st, W, H, lines, tabs):
    reps = st.data.reports()
    lines.append(_row(W, (W - 2, tabs)))
    lines.append(_rule(W, "├", "┤"))
    head = f"{st.data.per.name.upper():<30}  {'TOKENS':>7}  {'COST':>8}  {'CHANGE':>8}  {'SESSIONS':>8}"
    lines.append(_row(W, (W - 2, [(head, "dim")])))
    if not reps:
        lines.append(_row(W, (W - 2, [(f"no saved reports yet in {report.DEFAULT_DIR}; the first appears after a "
                                       f"{st.data.per.name} ends", "dim")])))
    st.sel = max(0, min(st.sel, len(reps) - 1))
    top = H // 2
    for i, r in enumerate(reps[: top]):
        lab = r["label"]
        c = r["change"]
        chg = ("–", "dim") if c is None else (change_label(100 + c, 100), "ok" if c > 0.5 else "bad" if c < -0.5 else "dim")
        segs = [(f"{lab:<30}  {fmt(r['fresh']):>7}  {money(r['cost']):>8}  ", None), (f"{chg[0]:>8}", chg[1]),
                (f"  {r['sessions']:>8}", None)]
        if i == st.sel:
            segs = [(t, "sel") for t, _ in segs]
        lines.append(_row(W, (W - 2, segs)))
    lines.append(_rule(W, "├", "┤"))
    if reps:
        md = reps[st.sel]["md"]
        text = md.read_text(errors="replace").splitlines() if md.exists() else ["(no .md next to this report)"]
        for t in text[: max(0, H - len(lines) - 3)]:
            lines.append(_row(W, (W - 2, [(_clean(t), "b" if t.startswith("#") else None)])))
    while len(lines) < H - 2:
        lines.append(_row(W, (W - 2, [])))
    lines = lines[: H - 2]
    lines.append(_rule(W, "└", "┘"))
    lines.append(_fit(_keys(st), W))
    return lines


def text(lines) -> str:
    return "\n".join("".join(t for t, _ in ln).rstrip() for ln in lines)


# ---------------------------------------------------------------- curses

def _run(scr, st: State):
    import curses
    curses.curs_set(0)
    scr.timeout(1000)
    styles = {None: curses.A_NORMAL, "b": curses.A_BOLD, "dim": curses.A_DIM, "sel": curses.A_REVERSE,
              "key": curses.A_REVERSE}
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for i, (name, col) in enumerate([("c1", curses.COLOR_CYAN), ("c2", curses.COLOR_MAGENTA), ("c3", curses.COLOR_YELLOW),
                                         ("c4", curses.COLOR_BLUE), ("ok", curses.COLOR_GREEN), ("bad", curses.COLOR_RED)], 1):
            curses.init_pair(i, col, bg)
            styles[name] = curses.color_pair(i)
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_CYAN)
        styles["sel"] = curses.color_pair(7) | curses.A_BOLD
    while True:
        if time.time() - st.data.loaded_at > REFRESH:
            st.data.load()
        H, W = scr.getmaxyx()
        scr.erase()
        if W < 60 or H < 16:
            scr.addstr(0, 0, "agentmeter needs at least 60×16"[: W - 1])
        else:
            for y, ln in enumerate(frame(st, W, H)):
                x = 0
                for t, s in ln:
                    if x >= W:
                        break
                    try:   # the bottom-right cell raises after drawing; that is fine
                        scr.addstr(y, x, t[: W - x], styles.get(s, curses.A_NORMAL))
                    except curses.error:
                        pass
                    x += len(t)
        scr.refresh()
        k = scr.getch()
        if k == -1:
            continue
        st.message = ""
        if k == 27:   # an arrow key curses didn't decode: ESC [ A or ESC O A
            scr.nodelay(True)
            seq = [scr.getch(), scr.getch()]
            scr.nodelay(False); scr.timeout(1000)
            if seq[0] in (ord("["), ord("O")):
                k = {ord("A"): curses.KEY_UP, ord("B"): curses.KEY_DOWN, ord("C"): curses.KEY_RIGHT,
                     ord("D"): curses.KEY_LEFT, ord("Z"): curses.KEY_BTAB}.get(seq[1], -1)
        if k == ord("q"):
            return
        if k in (curses.KEY_UP, ord("k")):
            st.sel -= 1
        elif k in (curses.KEY_DOWN, ord("j")):
            st.sel += 1
        elif k in (9, curses.KEY_BTAB):
            st.tab = (st.tab + (1 if k == 9 else -1)) % len(st.tabs); st.sel = 0
        elif k in (curses.KEY_LEFT, ord("h")) and st.tab == 0:
            st.key = st.data.per.previous(st.key); st.sel = 0
        elif k in (curses.KEY_RIGHT, ord("l")) and st.tab == 0:
            nxt = (st.data.per.end(st.key) + dt.timedelta(days=1)).isoformat()
            if nxt <= st.data.per.current():
                st.key = nxt; st.sel = 0
        elif k in (ord("r"),):
            st.data.load(st.key); st.message = "reloaded"
        elif k in (10, 13, curses.KEY_ENTER) and st.tab == 3:
            reps = st.data.reports()
            if reps:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                try:
                    subprocess.Popen([opener, str(reps[st.sel]["md"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    st.message = f"opened {reps[st.sel]['md'].name}"
                except OSError as e:
                    st.message = f"could not open: {e}"
        elif k == curses.KEY_RESIZE:
            pass


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="agentmeter tui", description="Full-screen view: windows, models, sessions, reports.")
    ap.parse_args(argv)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("agentmeter tui needs a terminal; use `agentmeter` or `agentmeter --json` in scripts")
    import curses
    import locale
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    data = Data(load_config())
    data.load()
    try:
        curses.wrapper(_run, State(data))
    except KeyboardInterrupt:
        pass
