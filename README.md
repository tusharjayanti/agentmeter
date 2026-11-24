<p align="center">
  <img src="assets/agentmeter-mark.svg" width="88" alt="agentmeter">
</p>

<h1 align="center">agentmeter</h1>

<p align="center"><strong>Your coding agents' token usage, every week.</strong></p>

<p align="center">
  <a href="https://github.com/tusharjayanti/agentmeter/actions/workflows/tests.yml"><img src="https://github.com/tusharjayanti/agentmeter/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-none-2ea44f" alt="no dependencies">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-555" alt="macOS and Linux">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <img src="docs/images/hero.png" alt="The agentmeter menu bar item showing TOKENS 2.18M, with its menu open: this week's tokens, cost and sessions, the cost split, Claude's 5-hour and weekly limits, tokens per model, and last week's total">
</p>

<p align="center"><sub>Screenshots use demo data.</sub></p>

## The problem

You use Claude Code, Codex or Gemini CLI every day, and you can't easily answer: how many tokens did I use this week? On which models? What would that cost at API prices? More or less than last week?

The answer is already on your disk. Every one of these tools writes a session log with every model call and its token counts. agentmeter reads those logs and turns them into a number in your menu bar and a report at the end of every week. Nothing leaves your machine.

## Get started

```sh
git clone https://github.com/tusharjayanti/agentmeter
cd agentmeter
./install.sh
```

The installer asks which tools you use and when your week starts, then sets up three things:

- the `agentmeter` command, in `~/.local/bin`
- a background job that saves a report when each week ends
- on macOS, the menu bar item, started at login

It needs Python 3.9 or newer and nothing else. On a Mac without developer tools, run `xcode-select --install` first: it provides Python and the compiler for the menu bar app.

## Always in view

The menu bar shows the week's tokens so far. Click it for the cost, your plan's 5-hour and weekly limits, the breakdown by model, last week's total, and the latest report.

