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
agentmeter                        # last 4 windows; --periods N for more
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

`--weeks` / `--week` are aliases of `--periods` / `--period`. `AGENTMETER_NO_WIZARD=1` stops setup from starting on a first run.

## Reports

Saved in `~/.local/share/agentmeter/reports/`, named by window start date:

- `<start>.md`: tokens, the change from the previous window, a per-model table with previous figures, totals including cache reads, and the largest sessions.
- `<start>.json`: `{period, start, end, generated_at, summary, previous, config, periods, sessions}`; `previous` is `{period, fresh, total, change_pct, source}`.

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
