import sqlite3

from conftest import ctx_of, deny_of
from skillwire.modules import chaos


def run_many(env, n=200):
    denied = []
    for i in range(n):
        out = env.fire("pre_tool_use_skill", tool_use_id=f"toolu_{i}")
        denied.append(deny_of(out) is not None)
    return denied


def test_requires_both_flag_and_env(env, monkeypatch):
    env.write_project({"chaos": {"enabled": True, "rate": 1.0}})
    assert env.fire("pre_tool_use_skill") is None  # env var missing
    monkeypatch.setenv("SKILLWIRE_CHAOS", "1")
    env.write_project({"chaos": {"enabled": False, "rate": 1.0}})
    assert env.fire("pre_tool_use_skill") is None  # flag off
    env.write_project({"chaos": {"enabled": True, "rate": 1.0}})
    assert deny_of(env.fire("pre_tool_use_skill")) == "skillwire chaos: proceed without this skill."


def test_fixed_seed_is_reproducible_and_near_rate(env, monkeypatch):
    monkeypatch.setenv("SKILLWIRE_CHAOS", "1")
    env.write_project({"chaos": {"enabled": True, "seed": 42}})  # default rate 0.2
    first = run_many(env)
    second = run_many(env)
    assert first == second
    assert 0.12 < sum(first) / len(first) < 0.28
    # The exact pattern is pinned for seed 42 so a change to the algorithm is noticed.
    assert [i for i, d in enumerate(first[:30]) if d] == [2, 11, 12, 15, 16, 21, 22, 28]


def test_different_seed_different_pattern(env, monkeypatch):
    monkeypatch.setenv("SKILLWIRE_CHAOS", "1")
    env.write_project({"chaos": {"enabled": True, "seed": 1}})
    a = run_many(env, 100)
    monkeypatch.setenv("SKILLWIRE_CHAOS_SEED", "2")  # env overrides config seed
    b = run_many(env, 100)
    assert a != b


def test_rate_bounds_and_exempt(env, monkeypatch):
    monkeypatch.setenv("SKILLWIRE_CHAOS", "1")
    env.write_project({"chaos": {"enabled": True, "rate": 0, "seed": 1}})
    assert not any(run_many(env, 50))
    env.write_project({"chaos": {"enabled": True, "rate": 7, "seed": 1, "exempt": ["code-*"]}})
    assert not any(run_many(env, 20))  # exempt despite clamped rate 1.0
    env.write_project({"chaos": {"enabled": True, "rate": "lots", "seed": 1}})
    assert 0 < sum(run_many(env, 100)) < 40  # bad rate falls back to 0.2


def test_banner_at_session_start(env, monkeypatch):
    env.write_project({"chaos": {"enabled": True, "rate": 0.3}})
    assert env.fire("session_start") is None
    monkeypatch.setenv("SKILLWIRE_CHAOS", "1")
    out = env.fire("session_start")
    assert "chaos mode is ACTIVE" in out["systemMessage"] and "30%" in out["systemMessage"]
    assert "chaos mode is active" in ctx_of(out)


def test_chaos_skipped_after_earlier_denial_and_telemetry_records_winner(env, monkeypatch):
    monkeypatch.setenv("SKILLWIRE_CHAOS", "1")
    env.write_project({"chaos": {"enabled": True, "rate": 1.0},
                       "hijacker": {"enabled": True, "map": {"code-review": "other"}}})
    assert "hijacker" in deny_of(env.fire("pre_tool_use_skill"))
    assert deny_of(env.fire("pre_tool_use_skill", tool_input={"skill": "other"})) == chaos.REASON
    rows = sqlite3.connect(env.data / "skillwire.db").execute(
        "SELECT skill, outcome, module FROM events ORDER BY id").fetchall()
    assert rows == [("code-review", "redirected", "hijacker"), ("other", "denied", "chaos")]
