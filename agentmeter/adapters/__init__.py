"""Adapters turn a tool's local logs into core.Session objects.

Each adapter module exposes:
    NAME: str                      # e.g. "codex"
    DESC: str                      # one line for menus, e.g. "OpenAI's Codex CLI"
    WHERE: str (optional)          # where logs are looked for, when that isn't one folder (aider)
    default_root() -> Path         # where the tool keeps its logs
    sessions(root: Path, since: float | None = None) -> Iterator[Session]
                                   # skip files last modified before `since` (epoch seconds)
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

BUILTIN = ["claude_code", "codex", "gemini", "aider", "generic"]


def load(name: str):
    return importlib.import_module(f"agentmeter.adapters.{name.replace('-', '_')}")


def where(mod, root=None) -> str:
    """Where a tool's logs are looked for, for messages (an adapter may say it better than one path)."""
    return str(root) if root else getattr(mod, "WHERE", None) or str(mod.default_root())


def available():
    """Adapters whose default log root exists on this machine."""
    out = []
    for n in BUILTIN:
        mod = load(n)
        if mod.default_root().exists():
            out.append(mod)
    return out


def recent(path: Path, since: float | None) -> bool:
    """True if the file may hold turns at or after `since` (logs are append-only)."""
    return since is None or path.stat().st_mtime >= since


def read_jsonl(path: Path):
    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue
