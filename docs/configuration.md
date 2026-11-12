# Configuration

`~/.config/agentmeter/config.json`, written by `agentmeter init` and editable by hand. `AGENTMETER_CONFIG` points somewhere else. [`examples/config.json`](../examples/config.json) shows every default.

## Windows: `period`

```json
"period": {"start": "2026-10-30", "length": "1w"}
```

- `start`: the date collection begins (`YYYY-MM-DD`), and the first day of the first window. Reports are saved only for windows from this date on; earlier ones can still be viewed with `--period` or `--from`. `null` means weeks starting Monday, with no begin date.
- `length`: `Nd`, `Nw` or `Nm`. Months are calendar months, clamped at month end, so a window that starts on the 31st starts on the 28th in February.

Windows are named by their start date. Starting on a Friday with `1w` gives Friday-to-Thursday weeks, and each report is saved within an hour after Thursday ends. If you change `period` later, saved reports keep their old boundaries. The older `week_start` key (a weekday name) still works when `start` is null.

## Tools: `tools`, `roots`

- `tools`: which tools to read, e.g. `["claude-code", "codex"]`. Empty means every tool whose logs exist.
- `roots`: where a tool keeps its logs, if not the usual place, e.g. `{"codex": "/Volumes/work/.codex/sessions"}`.

`agentmeter --tools` lists each tool and where it looks.

## Cost: `prices`

Every view shows what the tokens would cost at the vendors' API list prices: Anthropic for Claude Code, OpenAI for Codex, Google for Gemini CLI. Aider logs its own cost, which is used as it is. Models run locally through Ollama or LM Studio cost $0. The bundled prices are dated (`agentmeter/prices.py`, `AS_OF`) and copied from the vendors' pricing pages.

This is an API-equivalent figure. On a subscription (Claude Pro or Max, ChatGPT Plus or Pro, a Google login) it is not your bill. It shows what the same work would cost on pay-as-you-go, which is useful for comparing weeks and models.

How a turn is priced: input × input price + cache writes × write price + cache reads × read price + output × output price. Claude charges more for cache writes (1.25× input for the 5-minute cache, 2× for the 1-hour cache when the log says which). OpenAI and Google charge no cache writes and discount cached input. Where a vendor charges more for long prompts (Gemini Pro over 200K, GPT-5.4 and later over 272K, Haiku 5.5 over 100K), each turn is priced by its own prompt size.

A model with no listed price shows `–`, and the CLI says how many tokens that covers. It is never priced by a guess. Add a price, or correct one, in dollars per million tokens:

```json
"prices": {"gpt-5.1-codex": {"input": 1.25, "cache_read": 0.125, "output": 10}}
```

Fields are `input`, `output`, `cache_read`, `cache_write` and `cache_write_1h`; a missing cache field defaults to the input price. Model ids are matched exactly, ignoring date suffixes (`-20260401`) and platform prefixes (`us.anthropic.`, `models/`).

Every view also shows the cost split by kind of token, e.g. `cost: cache writes $65 · cache reads $56 · output $29`, so the total can be checked against the price list. On Claude Code, cache reads and 1-hour cache writes are usually most of it.

### Checking against Claude Code

Claude Code's `/usage` (Usage tab) counts each API call once and agrees with agentmeter within a few percent; the difference is Claude Code's background calls that never reach the session log (title and summary calls). Its Stats tab (`/stats`, from `~/.claude/stats-cache.json`) adds up every line of the session logs, and Claude Code writes one line per part of a reply with the same usage repeated, so its token totals run about 2.5× higher. Compare with `/usage`, not Stats.

## Plan limits

On a subscription, agentmeter shows how much of your 5-hour and weekly limits you have used, in the CLI (current window and ad hoc ranges), `agentmeter tui`, the menu bar menu, the Linux widget and `--json` (`limits`). It reads the copy each tool keeps on disk; it never contacts Anthropic or OpenAI.

- Claude Code: `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`), key `cachedUsageUtilization`, the reading `/usage` shows. Only that key is read; the rest of the file is account settings.
- Codex CLI: the `rate_limits` on the last `token_count` event of the newest session log.

A reading is as fresh as the tool's last check, so it is labelled `as of 16:00`. Once its reset time has passed it shows `reset since` instead of a stale percentage. Both formats are internal to the tools; if one changes, agentmeter shows no limits rather than wrong ones. API-key users have no plan limits, so nothing is shown.

## Menu bar: `widget`

```json
"widget": {"style": "stacked", "caption": "TOKENS", "icon": "chart", "refresh_minutes": 15}
```

- `style`: `stacked` (a small caption over the number) or `icon` (an icon, then the number).
- `caption`: the word above the number.
- `icon`: for the `icon` style: `chart`, `none`, or any SF Symbol name such as `chart.bar.fill`.
- `refresh_minutes`: how often the number updates. It also updates every time you open the menu.

Restart the app after changing these: **Quit agentmeter** from its menu, then `launchctl kickstart gui/$(id -u)/io.github.agentmeter.bar`.

## Model routing: `routing`, `tiers`, `policy`, `categories`

Off by default. With `"routing": true`, agentmeter also sorts models into tiers and flags sessions where a model did work outside its tier: an expensive model fixing typos, or a cheap one designing a system. `agentmeter init` sets this up with menus.

```json
"routing": true,
"tiers":  {"economy": ["haiku", "(^|-)mini\\b"], "premium": ["fable"], "strong": ["opus"], "standard": ["sonnet", "gpt-5"]},
"policy": {"premium": ["design", "research"], "strong": ["build", "refactor"], "standard": ["fix", "test", "docs", "ops", "explain"], "economy": ["trivial"]},
"categories": [["trivial", "\\b(typo|lint|quick)\\b"], ["docs", "..."]]
```

