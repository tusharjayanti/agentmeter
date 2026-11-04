"""First-run setup: `agentmeter init`. Also runs automatically the first time
agentmeter is used without a config and stdin is a terminal."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import adapters
from .core import DEFAULT_CONFIG, Periods, Policy, config_path, parse_length
from .prompt import BOLD, DIM, GREEN, RESET, Abort, confirm, multiselect, select, text

# (label, regex, default tier) — the catalogue people pick from
MODELS = [
    ("Claude Fable / Mythos", r"fable|mythos", "premium"),
    ("Claude Opus", r"opus", "strong"),
    ("Claude Sonnet", r"sonnet", "standard"),
    ("Claude Haiku", r"haiku", "economy"),
    ("GPT-5 Pro / o3-pro", r"gpt-5(\.\d)?-pro|o3-pro", "premium"),
    ("GPT-5 Codex (incl. -max)", r"gpt-5(\.\d)?-codex", "strong"),
    ("GPT-5 / GPT-4.x", r"gpt-5(\.\d)?$|gpt-4", "standard"),
    ("GPT-5 mini / nano", r"(^|-)mini\b|(^|-)nano\b", "economy"),
    ("Gemini Pro / Deep Think", r"gemini-.*-pro|deepthink", "strong"),
    ("Gemini Flash", r"gemini-.*-flash$", "standard"),
    ("Gemini Flash-Lite", r"flash-lite|flash-8b", "economy"),
    ("o3 / o4-mini", r"\bo3$|\bo4", "standard"),
]
TIERS = ["premium", "strong", "standard", "economy"]
TIER_BLURB = {
    "premium": "your most capable, most expensive model",
    "strong": "capable daily driver for building",
    "standard": "cheaper model for routine work",
    "economy": "smallest model for trivial edits",
}
CATEGORIES = [c for c, _ in DEFAULT_CONFIG["categories"]]
CAT_BLURB = {
    "design": "architecture, system design, trade-offs",
    "research": "comparisons, which library/db, investigations",
    "build": "new features, endpoints, scaffolding",
    "refactor": "restructuring, migrations, cleanups",
    "fix": "bugs, failing tests, debugging",
    "test": "writing tests, coverage",
    "docs": "README, docstrings, changelogs",
    "ops": "CI, deploys, docker, infra",
    "trivial": "typos, lint, quick questions",
    "explain": "how/why/what questions, understanding code",
}


def _seen_models(tools: list[str], roots: dict, weeks: int = 8) -> dict:
    """model id -> tokens over the last `weeks` weeks, read from the chosen tools' logs."""
    from collections import defaultdict
    from .cli import collect
    from .core import local
    frm, seen = dt.datetime.now().astimezone() - dt.timedelta(weeks=weeks), defaultdict(int)
    try:
        for s in collect(tools or None, roots, frm.timestamp() - 86400):
            for t in s.turns:
                if local(t.ts) >= frm:
                    seen[t.model] += t.total
    except Exception:   # a broken adapter must not break setup
        return {}
    return dict(seen)


def _model_options(seen: dict):
    """(options, prechecked). Catalogue families that match a model in the logs come first,
    then log models no family covers (so models released after this catalogue still get a tier),
    then the rest of the catalogue. Without logs, the plain catalogue with common picks ticked."""
    from .cli import fmt
    if not seen:
        pre = {i for i, (lbl, _, _) in enumerate(MODELS) if any(k in lbl for k in ("Claude", "GPT-5 Codex", "GPT-5 /"))}
        return list(MODELS), pre
    matched, rest, covered = [], [], set()
    for lbl, rx, d in MODELS:
        hits = [m for m in seen if m not in covered and re.search(rx, m, re.I)]
        covered.update(hits)
        if hits:
            matched.append((f"{lbl}  {DIM}seen: {', '.join(hits[:3])} · {fmt(sum(seen[m] for m in hits))}{RESET}", rx, d))
        else:
            rest.append((lbl, rx, d))
    defaults = Policy(DEFAULT_CONFIG)
    new = []
    for m in sorted(set(seen) - covered, key=lambda m: -seen[m]):
        t = defaults.tier(m)
        new.append((f"{m}  {DIM}seen in your logs · {fmt(seen[m])}{RESET}", re.escape(m), t if t in TIERS else None))
    options = matched + new + rest
    return options, set(range(len(matched) + len(new)))


