"""Generic adapter: bring your own sessions.

Drop files into ~/.config/agentmeter/sessions/*.jsonl, one session per line:

  {"tool": "cursor", "id": "abc", "project": "shop", "prompts": ["add a cart page"],
   "turns": [{"ts": "2026-01-05T10:22:14Z", "model": "gpt-5", "input": 1200,
              "cache_write": 0, "cache_read": 9000, "output": 400}]}

A turn may add "auto": true when a subagent or the harness picked its model (counted, not judged),
and "cost": dollars, when your tool knows what the turn cost (otherwise it is priced by model).
Any tool you can export from (Cursor, Copilot, OpenCode, your own harness) can feed
this with a few lines of script; the rest of agentmeter treats it like any other adapter.
"""
from __future__ import annotations

from pathlib import Path

from ..core import Session, Turn
from . import read_jsonl, recent

NAME = "generic"
DESC = "your own JSONL export"


def default_root() -> Path:
    return Path("~/.config/agentmeter/sessions").expanduser()


def sessions(root: Path, since: float | None = None):
    for path in sorted(root.glob("*.jsonl")):
        if not recent(path, since):
            continue
        for d in read_jsonl(path):
            turns = [Turn(ts=t["ts"], model=t.get("model", "unknown"), input=t.get("input", 0),
                          cache_write=t.get("cache_write", 0), cache_read=t.get("cache_read", 0),
                          output=t.get("output", 0), auto=bool(t.get("auto", False)),
                          cache_write_1h=t.get("cache_write_1h", 0), cost=t.get("cost"))
                     for t in d.get("turns", []) if t.get("ts")]
            if turns:
                yield Session(tool=d.get("tool", "generic"), id=str(d.get("id", path.stem)),
                              project=d.get("project", "unknown"), prompts=list(d.get("prompts", [])), turns=turns)
