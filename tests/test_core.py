import datetime as dt

from agentmeter.core import (DEFAULT_CONFIG, Periods, Policy, Session, Turn, add_months, aggregate, by_period, by_range,
                             local, on_policy_pct, parse_length, parse_since, since, validate)

P = Policy(DEFAULT_CONFIG)
TS = "2026-11-02T10:00:00Z"
MON = Periods.from_config(DEFAULT_CONFIG)          # default: weeks starting Monday
WK = by_period(MON, {"2026-11-02"})               # Monday-start week holding TS


def test_tiers():
    assert P.tier("claude-fable-5-1") == "premium"
    assert P.tier("claude-opus-5-5") == "strong"
    assert P.tier("claude-sonnet-5-5") == "standard"
    assert P.tier("claude-haiku-5-5") == "economy"
    assert P.tier("gpt-5.1-codex") == "strong"
    assert P.tier("gpt-5-mini") == "economy"
    assert P.tier("gemini-2.5-pro") == "strong"
    assert P.tier("gemini-2.5-flash") == "standard"
    assert P.tier("gemini-2.5-flash-lite") == "economy"
    assert P.tier("o3-pro") == "premium"


def test_classify_narrow_wins():
    assert P.classify(["fix typo in parser.rs"]) == "trivial"
    assert P.classify(["add a readme section on the eval harness"]) == "docs"
    assert P.classify(["Design the architecture for a multi-tenant eval pipeline"]) == "design"
    assert P.classify(["hello"]) == "unclassified"


def test_classify_questions_are_explain():
    assert P.classify(["is this tool just for fresh grads and interns?"]) == "explain"
    assert P.classify(["How do I leverage the plugin system"]) == "explain"


def test_classify_scores_prompts_not_matches():
    # a pasted log full of "error" is one fix prompt, not five
    assert P.classify(["refactor the parser module", "log: error error error error error"]) == "refactor"


def test_on_policy():
    assert P.on_policy("premium", "design") is True
    assert P.on_policy("premium", "fix") is False
    assert P.on_policy("unknown", "fix") is None
    assert P.on_policy("strong", "unclassified") is None


def _s(tool, sid, prompt, *turns):
    return Session(tool=tool, id=sid, project="p", prompts=[prompt], turns=list(turns))


def test_aggregate_keys_by_tool_and_weights_by_tokens():
    sessions = [
        _s("codex", "a", "implement the importer", Turn(TS, "gpt-5.1-codex", input=900, output=100)),   # build: on
        _s("generic", "b", "fix typo", Turn(TS, "gpt-5.1-codex", input=10)),                          # trivial: off
        _s("claude-code", "c", "implement it", Turn(TS, "claude-opus-5-5", input=50),
           Turn(TS, "claude-haiku-5-5", input=40, auto=True)),                                         # subagent: not judged
        _s("claude-code", "d", "implement it", Turn(TS, "mystery-model-9", input=70)),                 # unknown tier
    ]
    weekly, rows = aggregate(sessions, P, WK)
    by = {(r["tool"], r["model"]): r for r in weekly}
    assert set(by) == {("codex", "gpt-5.1-codex"), ("generic", "gpt-5.1-codex"), ("claude-code", "claude-opus-5-5"),
                       ("claude-code", "claude-haiku-5-5"), ("claude-code", "mystery-model-9")}
    assert by[("codex", "gpt-5.1-codex")]["on_policy_tokens"] == 1000
    assert by[("generic", "gpt-5.1-codex")]["off_policy_tokens"] == 10
    haiku = by[("claude-code", "claude-haiku-5-5")]
    assert haiku["auto_tokens"] == 40 and haiku["judged_tokens"] == 0 and haiku["mix"] == {"subagent": 40}
    assert by[("claude-code", "mystery-model-9")]["judged_tokens"] == 0
    # token-weighted: (1000 + 50) on of (1000 + 10 + 50) judged
    assert round(on_policy_pct(weekly), 1) == round(100 * 1050 / 1060, 1)
    assert by[("claude-code", "claude-opus-5-5")]["sessions"] == 1


def test_aggregate_fresh_excludes_cache_reads():
    (w,), _ = aggregate([_s("x", "a", "build it", Turn(TS, "opus", input=1, cache_write=2, cache_read=1000, output=3))], P, WK)
    assert w["total"] == 1006 and w["fresh"] == 6


def test_since_is_before_week_start():
    start = dt.datetime(2026, 11, 2).timestamp()
    assert start - 2 * 86400 < since({"2026-11-02", "2026-11-09"}) < start


def _per(start, length="1w"):
    return Periods.from_config({"period": {"start": start, "length": length}})


def test_default_weeks_start_monday_and_legacy_week_start_still_works():
    d = dt.date(2026, 11, 2)                                       # a Monday
    assert MON.key(d) == "2026-11-02" and MON.key(d + dt.timedelta(days=6)) == "2026-11-02"
    sat = Periods.from_config({"week_start": "saturday"})
    assert sat.key(d) == "2026-10-31" and sat.label("2026-10-31") == "Sat 31 Oct – Fri 6 Nov 2026"
    assert sat.begins is None


