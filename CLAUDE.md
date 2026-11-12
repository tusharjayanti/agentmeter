# agentmeter

Reads the local session logs of agentic coding tools (Claude Code, Codex CLI, Gemini CLI, Aider, or a generic JSONL export), and reports tokens per model per measurement window (any start date, any length), what kind of work each model did, and which sessions were **off-policy**: a model doing work its tier isn't meant for. It ships as a CLI, a status bar widget, and a report job. macOS and Linux. It is meant to be open source and usable by anyone, so personal choices are config, not code.

The product idea in one line: raw token count is a cost number; the useful question is whether the *routing* is right. Keep every feature in service of that.

## Layout

```
agentmeter/
  core.py        Session/Turn model, DEFAULT_CONFIG, validate(), Policy (tier + classify + on_policy), Periods (windows), aggregate()
  adapters/      one file per tool: NAME, default_root(), sessions(root, since=None) -> Iterator[Session]
  cli.py         argparse entry point; `init` and `check` subcommands; --status / --status-json / --save / --json
  report.py      reports: <start>.md + <start>.json, written once per finished window, never recomputed
  prices.py      bundled API list prices (dated AS_OF) and per-turn cost and split; config `prices` adds or overrides
  limits.py      plan limits (5-hour, weekly) from the tools' own on-disk copies: ~/.claude.json, Codex session logs
  tui.py         `agentmeter tui`: full-screen curses view; frame() returns plain lines so tests can check it
  wizard.py      `agentmeter init`: tools → models → tiers → policy → windows (begin date + length) → confirm
  prompt.py      stdlib-only TUI prompts (select / multiselect / text / confirm), numbered fallback without a TTY
macos/
  AgentmeterBar.swift        native menu bar app (NSStatusItem); install.sh builds it with swiftc, launchd starts it at login
widget/
  agentmeter.1h.py           Linux top-bar plugin (GNOME Argos, xbar-compatible); runs `agentmeter --periods 2 --json`
assets/          logo (TOKENS label) SVG + PNGs for README/social preview
docs/            configuration.md, adapters.md, maintaining.md (screenshots, Homebrew); images/ holds README screenshots (demo data)
.github/         CI: pytest on Ubuntu (3.9, latest) + macOS, Linux install smoke test, swiftc build; CODEOWNERS
install.sh       zipapp CLI → ~/.local/bin, setup questions, hourly report job (launchd / systemd user timer), menu bar app / widget
Formula/         Homebrew formula (tap repo: homebrew-agentmeter); sha256 placeholder until a release is tagged
tests/           pytest; fixtures/ holds minimal hand-written logs per adapter
```

User data: config `~/.config/agentmeter/config.json`; reports `~/.local/share/agentmeter/reports/`.

## Commands

```sh
python3 -m pytest -q tests                       # must pass before any commit
python3 -m agentmeter --periods 4                # run from the repo without installing
python3 -m agentmeter --today                    # any ad hoc range: --since 6h, --from DATE --to DATE
python3 -m zipapp . -m agentmeter.cli:main -o ~/.local/bin/agentmeter -p "/usr/bin/env python3"   # rebuild the installed CLI
./install.sh [--no-init] [--no-job] [--no-widget] [--widget-only|--job-only]
swiftc -O -swift-version 5 macos/AgentmeterBar.swift -o ~/.local/bin/agentmeter-bar && launchctl kickstart -k gui/$(id -u)/io.github.agentmeter.bar   # rebuild + restart the menu bar app
~/.local/bin/agentmeter-weekly.sh                # run the report job now
launchctl print gui/$(id -u)/io.github.agentmeter.weekly | head
```

After changing the widget or CLI, verify on the real menu bar, not only in tests: restart the app and look at it next to the system icons (`screencapture -x -R 900,0,828,30 out.png` needs Screen Recording permission and an unlocked screen).

## Hard constraints

- **Python 3.9+, stdlib only.** No runtime dependencies. The CLI ships as a zipapp so nobody needs pip.
- **No network.** Nothing leaves the machine. Don't add telemetry, update checks or remote config.
- **Don't modify the user's system beyond what was asked.** Homebrew is called with `HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1` because an early version triggered a full brew update and cache cleanup on install. Keep it that way.
- **Never prompt without a TTY.** The setup wizard runs only when stdin *and* stdout are terminals and no config exists; `AGENTMETER_NO_WIZARD=1` suppresses it. The report script and the widget set that variable. An early version hung `install.sh` because the wizard ran with stdout piped.
- **Adapters are the only code that knows a log format.** Everything downstream works on `Session`/`Turn`. Formats drift; a broken tool should mean one broken file.

