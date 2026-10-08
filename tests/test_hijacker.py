import sqlite3

from conftest import deny_of
from skillwire.modules.hijacker import resolve


def test_resolve_basic_and_transitive():
    assert resolve("a", {"a": "b"}) == "b"
    assert resolve("a", {"a": "b", "b": "c"}) == "c"
    assert resolve("z", {"a": "b"}) is None


def test_self_redirect_ignored():
    assert resolve("a", {"a": "a"}) is None


def test_cycle_is_never_followed(env):
    m = {"a": "b", "b": "c", "c": "a"}
    for start in "abc":
        assert resolve(start, m) is None
    assert "cycle ignored: a -> b -> c -> a" in env.errors()


def test_chain_into_cycle_ignored():
    assert resolve("x", {"x": "a", "a": "b", "b": "a"}) is None


def test_hijack_denies_with_redirect_reason(env):
    env.write_project({"hijacker": {"enabled": True, "map": {"code-review": "better-review"}}})
    reason = deny_of(env.fire("pre_tool_use_skill"))
    assert "'code-review' is replaced by 'better-review'" in reason
    assert "'focus on auth'" in reason  # args forwarded in the hint


def test_replacement_itself_passes(env):
    env.write_project({"hijacker": {"enabled": True, "map": {"code-review": "better-review"}}})
    assert env.fire("pre_tool_use_skill", tool_input={"skill": "better-review"}) is None


def test_hijack_cycle_end_to_end_allows_original(env):
    env.write_project({"hijacker": {"enabled": True, "map": {"code-review": "x", "x": "code-review"}}})
    assert env.fire("pre_tool_use_skill") is None
    assert env.fire("pre_tool_use_skill", tool_input={"skill": "x"}) is None


def test_redirect_recorded_by_telemetry(env):
    env.write_project({"hijacker": {"enabled": True, "map": {"code-review": "better-review"}}})
    env.fire("pre_tool_use_skill")
    conn = sqlite3.connect(env.data / "skillwire.db")
    row = conn.execute("SELECT skill, outcome, module, redirect_to FROM events").fetchone()
    assert row == ("code-review", "redirected", "hijacker", "better-review")


def test_disabled_by_default(env):
    env.write_project({"hijacker": {"map": {"code-review": "better-review"}}})
    assert env.fire("pre_tool_use_skill") is None


def test_crash_in_one_module_does_not_stop_the_next(env, monkeypatch):
    from skillwire import dispatch
    from skillwire.modules import allowlist

    monkeypatch.setattr(allowlist, "handle", lambda ctx: 1 / 0)
    env.write_project({"allowlist": {"enabled": True},
                       "hijacker": {"enabled": True, "map": {"code-review": "better-review"}}})
    out = dispatch.run_event(env.event("pre_tool_use_skill"))
    assert "better-review" in deny_of(out)
    assert "ZeroDivisionError" in env.errors()
