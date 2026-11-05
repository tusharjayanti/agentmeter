import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
FX = Path(__file__).parent / "fixtures"


def run(tmp_path, *args, cfg=None):
    if cfg is not None:
        (tmp_path / "cfg.json").write_text(json.dumps(cfg))
    env = {**os.environ, "HOME": str(tmp_path), "CLAUDE_DIR": str(FX / "claude_code"),
           "AGENTMETER_CONFIG": str(tmp_path / "cfg.json"), "AGENTMETER_NO_WIZARD": "1"}
    env.pop("CODEX_HOME", None); env.pop("AIDER_REPOS", None)
    return subprocess.run([sys.executable, "-m", "agentmeter", *args], env=env, cwd=REPO, capture_output=True, text=True)


def test_json(tmp_path):
    r = run(tmp_path, "--week", "2026-W45", "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["config"]["tiers"] == ["premium", "strong", "standard", "economy"]
    assert {w["period"] for w in d["periods"]} == {"2026-11-02"}
    assert d["config"]["period"] == {"length": "1w", "start": None, "name": "week"}
    by = {w["model"]: w for w in d["periods"]}
    assert set(by) == {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}
    assert by["claude-opus-5-5"]["total"] == 1160 and by["claude-opus-5-5"]["fresh"] == 160
    assert by["claude-haiku-5-5"]["auto_tokens"] == 340
    assert all(s["prompt"] == "fix the failing checkout test" for s in d["sessions"])


def test_report_lists_each_session_once(tmp_path):
    r = run(tmp_path, "--week", "2026-W45")
    assert r.returncode == 0, r.stderr
    assert "=== Mon 2 Nov – Sun 8 Nov 2026 ===" in r.stdout and "subagents 340" in r.stdout
    assert "on-policy" not in r.stdout and "225 tokens · 1 session\n" in r.stdout
    assert r.stdout.count("fix the failing checkout test (160)") == 1
    judged = run(tmp_path, "--week", "2026-W45", cfg={"routing": True})
    assert "subagents 340 (not judged)" in judged.stdout and "on-policy" in judged.stdout


def test_status_json_shape(tmp_path):
    r = run(tmp_path, "--status-json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert set(d) == {"text", "tooltip", "class"} and "TOKENS" in d["text"] and "%" not in d["text"]
    assert run(tmp_path, "--status").stdout.startswith("TOKENS ")


def test_check(tmp_path):
    r = run(tmp_path, "check", "--weeks", "520")
    assert r.returncode == 0, r.stderr
    assert "claude-opus-5-5" in r.stdout and "strong" in r.stdout
    bad = run(tmp_path, "check", cfg={"tiers": {"top": ["(unclosed"]}})
    assert bad.returncode == 1 and "bad regex" in bad.stdout
    assert run(tmp_path, "--week", "this").returncode != 0   # a bad config stops normal runs too


def test_bad_week_argument(tmp_path):
    r = run(tmp_path, "--week", "someday")
    assert r.returncode == 2 and "expected this, last" in r.stderr


def test_period_from_config(tmp_path):
    r = run(tmp_path, "--period", "2026-11-02", "--json", cfg={"period": {"start": "2026-10-31", "length": "2w"}})
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert {w["period"] for w in d["periods"]} == {"2026-10-31"}
    assert d["config"]["labels"]["2026-10-31"] == "Sat 31 Oct – Fri 13 Nov 2026"
    legacy = json.loads(run(tmp_path, "--week", "2026-11-02", "--json", cfg={"week_start": "saturday"}).stdout)
    assert {w["period"] for w in legacy["periods"]} == {"2026-10-31"}


def test_adhoc_range(tmp_path):
    r = run(tmp_path, "--from", "2026-11-02", "--to", "2026-11-02")
    assert r.returncode == 0, r.stderr
    assert "=== Mon 2 Nov 2026 ===" in r.stdout and "claude-opus-5-5" in r.stdout
    assert "no sessions" in run(tmp_path, "--from", "2026-11-03", "--to", "2026-11-04").stdout
    assert run(tmp_path, "--today", "--save").returncode == 2
    assert run(tmp_path, "--since", "3d").returncode == 0


def test_bad_tool_and_root_arguments(tmp_path):
    assert "unknown tool" in run(tmp_path, "--tool", "cursor").stderr
    assert "TOOL=DIR" in run(tmp_path, "--root", "codex").stderr


def _two_weeks(tmp_path):
    d = tmp_path / "sessions"; d.mkdir()
    rows = [("a", "2026-10-28T10:00:00Z", 100), ("b", "2026-11-04T10:00:00Z", 150)]   # Wed of two Monday weeks
    d.joinpath("s.jsonl").write_text("".join(json.dumps({"tool": "codex", "id": i, "project": "p", "prompts": ["build it"],
                                                         "turns": [{"ts": ts, "model": "gpt-5", "input": n}]}) + "\n"
                                             for i, ts, n in rows))
    return {"tools": ["generic"], "roots": {"generic": str(d)}}


def test_single_week_is_compared_with_the_one_before(tmp_path):
    cfg = _two_weeks(tmp_path)
    r = run(tmp_path, "--period", "2026-11-04", cfg=cfg)
    assert "150 tokens · 1 session · ▲ 50% vs previous week (100)" in r.stdout and "Oct" not in r.stdout.split("\n")[1]
    d = json.loads(run(tmp_path, "--period", "2026-11-04", "--json", cfg=cfg).stdout)
    assert {w["period"] for w in d["periods"]} == {"2026-11-02"}          # the earlier week is only used for the comparison


def test_colour_only_when_asked(tmp_path):
    cfg = _two_weeks(tmp_path)
    assert "\x1b[" not in run(tmp_path, "--period", "2026-11-04", cfg=cfg).stdout      # piped: plain
    env_run = lambda **e: subprocess.run([sys.executable, "-m", "agentmeter", "--period", "2026-11-04"], cwd=REPO, text=True,
                                         capture_output=True, env={**os.environ, "HOME": str(tmp_path), "AGENTMETER_NO_WIZARD": "1",
                                                                   "AGENTMETER_CONFIG": str(tmp_path / "cfg.json"), **e}).stdout
    assert "\x1b[1m" in env_run(FORCE_COLOR="1")
    assert "\x1b[" not in env_run(FORCE_COLOR="1", NO_COLOR="1")