## Decisions already made (don't relitigate without a reason)

- **Tokens first; routing is opt-in (`routing: false` by default).** The owner tracks token usage week to week, with no target. Tiers/policy/off-policy stay for those who turn routing on; with it off, the CLI, reports, status line and menu bar show only tokens.
- **Reports compare with the previous window**, in total and per model. The previous numbers come from that window's saved JSON when present (frozen), else from logs.
- **Policy is by tier, not model name.** Config maps model-id regexes → tiers (`premium / strong / standard / economy` by default; names are user-defined) and tiers → work categories. This is what makes the tool work across vendors.
- **Classification is regex over a session's first five prompts.** Deliberately simple and user-tunable. The off-policy list is a shortlist to eyeball, not a verdict; say so wherever it's shown.
- **On-policy % is token-weighted; the headline token number is fresh tokens** (input + cache write + output). Cache reads are 90%+ of totals on real Claude Code logs, so totals overstated work. `total` stays in the JSON rows.
- **Subagent and sidechain turns are counted but never judged** (`Turn.auto`). The harness or agent definition picks their model, not the user.
- **The menu bar app and the Linux widget get all data from `agentmeter --json`** (`periods`, `config.this_period`, `config.period.name`, `config.labels`), so neither knows log formats or window rules.
- **The menu bar label shows tokens used this window, nothing else** (cost is inside the menu, not in the bar). No on-policy % or anything goal-like: the owner tracks usage, not a target. Default look is a two-line label (small `TOKENS` caption over `1.13M`), matching compact items like Stats' `GPU / 10%`, and narrow enough for a notched MacBook. `widget.style: "icon"` switches to icon + number.
- **No icon by default; the caption is the mark.** The fork mark read as a trident and rising bars as signal strength. The `icon` style uses a bar chart on a baseline (drawn in code as a template image) or any SF Symbol.
- **Setup questions run inside `install.sh`** when there's a terminal. Otherwise the menu bar app opens `agentmeter init` in Terminal (via a `.command` file, so no Automation prompt) on its first launch without a config, once (marker `~/.local/share/agentmeter/.setup-offered`), and shows a **Set up** menu item until a config exists. Setup asks tools → windows → optional routing; defaults work until then.
- **The macOS menu bar app is native Swift, built on the user's machine.** SwiftBar was dropped (an extra app to install). `swiftc` from the Xcode Command Line Tools compiles one file at install time, so there's no signing, no cask and no runtime dependency; the CLI stays pure Python and the app only reads `agentmeter --json`. A launchd agent (`io.github.agentmeter.bar`, RunAtLoad, restart only on crash) starts it at login. Linux bars get the one-line form of the same look via Pango markup (`--status-json`, Argos plugin) and start with the session.
- **Reports are local files, written once.** `<start>.md` to read, `<start>.json` for scripts. A finished window is never recomputed: Claude Code prunes transcripts after 30 days, so a recompute would undercount. Empty windows aren't written (can't tell idle from pruned).
- **Windows are user config (`period: {start, length}`), not a schedule.** `start` is the date collection begins and anchors every window; `length` is `Nd`/`Nw`/`Nm` (months clamp at month end). Windows are keyed by start date (`2026-11-06`). Reports are saved only for windows from `start` on. `start: null` means Monday weeks with no begin date; legacy `week_start` is honoured then. The report job runs hourly and at login, and `--save` writes only newly finished windows (looking back ~35 days), so changing the windows needs no rescheduling and there is no time of day to configure. `--weeks`/`--week` are kept as aliases of `--periods`/`--period`.
- **Ad hoc ranges are separate from windows.** `--today`, `--since 6h|3d|DATE`, `--from … --to …` build a one-off window for looking at any time; they can't be saved as reports. JSON rows carry `period` (window start), and `--json` returns `{periods, sessions, config}`.
- **Cost is API-equivalent, from a bundled price list.** Prices are copied by hand from the vendors' pricing pages (Anthropic via the claude-api skill, OpenAI, Google) with an `AS_OF` date, never from memory and never downloaded. Model ids match exactly after dropping date suffixes and platform prefixes; a model with no listed price shows `–`, not a guess. A cost the tool logs itself (Aider) wins; local models (Ollama, LM Studio) are $0. Always label it as API prices, not a bill: most users are on subscriptions.
- **Plan limits come only from what the tools already keep on disk** (`cachedUsageUtilization` in `~/.claude.json`, Codex `token_count.rate_limits`), labelled with their age. Calling Anthropic's or OpenAI's usage endpoints was rejected: it would break "no network", need the login token (a Keychain prompt) and rely on undocumented APIs. Read only the needed keys; any format surprise means no limits, never an error.
- **Compare costs with Claude Code's `/usage`, not its Stats tab.** Stats (`stats-cache.json`) sums every transcript line, and Claude Code repeats a reply's usage on each line, so it runs ~2.5× high. agentmeter counts each API call once and matches `/usage` within a few percent (unlogged background calls).
- **Terminal output is tables that fit 80 columns**, after Linux feedback that the old output was hard to read. Session details are behind `--sessions`. The full-screen view (`agentmeter tui`, chosen over an OpenTUI mock-up) is curses from the standard library: OpenTUI would need Bun and a TypeScript codebase.
- **install.sh prints one line per part.** Removal commands live in docs/configuration.md, not in the install output.
- **No dashboard for now.** `dashboard_url` and `--rows` were removed; the local reports are the record.
- **A richer Stats-style popover (charts, history) is not built.** The native app uses a plain NSMenu; a popover could be added to the same Swift file later. Listed under help-wanted in the README.

