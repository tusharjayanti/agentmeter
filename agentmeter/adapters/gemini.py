"""Gemini CLI: ~/.gemini/tmp/<project-hash>/chats/session-*.json

One JSON object per session: {sessionId, messages: [{id, type: "user"|"gemini", model,
timestamp, content?, tokens: {input (incl. cached), cached, output, thoughts}}]}.
The project folder is a hash, so the project name is unknown unless the file says.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core import Session, Turn
from . import recent

NAME = "gemini"
DESC = "Google's Gemini CLI"


def default_root() -> Path:
    return Path("~/.gemini/tmp").expanduser()


def _text(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    if isinstance(c, dict):
        return c.get("text", "")
    return ""


def sessions(root: Path, since: float | None = None):
    for path in sorted(root.glob("*/chats/session-*.json")):
        if not recent(path, since):
            continue
        try:
            d = json.loads(path.read_text(errors="replace"))
        except ValueError:
            continue
        proj = d.get("projectName") or d.get("cwd") or path.parents[1].name[:8]
        s = Session(tool=NAME, id=str(d.get("sessionId") or path.stem), project=Path(proj).name)
        seen = set()
        for m in d.get("messages") or []:
            if not isinstance(m, dict):
                continue
            if m.get("type") == "user":
                t = _text(m.get("content") or m.get("text"))
                if t.strip():
                    s.prompts.append(t)
            elif m.get("type") == "gemini":
                tk = m.get("tokens") or {}
                if not tk or not m.get("timestamp"):
                    continue
                key = m.get("id") or (m.get("timestamp"), json.dumps(tk, sort_keys=True))
                if key in seen:
                    continue
                seen.add(key)
                cached = tk.get("cached", 0) or 0
                s.turns.append(Turn(ts=m["timestamp"], model=m.get("model") or "unknown",
                                    input=max(0, (tk.get("input", 0) or 0) - cached),
                                    cache_read=cached,
                                    output=(tk.get("output", 0) or 0) + (tk.get("thoughts", 0) or 0)))
        if s.turns:
            yield s
