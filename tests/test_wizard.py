import json, os, subprocess, sys
from pathlib import Path


def test_wizard_non_tty(tmp_path):
    (tmp_path / ".claude/projects").mkdir(parents=True)
    (tmp_path / "codexlogs").mkdir()
    env = {**os.environ, "HOME": str(tmp_path), "AGENTMETER_CONFIG": str(tmp_path / "cfg.json")}
    # tools, codex path, begin "a date I choose", the date, 1 week, routing: default no, save: default yes
    # gemini is ticked with no logs: enter keeps its usual place instead of demanding an existing folder
    answers = "1,2,3\n" + str(tmp_path / "codexlogs") + "\n" + "\n" + "4\n2026-10-31\n" + "1\n" + "\n" + "\n"
    r = subprocess.run([sys.executable, "-m", "agentmeter", "init"], input=answers, text=True, env=env,
                       capture_output=True, cwd=Path(__file__).parent.parent)
    assert r.returncode == 0, r.stderr
    cfg = json.loads((tmp_path / "cfg.json").read_text())
    assert cfg["tools"] == ["claude-code", "codex", "gemini"] and "gemini" not in cfg["roots"]
    assert cfg["roots"]["codex"] == str(tmp_path / "codexlogs")
    assert cfg["period"] == {"start": "2026-10-31", "length": "1w"} and "week_start" not in cfg
    assert "next report:" in r.stdout
    assert cfg["routing"] is False and "routing: off" in r.stdout
