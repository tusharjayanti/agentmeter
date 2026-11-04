"""Claude Code: ~/.claude/projects/<project>/<session>.jsonl

Subagent transcripts live next to it in <project>/<session>/subagents/agent-*.jsonl.
Their turns count towards the session but are marked auto: the harness or the
agent definition picked that model, so they are not judged against the policy.
Sidechain turns inside the main file (older versions) are treated the same way.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..core import Session, Turn
from . import read_jsonl, recent

NAME = "claude-code"
DESC = "Anthropic's Claude Code"
COMPACT_PREFIX = "This session is being continued from a previous conversation"


def default_root() -> Path:
    return Path(os.environ.get("CLAUDE_DIR", "~/.claude")).expanduser() / "projects"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _real_prompt(e: dict, t: str) -> bool:
    if e.get("isMeta") or e.get("isSidechain") or e.get("isCompactSummary"):
        return False
    t = t.strip()
    return bool(t) and not t.startswith(("<", "[Request interrupted", COMPACT_PREFIX))


def _read(path: Path, s: Session, seen: set, auto: bool):
    for e in read_jsonl(path):
        if not auto and e.get("cwd") and s.project == path.parent.name:
            s.project = Path(e["cwd"]).name
        msg = e.get("message") or {}
        ts = e.get("timestamp")
        if not ts or not isinstance(msg, dict):
            continue
        if e.get("type") == "user" and not auto:
            t = _text(msg.get("content"))
            if _real_prompt(e, t):
                s.prompts.append(t)
        elif e.get("type") == "assistant":
            u = msg.get("usage") or {}
            model = msg.get("model") or "unknown"
            if not u or model == "<synthetic>":   # synthetic = client-side error notices, 0 tokens
                continue
            key = (msg.get("id") or e.get("uuid"), e.get("requestId"))
            if key in seen:
                continue
            seen.add(key)
            s.turns.append(Turn(ts=ts, model=model,
                                input=u.get("input_tokens", 0) or 0,
                                cache_write=u.get("cache_creation_input_tokens", 0) or 0,
                                cache_read=u.get("cache_read_input_tokens", 0) or 0,
                                output=u.get("output_tokens", 0) or 0,
                                auto=auto or bool(e.get("isSidechain"))))


def sessions(root: Path, since: float | None = None):
    for path in sorted(root.glob("*/*.jsonl")):
        subs = sorted((path.parent / path.stem / "subagents").glob("*.jsonl"))
        if not any(recent(p, since) for p in [path, *subs]):
            continue
        s = Session(tool=NAME, id=path.stem, project=path.parent.name)
        seen = set()
        _read(path, s, seen, auto=False)
        for p in subs:
            _read(p, s, seen, auto=True)
        if s.turns:
            yield s