On Linux, the same number goes in your top bar: a GNOME extension through [Argos](https://github.com/p-e-w/argos), or one line for Waybar, Polybar or tmux ([snippets](docs/configuration.md#linux-status-bars)).

### The menu, part by part

What you see when you click **TOKENS** in the menu bar. The screenshot uses demo data (made-up projects, made-up limits), so the figures are examples. Each number matches a section below.

<p align="center">
  <img src="docs/images/menu.png" width="560" alt="The agentmeter menu with six numbered parts: this week's totals, models, cost by kind of token, plan limits, last week, and actions">
</p>

#### 1. This week at a glance

```
This week (since Fri 6 Nov)
2.18M tokens · $22.53 · 8 sessions
45.35M including cache reads · cost at API prices
```

- **Window:** your measurement window from settings (`period`). Here it is weeks starting on Friday.
- **Tokens:** fresh tokens: input, cache writes and output. The same number as the **TOKENS** label in the menu bar.
- **Cost:** what those calls would cost at the vendors' published API prices. On a Pro or Max subscription it is not your bill; it is the pay-as-you-go equivalent, useful for comparing weeks. See [Cost](docs/configuration.md#cost-prices).
- **Sessions:** distinct coding sessions this week. A session that used two models counts once.
- **Grey line:** the total if you add cache reads, the cheap re-reading of the conversation so far. They are left out of the headline on purpose: on Claude Code they are usually over 90% of all tokens.
- **Click:** opens this week's full breakdown in Terminal.

#### 2. Models

```
claude-opus-5-5     ██████────   1.23M   $16.60
gpt-5.3-codex       ███───────    610k    $3.90
```

- **Bar:** each model's share of this week's tokens. Models are sorted largest first, and each keeps its colour in the last-week submenu.
- **Tokens:** that model's fresh tokens this week, across every tool that used it (Claude Code, Codex, Gemini CLI, Aider).
- **Cost:** that model's cost at its own price. The rows add up to the headline: $16.60 + $3.90 + $1.89 + $0.14 = $22.53.
- **Click:** opens the breakdown in Terminal. Hover for the tool and session count.

A model with no published price shows `–` instead of a guess. Add its price under `prices` in settings.

#### 3. What the cost is made of

```
COST · at API prices
output         ████──────   $9.02
cache reads    ███───────   $7.61
```

The same $22.53, split by kind of token instead of by model, largest first. The rows add up to the headline.

- **Output:** text and code the model wrote, including thinking. The most expensive kind per token.
- **Cache reads:** the model re-reading the conversation so far. Very cheap per token, but there are so many that they add up.
- **Cache writes:** putting new context into the cache. Claude charges 1.25× the input price for the 5-minute cache and 2× for the 1-hour cache.
- **Input:** prompt tokens that weren't cached.

The split is there so the cost can be checked by hand. It also shows why a week can cost more than its token count suggests: much of the money often goes on cache reads and writes.

#### 4. Plan limits

```
LIMITS · Claude as of 16:24
Claude 5-hour   ██████────   62%   resets 18:44
Claude week     ████──────   41%   resets Mon 16 Nov
```

- **Bar:** how much of each subscription limit you have used, 0 to 100%. The same figures as Claude Code's `/usage`.
- **Resets:** when that limit starts over: a time if it is today, otherwise a date.
- **As of:** when the reading was taken. agentmeter never goes online. For Claude it reads the copy Claude Code saves in `~/.claude.json`; for Codex, the limits written into its session logs. Opening `/usage` in Claude Code refreshes Claude's reading.
- **Colour:** green below 70%, orange from 70%, red from 90%. Grey, with "reset since", once the reset time has passed and the reading is out of date.

API-key users have no plan limits, so this part is left out for them. See [Plan limits](docs/configuration.md#plan-limits).

#### 5. Last week

```
Last week: 1.75M · $17.70   this week so far ↑25%   ›
```

- **Figures:** last week's tokens and cost, and how this week compares so far: green ↑ for more, red ↓ for less. Early in a week the change reads low, because the week isn't over yet.
- **Submenu:** last week's models with the same bars, and a link to its saved report.

#### 6. Actions

- **Open latest report:** the last finished week's report, saved as Markdown in `~/.local/share/agentmeter/reports/`. One is written for each week when it ends, and never changed after.
- **Open reports folder:** one `.md` to read and one `.json` for scripts per week.
- **Change setup…:** runs `agentmeter init` in Terminal to change tools, the week's start day and length, or model routing.
- **Edit settings file:** opens `~/.config/agentmeter/config.json`, for settings the setup questions don't ask, like extra prices.
- **Refresh now (⌘R):** re-reads the logs. The menu also refreshes every 15 minutes and each time you open it.
- **Quit (⌘Q):** closes the app until your next login.

## Any range, any time

<p align="center">
  <img src="docs/images/terminal.png" width="680" alt="agentmeter in a terminal: four weeks with tokens, cost and change, then this week's models in a table with share bars, cost and change">
</p>

```sh
agentmeter                     # the last 4 weeks, then this week per model, with cost
agentmeter tui                 # full screen: flip through weeks, today, the last 5 hours, reports
agentmeter --today             # or --since 6h, --since 3d, --from 2026-10-01 --to 2026-10-15
agentmeter --period last       # one week: this, last, or any date in it; --sessions for the largest sessions
agentmeter --json              # everything, for your own scripts
```

<p align="center">
  <img src="docs/images/tui.png" width="760" alt="agentmeter tui: a full-screen view with tabs for the week, today, the last 5 hours and reports; tokens and cost with changes, tokens per day, a model table, and the selected model's sessions">
</p>

Cost is what the tokens would cost at each vendor's API list prices, bundled and dated in the code. On a subscription it isn't your bill, but it's a fair way to compare weeks and models. [How it's worked out](docs/configuration.md#cost-prices).

Plan limits (Claude's and Codex's 5-hour and weekly) come from the copy each tool already keeps on disk, so agentmeter still never goes online. [Details](docs/configuration.md#plan-limits).

## A report every week

<p align="center">
  <img src="docs/images/report.png" width="760" alt="A weekly report: total tokens, the change from the previous week, and a per-model table with previous figures">
</p>

When a week ends, agentmeter saves it to `~/.local/share/agentmeter/reports/`, as Markdown to read and JSON for scripts. Reports are written once and kept. Claude Code deletes its logs after 30 days, so the saved reports become your history.

"Tokens" means fresh tokens: input, cache writes and output. Cache reads, where the model re-reads the conversation at a fraction of the price, are counted separately.

## Make it yours

Change your answers any time with `agentmeter init`, or **Change setup…** in the menu.

| Setting | What it does |
|---|---|
| `period` | when collection begins, and how long a window is: a week from any day, two weeks, a month, ten days |
| `tools` | which tools to read |
| `widget` | the menu bar look: a caption over the number, or an icon beside it |
| `prices` | add or correct a model's price |
| `routing` | optional: flag sessions where an expensive model did routine work |

Every setting, the full command line and uninstall steps are in [docs/configuration.md](docs/configuration.md).

## Why agentmeter

- **Nothing to install.** About 2,400 lines of standard-library Python, plus one Swift file for the menu bar. No Node, no pip, no Electron.
- **No network.** It never connects to anything: no telemetry, no update checks, no price downloads (prices ship with the code).
- **Your history is plain files.** One Markdown and one JSON file per week, readable without agentmeter.

## Works with

| Tool | Status |
|---|---|
| Claude Code | tested on real logs |
| OpenAI Codex CLI, Gemini CLI, Aider | built from their documented formats; tested on sample files only |
| Anything else | export to a [simple JSONL format](docs/adapters.md#your-own-tool) |

## Help wanted

- **Linux users:** the installer and top-bar output have only run in CI. Try it and [open an issue](https://github.com/tusharjayanti/agentmeter/issues) with what you find.
- **Codex CLI, Gemini CLI and Aider users:** tell us whether your logs are read correctly.
- **More tools:** Cursor, GitHub Copilot CLI and OpenCode each need one adapter file ([how](docs/adapters.md#writing-an-adapter)).

Run the tests with `python3 -m pytest -q tests`.

## License

[MIT](LICENSE)
