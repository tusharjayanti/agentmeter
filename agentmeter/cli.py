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
from .core import (Periods, Policy, aggregate, by_period, by_range, config_path, load_config, on_policy_pct,
                   parse_since, since, span_label, validate)


def fmt(n):
    n = float(n)
    return f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.0f}k" if n >= 1e3 else str(int(n))


def pct(p):
    return f"{p:.0f}%" if p is not None else "–"


def collect(tool_names, roots, since_ts=None):
    mods = [adapters.load(t) for t in tool_names] if tool_names else adapters.available()
    for mod in mods:
        root = Path(roots.get(mod.NAME)).expanduser() if roots.get(mod.NAME) else mod.default_root()
        if not root.exists():
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
                                 by_period(per, wanted))

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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["init"]:
        from .wizard import main_init
        return main_init()
    if argv[:1] == ["check"]:
        return check(argv[1:])
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
    ap.add_argument("--prompts", type=int, default=3, help="sample prompts per model per window")
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
        bucket = by_period(per, wanted)
        label = per.label
    weekly, sessions = aggregate(collect(args.tool, roots, since(wanted)), policy, bucket)

    if args.status or args.status_json:
        rows = sorted((r for r in weekly if r["period"] == this_p), key=lambda r: -r["fresh"])
        fresh = sum(r["fresh"] for r in rows)
        if args.status:
            print(f"TOKENS {fmt(fresh)}"); return
        prev = sum(r["fresh"] for r in weekly if r["period"] == last_p)
        tip = [f"Tokens this {per.name} ({per.label(this_p)}): {fmt(fresh)}",
               f"{fmt(sum(r['total'] for r in rows))} including cache reads"]
        tip += [f"  {r['model'][:24]:<24} {fmt(r['fresh']):>7}" for r in rows]
        tip.append(f"Last {per.name}: {fmt(prev)}")
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
                           per, n_prompts=max(args.prompts, 5), force=args.force)
        d = Path(args.save).expanduser()
        print(f"wrote {', '.join(done)} to {d}" if done else f"no new finished {per.name}s to write in {d}")
        return
    if args.json:
        json.dump({"periods": weekly, "sessions": sessions, "config": meta}, sys.stdout, indent=1)
        return
    if not weekly:
        print(f"no sessions in {label(wanted[0]) if adhoc else 'the selected ' + per.name + 's'}"); return

    by_week = defaultdict(list)
    for r in weekly:
        by_week[r["period"]].append(r)
    sess_by = defaultdict(list)
    for s in sessions:
        sess_by[(s["period"], s["tool"], s["model"])].append(s)

    routing = bool(cfg.get("routing"))
    keys = sorted(by_week)
    for i, wk in enumerate(keys):
        rows = sorted(by_week[wk], key=lambda r: -r["fresh"])
        fresh = sum(r["fresh"] for r in rows)
        print(f"\n=== {label(wk)} ===")
        n = len({(x["tool"], x["session"]) for x in sessions if x["period"] == wk and not x["auto"]})
        line = f"{fmt(fresh)} tokens · {n} session{'s' * (n != 1)}"
        if not adhoc and i > 0 and keys[i - 1] == per.previous(wk):
            prev = sum(r["fresh"] for r in by_week[keys[i - 1]])
            line += f" · previous {per.name} {fmt(prev)} ({100 * (fresh - prev) / prev:+.0f}%)" if prev else ""
        print(line)
        tier = f"{'tier':<9}" if routing else ""
        print(f"{'tool':<12}{'model':<22}{tier}{'tokens':>8}{'in':>8}{'cache_w':>8}{'out':>8}{'cache_r':>9}{'turns':>6}")
        for r in rows:
            t = f"{r['tier']:<9}" if routing else ""
            print(f"{r['tool']:<12}{r['model'][:21]:<22}{t}{fmt(r['fresh']):>8}{fmt(r['input']):>8}{fmt(r['cache_write']):>8}{fmt(r['output']):>8}{fmt(r['cache_read']):>9}{r['turns']:>6}")
        auto = sum(r["auto_tokens"] for r in rows)
        extra = [f"{fmt(sum(r['total'] for r in rows))} including cache reads"]
        if auto:
            extra.append(f"subagents {fmt(auto)}" + (" (not judged)" if routing else ""))
        if routing:
            extra.insert(0, f"on-policy {pct(on_policy_pct(rows))} of judged tokens")
        print(" · ".join(extra))
        if routing:
            note = unmapped_note(rows)
            if note:
                print(f"note: {note}")
        for r in rows:
            ss = [s for s in sess_by[(wk, r["tool"], r["model"])] if not s["auto"]]
            if routing:
                mix = ", ".join(f"{c} {100*n//max(1,r['total'])}%" for c, n in sorted(r["mix"].items(), key=lambda x: -x[1]))
                print(f"\n  {r['model']} [{r['tier']}]: {r['sessions']} sessions — {mix}")
                off = sorted((s for s in ss if s["on_policy"] == "no"), key=lambda s: -s["tokens"])
                if off:
                    print(f"    off-policy: {len(off)} sessions, {fmt(r['off_policy_tokens'])} tokens ({100*r['off_policy_tokens']//max(1,r['total'])}%)")
                    for s in off[:args.prompts]:
                        print(f"      [{s['category']}] {s['project']}: {s['prompt'][:90]} ({fmt(s['tokens'])})")
                ss = [s for s in ss if s["on_policy"] != "no"]
            else:
                print(f"\n  {r['model']}: {r['sessions']} session{'s' * (r['sessions'] != 1)}")
            for s in sorted(ss, key=lambda s: -s["fresh"])[:args.prompts]:
                tag = f"[{s['category']}] " if routing else ""
                print(f"    • {tag}{s['project']}: {s['prompt'][:90]} ({fmt(s['fresh'])})")

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
