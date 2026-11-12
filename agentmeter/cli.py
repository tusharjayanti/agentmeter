"""agentmeter CLI.

  agentmeter                      # last 4 windows (config `period`), every tool whose logs exist
  agentmeter --tool codex --periods 8
  agentmeter --period last         # or this, or any date in the window: --period 2026-10-22
  agentmeter --today               # any time: since midnight; or --since 6h / 3d / 2026-10-01
  agentmeter --from 2026-10-01 --to 2026-10-15
  agentmeter --json
  agentmeter --save               # keep <start>.md + <start>.json for each finished window
  agentmeter --tools              # which adapters found logs
  agentmeter check                # validate config; show how recent models and sessions resolve
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
    return f"{fmt(sum(um.values()))} tokens on models with no tier ({names}): add them with `agentmeter init` or to 'tiers'"


def load_policy(cfg) -> Policy:
    errors, _ = validate(cfg)
    if errors:
        sys.exit(f"bad config {config_path()}:\n  " + "\n  ".join(errors) + "\nrun `agentmeter check` for details")
    return Policy(cfg)


def check(argv):
    ap = argparse.ArgumentParser(prog="agentmeter check",
                                 description="Validate the config and show how recent models and sessions resolve.")
    ap.add_argument("--periods", "--weeks", type=int, default=4, dest="periods")
    args = ap.parse_args(argv)
    cfg, p = load_config(), config_path()
    print(f"config: {p}" + ("" if p.exists() else "  (not found: built-in defaults apply; create one with `agentmeter init`)"))
    errors, warnings = validate(cfg)
    for m in errors:
        print(f"  error:   {m}")
    for m in warnings:
        print(f"  warning: {m}")
    if errors:
        sys.exit(1)
    if not warnings:
        print("  ok")
    policy = Policy(cfg)
    per = Periods.from_config(cfg)
    cur = per.current()
    print(f"windows: {per.describe()}")
    print(f"  current: {per.label(cur)} · its report is saved on {per.end(cur) + dt.timedelta(days=1):%a %-d %b %Y}")
    if per.begins and per.begins > dt.date.today():
        print(f"  collection begins {per.begins:%a %-d %b %Y}: nothing is saved before then")
    wanted = per.back(args.periods)
    weekly, sessions = aggregate(collect(cfg.get("tools") or None, cfg.get("roots", {}), since(wanted)), policy,
                                 by_period(per, wanted), Prices(cfg.get("prices")))

    models = defaultdict(int)
    for r in weekly:
        models[r["model"]] += r["total"]
    print(f"\nmodels seen in the last {args.periods} {per.name}s → tier → work it is meant for")
    for m in sorted(models, key=lambda m: -models[m]):
        t = policy.tier(m)
        meant = ", ".join(cfg["policy"].get(t, [])) or ("never judged: no tier matches" if t == "unknown" else "(no policy)")
        print(f"  {m[:28]:<28} {fmt(models[m]):>8}  {t:<9} {meant}")

    judged = [s for s in sessions if not s["auto"]]
    cats = defaultdict(lambda: [0, 0])
    for s in judged:
        cats[s["category"]][0] += 1
        cats[s["category"]][1] += s["tokens"]
    print("\nwork categories (session slices, tokens)")
    for c, (n, tok) in sorted(cats.items(), key=lambda x: -x[1][1]):
        print(f"  {c:<13}{n:>4}  {fmt(tok):>8}")
    un = sorted((s for s in judged if s["category"] == "unclassified"), key=lambda s: -s["tokens"])
    if un:
        print("\nlargest unclassified sessions (no category regex matched; tune 'categories' to catch them):")
        for s in un[:5]:
            print(f"  {fmt(s['tokens']):>8}  {s['project']}: {s['prompt'][:90]}")


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


def limit_lines(st, limits) -> list[str]:
    """'Claude limits: 5-hour 4% resets 20:29 · week 1% resets Tue 17 Nov · as of 16:00', one line per tool."""
    from .limits import age, short
    out = []
    for tool in dict.fromkeys(x["tool"] for x in limits):
        mine = [x for x in limits if x["tool"] == tool and (x["percent"] or "(" not in x["name"])]
        if not mine:
            continue
        parts = []
        for x in mine:
            hue = st.red if x["percent"] >= 90 else st.yellow if x["percent"] >= 70 else ""
            pct = f"{hue}{x['percent']}%{st.reset}" if hue else f"{x['percent']}%"
            parts.append(f"{x['name']} {st.dim if x['stale'] else ''}{pct}{st.reset if x['stale'] else ''} {short(x)}".rstrip())
        out.append(f"{tool} limits: " + " · ".join(parts) + f" {st.dim}· {age(mine[0])}{st.reset}")
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
        parts = [f"{fmt(t['total'])} incl. cache reads", f"in {fmt(sum(r['input'] for r in rows))}",
                 f"cache writes {fmt(sum(r['cache_write'] for r in rows))}", f"out {fmt(sum(r['output'] for r in rows))}"]
        if auto:
            parts.append(f"subagents {fmt(auto)}" + (" (not judged)" if routing else ""))
        if routing:
            parts.insert(0, f"on-policy {pct(on_policy_pct(rows))} of judged tokens")
        print(f"{st.dim}" + " · ".join(parts) + st.reset)
        parts = defaultdict(float)
        for r in rows:
            for k, v in (r.get("cost_parts") or {}).items():
                parts[k] += v
        if split(parts):
            print(f"{st.dim}cost: {split(parts)}{st.reset}")
        notes = [f"API prices of {AS_OF}, not a subscription bill"]
        if t["unpriced"]:
            um = sorted({r["model"] for r in rows if r.get("unpriced")})
            notes.append(f"{fmt(t['unpriced'])} tokens have no price ({', '.join(um[:3])}): add them under \"prices\" in config")
        if not args.sessions:
            notes.append("--sessions for details")
        print(f"{st.dim}" + " · ".join(notes) + st.reset)
        if adhoc or wk == per.current():
            for line in limit_lines(st, limits):
                print(line)
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
            print(f"  {fmt(s['fresh']):>7} {money(s.get('cost')):>8}  {st.dim}{clip(s['project'], 14):<14}{st.reset} {tag}{clip(s['prompt'], 60)}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["init"]:
        from .wizard import main_init
        return main_init()
    if argv[:1] == ["check"]:
        return check(argv[1:])
    if argv[:1] == ["tui"]:
        from .tui import main as tui_main
        return tui_main(argv[1:])
    if not config_path().exists() and sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("AGENTMETER_NO_WIZARD") and "--tools" not in argv:
        print("No config yet; running setup (skip with AGENTMETER_NO_WIZARD=1).")
        from .wizard import main_init
        main_init()
    ap = argparse.ArgumentParser(prog="agentmeter", description="Token usage and model routing for agentic coding tools.",
                                 epilog="agentmeter init    interactive setup (tools, models, tiers, policy)\n"
                                        "agentmeter check   validate the config; show how models and sessions resolve",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tool", action="append", help="adapter name; repeatable. Default: every adapter with logs present")
    ap.add_argument("--root", action="append", default=[], metavar="TOOL=DIR", help="override a tool's log root")
    ap.add_argument("--periods", "--weeks", type=int, dest="periods", metavar="N",
                    help="last N windows, current included (default 4; window length and start come from config `period`)")
    ap.add_argument("--period", "--week", dest="period",
                    help="one window: 'this', 'last', any date in it (2026-10-22), or an ISO week (2026-W43)")
    ap.add_argument("--since", help="ad hoc window from then until now: 6h, 3d, 2w, today, a date or an ISO datetime")
    ap.add_argument("--from", dest="frm", metavar="DATE", help="ad hoc window start (date or ISO datetime)")
    ap.add_argument("--to", metavar="DATE", help="with --from: ad hoc window end; a plain date includes that whole day")
    ap.add_argument("--today", action="store_true", help="same as --since today")
    ap.add_argument("--status", action="store_true", help="one line for a status bar: tokens used this window, e.g. 'TOKENS 1.13M'")
    ap.add_argument("--status-json", action="store_true", help="Waybar JSON: {text (Pango markup), tooltip, class}")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", nargs="?", const=report.DEFAULT_DIR, metavar="DIR",
                    help=f"write <start>.md and <start>.json for each finished window that has no report yet "
                         f"(default DIR: {report.DEFAULT_DIR})")
    ap.add_argument("--force", action="store_true", help="with --save: rewrite reports that already exist")
    ap.add_argument("--sessions", action="store_true", help="list the largest sessions per model under the table")
    ap.add_argument("--prompts", type=int, metavar="N", help="how many sessions to list per model (default 5 with --sessions)")
    ap.add_argument("--tools", action="store_true", help="list adapters and whether their logs exist")
    args = ap.parse_args(argv)

    if args.tools:
        for n in adapters.BUILTIN:
            mod = adapters.load(n)
            r = mod.default_root()
            print(f"{mod.NAME:<12} {'found ' if r.exists() else 'absent'}  {adapters.where(mod, r if r.exists() else None):<52} {mod.DESC}")
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
        from .prices import split
        limits = all_limits()
        parts = defaultdict(lambda: defaultdict(float))
        for r in weekly:
            for k, v in (r.get("cost_parts") or {}).items():
                parts[r["period"]][k] += v
        meta["cost_split"] = {k: split(v) for k, v in parts.items()}      # ready-made text for the menu bar app
        meta["limit_lines"] = limit_lines(Style(False), limits)
        json.dump({"periods": weekly, "sessions": sessions, "config": meta, "limits": limits}, sys.stdout, indent=1)
        return
    if not weekly:
        print(f"no sessions in {label(wanted[0]) if adhoc else 'the selected ' + per.name + 's'}")
        if adhoc or per.current() in wanted:
            for line in limit_lines(Style(use_color()), all_limits()):
                print(line)
        return
    show(weekly, sessions, wanted, label, per, prev, cfg, adhoc, args, all_rows, all_limits())


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