- `tiers`: model-name regexes (case-insensitive, first match wins, in the order written) mapped to tier names. Name your tiers anything you like. A model that matches nothing is `unknown` and is never judged.
- `policy`: the kinds of work each tier is for. Its key order ranks the tiers, most capable first.
- `categories`: ordered `[name, regex]` pairs, matched against a session's first five prompts (`prompts_for_classification`). Each category scores one point per distinct match in each prompt; earlier categories win ties, so keep narrow patterns first.
- On-policy share: tokens in sessions whose work fits their model's tier, divided by all judged tokens. Subagent turns, unclassified sessions and models without a tier aren't judged.

The classification is keyword-based on purpose. Treat flagged sessions as a list to look at, not a verdict. `agentmeter check` shows the largest unclassified sessions, to help you tune the patterns.

## Command line

```sh
agentmeter                        # last 4 windows in one table, then the latest per model; --periods N for more
agentmeter --sessions             # also list the largest sessions per model (--prompts N for how many)
agentmeter tui                    # full-screen view: switch windows and views with the keyboard
agentmeter --period last          # this, last, any date in the window (2026-10-22), or an ISO week (2026-W43)
agentmeter --today                # since local midnight
agentmeter --since 6h             # or 3d, 2w, a date, an ISO datetime
agentmeter --from 2026-10-01 --to 2026-10-15   # a plain --to date includes that whole day
agentmeter --tool codex           # only this tool; repeatable
agentmeter --root codex=/path     # read a tool's logs from somewhere else
agentmeter --status               # TOKENS 1.13M
agentmeter --status-json          # {"text", "tooltip", "class"}, text in Pango markup, for Waybar
agentmeter --json                 # {"periods": [...], "sessions": [...], "config": {...}}
agentmeter --save [DIR]           # save reports for finished windows that have none yet; --force rewrites
agentmeter --tools                # which tools have logs, and where agentmeter looks
agentmeter init                   # setup questions
agentmeter check                  # validate the config; show windows, next report date, models seen
```

`--weeks` / `--week` are aliases of `--periods` / `--period`. Each window is compared with the one before it, which is loaded for that purpose even when it isn't shown. Tables fit in 80 columns.

### Full-screen view: `agentmeter tui`

Stays open and reloads the logs every minute. It uses curses from Python's standard library, so there is nothing extra to install.

- Views (`tab`): the current window, today (per hour), the last 5 hours (per 15 minutes), and saved reports.
- `←` `→` move to the previous or next window; `↑` `↓` pick a model, whose sessions are listed below the table.
- In Reports, `↑` `↓` pick a report and `enter` opens its Markdown file. `r` reloads, `q` quits.

It needs a terminal at least 60 columns by 16 rows. For scripts and pipes, use `agentmeter` or `--json`.

Environment: `AGENTMETER_CONFIG` (config path), `AGENTMETER_NO_WIZARD=1` (never start setup on a first run), `NO_COLOR` / `FORCE_COLOR` (colours are on only in a terminal by default), `AGENTMETER_REPORTS` (the menu bar app reads reports from this folder instead).

## Reports

Saved in `~/.local/share/agentmeter/reports/`, named by window start date:

- `<start>.md`: tokens and cost, the change from the previous window, a per-model table with cost and previous figures, totals including cache reads, and the largest sessions.
- `<start>.json`: `{period, start, end, generated_at, prices_as_of, summary, previous, config, periods, sessions}`; `summary.cost` is dollars at API prices (`null` when nothing had a price); `previous` is `{period, fresh, total, cost, change_pct, source}`.

Cost is frozen with the report, at the prices of the day it was saved. Reports saved before cost was added show `–`.

The previous window's figures come from its saved report when there is one, so they don't shrink as old logs are deleted. A report is written once; `--save --force` rewrites it. To keep Claude Code's raw logs longer, set `"cleanupPeriodDays": 365` in `~/.claude/settings.json`.

Reports include the first line of each session's first prompt. Check them before sharing.

## Linux status bars

```jsonc
// Waybar
"custom/agentmeter": {"exec": "~/.local/bin/agentmeter --status-json", "return-type": "json", "interval": 900}
```
```ini
; Polybar
[module/agentmeter]
type = custom/script
exec = ~/.local/bin/agentmeter --status
interval = 900
```
```
# tmux
set -g status-right '#(~/.local/bin/agentmeter --status) | %H:%M'
```

GNOME: install the [Argos](https://github.com/p-e-w/argos) extension and re-run `./install.sh`.

## Install options and uninstall

`install.sh` prints one line per part (cli, logs found, setup, job, widget).

```sh
./install.sh --no-init      # skip the questions (the menu bar app asks on first launch)
./install.sh --no-widget    # no menu bar app or top-bar plugin
./install.sh --no-job       # no report job
```

Uninstall on macOS:

```sh
launchctl bootout gui/$(id -u)/io.github.agentmeter.bar
launchctl bootout gui/$(id -u)/io.github.agentmeter.weekly
rm ~/Library/LaunchAgents/io.github.agentmeter.*.plist ~/.local/bin/agentmeter*
```

On Linux: `systemctl --user disable --now agentmeter-weekly.timer`, then remove `~/.local/bin/agentmeter*` and the plugin from your bar. Your config and reports stay in `~/.config/agentmeter` and `~/.local/share/agentmeter` until you delete them.
