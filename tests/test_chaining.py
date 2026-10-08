import json

from conftest import ctx_of

CHAINS = {"chaining": {"chains": {"code-review": ["security-review", "code-review", "tdd"]}}}


def test_follow_ups_added_after_load(env):
    env.write_project(CHAINS)
    text = ctx_of(env.fire("post_tool_use_skill"))
    assert "security-review, tdd" in text
    assert "code-review" not in text.split("followed by:")[1]  # never chain to itself


def test_skips_already_loaded_in_session(env):
    env.write_project(CHAINS)
    env.skill("tdd")
    text = ctx_of(env.fire("post_tool_use_skill"))
    assert "security-review" in text and "tdd" not in text.split("followed by:")[1]


def test_ping_pong_terminates(env):
    env.write_project({"chaining": {"chains": {"a": ["b"], "b": ["a"]}}})
    _, post_a = env.skill("a")
    assert "followed by: b" in ctx_of(post_a)
    _, post_b = env.skill("b")
    assert post_b is None  # 'a' already loaded, so no suggestion


def test_no_suggestion_on_failed_load(env):
    env.write_project(CHAINS)
    assert env.fire("post_tool_use_skill", tool_response={"success": False}) is None


def test_disabled(env):
    env.write_project({**CHAINS, "chaining": {**CHAINS["chaining"], "enabled": False}})
    assert env.fire("post_tool_use_skill") is None


def test_malformed_chains_are_harmless(env):
    env.write_project({"chaining": {"chains": {"code-review": "tdd"}}})
    assert env.fire("post_tool_use_skill") is None
    env.write_project({"chaining": {"chains": ["nope"]}})
    assert env.fire("post_tool_use_skill") is None


def test_suggest_chains(env, capsys):
    from skillwire.cli import main
    for i in range(4):
        sid = f"s{i}"
        env.skill("plan", session_id=sid)
        env.skill("implement", session_id=sid)
        if i < 2:
            env.skill("rare", session_id=sid)
    # One session in the reverse order: plan->implement still wins 4:1.
    env.skill("implement", session_id="r")
    env.skill("plan", session_id="r")
    env.write_project({"chaining": {"chains": {"plan": []}}})
    cfg_before = (env.project / ".claude" / "skillwire.json").read_text()
    assert main(["suggest-chains", "--min", "3"]) == 0
    out = capsys.readouterr().out
    snippet = json.loads(out.split("```json")[1].split("```")[0])
    assert snippet == {"chaining": {"chains": {"plan": ["implement"]}}}
    assert "| plan | implement | 4 | 1 |" in out
    assert (env.project / ".claude" / "skillwire.json").read_text() == cfg_before  # never edits config


def test_suggest_chains_excludes_existing_and_reports_nothing(env, capsys):
    from skillwire.cli import main
    for i in range(3):
        env.skill("a", session_id=f"s{i}")
        env.skill("b", session_id=f"s{i}")
    env.write_project({"chaining": {"chains": {"a": ["b"]}}})
    assert main(["suggest-chains"]) == 0
    assert "Nothing to propose" in capsys.readouterr().out