def _header(step, total: int, title: str):
    print(f"\n{DIM}[{step}/{total}]{RESET} {BOLD}{title}{RESET}")


def _routing(cfg: dict, tools: list[str], total: int):
    """Optional: tiers and policy, for people who also want to see which model did which kind of work."""
    # models ----------------------------------------------------------
    _header("3a", total, "Which models do you use?")
    seen = _seen_models(tools, cfg["roots"])
    catalogue, pre = _model_options(seen)
    if seen:
        print(f"  {DIM}Models found in your logs over the last 8 weeks are listed first and ticked.{RESET}")
    picked = multiselect("Select every model family you use", [m[0] for m in catalogue], checked=pre)
    extra = []
    if confirm("Add a model that isn't listed?", default=False):
        while True:
            name = text("  model id substring (e.g. deepseek-v4, qwen3-coder)")
            if not name:
                break
            extra.append((name, re.escape(name), None))
            if not confirm("  add another?", default=False):
                break
    models = [catalogue[i] for i in picked] + extra

    # tiers -----------------------------------------------------------
    _header("3b", total, "Rank them into tiers")
    print(f"  {DIM}" + " · ".join(f"{t}: {TIER_BLURB[t]}" for t in TIERS) + RESET)
    tiers: dict[str, list[str]] = {t: [] for t in TIERS}
    for label, rx, default in models:
        d = TIERS.index(default) if default else 1
        t = TIERS[select(f"  {label}", TIERS, default=d)]
        tiers[t].append(rx)
    cfg["tiers"] = {t: rxs for t, rxs in tiers.items() if rxs}

    # policy ----------------------------------------------------------
    _header("3c", total, "What should each tier be used for?")
    print(f"  {DIM}Sessions whose work falls outside a tier's list count as off-policy.{RESET}")
    policy = {}
    for t in cfg["tiers"]:
        defaults = {CATEGORIES.index(c) for c in DEFAULT_CONFIG["policy"].get(t, []) if c in CATEGORIES}
        idx = multiselect(f"  {t}", [f"{c:<9} {DIM}{CAT_BLURB[c]}{RESET}" for c in CATEGORIES], checked=defaults)
        policy[t] = [CATEGORIES[i] for i in sorted(idx)]
    cfg["policy"] = policy


