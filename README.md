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
  <img src="docs/images/hero.png" alt="The agentmeter menu bar item showing TOKENS 2.18M, with its menu open: this week's tokens and sessions, tokens per model, and last week's total">
</p>

<p align="center"><sub>Screenshots use demo data.</sub></p>

## The problem

You use Claude Code, Codex or Gemini CLI every day, and you can't easily answer: how many tokens did I use this week? On which models? More or less than last week?

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

The menu bar shows the week's tokens so far. Click it for the breakdown by model, last week's total, and the latest report.

On Linux, the same number goes in your top bar: a GNOME extension through [Argos](https://github.com/p-e-w/argos), or one line for Waybar, Polybar or tmux ([snippets](docs/configuration.md#linux-status-bars)).

## Any range, any time

<p align="center">
  <img src="docs/images/terminal.png" width="760" alt="agentmeter in a terminal: this week's tokens, the change from last week, and a table of models with share bars">
</p>

```sh
agentmeter                     # the last 4 weeks, each compared with the week before
agentmeter --today             # or --since 6h, --since 3d, --from 2026-10-01 --to 2026-10-15
agentmeter --period last       # one week: this, last, or any date in it
agentmeter --json              # everything, for your own scripts
```

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
| `routing` | optional: flag sessions where an expensive model did routine work |

Every setting, the full command line and uninstall steps are in [docs/configuration.md](docs/configuration.md).

## Why agentmeter

- **Nothing to install.** About 1,700 lines of standard-library Python, plus one Swift file for the menu bar. No Node, no pip, no Electron.
- **No network.** It never connects to anything: no telemetry, no update checks, no pricing downloads.
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
