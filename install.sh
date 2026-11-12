#!/bin/bash
# agentmeter installer (macOS and Linux).
#   bash install.sh              CLI + report job + status bar widget
#   bash install.sh --no-widget  skip the widget
#   bash install.sh --no-job     skip the report job
#   bash install.sh --no-init    don't ask the setup questions (defaults apply)
#   bash install.sh --widget-only | --job-only   when the CLI came from Homebrew
# macOS: launchd job, native menu bar app built with swiftc (Xcode Command Line Tools), started at login.
# Linux: systemd user timer; GNOME gets the top-bar plugin via Argos if installed,
#        other bars use `agentmeter --status` / `--status-json` (see docs/configuration.md). Bars start with your session.
# Output is one line per part; how to remove each part is in docs/configuration.md.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"; DATA="$HOME/.local/share/agentmeter"; CFGDIR="$HOME/.config/agentmeter"
LABEL="io.github.agentmeter.weekly"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$BIN" "$DATA" "$CFGDIR"

# 1. CLI as a single-file zipapp (no pip needed). Skipped when agentmeter is
#    already on PATH (e.g. installed with Homebrew) or with --widget-only/--job-only.
if command -v agentmeter >/dev/null && [[ " $* " == *"-only "* ]]; then
  AM="$(command -v agentmeter)"
else
  python3 -m zipapp "$HERE" -m "agentmeter.cli:main" -o "$BIN/agentmeter" -p "/usr/bin/env python3" \
    && chmod +x "$BIN/agentmeter"
  AM="$BIN/agentmeter"
  case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: $BIN is not on your PATH, so type the full path, or add to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
  # versions before 0.2 installed into ~/bin; remove those copies (only agentmeter's own files)
  for f in agentmeter agentmeter-bar agentmeter-weekly.sh; do [ -f "$HOME/bin/$f" ] && rm "$HOME/bin/$f" && echo "moved:  removed old $HOME/bin/$f"; done
  rmdir "$HOME/bin" 2>/dev/null || true
  echo "cli:    $AM"
fi
[[ " $* " == *" --widget-only "* ]] && set -- --no-job
[[ " $* " == *" --job-only "* ]] && set -- --no-widget
FOUND="$(AGENTMETER_NO_WIZARD=1 "$AM" --tools 2>/dev/null | awk '$2 == "found" {printf "%s%s", sep, $1; sep=", "}')"
echo "logs:   ${FOUND:-none yet (agentmeter picks them up once you use Claude Code, Codex, Gemini CLI or Aider)}"

# Setup questions: run now, before the job and widget, so their first numbers use
# your policy. Skipped when a config exists (re-run any time: agentmeter init),
# when not at a terminal, or with --no-init.
if [ -f "$CFGDIR/config.json" ]; then
  echo "setup:  using $CFGDIR/config.json (change: agentmeter init)"
elif [ -t 0 ] && [ -t 1 ] && [[ " $* " != *" --no-init "* ]]; then
  "$AM" init || echo "setup:  skipped; defaults apply until you run: agentmeter init"
else
  echo "setup:  not interactive; defaults apply until you run: agentmeter init"
fi

# 2. Report job: runs hourly (and at login) and saves each window's report within the hour after
#    that window ends. Window start and length live in config (period), not here, so changing
#    them with `agentmeter init` needs no reinstall, and there is no fixed time of day to pick.
if [[ " $* " != *" --no-job "* ]]; then
  cat > "$BIN/agentmeter-weekly.sh" <<'EOS'
#!/bin/bash
set -euo pipefail
# Runs hourly. Saves <start>.md + <start>.json for each finished window that has no report yet,
# so it is a no-op almost every time and a run missed while the machine was off is filled in by the next.
# Written reports are never rewritten: tools prune old logs (Claude Code after 30 days), so recomputing would undercount.
DATA="$HOME/.local/share/agentmeter"; mkdir -p "$DATA/reports"
export AGENTMETER_NO_WIZARD=1
AM_BIN="$(command -v agentmeter || echo "$HOME/.local/bin/agentmeter")"
OUT="$("$AM_BIN" --save "$DATA/reports")"
case "$OUT" in wrote*) echo "$(date -Iseconds) $OUT" >> "$DATA/run.log";; esac
EOS
  chmod +x "$BIN/agentmeter-weekly.sh"
fi
if [ "$(uname)" = "Darwin" ] && [[ " $* " != *" --no-job "* ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$BIN/agentmeter-weekly.sh</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DATA/launchd.out</string>
  <key>StandardErrorPath</key><string>$DATA/launchd.err</string>
</dict></plist>
EOP
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "job:    saves a report when each window ends → $DATA/reports"
elif [ "$(uname)" = "Linux" ] && [[ " $* " != *" --no-job "* ]] && command -v systemctl >/dev/null; then
  UNIT="$HOME/.config/systemd/user"; mkdir -p "$UNIT"
  cat > "$UNIT/agentmeter-weekly.service" <<EOU
[Unit]
Description=agentmeter weekly report
[Service]
Type=oneshot
ExecStart=$BIN/agentmeter-weekly.sh
EOU
  cat > "$UNIT/agentmeter-weekly.timer" <<EOU
[Unit]
Description=agentmeter reports (checked hourly)
[Timer]
OnCalendar=hourly
OnBootSec=2min
Persistent=true
[Install]
WantedBy=timers.target
EOU
  if systemctl --user daemon-reload 2>/dev/null && systemctl --user enable --now agentmeter-weekly.timer 2>/dev/null; then
    "$BIN/agentmeter-weekly.sh" || true
    echo "job:    saves a report when each window ends → $DATA/reports"
    loginctl show-user "$(id -un)" 2>/dev/null | grep -q 'Linger=yes' || echo "note: 'loginctl enable-linger $(id -un)' lets the timer fire while you are logged out"
  else
    echo "job:    units written to $UNIT but systemd --user is not reachable; enable later with: systemctl --user enable --now agentmeter-weekly.timer"
    echo "        or add a cron line:  0 * * * * $BIN/agentmeter-weekly.sh"
  fi
fi

# 3. Menu bar widget
# macOS: a small native app (macos/AgentmeterBar.swift) built here with swiftc from the Xcode
# Command Line Tools, started at login by a launchd agent. No SwiftBar, no Xcode, nothing from the network.
BAR_LABEL="io.github.agentmeter.bar"; BAR_PLIST="$HOME/Library/LaunchAgents/$BAR_LABEL.plist"
if [ "$(uname)" = "Darwin" ] && [[ " $* " != *" --no-widget "* ]]; then
  if ! xcrun --find swiftc >/dev/null 2>&1; then
    echo "widget: needs the Xcode Command Line Tools to build the menu bar app. Run: xcode-select --install, then re-run install.sh"
  else
    swiftc -O -swift-version 5 "$HERE/macos/AgentmeterBar.swift" -o "$BIN/agentmeter-bar"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$BAR_PLIST" <<EOP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$BAR_LABEL</string>
  <key>ProgramArguments</key><array><string>$BIN/agentmeter-bar</string></array>
  <key>EnvironmentVariables</key><dict><key>AGENTMETER_BIN</key><string>$AM</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict></plist>
EOP
    launchctl bootout "gui/$(id -u)/$BAR_LABEL" 2>/dev/null || true
    pkill -f "$BIN/agentmeter-bar" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$BAR_PLIST"
    echo "widget: menu bar app, starts at login"
    # earlier versions installed a SwiftBar plugin; remove only that file, leave SwiftBar itself alone
    OLDDIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || echo "$HOME/.swiftbar")"
    [ -f "$OLDDIR/agentmeter.1h.py" ] && rm "$OLDDIR/agentmeter.1h.py" || true
  fi
elif [ "$(uname)" = "Linux" ] && [[ " $* " != *" --no-widget "* ]]; then
  if [ -d "$HOME/.config/argos" ]; then
    cp "$HERE/widget/agentmeter.1h.py" "$HOME/.config/argos/agentmeter.1h.py"; chmod +x "$HOME/.config/argos/agentmeter.1h.py"
    echo "widget: GNOME top bar (Argos)"
  else
    echo "widget: for Waybar, Polybar or tmux, see 'Linux status bars' in docs/configuration.md"
  fi
fi
echo "done:   run agentmeter, or agentmeter tui for the full-screen view"