def run(existing: dict | None = None) -> dict:
    cfg = json.loads(json.dumps(existing or DEFAULT_CONFIG))
    cfg.setdefault("roots", {})
    cfg.pop("dashboard_url", None)
    total = 3
    print(f"\n{BOLD}agentmeter setup{RESET}  {DIM}arrow keys move · space toggles · enter confirms · q quits{RESET}")

    # 1. tools -----------------------------------------------------------
    _header(1, total, "Which coding tools do you use?")
    mods = [adapters.load(n) for n in adapters.BUILTIN if n != "generic"]
    found = []
    labels = []
    for i, m in enumerate(mods):
        custom = cfg["roots"].get(m.NAME)
        ok = Path(custom or m.default_root()).expanduser().exists()
        if ok:
            found.append(i)
        status = f"{GREEN}logs found" if ok else f"{DIM}no logs yet in {adapters.where(m, custom)}"
        labels.append(f"{m.NAME:<12} {m.DESC:<38} {status}{RESET}")
    print(f"  {DIM}Tick with space, then press enter. A tool with no logs yet can still be ticked: it is read once logs appear.{RESET}")
    chosen = multiselect("Select the tools you use", labels, checked=set(found))
    tools = []
    for i in chosen:
        m = mods[i]
        custom = cfg["roots"].get(m.NAME)
        if not Path(custom or m.default_root()).expanduser().exists() and not hasattr(m, "WHERE"):
            usual = str(m.default_root())
            ans = text(f"  {m.NAME} has no logs at {usual} yet. Enter keeps that; or type where yours are",
                       default=custom or usual,
                       validate=lambda v, usual=usual: None if v == usual or Path(v).expanduser().exists()
                       else "  that path does not exist (enter keeps the usual place)")
            if ans == usual:
                cfg["roots"].pop(m.NAME, None)
            else:
                cfg["roots"][m.NAME] = str(Path(ans).expanduser())
        tools.append(m.NAME)
    cfg["tools"] = tools
    if not tools:
        print(f"  {DIM}No tools selected; agentmeter will scan every adapter whose logs exist.{RESET}")

    # 5. windows -------------------------------------------------------
    _header(2, total, "What should each report cover?")
    print(f"  {DIM}Reports cover back-to-back windows of one length. Each is saved the first hour after it ends.{RESET}")
    print(f"  {DIM}You can still look at any range at any time: agentmeter --today, --since 3d, --from … --to …{RESET}")
    today = dt.date.today()
    cur = cfg.get("period") or {}
    begin_opts = [("today", today),
                  ("this Monday", today - dt.timedelta(days=today.weekday())),
                  ("the 1st of this month", today.replace(day=1)),
                  ("a date I choose", None)]
    i = select("  Collection begins", [f"{n:<22} {DIM}{d:%a %-d %b %Y}{RESET}" if d else n for n, d in begin_opts])
    begins = begin_opts[i][1]
    if begins is None:
        def _date(v):
            try:
                dt.date.fromisoformat(v)
            except ValueError:
                return "  expected YYYY-MM-DD"
        begins = dt.date.fromisoformat(text("  Date (YYYY-MM-DD)", default=str(cur.get("start") or today), validate=_date))
    if (today - begins).days > 30:
        print(f"  {DIM}Note: Claude Code deletes transcripts after 30 days by default, so older windows may be partial.{RESET}")
    lengths = [("1 week", "1w"), ("2 weeks", "2w"), ("1 month", "1m"), ("1 day", "1d"), ("custom", None)]
    j = select("  Each window lasts", [n for n, _ in lengths])
    length = lengths[j][1]
    if length is None:
        def _len(v):
            try:
                parse_length(v)
            except ValueError as e:
                return f"  {e}"
        length = text("  Length (e.g. 10d, 3w, 2m)", default=str(cur.get("length") or "1w"), validate=_len)
    cfg["period"] = {"start": begins.isoformat(), "length": length}
    cfg.pop("week_start", None)
    per = Periods.from_config(cfg)

    # 3. optional: routing ---------------------------------------------
    _header(3, total, "Also check which model did which kind of work? (optional)")
    print(f"  {DIM}Token counts don't need this. It sorts your models into tiers and flags sessions where an expensive")
    print(f"  model did routine work, or a cheap one did hard work. You can turn it on later with: agentmeter init{RESET}")
    routing = confirm("  Set up model routing?", default=bool(cfg.get("routing")))
    cfg["routing"] = routing
    if routing:
        _routing(cfg, tools, total)

    # summary ------------------------------------------------------------
    first = per.current(max(today, begins))
    print(f"\n{BOLD}Summary{RESET}")
    print(f"  tools:   {', '.join(tools) or 'auto-detect'}")
    print(f"  windows: {per.describe()}")
    done = [k for k in per.covering(begins) if k < first] if begins < today else []
    if done:
        print(f"  saved on the first run: {len(done)} finished {per.name}(s) since {begins:%-d %b}")
    print(f"  next report: {per.end(first) + dt.timedelta(days=1):%a %-d %b %Y}, covering {per.label(first)}")
    print(f"  routing: {'on' if routing else 'off'}")
    for t, rxs in (cfg["tiers"].items() if routing else []):
        print(f"  {t:<9}{len(rxs)} model pattern(s) → {', '.join(cfg['policy'].get(t, [])) or '(nothing)'}")
    p = config_path()
    choice = select(f"Save this to {p}?", ["Save", "Start over (nothing is saved yet)", "Quit without saving"])
    if choice == 1:
        raise StartOver
    if choice == 0:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2))
        print(f"  {GREEN}saved{RESET}. Change it any time with: agentmeter init (or Change setup… in the menu bar)")
    else:
        print("  not saved")
    return cfg


class StartOver(Exception):
    pass


def main_init():
    existing = json.loads(config_path().read_text()) if config_path().exists() else None
    while True:
        try:
            run(existing)
            return
        except StartOver:
            print(f"\n{DIM}Starting over.{RESET}")
        except Abort:
            print("\naborted: nothing saved")
            return
