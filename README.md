# agentmeter

<img src="assets/agentmeter-mark.svg" width="72" alt="">

How many tokens did your coding agents use this week?

`agentmeter` reads the local session logs your agentic coding tools already write and tells you how many tokens you used, per model, in windows you choose (a week, a fortnight, a month, starting on any date), compared with the window before. It ships as a CLI, a menu bar app on macOS (a top-bar widget or status line on Linux), and a report job that saves each finished window as a Markdown and JSON file. macOS and Linux. No network, no API keys, nothing leaves your machine.

Supported out of the box: **Claude Code**, **OpenAI Codex CLI**, **Gemini CLI**, **Aider**. Anything else via a one-line-per-session JSONL export.

```
TOKENS
1.13M               ← menu bar: tokens used this week so far (click for the per-model breakdown)
```

```
=== Fri 30 Oct – Thu 5 Nov 2026 ===
2.41M tokens · 14 sessions · previous week 1.98M (+22%)
tool        model                   tokens      in cache_w     out  cache_r turns
claude-code claude-opus-5-5          1.52M      9k   1.31M    201k   41.20M   388
codex       gpt-5.1-codex             610k    540k       0     70k    2.10M    96
claude-code claude-sonnet-5-5         280k      1k    251k     28k    6.03M    74
45.67M including cache reads · subagents 190k

  claude-opus-5-5: 6 sessions
    • shop: add a cart page with saved items (820k)
    • billing: migrate invoices to the new schema (410k)
```

## Why

If you use these tools heavily, it's worth knowing what you actually use, week to week, without logging into a dashboard or exporting anything: which models, how much, and whether that's going up or down. `agentmeter` keeps that number in your menu bar and writes a short report at the end of every window, so the history is there when you want to look back.

Optionally (`routing` in the config, off by default) it can also sort your models into tiers and flag sessions where an expensive model did routine work, or a cheap one did hard work.

## Install

**Homebrew (macOS / Linux)**

```sh
brew tap tusharjayanti/agentmeter
brew install agentmeter
agentmeter init                 # first-run setup (also runs automatically on first use)
```

Then, for the widget and the report job: `bash "$(brew --prefix)/share/agentmeter/install.sh" --widget-only` (or `--job-only`).

**From source**

```sh
git clone https://github.com/tusharjayanti/agentmeter && cd agentmeter
./install.sh                    # CLI + report job + status bar widget
./install.sh --no-widget        # CLI + job
./install.sh --no-job --no-widget
```

Requires Python 3.9+. The CLI is built as a single-file zipapp at `~/.local/bin/agentmeter` (the usual per-user folder, already on most PATHs; the installer says so if yours lacks it), so there is nothing to pip-install; `pip install .` works too if you prefer a package.

## First run

`./install.sh` asks a few setup questions before it schedules anything. If it can't ask (no terminal, `--no-init`, or a Homebrew install), the menu bar app opens them in Terminal the first time it starts, and keeps a **Set up agentmeter…** item at the top of its menu until you've done it. Everything works on defaults (Monday weeks) in the meantime. Re-run setup any time with `agentmeter init` or **Change setup…** in the menu. With arrow-key menus it asks:

1. **Which tools you use**: detected ones are pre-ticked; for a tool whose logs aren't where expected it asks for the path and validates it.
2. **Windows**: the date collection begins (today, this Monday, the 1st, or any date) and how long each window is (1 week, 2 weeks, 1 month, 1 day, or custom like `10d`). Starting on a Friday with 1-week windows gives Friday-to-Thursday weeks everywhere (CLI, menu bar, saved reports), with each report saved on the Friday after. The summary shows when the next report lands.
3. **Model routing (optional, off by default)**: token counts don't need it. If you turn it on, it asks which models you use, ranks them into tiers (premium / strong / standard / economy) and asks what kind of work each tier is for; the CLI then also shows an on-policy share and flags sessions where a model did work outside its tier.