def test_windows_anchor_on_the_start_date():
    p = _per("2026-11-06")                                         # a Friday
    assert p.key(dt.date(2026, 11, 12)) == "2026-11-06" and p.key(dt.date(2026, 11, 13)) == "2026-11-13"
    assert p.key(dt.date(2026, 11, 5)) == "2026-10-30"             # before the start: windows extend backwards
    assert p.end("2026-11-06") == dt.date(2026, 11, 12) and p.begins == dt.date(2026, 11, 6)
    two = _per("2026-11-04", "2w")
    assert two.back(3, today=dt.date(2026, 12, 1)) == ["2026-10-21", "2026-11-04", "2026-11-18"]
    assert two.covering(dt.date(2026, 11, 10), today=dt.date(2026, 12, 2)) == ["2026-11-04", "2026-11-18", "2026-12-02"]
    assert two.name == "fortnight" and _per("2026-11-04", "10d").name == "period"


def test_month_windows_clamp_to_month_end():
    assert add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    p = _per("2026-01-31", "1m")
    assert p.key(dt.date(2026, 2, 28)) == "2026-02-28" and p.key(dt.date(2026, 2, 27)) == "2026-01-31"
    assert p.key(dt.date(2026, 3, 30)) == "2026-02-28" and p.key(dt.date(2026, 3, 31)) == "2026-03-31"
    assert p.end("2026-01-31") == dt.date(2026, 2, 27)
    q = _per("2026-10-15", "3m")
    assert q.key(dt.date(2027, 1, 14)) == "2026-10-15" and q.key(dt.date(2027, 1, 15)) == "2027-01-15"
    assert q.key(dt.date(2026, 10, 1)) == "2026-07-15"


def test_parse_length():
    assert parse_length("7d") == (7, "d") and parse_length("2w") == (14, "d") and parse_length("1 month") == (1, "m")
    for bad in ("0d", "week", "3y", ""):
        try:
            parse_length(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should not parse")


def test_parse_window_arguments():
    for p in (MON, _per("2026-11-07"), _per("2026-01-01", "1m"), _per("2026-11-04", "3d")):
        this, last = p.back(2)[::-1]
        assert p.parse("this") == this and p.parse("last") == last and last < this
    assert MON.parse("2026-11-04") == "2026-11-02" and MON.parse("2026-W45") == "2026-11-02"
    assert _per("2026-10-31").parse("2026-11-04") == "2026-10-31"


def test_change_label():
    from agentmeter.core import change_label
    assert change_label(125, 100) == "↑25%" and change_label(81, 100) == "↓19%"
    assert change_label(100, 100) == "no change" and change_label(5, 0) == "new" and change_label(0, 0) == "–"


def test_parse_since():
    now = dt.datetime(2026, 11, 4, 15, 30).astimezone()
    assert parse_since("6h", now) == now - dt.timedelta(hours=6)
    assert parse_since("2w", now) == now - dt.timedelta(days=14)
    assert parse_since("today", now) == now.replace(hour=0, minute=0)
    assert parse_since("2026-10-01", now).date() == dt.date(2026, 10, 1)


def test_aggregate_by_range():
    frm = local("2026-11-02T09:00:00Z")
    s = _s("x", "a", "build it", Turn("2026-11-02T08:00:00Z", "opus", input=1), Turn("2026-11-02T10:00:00Z", "opus", input=2),
           Turn("2026-11-03T10:00:00Z", "opus", input=4))
    (w,), _ = aggregate([s], P, by_range(frm, local("2026-11-03T00:00:00Z")))
    assert w["input"] == 2 and w["period"] == frm.date().isoformat()


def test_aggregate_buckets_by_start_day():
    s = _s("x", "a", "build it", Turn("2026-11-06T12:00:00Z", "opus", input=1), Turn("2026-11-07T12:00:00Z", "opus", input=2))
    sat = _per("2026-10-31")
    weekly, _ = aggregate([s], P, by_period(sat, {"2026-10-31", "2026-11-07"}))    # Fri 6th / Sat 7th split
    assert {r["period"]: r["input"] for r in weekly} == {"2026-10-31": 1, "2026-11-07": 2}


def test_validate():
    assert validate(DEFAULT_CONFIG) == ([], [])
    bad = {**DEFAULT_CONFIG, "tiers": {"top": ["(unclosed"]}, "policy": {"ghost": ["build"], "top": ["nope"]}}
    errors, warnings = validate(bad)
    assert any("bad regex" in e for e in errors)
    assert any("week_start" in e for e in validate({**DEFAULT_CONFIG, "week_start": "funday"})[0])
    assert any("period.length" in e for e in validate({**DEFAULT_CONFIG, "period": {"length": "fortnightly"}})[0])
    assert any("period.start" in e for e in validate({**DEFAULT_CONFIG, "period": {"start": "6 Nov", "length": "1w"}})[0])
    assert any("ghost" in w for w in warnings) and any("'nope'" in w for w in warnings)
