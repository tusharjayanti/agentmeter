import datetime as dt
import json

from agentmeter import report
from agentmeter.core import DEFAULT_CONFIG, Periods, Policy, Session, Turn, aggregate, by_period

P = Policy(DEFAULT_CONFIG)
OLD = "2020-01-01T10:00:00Z"   # a Wednesday, in the Monday-start week of 2019-12-30: always finished
NOW = dt.datetime.now(dt.timezone.utc).isoformat()
MON = Periods.from_config(DEFAULT_CONFIG)


def _sessions():
    return [
        Session("claude-code", "a", "shop", ["fix typo | in readme"], [Turn(OLD, "claude-fable-5-1", input=10, output=5)]),
        Session("claude-code", "b", "shop", ["implement checkout"], [Turn(OLD, "claude-opus-5-5", input=100),
                                                                     Turn(NOW, "claude-opus-5-5", input=7)]),
    ]


def _data():
    sessions = _sessions()
    return aggregate(sessions, P, by_period(MON, {"2019-12-30", MON.current()}))


def test_save_writes_finished_weeks_once(tmp_path):
    weekly, sessions = _data()
    meta = {"tiers": list(DEFAULT_CONFIG["policy"]), "policy": DEFAULT_CONFIG["policy"]}
    weeks = {"2019-12-30", "2020-01-06", MON.current()}
    assert report.save(tmp_path, weekly, sessions, meta, weeks, MON) == ["2019-12-30"]   # empty and current weeks skipped
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2019-12-30.json", "2019-12-30.md"]

    d = json.loads((tmp_path / "2019-12-30.json").read_text())
    assert d["period"] == "2019-12-30" and d["end"] == "2020-01-05" and d["summary"]["fresh"] == 115
    assert {r["period"] for r in d["periods"] + d["sessions"]} == {"2019-12-30"}
    md = (tmp_path / "2019-12-30.md").read_text()
    assert "# agentmeter: Mon 30 Dec – Sun 5 Jan 2020" in md and "**115 tokens** this week · 2 sessions" in md
    assert "fix typo \\| in readme" in md and "Previous week (Mon 23 Dec – Sun 29 Dec 2019): no data" in md
    assert "on-policy" not in md.lower() and d["previous"]["source"] is None

    # never rewritten: logs get pruned, so a later recompute would undercount
    (tmp_path / "2019-12-30.md").write_text("kept")
    assert report.save(tmp_path, [], [], meta, weeks, MON) == []
    assert report.save(tmp_path, weekly, sessions, meta, weeks, MON) == []
    assert (tmp_path / "2019-12-30.md").read_text() == "kept"
    assert report.save(tmp_path, weekly, sessions, meta, weeks, MON, force=True) == ["2019-12-30"]


def test_save_skips_windows_before_collection_begins(tmp_path):
    weekly, sessions = _data()
    later = Periods(dt.date(2019, 12, 30), "1w", begins=dt.date(2020, 1, 6))
    assert report.save(tmp_path, weekly, sessions, {}, {"2019-12-30"}, later) == []
    month = Periods(dt.date(2019, 12, 15), "1m", begins=dt.date(2019, 12, 15))
    w2, s2 = aggregate(_sessions(), P, by_period(month, {"2019-12-15"}))
    assert report.save(tmp_path, w2, s2, {}, {"2019-12-15"}, month) == ["2019-12-15"]
    assert "Sun 15 Dec – Tue 14 Jan 2020" in (tmp_path / "2019-12-15.md").read_text()


def test_report_compares_with_previous_week(tmp_path):
    a, b = "2020-01-01T10:00:00Z", "2020-01-08T10:00:00Z"           # Wed of two consecutive Monday weeks
    sessions = [Session("claude-code", "x", "shop", ["implement checkout"], [Turn(a, "claude-opus-5-5", input=100)]),
                Session("claude-code", "y", "shop", ["implement cart"], [Turn(b, "claude-opus-5-5", input=150),
                                                                        Turn(b, "claude-sonnet-5-5", input=50)])]
    keys = {"2019-12-30", "2020-01-06"}
    weekly, ss = aggregate(sessions, P, by_period(MON, keys))
    assert report.save(tmp_path, weekly, ss, {}, keys, MON) == ["2019-12-30", "2020-01-06"]
    md = (tmp_path / "2020-01-06.md").read_text()
    assert "**200 tokens** this week" in md and "Previous week (Mon 30 Dec – Sun 5 Jan 2020): 100 · **▲ 100%**" in md
    assert "| claude-opus-5-5 | claude-code | 150 | 100 | ▲ 50% |" in md and "| claude-sonnet-5-5 | claude-code | 50 | 0 | new |" in md
    d = json.loads((tmp_path / "2020-01-06.json").read_text())
    assert d["previous"] == {"period": "2019-12-30", "source": "report", "fresh": 100, "total": 100, "change_pct": 100.0}
    # a model used last week but not this week still shows up, at 0
    weekly2, ss2 = aggregate(sessions[1:2], P, by_period(MON, keys))
    md2 = report.render_md("2020-01-13", [], [], MON, prev_rows=[r for r in weekly2 if r["period"] == "2020-01-06"])
    assert "| claude-opus-5-5 | claude-code | 0 | 150 | ▼ 100% |" in md2