It writes `~/.config/agentmeter/config.json`; everything is editable by hand afterwards. Without a terminal (CI, cron, the widget) the wizard never runs; set `AGENTMETER_NO_WIZARD=1` to suppress it explicitly.

| | macOS | Linux |
|---|---|---|
| Report job (hourly, no-op unless a window just ended) | launchd agent, also at login | systemd user timer (falls back to a printed cron line) |
| Widget | native menu bar app, built on install with `swiftc` from the Xcode Command Line Tools (`xcode-select --install`), starts at login | GNOME: top-bar plugin via [Argos](https://github.com/p-e-w/argos); any other bar: `agentmeter --status` (plain) or `--status-json` (Waybar JSON with Pango markup and a per-model tooltip). Bars start with your session |

The menu bar app refreshes every 15 minutes and whenever you open it, so it shows the current window. The report job saves each finished window's report to `~/.local/share/agentmeter/reports/` (see [Reports](#reports)).

Bar snippets:

```jsonc
// Waybar
"custom/agentmeter": {"exec": "~/.local/bin/agentmeter --status-json", "return-type": "json", "interval": 3600}
```
```ini
; Polybar
[module/agentmeter]
type = custom/script
exec = ~/.local/bin/agentmeter --status
interval = 3600
```
```
# tmux
set -g status-right '#(~/.local/bin/agentmeter --status) | %H:%M'
```

Uninstall: macOS `launchctl bootout gui/$(id -u)/io.github.agentmeter.weekly` and `launchctl bootout gui/$(id -u)/io.github.agentmeter.bar`, then delete both plists in `~/Library/LaunchAgents`; Linux `systemctl --user disable --now agentmeter-weekly.timer`. Then remove `~/.local/bin/agentmeter*` and the plugin from your bar.

## CLI

```sh
agentmeter                        # last 4 windows, every tool whose logs exist
agentmeter --tools                # which adapters found logs, and where they looked
agentmeter --tool codex --periods 8
agentmeter --period last          # or this, any date in the window (2026-10-22), or an ISO week (2026-W43)
agentmeter --today                # any time, any range: since local midnight
agentmeter --since 6h             # or 3d, 2w, a date, an ISO datetime
agentmeter --from 2026-10-01 --to 2026-10-15   # a plain --to date includes that whole day
agentmeter --status               # "TOKENS 1.13M" (tokens used this window) for any status bar
agentmeter --status-json          # {"text", "tooltip", "class", "percentage"} for Waybar/Polybar
agentmeter --json                 # {"periods": [...], "sessions": [...], "config": {tiers, policy, unmapped, period, ...}}
agentmeter --save [DIR]           # <start>.md + <start>.json for each finished window with no report yet
agentmeter --root codex=/path     # override a tool's log root
agentmeter check                  # validate the config; show the windows and when the next report lands,
                                  # which tier each recent model lands in,
                                  # the category mix, and the biggest unclassified sessions to tune against
```

`--weeks` / `--week` still work as aliases of `--periods` / `--period`.

## What it measures

| Metric | Definition |
|---|---|
| Tokens per model per window | fresh input + cache write + cache read + output, per assistant turn, deduplicated, per tool and model |
| Fresh tokens | the same without cache reads. Cache reads are usually 90%+ of the total and billed at a fraction of the price, so this is the headline in the status line and widget |
| Cache hit rate | cache reads ÷ all input tokens. Low values usually mean too many fresh sessions |
| Work category | keyword classification of a session's first few prompts: `design`, `research`, `build`, `refactor`, `fix`, `test`, `docs`, `ops`, `trivial`, `explain` (questions) |
| Tier | which bucket a model id falls in: `premium`, `strong`, `standard`, `economy` (regex-mapped, see below) |
| On-policy share | tokens in sessions whose work category is one the model's tier is assigned to ÷ tokens in all judged sessions. Token-weighted, so a typo fix doesn't count as much as a day-long build |
| Off-policy sessions | the rest, listed largest first so you can eyeball them |
| Subagents | turns from subagents and sidechains are counted in the token totals but never judged: the harness or the agent definition chose that model, not you |

Not judged, so outside the on-policy share: subagent turns, sessions with no category match (`unclassified`), and models no tier regex matches. The last are flagged in the report, the status tooltip and the widget, so a new model release doesn't vanish silently.

Classification is regex-based and deliberately simple: each category scores one point per distinct match in each prompt, so a pasted stack trace full of "error" counts once. Treat the off-policy list as a shortlist, not a verdict, and tune the patterns to your own vocabulary (`agentmeter check` lists the largest unclassified sessions).

## Configuration

`~/.config/agentmeter/config.json` (written by `agentmeter init`; `examples/config.json` shows the defaults):

```json
{
  "tiers": {
    "economy":  ["haiku", "(^|-)mini\\b", "(^|-)nano\\b", "flash-lite"],
    "premium":  ["fable", "mythos", "gpt-5(\\.\\d)?-pro", "o3-pro", "deepthink"],
    "strong":   ["opus", "gemini-.*-pro", "gpt-5(\\.\\d)?-codex$"],
    "standard": ["sonnet", "gpt-5", "gpt-4", "gemini-.*-flash"]
  },
  "policy": {
    "premium":  ["design", "research"],
    "strong":   ["build", "refactor"],
    "standard": ["fix", "test", "docs", "ops", "explain"],
    "economy":  ["trivial"]
  },
  "categories": [["trivial", "\\b(typo|lint|quick)\\b"], ["docs", "..."], ...],
  "period": {"start": "2026-11-06", "length": "1w"},
  "tools": ["claude-code", "codex"],
  "roots": {"codex": "/Volumes/work/.codex/sessions"}
}
```

- **routing** (default `false`): also judge which model did which kind of work, using `tiers`, `policy` and `categories` below. Off, those keys are ignored by the CLI output and reports.
- **tools** restricts which adapters run (empty: every adapter whose logs exist); **roots** overrides where a tool's logs are.
- **tiers** map model-id regexes (case-insensitive, first match wins, in the order written) to tier names. Tier names are yours; three tiers, five tiers, whatever. A model matching nothing is `unknown` and never counts as off-policy.
- **policy** says which work categories each tier is for. Its key order is the tier ranking (most capable first) used by the widget; `tiers` order is only regex match order.
- **categories** are ordered `[name, regex]` pairs. Earlier wins ties, so keep narrow patterns first.
- **period**: `start` is the date collection begins (`YYYY-MM-DD`) and the first window's first day; `length` is `Nd`, `Nw` or `Nm` (calendar months, clamped at month end: a window starting the 31st starts on the 28th in February). Windows are labelled by their start date. Reports are only saved for windows from `start` on; you can still look at earlier ones with `--period` or `--from`. With `start` null, windows are weeks starting Monday and nothing limits where saving begins. (The older `week_start` key still works when `start` is null.)
- **widget** (optional): `{"style": "stacked", "caption": "TOKENS", "icon": "chart", "refresh_minutes": 15}`. `stacked` (default) shows a small caption over the number; `icon` shows an icon then the number, where `icon` is `chart`, `none` or any SF Symbol name (e.g. `chart.bar.fill`). Restart the app after changing it: click it → Quit, then `launchctl kickstart gui/$(id -u)/io.github.agentmeter.bar`.

`AGENTMETER_CONFIG` overrides the path.

## Adapters

| Tool | Reads | Notes |
|---|---|---|
| `claude-code` | `~/.claude/projects/*/*.jsonl` and `<session>/subagents/*.jsonl` | input / cache write / cache read / output from each assistant `usage`; streamed chunks deduped by message id; subagent turns marked as not judged; compaction summaries, meta messages and `<synthetic>` error notices skipped |
| `codex` | `$CODEX_HOME/sessions/**/rollout-*.jsonl` | `token_count` events' `last_token_usage`; `cached_input_tokens` is split out of `input_tokens`; reasoning tokens are already inside `output_tokens` |
| `gemini` | `~/.gemini/tmp/*/chats/session-*.json` | per-message `tokens` (`cached` split out of `input`, `thoughts` added to output). Project folders are hashes, so the project column is the hash prefix unless the file names a cwd |
| `aider` | `.aider.chat.history.md` under `$AIDER_REPOS` (colon-separated) or `~/code`, `~/src`, `~/projects`, `~/dev` | parses `> Tokens: 12k sent, 1.2k received`; no cache data |
| `generic` | `~/.config/agentmeter/sessions/*.jsonl` | your own export, one session per line (schema below) |

Generic schema:

```json
{"tool": "cursor", "id": "abc", "project": "shop", "prompts": ["add a cart page"],
 "turns": [{"ts": "2026-01-05T10:22:14Z", "model": "gpt-5", "input": 1200,
            "cache_write": 0, "cache_read": 9000, "output": 400}]}
```

A turn may carry `"auto": true` when a subagent or the harness picked its model; it is counted but not judged.

Writing an adapter is one file in `agentmeter/adapters/` with `NAME`, `default_root()` and `sessions(root, since=None)` yielding `core.Session` objects (skip files last modified before `since`, epoch seconds, so hourly widget runs stay fast); add it to `BUILTIN` in `adapters/__init__.py`. Log formats drift; if one breaks, that one file is the only thing that cares.

## Reports

`agentmeter --save` writes two files per finished window to `~/.local/share/agentmeter/reports/` (or the directory you pass):

Files are named by the date the window starts on, so they sort in order and work for any start date and length.

- `2026-10-26.md`: the window to read: tokens used and the change from the previous window, a per-model table with each model's previous figure and change, tokens including cache reads, and the largest sessions with their first prompt. The previous window's numbers come from its own saved report when there is one, so they don't shrink as old logs are pruned.
- `2026-10-26.json`: the same data for scripts: `{period, start, end, generated_at, summary, previous, config, periods, sessions}`; `previous` holds `{period, fresh, total, change_pct, source}`.

The report job runs `agentmeter --save` every hour and at login. Almost every run finds nothing new and writes nothing; the first run after a window ends saves it. That is why the start date and length can live in the config: change them with `agentmeter init` and the next report follows, with no rescheduling and no time of day to choose. Runs missed while the machine was off are filled in by the next one (it looks back over every window that could still have logs, about 35 days). The current window is never saved because it isn't over yet.

If you change `period` later, reports already saved keep their old boundaries; new ones use the new windows.

A report is written once and then left alone; `--force` rewrites it. The reason is that tools prune their own logs: Claude Code deletes transcripts older than 30 days by default, so recomputing an old window later would quietly undercount it. Saved reports are your history. To keep the raw logs longer as well, set `"cleanupPeriodDays": 365` in `~/.claude/settings.json`.

The JSON files include the first line of each session's prompt. Keep that in mind before sharing them.

## Publishing to Homebrew

`Formula/agentmeter.rb` is a ready formula. To let people `brew install` it:

1. Tag a release (`git tag v0.1.0 && git push --tags`) and note the tarball's sha256: `curl -sL https://github.com/<you>/agentmeter/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256`.
2. Create a repo named `homebrew-agentmeter` containing `Formula/agentmeter.rb` with that `url` and `sha256`.
3. Users run `brew tap <you>/agentmeter && brew install agentmeter`. `brew install --HEAD agentmeter` tracks `main`.

homebrew-core has notability requirements (stars, age); a personal tap has none.

## Tests

```sh
python3 -m pytest -q tests
```

Fixtures under `tests/fixtures/` are hand-written minimal logs for each adapter. If you have a real log file in a format that doesn't parse, a trimmed, anonymised copy as a fixture plus a failing test is the most useful PR.

## Roadmap / help wanted

Cursor and GitHub Copilot CLI adapters, OpenCode, Windows (Task Scheduler + a tray app), a native macOS popover (Stats-style: rings, usage history, details; a SwiftUI or WKWebView status-item app shipped as a Brew cask), an Übersicht desktop widget, per-project policies, and an optional LLM-based classifier for people who want better categories than regexes.

## Licence

MIT
