import sqlite3

from conftest import ctx_of, deny_of
from skillwire.modules.allowlist import check


def cfg(rules):
    return {"allowlist": {"enabled": True, "rules": rules}}


def test_block_glob(tmp_path):
    c = cfg([{"paths": [str(tmp_path / "work" / "*")], "block": ["personal-*"]}])
    assert "blocked" in check("personal-notes", str(tmp_path / "work" / "repo" / "src"), c)
    assert check("code-review", str(tmp_path / "work" / "repo"), c) is None
    assert check("personal-notes", str(tmp_path / "home"), c) is None


def test_allow_list_restricts(tmp_path):
    repo = tmp_path / "payments"
    c = cfg([{"paths": [str(repo)], "allow": ["code-review", "security-*"]}])
    assert check("code-review", str(repo / "sub"), c) is None  # ancestors match
    assert check("security-audit", str(repo), c) is None
    assert "not on the allowlist" in check("pirate-voice", str(repo), c)


def test_block_beats_allow_and_plugin_names(tmp_path):
    c = cfg([{"paths": [str(tmp_path)], "allow": ["*"], "block": ["danger"]}])
    assert check("myplugin:danger", str(tmp_path), c)
    assert check("myplugin:ok", str(tmp_path), c) is None


def test_tilde_and_symlinks(env, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    c = cfg([{"paths": [str(link)], "block": ["x"]}])
    assert check("x", str(real), c)
    (env.home / "w").mkdir()
    assert check("x", str(env.home / "w"), cfg([{"paths": ["~/w"], "block": ["x"]}]))


def test_dispatch_denies_and_records(env):
    env.write_project(cfg([{"paths": [str(env.project)], "block": ["code-review"]}]))
    reason = deny_of(env.fire("pre_tool_use_skill"))
    assert "blocked in" in reason and "code-review" in reason
    row = sqlite3.connect(env.data / "skillwire.db").execute("SELECT outcome, module FROM events").fetchone()
    assert row == ("denied", "allowlist")


def test_allowlist_runs_before_hijacker(env):
    env.write_project({**cfg([{"paths": [str(env.project)], "block": ["code-review"]}]),
                       "hijacker": {"enabled": True, "map": {"code-review": "better-review"}}})
    assert "allowlist" in deny_of(env.fire("pre_tool_use_skill"))


def test_hijacker_wont_redirect_into_blocked_skill(env):
    env.write_project({**cfg([{"paths": [str(env.project)], "block": ["better-review"]}]),
                       "hijacker": {"enabled": True, "map": {"code-review": "better-review"}}})
    assert env.fire("pre_tool_use_skill") is None
    assert "target is blocked" in env.errors()


def test_router_and_chaining_skip_blocked(env):
    env.write_project({**cfg([{"paths": [str(env.project)], "block": ["secret-skill"]}]),
                       "router": {"rules": [{"skill": "secret-skill", "keywords": ["deploy"]},
                                            {"skill": "ok-skill", "keywords": ["deploy"]}]},
                       "chaining": {"chains": {"code-review": ["secret-skill", "ok-skill"]}}})
    routed = ctx_of(env.fire("user_prompt_submit", prompt="deploy it"))
    assert "ok-skill" in routed and "secret-skill" not in routed
    chained = ctx_of(env.fire("post_tool_use_skill"))
    assert "ok-skill" in chained and "secret-skill" not in chained


def test_malformed_rules_ignored(env):
    env.write_project({"allowlist": {"enabled": True, "rules": ["x", {"paths": 5}, {"block": ["code-review"]}]}})
    assert env.fire("pre_tool_use_skill") is None
