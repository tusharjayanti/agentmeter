"""agentmeter CLI: five commands, everything else is a range or an output format.

  agentmeter                       this window (a week by default): tokens, cost, models, plan limits
  agentmeter tui                   full-screen view
  agentmeter reports [last|DATE]   saved reports; `reports save` writes newly finished windows
  agentmeter setup                 the setup questions (tools, window, routing)
  agentmeter doctor                is it working: config, tools, windows, reports, limits

Ranges: --today, --since 6h, --from DATE --to DATE, --period last, --periods 8.
Older spellings (init, check, --tools, --weeks, --week, --sessions, --prompts, --save) still work, unlisted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from . import adapters, report
from .limits import all_limits
from .prices import Prices, money
from .core import (Periods, Policy, aggregate, by_period, by_range, change_label, config_path, load_config, on_policy_pct,
                   parse_since, since, span_label, validate)


def fmt(n):
    n = float(n)
    return f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.0f}k" if n >= 1e3 else str(int(n))


def use_color() -> bool:
    """Colour only on a terminal; NO_COLOR turns it off, FORCE_COLOR on (https://no-color.org)."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


class Style:
    """ANSI codes, or empty strings when colour is off."""

    def __init__(self, on: bool):
        self.on = on
        code = (lambda c: f"\x1b[{c}m") if on else (lambda c: "")
        self.b, self.dim, self.cyan, self.yellow, self.reset = code("1"), code("2"), code("36"), code("33"), code("0")
        self.green, self.red, self.magenta, self.blue = code("32"), code("31"), code("35"), code("34")


def pct(p):
    return f"{p:.0f}%" if p is not None else "–"


def collect(tool_names, roots, since_ts=None, quiet=False):
    mods = [adapters.load(t) for t in tool_names] if tool_names else adapters.available()
    for mod in mods:
        root = Path(roots.get(mod.NAME)).expanduser() if roots.get(mod.NAME) else mod.default_root()
        if not root.exists():
            if quiet:
                continue
            print(f"[{mod.NAME}] no logs yet in {adapters.where(mod, roots.get(mod.NAME))}", file=sys.stderr)
            continue
        yield from mod.sessions(root, since=since_ts)


def tier_order(cfg) -> list[str]:
    """Tiers from most to least capable: the order of 'policy', then any tier it leaves out.
    ('tiers' is in regex-match order, which is not a ranking.)"""
    order = list(cfg.get("policy") or {})
    return order + [t for t in cfg.get("tiers") or {} if t not in order]


def unmapped(weekly) -> dict:
    """model -> tokens for models no tier regex matched; they are never judged."""
    out = defaultdict(int)
    for r in weekly:
        if r["tier"] == "unknown":
            out[r["model"]] += r["total"]
    return dict(out)


def unmapped_note(weekly) -> str:
    um = unmapped(weekly)
    if not um:
        return ""
    names = ", ".join(sorted(um, key=lambda m: -um[m])[:4])
    return f"{fmt(sum(um.values()))} tokens on models with no tier ({names}): add them with `agentmeter setup` or to 'tiers'"


def load_policy(cfg) -> Policy:
    errors, _ = validate(cfg)
    if errors:
        sys.exit(f"bad config {config_path()}:\n  " + "\n  ".join(errors) + "\nrun `agentmeter doctor` for details")
    return Policy(cfg)


def tilde(p) -> str:
    p, home = str(p), str(Path.home())
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def reports_dir(d=None) -> Path:
    return Path(d or os.environ.get("AGENTMETER_REPORTS") or report.DEFAULT_DIR).expanduser()


def tool_rows(roots=None) -> list[list[str]]:
    """[name, found/absent, where it looks, description] for every built-in adapter."""
    roots, out = roots or {}, []
    for n in adapters.BUILTIN:
        mod = adapters.load(n)
        r = Path(roots[mod.NAME]).expanduser() if roots.get(mod.NAME) else mod.default_root()
        out.append([mod.NAME, "found" if r.exists() else "absent", tilde(adapters.where(mod, r if r.exists() else None)), mod.DESC])
    return out


def saved_reports(d: Path) -> list[dict]:
    """The summary of each saved report, oldest first; unreadable files are skipped."""
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            j = json.loads(f.read_text())
            out.append({"key": j["start"], "end": j["end"], "fresh": j["summary"]["fresh"], "cost": j["summary"].get("cost"),
                        "prev": (j.get("previous") or {}).get("fresh"), "md": f.with_suffix(".md")})
        except (ValueError, KeyError, TypeError):
            continue
    return out


def reports_cmd(argv):
    ap = argparse.ArgumentParser(prog="agentmeter reports",
                                 description="Saved reports: one per finished window, written once and kept.",
                                 epilog="agentmeter reports         list them\n"
                                        "agentmeter reports last    print the latest one\n"
                                        "agentmeter reports DATE    print the one whose window holds that date\n"
                                        "agentmeter reports save    write any finished window that has no report yet\n"
                                        "                           (the background job runs this every hour)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("which", nargs="?", metavar="last|DATE|save", help="leave out to list them")
    ap.add_argument("--dir", help=f"reports folder (default {report.DEFAULT_DIR})")
    ap.add_argument("--force", action="store_true", help="with save: rewrite reports that already exist")
    args = ap.parse_args(argv)
    d = reports_dir(args.dir)
    if args.which == "save":
        return main(["--save", str(d)] + (["--force"] if args.force else []))
    saved = saved_reports(d)
    if args.which:
        if args.which == "last":
            pick = saved[-1:]
        else:
            try:
                day = dt.date.fromisoformat(args.which).isoformat()
            except ValueError:
                ap.error(f"expected last, a date (YYYY-MM-DD) or save, got {args.which!r}")
            pick = [r for r in saved if r["key"] <= day <= r["end"]]
        if not pick or not pick[-1]["md"].exists():
            sys.exit(f"no saved report for that window in {tilde(d)}")
        print(pick[-1]["md"].read_text(), end="")
        return
    if not saved:
        per = Periods.from_config(load_config())
        cur = per.current()
        print(f"No reports yet in {tilde(d)}.\nThe first is saved on {per.end(cur) + dt.timedelta(days=1):%a %-d %b}, "
              f"when this {per.name} ({per.label(cur)}) ends.")
        return
    st = Style(use_color())
    rows = [[span_label(dt.date.fromisoformat(r["key"]), dt.date.fromisoformat(r["end"])),
             f"{st.b}{fmt(r['fresh'])}{st.reset}", money(r["cost"]),
             change(st, r["fresh"], r["prev"]) if r["prev"] else "–"] for r in saved]
    print(table(st, ["window", "tokens", "cost", "vs prev"], rows, "<>>>"))
    print(f"{st.dim}in {tilde(d)}: a .md to read and a .json for scripts each\n"
          f"agentmeter reports last prints the latest; agentmeter reports DATE any other{st.reset}")


def doctor(argv):
    ap = argparse.ArgumentParser(prog="agentmeter doctor",
                                 description="Is it working: config, tools found, windows, reports, plan limits, background parts. "
                                             "With routing on, also how models and sessions are classified.")
    ap.add_argument("--periods", type=int, default=4, metavar="N", help="with routing on: windows of sessions to look at (default 4)")
    ap.add_argument("--weeks", type=int, dest="periods", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    st = Style(use_color())
    head = lambda s: f"\n{st.b}{s}{st.reset}"
    cfg, p = load_config(), config_path()
    print(head("config"))
    print(f"  {tilde(p)}" + ("" if p.exists() else "  not found: defaults apply (weeks from Monday, every tool). "
                                                   "Choose yours with `agentmeter setup`"))
    errors, warnings = validate(cfg)
    for m in errors:
        print(f"  {st.red}error{st.reset}:   {m}")
    for m in warnings:
        print(f"  {st.yellow}warning{st.reset}: {m}")
    if errors:
        sys.exit(1)
    if p.exists() and not warnings:
        print(f"  {st.green}ok{st.reset}")

    print(head("tools"))
    chosen = cfg.get("tools") or []
    for name, state, where, _ in tool_rows(cfg.get("roots", {})):
        read = state == "found" and (not chosen or name in chosen)
        label = "reading" if read else "skipped" if state == "found" else "no logs"
        print(f"  {name:<12} {st.green if read else st.dim}{label:<8}{st.reset} {st.dim}{clip(where, 56)}{st.reset}")
    print(f"  {st.dim}" + ("tools come from your setup" if chosen else "every tool with logs is read") + st.reset)

    per = Periods.from_config(cfg)
    cur = per.current()
    print(head("windows"))
    print(f"  {per.describe()}")
    print(f"  now: {per.label(cur)} · its report is saved on {per.end(cur) + dt.timedelta(days=1):%a %-d %b}")
    if per.begins and per.begins > dt.date.today():
        print(f"  collection begins {per.begins:%a %-d %b %Y}: nothing is saved before then")

    d = reports_dir()
    saved = saved_reports(d)
    print(head("reports"))
    if saved:
        last = saved[-1]
        print(f"  {len(saved)} saved, latest {span_label(dt.date.fromisoformat(last['key']), dt.date.fromisoformat(last['end']))}")
        print(f"  {st.dim}{tilde(d)}{st.reset}")
    else:
        print(f"  none yet in {tilde(d)}")

    from .limits import age
    print(head("plan limits"))
    lims = all_limits()
    if not lims:
        print(f"  {st.dim}none found (API-key users have none; Claude Code keeps its copy in ~/.claude.json){st.reset}")
    for tool in dict.fromkeys(x["tool"] for x in lims):
        mine = [x for x in lims if x["tool"] == tool]
        stale = ", out of date" + (": open /usage in Claude Code" if tool == "Claude" else "") if any(x["stale"] for x in mine) else ""
        print(f"  {tool}: {age(mine[0])}{stale}")

    print(head("background"))
    home = Path.home()
    if sys.platform == "darwin":
        parts = [("report job", home / "Library/LaunchAgents/io.github.agentmeter.weekly.plist"),
                 ("menu bar app", home / "Library/LaunchAgents/io.github.agentmeter.bar.plist")]
    else:
        parts = [("report job", home / ".config/systemd/user/agentmeter-weekly.timer")]
    for name, f in parts:
        print(f"  {name:<13}" + (f"{st.green}installed{st.reset}" if f.exists() else
                                  f"{st.yellow}not installed{st.reset} {st.dim}(run ./install.sh from the repo){st.reset}"))

    print(head("routing"))
    if not cfg.get("routing"):
        print(f"  off: tokens only. `agentmeter setup` can turn it on, to flag sessions\n"
              f"  where a model did work its tier isn't meant for.")
        return
    policy = Policy(cfg)
    wanted = per.back(args.periods)
    weekly, sessions = aggregate(collect(cfg.get("tools") or None, cfg.get("roots", {}), since(wanted), quiet=True), policy,
                                 by_period(per, wanted), Prices(cfg.get("prices")))
    models = defaultdict(int)
    for r in weekly:
        models[r["model"]] += r["fresh"]
    print(f"  on, as of the last {args.periods} {per.name}s")
    print(f"  {st.dim}model → tier: work it is meant for{st.reset}")
    for m in sorted(models, key=lambda m: -models[m]):
        t = policy.tier(m)
        meant = ", ".join(cfg["policy"].get(t, [])) or ("never judged: no tier matches" if t == "unknown" else "(no policy)")
        print(f"    {clip(m, 22):<22} {fmt(models[m]):>7}  {t}")
        print(f"      {st.dim}{clip(meant, 72)}{st.reset}")
    judged = [s for s in sessions if not s["auto"]]
    cats = defaultdict(lambda: [0, 0])
    for s in judged:
        cats[s["category"]][0] += 1
        cats[s["category"]][1] += s["tokens"]
    print("  work categories (sessions, tokens)")
    for c, (n, tok) in sorted(cats.items(), key=lambda x: -x[1][1]):
        print(f"    {c:<13}{n:>4}  {fmt(tok):>8}")
    un = sorted((s for s in judged if s["category"] == "unclassified"), key=lambda s: -s["tokens"])
    if un:
        print(f"  largest unclassified sessions {st.dim}(tune 'categories' in config to catch them){st.reset}")
        for s in un[:5]:
            print(f"    {fmt(s['tokens']):>7}  {clip(s['project'], 14)}: {clip(s['prompt'], 52)}")


# ---------------------------------------------------------------- text output

PALETTE = ["cyan", "magenta", "yellow", "blue", "green"]


def totals(rows) -> dict:
    """window -> {fresh, total, cost, unpriced} summed over rows."""
    out = defaultdict(lambda: {"fresh": 0, "total": 0, "cost": 0.0, "priced": False, "unpriced": 0})
    for r in rows:
        t = out[r["period"]]
        t["fresh"] += r["fresh"]; t["total"] += r["total"]; t["unpriced"] += r.get("unpriced", 0)
        if r.get("cost") is not None:
            t["cost"] += r["cost"]; t["priced"] = True
    return out


def cost_of(t):
    return t["cost"] if t["priced"] else None


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def change(st, cur, prev) -> str:
    """Coloured change label; green for an increase, red for a decrease."""
    if cur is None or prev is None:
        return "–"
    lab = change_label(cur, prev)
    hue = st.green if lab.startswith("↑") else st.red if lab.startswith("↓") else ""
    return f"{hue}{lab}{st.reset}" if hue else lab


def visible(s: str) -> int:
    import re
    return len(re.sub(r"\x1b\[[0-9;]*m", "", s))


def table(st, headers, rows, align):
    """Rounded box table. Cells may hold ANSI codes; widths use the visible text."""
    w = [max([visible(h)] + [visible(r[i]) for r in rows]) for i, h in enumerate(headers)]

    def cell(text, i):
        pad = " " * (w[i] - visible(text))
        return pad + text if align[i] == ">" else text + pad

    def rule(a, m, b):
        return f"{st.dim}{a}" + m.join("─" * (x + 2) for x in w) + f"{b}{st.reset}"

    bar = f"{st.dim}│{st.reset}"
    out = [rule("╭", "┬", "╮"),
           bar + bar.join(f" {st.dim}{cell(h, i)}{st.reset} " for i, h in enumerate(headers)) + bar,
           rule("├", "┼", "┤")]
    out += [bar + bar.join(f" {cell(c, i)} " for i, c in enumerate(r)) + bar for r in rows]
    out.append(rule("╰", "┴", "╯"))
    return "\n".join(out)


def wrap(line: str, width: int = 80, sep: str = " · ") -> list[str]:
    """Break a ' · '-joined line at its separators so each piece fits `width` (ANSI codes don't count).
    Continuation lines are indented under the text after a leading 'label: '."""
    pieces = line.split(sep)
    head = visible(pieces[0].split(": ", 1)[0]) + 2 if ": " in pieces[0] else 0
    out = [pieces[0]]
    for x in pieces[1:]:
        if visible(out[-1]) + len(sep) + visible(x) <= width:
            out[-1] += sep + x
        else:
            out.append(" " * head + x)
    return out


def limit_lines(st, limits) -> list[str]:
    """'Claude limits: 5-hour 4% resets 20:29 · week 1% resets Tue 17 Nov · as of 16:00', one line per tool.
    A reading whose reset time has passed is out of date: its numbers are dimmed and that is said once."""
    from .limits import age, short
    out = []
    for tool in dict.fromkeys(x["tool"] for x in limits):
        mine = [x for x in limits if x["tool"] == tool and (x["percent"] or "(" not in x["name"])]
        if not mine:
            continue
        parts = []
        for x in mine:
            hue = st.dim if x["stale"] else st.red if x["percent"] >= 90 else st.yellow if x["percent"] >= 70 else ""
            pct = f"{hue}{x['percent']}%{st.reset}" if hue else f"{x['percent']}%"
            parts.append(f"{x['name']} {pct}" + ("" if x["stale"] else f" {short(x)}".rstrip()))
        note = age(mine[0])
        if any(x["stale"] for x in mine):
            note += ", out of date" + (": open /usage in Claude Code" if tool == "Claude" else "")
        out.append(f"{tool} limits: " + " · ".join(parts) + f" {st.dim}· {note}{st.reset}")
    return out


def show(weekly, sessions, wanted, label, per, prev, cfg, adhoc, args, all_rows=(), limits=()):
    from .prices import AS_OF, money, split
    st = Style(use_color())
    routing = bool(cfg.get("routing"))
    by_week = defaultdict(list)
    for r in weekly:
        by_week[r["period"]].append(r)
    keys = sorted(by_week)
    cur = totals(weekly)
    noun = per.name

    if len(wanted) > 1:                                     # several windows: one line each, then the latest in detail
        rows = []
        for wk in sorted(wanted):
            t, p = cur.get(wk), prev.get(per.previous(wk))
            if not t:
                rows.append([label(wk), "0", "–", "–"]); continue
            rows.append([label(wk), f"{st.b}{fmt(t['fresh'])}{st.reset}", money(cost_of(t)),
                         change(st, t["fresh"], p["fresh"]) if p else "–"])
        print(table(st, [noun, "tokens", "cost", f"vs prev"], rows, "<>>>"))
        keys = keys[-1:]

    for wk in keys:
        rows = sorted(by_week[wk], key=lambda r: -r["fresh"])
        t = cur[wk]
        fresh, cost = t["fresh"], cost_of(t)
        n = len({(x["tool"], x["session"]) for x in sessions if x["period"] == wk and not x["auto"]})
        print(f"\n{st.b}{st.cyan}{label(wk)}{st.reset}" if st.on else f"\n=== {label(wk)} ===")
        line = f"{st.b}{fmt(fresh)} tokens{st.reset} · {st.b}{money(cost)}{st.reset} · {n} session{'s' * (n != 1)}"
        p = None if adhoc else prev.get(per.previous(wk))
        if p and p["fresh"]:
            line += f" · {change(st, fresh, p['fresh'])} vs previous {noun} ({fmt(p['fresh'])})"
        print(line)

        prev_by = defaultdict(int)
        if not adhoc:
            for r in all_rows:
                if r["period"] == per.previous(wk):
                    prev_by[(r["tool"], r["model"])] += r["fresh"]
        headers = ["model"] + (["tier"] if routing else []) + ["tool", "tokens", "share", "cost"] + ([] if adhoc else [f"vs prev"])
        out = []
        for i, r in enumerate(rows):
            share = r["fresh"] / fresh if fresh else 0
            k = round(share * 10)
            hue = getattr(st, PALETTE[i % len(PALETTE)])
            cells = [clip(r["model"], 24)] + ([r["tier"]] if routing else []) + [
                r["tool"], f"{st.b}{fmt(r['fresh'])}{st.reset}", f"{hue}{'█' * k}{st.reset}{st.dim}{'░' * (10 - k)}{st.reset}",
                money(r.get("cost"))]
            if not adhoc:
                pv = prev_by.get((r["tool"], r["model"]), 0)
                cells.append(change(st, r["fresh"], pv) if p else "–")
            out.append(cells)
        align = "<" + ("<" if routing else "") + "<>" + "<>" + ("" if adhoc else ">")
        print(table(st, headers, out, align))

        auto = sum(r["auto_tokens"] for r in rows)
        if args.sessions:                       # --detail: what the tokens and the cost are made of
            kinds = [f"{fmt(t['total'])} incl. cache reads", f"input {fmt(sum(r['input'] for r in rows))}",
                     f"cache writes {fmt(sum(r['cache_write'] for r in rows))}", f"output {fmt(sum(r['output'] for r in rows))}"]
            print(f"{st.dim}tokens: " + " · ".join(kinds) + st.reset)
            cparts = defaultdict(float)
            for r in rows:
                for k, v in (r.get("cost_parts") or {}).items():
                    cparts[k] += v
            if split(cparts):
                print(f"{st.dim}cost: {split(cparts)}{st.reset}")
        if adhoc or wk == per.current():
            for line in limit_lines(st, limits):
                print("\n".join(wrap(line)))
        notes = []
        if routing:
            notes.append(f"on-policy {pct(on_policy_pct(rows))} of judged tokens")
        if auto:
            notes.append(f"subagents {fmt(auto)}" + (" (not judged)" if routing else ""))
        if t["unpriced"]:
            um = sorted({r["model"] for r in rows if r.get("unpriced")})
            notes.append(f"{fmt(t['unpriced'])} tokens have no price ({', '.join(um[:3])}): add them under \"prices\" in config")
        notes.append(f"cost at API prices of {AS_OF}, not your bill")
        if not args.sessions:
            notes.append("more: --detail, agentmeter tui")
        print("\n".join(f"{st.dim}{x}{st.reset}" for x in wrap(" · ".join(notes))))
        if routing:
            note = unmapped_note(rows)
            if note:
                print(f"note: {note}")
            off = sorted((s for s in sessions if s["period"] == wk and s["on_policy"] == "no"), key=lambda s: -s["tokens"])
            if off:
                print(f"\n{st.yellow}off-policy{st.reset}: {len(off)} session{'s' * (len(off) != 1)}, {fmt(sum(s['tokens'] for s in off))} tokens "
                      f"{st.dim}(a shortlist to look at, not a verdict){st.reset}")
                for s in off[: args.prompts or 3]:
                    print(f"  [{s['category']}] {s['model']} · {s['project']}: {clip(s['prompt'], 70)} ({fmt(s['tokens'])})")
        if args.sessions:
            sessions_detail(st, rows, [s for s in sessions if s["period"] == wk and not s["auto"]], routing, args.prompts or 5)


def sessions_detail(st, rows, ss, routing, n):
    from .prices import money
    for r in rows:
        mine = sorted((s for s in ss if s["tool"] == r["tool"] and s["model"] == r["model"]), key=lambda s: -s["fresh"])
        if not mine:
            continue
        print(f"\n{st.b}{r['model']}{st.reset} {st.dim}· {r['tool']} · {len(mine)} session{'s' * (len(mine) != 1)}{st.reset}")
        for s in mine[:n]:
            tag = f"[{s['category']}] " if routing else ""
            print(f"  {fmt(s['fresh']):>7} {money(s.get('cost')):>8}  {st.dim}{clip(s['project'], 14):<14}{st.reset} "
                  f"{tag}{clip(s['prompt'], 45 - len(tag))}")


HELP = """Tokens your coding agents used, per model, per window (a week by default).

commands:
  agentmeter              this window: tokens, cost, models, plan limits
  agentmeter tui          full-screen view: flip through windows, today, reports
  agentmeter reports      saved reports, one per finished window
  agentmeter setup        choose tools, your window, and routing
  agentmeter doctor       check it's working: config, tools found, reports

Each command has its own --help."""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[:1]
    if cmd in (["setup"], ["init"]):
        from .wizard import main_init
        if "-h" in argv or "--help" in argv:
            print("usage: agentmeter setup\n\nThe setup questions: which tools to read, when your window starts and how long it is, "
                  "and optional routing. Change your answers any time by running it again.")
            return
        return main_init()
    if cmd in (["doctor"], ["check"]):
        return doctor(argv[1:])
    if cmd == ["reports"]:
        return reports_cmd(argv[1:])
    if cmd == ["tui"]:
        from .tui import main as tui_main
        return tui_main(argv[1:])
    quiet = {"--tools", "--json", "--status", "--status-json", "--save", "-h", "--help"}
    if (not config_path().exists() and sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("AGENTMETER_NO_WIZARD")
            and not quiet & set(argv)):
        print("No setup yet, so here are the questions (skip with AGENTMETER_NO_WIZARD=1).")
        from .wizard import main_init
        main_init()
    ap = argparse.ArgumentParser(prog="agentmeter", usage="agentmeter [command] [options]", description=HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    rng = ap.add_argument_group("which time to show (default: the last 4 windows, this one in detail)")
    rng.add_argument("--today", action="store_true", help="since midnight")
    rng.add_argument("--since", metavar="WHEN", help="from then until now: 6h, 3d, 2w, a date or an ISO datetime")
    rng.add_argument("--from", dest="frm", metavar="DATE", help="from this date (or ISO datetime) ...")
    rng.add_argument("--to", metavar="DATE", help="... to this one; a plain date includes that whole day")
    rng.add_argument("--period", dest="period", metavar="WHICH", help="one window: this, last, or any date in it")
    rng.add_argument("--periods", type=int, dest="periods", metavar="N", help="the last N windows (default 4)")
    det = ap.add_argument_group("detail")
    det.add_argument("--detail", action="store_true", dest="sessions",
                     help="also the largest sessions per model, and what the tokens and cost are made of")
    det.add_argument("--top", type=int, dest="prompts", metavar="N", help="with --detail: sessions per model (default 5)")
    out = ap.add_argument_group("for scripts and status bars")
    out.add_argument("--json", action="store_true", help="everything as JSON: {periods, sessions, config, limits}")
    out.add_argument("--status", action="store_true", help="one line: TOKENS 1.13M")
    out.add_argument("--status-json", action="store_true", help="Waybar JSON: {text, tooltip, class}")
    adv = ap.add_argument_group("where to read")
    adv.add_argument("--tool", action="append", metavar="NAME", help="only this tool (repeatable); default: your setup, else every tool found")
    adv.add_argument("--root", action="append", default=[], metavar="TOOL=DIR", help="read a tool's logs from another folder")
    # older spellings: still accepted, not listed
    hide = argparse.SUPPRESS
    ap.add_argument("--weeks", type=int, dest="periods", help=hide)
    ap.add_argument("--week", dest="period", help=hide)
    ap.add_argument("--sessions", action="store_true", dest="sessions", help=hide)
    ap.add_argument("--prompts", type=int, dest="prompts", help=hide)
    ap.add_argument("--tools", action="store_true", help=hide)
    ap.add_argument("--save", nargs="?", const=report.DEFAULT_DIR, metavar="DIR", help=hide)
    ap.add_argument("--force", action="store_true", help=hide)
    args = ap.parse_args(argv)

    if args.tools:
        for name, state, where, desc in tool_rows():
            print(f"{name:<12} {state:<6}  {where:<46} {desc}")
        return

    cfg = load_config()
    try:
        roots = {**cfg.get("roots", {}), **dict(r.split("=", 1) for r in args.root)}
    except ValueError:
        ap.error("--root: expected TOOL=DIR, e.g. --root codex=/path/to/sessions")
    if not args.tool and cfg.get("tools"):
        args.tool = cfg["tools"]
    for t in args.tool or []:
        if t.replace("-", "_") not in adapters.BUILTIN:
            ap.error(f"--tool: unknown tool {t!r}; known: {', '.join(n.replace('_', '-') for n in adapters.BUILTIN)}")
    policy = load_policy(cfg)
    per = Periods.from_config(cfg)
    this_p, last_p = per.back(2)[::-1]

    adhoc = args.today or args.since or args.frm
    if args.to and not args.frm:
        ap.error("--to needs --from")
    if adhoc and (args.period or args.periods or args.save or args.status or args.status_json):
        ap.error("--since / --from / --today make their own window; don't combine them with --period(s), --save or --status")
    if adhoc:
        try:
            frm = parse_since("today" if args.today else args.since or args.frm)
            to = None
            if args.to:
                to = parse_since(args.to)
                if len(args.to) == 10:          # a plain date includes that whole day
                    to += dt.timedelta(days=1)
        except ValueError:
            ap.error("--since/--from/--to: expected 6h, 3d, 2w, today, YYYY-MM-DD or an ISO datetime")
        wanted = [frm.date().isoformat()]
        bucket = by_range(frm, to)
        end = (to - dt.timedelta(seconds=1)) if to else dt.datetime.now().astimezone()
        midnight = dt.time()
        label = lambda k: (span_label(frm.date(), end.date()) if to and frm.time() == midnight == to.time() else
                           f"{frm:%a %-d %b %H:%M} – {'now' if not to else f'{end:%a %-d %b %H:%M}'}")
    else:
        if args.period:
            try:
                args.period = per.parse(args.period)
            except ValueError:
                ap.error(f"--period: expected this, last, YYYY-MM-DD or YYYY-Www, got {args.period!r}")
        if args.status or args.status_json:
            wanted = [last_p, this_p]
        elif args.period:
            wanted = [args.period]
        elif args.save and not args.periods:
            # every window that could still have logs (tools prune after ~30 days), so a long gap is caught up
            wanted = per.covering(dt.date.today() - dt.timedelta(days=35))
        else:
            wanted = per.back(args.periods or 4)
        # also load the window before the first one asked for, so it can be compared; it isn't shown
        lookback = [] if args.save or args.status or args.status_json else [per.previous(min(wanted))]
        bucket = by_period(per, list(wanted) + lookback)
        label = per.label
    if adhoc:
        lookback = []
    weekly, sessions = aggregate(collect(args.tool, roots, since(list(wanted) + lookback)), policy, bucket,
                                 Prices(cfg.get("prices")))
    prev = totals(weekly)                  # window -> totals, for "vs previous" lines (includes the lookback window)
    all_rows = weekly
    weekly = [r for r in weekly if r["period"] in wanted]
    sessions = [s for s in sessions if s["period"] in wanted]

    if args.status or args.status_json:
        rows = sorted((r for r in weekly if r["period"] == this_p), key=lambda r: -r["fresh"])
        fresh = sum(r["fresh"] for r in rows)
        if args.status:
            print(f"TOKENS {fmt(fresh)}"); return
        prev = sum(r["fresh"] for r in weekly if r["period"] == last_p)
        cost = sum(r["cost"] for r in rows if r.get("cost") is not None) if any(r.get("cost") is not None for r in rows) else None
        tip = [f"Tokens this {per.name} ({per.label(this_p)}): {fmt(fresh)} · {money(cost)} at API prices",
               f"{fmt(sum(r['total'] for r in rows))} including cache reads"]
        tip += [f"  {r['model'][:24]:<24} {fmt(r['fresh']):>7}" for r in rows]
        tip.append(f"Last {per.name}: {fmt(prev)}")
        tip += [x for x in limit_lines(Style(False), all_limits())]
        # Pango markup: a small caption before the number, the one-line form of the macOS menu bar look
        text = f"<span size='x-small' weight='medium'>TOKENS</span> {fmt(fresh)}"
        print(json.dumps({"text": text, "tooltip": "\n".join(tip), "class": "agentmeter"}))
        return

    meta = {"tiers": tier_order(cfg), "policy": cfg["policy"], "unmapped": unmapped(weekly),
            "period": {"length": per.length, "start": per.begins.isoformat() if per.begins else None, "name": per.name},
            "this_period": this_p, "last_period": last_p,
            "labels": {k: label(k) for k in wanted}}
    if args.save:
        done = report.save(args.save, weekly, sessions, {k: meta[k] for k in ("tiers", "policy", "period")}, wanted,
                           per, n_prompts=max(args.prompts or 5, 5), force=args.force)
        d = Path(args.save).expanduser()
        print(f"wrote {', '.join(done)} to {d}" if done else f"no new finished {per.name}s to write in {d}")
        return
    if args.json:
        from .limits import age, short
        from .prices import PARTS, split
        limits = all_limits()
        parts = defaultdict(lambda: defaultdict(float))
        for r in weekly:
            for k, v in (r.get("cost_parts") or {}).items():
                parts[r["period"]][k] += v
        meta["cost_split"] = {k: split(v) for k, v in parts.items()}      # ready-made text for the menu bar app
        meta["limit_lines"] = limit_lines(Style(False), limits)
        # rows for the menu bar app, drawn like the model rows: [label, dollars] largest first; limits with a note
        names = dict(PARTS)
        meta["cost_parts"] = {k: [[names.get(n, n), round(x, 4)] for n, x in sorted(v.items(), key=lambda kv: -kv[1]) if x >= 0.005]
                              for k, v in parts.items()}
        shown = [x for x in limits if x["percent"] or "(" not in x["name"]]
        meta["limit_rows"] = [{"label": f"{x['tool']} {x['name']}", "percent": x["percent"], "stale": x["stale"],
                               "note": short(x)} for x in shown]
        meta["limits_caption"] = " · ".join(f"{t} {age(next(x for x in shown if x['tool'] == t))}"
                                            for t in dict.fromkeys(x["tool"] for x in shown))
        json.dump({"periods": weekly, "sessions": sessions, "config": meta, "limits": limits}, sys.stdout, indent=1)
        return
    if not weekly:
        print(f"no sessions in {label(wanted[0]) if adhoc else 'the selected ' + per.name + 's'}")
        if adhoc or per.current() in wanted:
            for line in limit_lines(Style(use_color()), all_limits()):
                print("\n".join(wrap(line)))
        return
    show(weekly, sessions, wanted, label, per, prev, cfg, adhoc, args, all_rows, all_limits())


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
