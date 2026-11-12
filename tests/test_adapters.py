import json
import os
import shutil
import time
from pathlib import Path

from agentmeter.adapters import aider, claude_code, codex, gemini, generic

FX = Path(__file__).parent / "fixtures"


def test_codex():
    (s,) = list(codex.sessions(FX / "codex"))
    assert s.project == "shop" and s.prompts == ["implement the checkout endpoint"]
    assert [t.input for t in s.turns] == [13863 - 2432, 2000]
    assert s.turns[0].cache_read == 2432 and s.turns[0].output == 302


def test_gemini():
    (s,) = list(gemini.sessions(FX / "gemini"))
    assert s.turns[0].input == 5000 and s.turns[0].cache_read == 4000 and s.turns[0].output == 1000


def test_aider():
    (s,) = list(aider.sessions(FX / "aider"))
    assert s.turns[0].model == "gpt-4o" and s.turns[0].input == 2100 and s.turns[0].output == 150
    assert s.turns[0].cost == 0.01          # Aider's own figure, used as the turn's cost


def test_claude_code():
    (s,) = list(claude_code.sessions(FX / "claude_code" / "projects"))
    assert s.project == "shop" and s.id == "s1"
    # meta, compaction summary, <command> and subagent prompts are not the user's
    assert s.prompts == ["fix the failing checkout test", "add a cart page"]
    # streamed duplicate dropped, <synthetic> dropped, subagent turn included and marked auto
    assert [(t.model, t.auto) for t in s.turns] == [
        ("claude-opus-5-5", False), ("claude-sonnet-5-5", False), ("claude-haiku-5-5", True)]
    assert (s.turns[0].input, s.turns[0].cache_write, s.turns[0].cache_read, s.turns[0].output) == (10, 100, 1000, 50)


def test_claude_code_skips_files_older_than_since(tmp_path):
    root = tmp_path / "projects"
    shutil.copytree(FX / "claude_code" / "projects", root)
    old = time.time() - 30 * 86400
    for p in root.rglob("*.jsonl"):
        os.utime(p, (old, old))
    assert list(claude_code.sessions(root, since=time.time() - 86400)) == []
    # a subagent written recently keeps its session in range
    sub = next(root.rglob("agent-*.jsonl"))
    os.utime(sub, None)
    assert len(list(claude_code.sessions(root, since=time.time() - 86400))) == 1


def test_generic(tmp_path):
    (tmp_path / "x.jsonl").write_text(json.dumps({
        "tool": "cursor", "id": "c1", "project": "shop", "prompts": ["add a cart page"],
        "turns": [{"ts": "2026-11-02T10:00:00Z", "model": "gpt-5", "input": 1, "output": 2},
                  {"ts": "2026-11-02T10:01:00Z", "model": "gpt-5-mini", "input": 3, "auto": True},
                  {"model": "no-timestamp"}]}) + "\n")
    (s,) = list(generic.sessions(tmp_path))
    assert s.tool == "cursor" and [t.auto for t in s.turns] == [False, True]
