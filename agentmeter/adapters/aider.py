"""Aider: .aider.chat.history.md in each repo (markdown).

Set AIDER_REPOS to a colon-separated list of directories to scan (recursively, depth 3);
default is ~/code, ~/src, ~/projects, ~/dev, ~ (depth 2).

Markers used:
  "# aider chat started at 2026-01-05 10:22:14"   -> new session
  "> Model: gpt-4o with diff edit format"         -> model
  "#### <prompt>"                                 -> user prompt
  "> Tokens: 12k sent, 1.2k received. Cost: $0.01 message, $0.05 session."
                                                  -> one turn (sent = input, received = output, Aider's own cost)
Aider does not report cache reads, so they are 0. Its own cost figure is used as the turn's cost.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..core import Session, Turn
from . import recent

NAME = "aider"
DESC = "Aider, open-source terminal assistant"
# where to look, for messages: aider keeps a log inside each repo rather than in one folder
WHERE = "~/code, ~/src, ~/projects, ~/dev (or $AIDER_REPOS)"
_START = re.compile(r"^# aider chat started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_MODEL = re.compile(r"^> Model: (\S+)")
_TOK = re.compile(r"^> Tokens: ([\d.,]+)(k?) sent(?:.*?([\d.,]+)(k?) received)?", re.I)
_PROMPT = re.compile(r"^#### (.+)")
_COST = re.compile(r"Cost: \$([\d.,]+) message", re.I)


def _n(v, k) -> int:
    x = float(v.replace(",", ""))
    return int(x * 1000) if k else int(x)


def default_root() -> Path:
    for d in os.environ.get("AIDER_REPOS", "").split(":"):
        if d and Path(d).expanduser().exists():
            return Path(d).expanduser()
    for d in ("~/code", "~/src", "~/projects", "~/dev"):
        if Path(d).expanduser().exists():
            return Path(d).expanduser()
    return Path("~/.aider-none").expanduser()


def _history_files(root: Path):
    roots = [Path(d).expanduser() for d in os.environ.get("AIDER_REPOS", "").split(":") if d] or [root]
    for r in roots:
        for depth in ("", "*/", "*/*/", "*/*/*/"):
            yield from r.glob(f"{depth}.aider.chat.history.md")


def sessions(root: Path, since: float | None = None):
    for path in sorted(set(_history_files(root))):
        if not recent(path, since):
            continue
        project = path.parent.name
        s = None
        model = "unknown"
        n = 0
        for line in path.read_text(errors="replace").splitlines():
            m = _START.match(line)
            if m:
                if s and s.turns:
                    yield s
                n += 1
                s = Session(tool=NAME, id=f"{project}-{n}", project=project)
                start = m.group(1).replace(" ", "T")
                continue
            if s is None:
                continue
            m = _MODEL.match(line)
            if m:
                model = m.group(1); continue
            m = _PROMPT.match(line)
            if m:
                s.prompts.append(m.group(1)); continue
            m = _TOK.match(line)
            if m:
                c = _COST.search(line)
                s.turns.append(Turn(ts=start, model=model, input=_n(m.group(1), m.group(2)),
                                    output=_n(m.group(3), m.group(4)) if m.group(3) else 0,
                                    cost=float(c.group(1).replace(",", "")) if c else None))
        if s and s.turns:
            yield s
