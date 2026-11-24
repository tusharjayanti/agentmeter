"""Claude Code's status line setting: the one supported way it shares plan limits
(https://code.claude.com/docs/en/statusline.md). agentmeter setup offers to point it at
`agentmeter statusline`; this module reads and writes only the `statusLine` key of
~/.claude/settings.json (or $CLAUDE_CONFIG_DIR/settings.json) and never replaces a status line
someone else set.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

MARK = "agentmeter statusline"


def settings_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path("~/.claude").expanduser()) / "settings.json"


def command() -> str:
    """The status line command, with agentmeter's full path: Claude Code may not have ~/.local/bin on PATH."""
    exe = shutil.which("agentmeter") or str(Path("~/.local/bin/agentmeter").expanduser())
    return f"{exe} statusline"


def _read() -> dict | None:
    """The settings, {} when there is no file, None when the file can't be read as a JSON object."""
    p = settings_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def status() -> str:
    """'agentmeter' (ours is set), 'other' (someone else's), '' (none), or 'unreadable'."""
    d = _read()
    if d is None:
        return "unreadable"
    sl = d.get("statusLine")
    if not sl:
        return ""
    return "agentmeter" if MARK in str(sl.get("command", "") if isinstance(sl, dict) else sl) else "other"


def install() -> str:
    """Set agentmeter's status line if there is none. Returns a one-line result to print."""
    st = status()
    if st == "agentmeter":
        return "already on"
    if st == "unreadable":
        return f"not changed: {settings_path()} isn't valid JSON"
    if st == "other":
        return (f"not changed: you already have a status line. To keep the limits current, add this to it: "
                f"echo \"$input\" | {command()} --quiet")
    d = _read() or {}
    d["statusLine"] = {"type": "command", "command": command()}
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.agentmeter-tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n")
    tmp.replace(p)
    return f"on: set statusLine in {p}"


def remove() -> str:
    """Remove agentmeter's status line, leaving any other one alone."""
    if status() != "agentmeter":
        return "nothing to remove"
    d = _read() or {}
    d.pop("statusLine", None)
    p = settings_path()
    tmp = p.with_suffix(".json.agentmeter-tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n")
    tmp.replace(p)
    return f"off: removed statusLine from {p}"
