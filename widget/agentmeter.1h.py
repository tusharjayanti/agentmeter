#!/usr/bin/env python3
# <xbar.title>agentmeter</xbar.title>
# <xbar.version>0.2.0</xbar.version>
# <xbar.author>agentmeter contributors</xbar.author>
# <xbar.desc>Tokens used this week across your agentic coding tools, per model.</xbar.desc>
# <xbar.dependencies>python3,agentmeter</xbar.dependencies>
"""Top-bar plugin for GNOME (Argos) and xbar-compatible hosts. On macOS the native app
in macos/ is the default; this is for Linux. Runs `agentmeter --periods 2 --json` hourly.

Bar: a small TOKENS caption and the number (Pango markup), the one-line form of the macOS look.
Menu: tokens and cost this window, plan limits, per model, last window, latest report."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
BIN = shutil.which("agentmeter") or str(HOME / ".local" / "bin" / "agentmeter")
CFG = Path(os.environ.get("AGENTMETER_CONFIG", "~/.config/agentmeter/config.json")).expanduser()
REPORTS = HOME / ".local" / "share" / "agentmeter" / "reports"
MONO = "font=monospace size=10"
GRAY = "color=gray"
OPEN = "/usr/bin/open" if sys.platform == "darwin" else "xdg-open"


def fmt(n):
    n = float(n)
    return f"{n/1e9:.2f}B" if n >= 1e9 else f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.0f}k" if n >= 1e3 else f"{int(n)}"


def money(x):
    if x is None:
        return "–"
    return "$0" if x == 0 else "<$0.01" if x < 0.01 else f"${x:,.0f}" if x >= 1000 else f"${x:,.2f}"


def cost(rows):
    priced = [r["cost"] for r in rows if r.get("cost") is not None]
    return sum(priced) if priced else None


def day(key):
    d = dt.date.fromisoformat(key)
    return f"{d:%a} {d.day} {d:%b}"


def fail(msg):
    print("<span size='x-small'>TOKENS</span> — | useMarkup=true")
    print("---")
    print(msg)
    print(f"Run install.sh from the agentmeter repo | {GRAY}")
    sys.exit(0)


if not Path(BIN).exists():
    fail("agentmeter not found on PATH or in ~/.local/bin")
try:
    out = subprocess.run([BIN, "--periods", "2", "--json"], check=True, capture_output=True, text=True, timeout=120,
                         env={**os.environ, "AGENTMETER_NO_WIZARD": "1"}).stdout
    data = json.loads(out)
    rows_all, meta = data["periods"], data.get("config", {})
except subprocess.CalledProcessError as e:
    fail(f"agentmeter failed: {e.stderr.strip()[:140]}")
except Exception as e:  # noqa
    fail(f"could not read agentmeter output: {e}")

this_p, last_p = meta["this_period"], meta["last_period"]
name = (meta.get("period") or {}).get("name") or "period"
rows = sorted((r for r in rows_all if r["period"] == this_p), key=lambda r: -r["fresh"])
fresh = sum(r["fresh"] for r in rows)
prev = sum(r["fresh"] for r in rows_all if r["period"] == last_p)
caption = str((json.loads(CFG.read_text()).get("widget", {}) if CFG.exists() else {}).get("caption", "TOKENS")).upper()

print(f"<span size='x-small' weight='medium'>{caption}</span> {fmt(fresh)} | useMarkup=true")
print("---")
print(f"This {name} (since {day(this_p)}) | {GRAY} size=10")
print(f"{fmt(fresh)} tokens · {money(cost(rows))} · {sum(r['sessions'] for r in rows)} session{'s' * (sum(r['sessions'] for r in rows) != 1)} | size=13")
print(f"{fmt(sum(r['total'] for r in rows))} including cache reads · cost at API prices | {GRAY} size=10")
if meta.get("cost_split", {}).get(this_p):
    print(f"cost: {meta['cost_split'][this_p]} | {GRAY} size=10")
for line in meta.get("limit_lines") or []:
    print(f"{line} | {GRAY} size=10")
print("---")
if not rows:
    print(f"No sessions yet this {name} | {GRAY}")
for r in rows:
    print(f"{r['model'][:26]:<26} {fmt(r['fresh']):>7} | {MONO} trim=false")
print("---")
def change_label(cur, prev):
    if not prev:
        return "new" if cur else "–"
    p = round(100 * (cur - prev) / prev)
    if p == 0:
        return "no change"
    # Pango markup: green up, red down
    return f"<span foreground='{'#2ea44f' if p > 0 else '#d73a49'}'>{'↑' if p > 0 else '↓'}{abs(p)}%</span>"


change = f"   this {name} so far {change_label(fresh, prev)}" if prev else ""
prev_cost = cost([r for r in rows_all if r["period"] == last_p])
print(f"Last {name}: {fmt(prev)} · {money(prev_cost)}{change} | {GRAY} size=11 useMarkup=true")
print("---")
reports = sorted(REPORTS.glob("????-??-??.md"))
if reports:
    print(f"Open latest report ({day(reports[-1].stem)}) | bash={OPEN} param1={reports[-1]} terminal=false")
    print(f"Open reports folder | bash={OPEN} param1={REPORTS} terminal=false")
if CFG.exists():
    print(f"Edit settings | bash={OPEN} param1={CFG} terminal=false")
else:
    print(f"Set up (agentmeter init) | bash={BIN} param1=init terminal=true")
print("Refresh now | refresh=true")