## Known gaps

- Codex CLI and Gemini CLI adapters are written against documented formats and tested only on fixtures, never on a real machine's logs. Verify with a real file before claiming support.
- Aider logs carry no cache data; its cache columns are always 0.
- Older Codex models (`gpt-5-codex`, `gpt-5.1-codex`, `gpt-5.1-codex-max`, `gpt-5.2-codex`) aren't on OpenAI's pricing page, so they have no bundled price; users add one under `prices`.
- Claude Code logs seen so far don't say which cache writes went to the 1-hour cache, so all are priced at the 5-minute rate (1.25×); a 1-hour write costs 2×, so cost may be understated for sessions that use it.
- Gemini project folders are hashes, so the project column is a hash prefix unless the file names a cwd.
- Model tier defaults (e.g. `gpt-5.1-codex` → strong, plain `gpt-5` → standard) are judgement calls.
- No Windows scheduler or tray support.
- The Linux top-bar output (Argos plugin, Waybar markup) has not been tried on a real Linux desktop.

## Open product questions

- Final name (`agentmeter` is a working name; check GitHub and PyPI for collisions).
- Does a notification when a report is saved earn its place? If yes, its *body* should carry the review ("Week of 2 Nov: 2.1M tokens, 67% on-policy, worst: …"), not "your report is ready".
- Is a local HTML report worth having? Only if built around one trend chart (tokens per window stacked by tier, on-policy % as a line).
- `agentmeter schedule install|remove|status` as a subcommand vs leaving scheduling to `install.sh`.

## Conventions

- **Commits: one line, conventional-commit format** (`feat: …`, `fix: …`, `docs: …`). No body, and **no `Co-Authored-By` or any AI co-author trailer**. Rationale, data and tables go in the PR description.
- Prefer CLI tools (`gh`, `brew`, `launchctl`) over web dashboards for ops.
- **README stays short** (what, screenshots, install, use, report, main settings, help wanted), with one exception the owner asked for: the "The menu, part by part" section (annotated menu screenshot, each part explained) lives in the README, not in docs/. Detail goes in `docs/`. Don't document an install path that doesn't work yet (no Homebrew line until the tap exists).
- **Screenshots use demo data, never the owner's usage**, and README/fixture examples use made-up projects and prompts. How to retake them: `docs/maintaining.md` (`swiftc -D SCREENSHOT`).
- `main` is protected: changes go through a branch and pull request; only the owner approves.
- Before a Homebrew release: `v0.1.0` tag, tarball sha256 into `Formula/agentmeter.rb`, push the formula to a `homebrew-agentmeter` repo.
