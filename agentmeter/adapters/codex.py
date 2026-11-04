"""OpenAI Codex CLI: $CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl

Lines are {timestamp, type, payload}. We use:
  session_meta  -> payload.id, payload.cwd
  turn_context  -> payload.model (last one wins)
  event_msg/user_message -> payload.message
  event_msg/token_count  -> payload.info.last_token_usage
      {input_tokens (incl. cached), cached_input_tokens, output_tokens, reasoning_output_tokens}
Reasoning tokens are part of output_tokens in OpenAI's accounting, so they are not added again.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..core import Session, Turn
from . import read_jsonl, recent

NAME = "codex"
DESC = "OpenAI's Codex CLI"


def default_root() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "sessions"


def sessions(root: Path, since: float | None = None):
    for path in sorted(root.rglob("rollout-*.jsonl")):
        if not recent(path, since):
            continue
        s = Session(tool=NAME, id=path.stem.rsplit("-", 1)[-1], project=path.parent.name)
        model = "unknown"
        meta_seen = False
        for e in read_jsonl(path):
            p = e.get("payload") or {}
            t = e.get("type")
            ts = e.get("timestamp")
            if t == "session_meta" and not meta_seen:
                meta_seen = True
                if p.get("cwd"):
                    s.project = Path(p["cwd"]).name
                if p.get("id"):
                    s.id = p["id"]
            elif t == "turn_context":
                model = p.get("model") or model
            elif t == "event_msg":
                k = p.get("type")
                if k == "user_message":
                    m = p.get("message")
                    if isinstance(m, str) and m.strip():
                        s.prompts.append(m)
                elif k == "token_count" and ts:
                    u = ((p.get("info") or {}).get("last_token_usage")) or {}
                    if not u:
                        continue
                    cached = u.get("cached_input_tokens", 0) or 0
                    s.turns.append(Turn(ts=ts, model=(p.get("turn_context") or {}).get("model") or model,
                                        input=max(0, (u.get("input_tokens", 0) or 0) - cached),
                                        cache_read=cached,
                                        output=u.get("output_tokens", 0) or 0))
        if s.turns:
            yield s
