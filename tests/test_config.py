from skillwire import config


def test_defaults_router_telemetry_chaining_on_rest_off(env):
    cfg, problems = config.load(env.project)
    assert problems == []
    on = {m for m in config.MODULES if cfg[m]["enabled"]}
    assert on == {"router", "telemetry", "chaining"}


def test_project_overrides_global(env):
    env.write_global({"chaos": {"enabled": True, "rate": 0.5}, "telemetry": {"store_prompts": True}})
    env.write_project({"chaos": {"rate": 0.1}})
    cfg, _ = config.load(env.project)
    assert cfg["chaos"] == {"enabled": True, "rate": 0.1, "seed": None, "exempt": []}
    assert cfg["telemetry"]["store_prompts"] is True


def test_lists_replace_rather_than_merge(env):
    env.write_global({"router": {"rules": [{"skill": "a"}]}})
    env.write_project({"router": {"rules": [{"skill": "b"}]}})
    cfg, _ = config.load(env.project)
    assert [r["skill"] for r in cfg["router"]["rules"]] == ["b"]


def test_corrupted_project_config_falls_back_to_global(env):
    env.write_global({"hijacker": {"enabled": True, "map": {"a": "b"}}})
    env.write_project('{"hijacker": {"enabled": tru')  # truncated JSON
    cfg, problems = config.load(env.project)
    assert cfg["hijacker"]["map"] == {"a": "b"}
    assert len(problems) == 1 and "invalid JSON" in problems[0]
    assert "invalid JSON" in env.errors()


def test_corrupted_config_does_not_break_hooks(env):
    env.write_project("\x00\xff garbage")
    env.write_global("[1, 2, 3]")
    out = env.fire("pre_tool_use_skill")
    assert out is None  # defaults: nothing to deny
    assert "top level must be a JSON object" in env.errors()


def test_wrong_shapes_are_sanitized(env):
    env.write_project({"chaos": "yes please", "router": {"enabled": "true"}})
    cfg, problems = config.load(env.project)
    assert cfg["chaos"]["enabled"] is False
    assert cfg["router"]["enabled"] is True
    assert len(problems) == 2


def test_find_cycles():
    assert config.find_cycles({"a": "b", "b": "c", "c": "a", "x": "y"}) == [["a", "b", "c", "a"]]
    assert config.find_cycles({"a": "b"}) == []


def test_validate_flags_problems(env):
    env.write_project({
        "router": {"rules": [{"skill": "x", "regex": ["("], "priority": "maybe"}, {}]},
        "hijacker": {"map": {"a": "a", "b": "c", "c": "b"}},
        "chaos": {"rate": 3},
        "allowlist": {"rules": [{"paths": ["/x"]}]},
        "bogus": 1,
    })
    cfg, _ = config.load(env.project)
    text = "\n".join(config.validate(cfg))
    for needle in ("bad regex", "priority", "needs a 'skill'", "to itself", "cycle", "chaos.rate",
                   "needs 'allow' or 'block'", "unknown top-level key 'bogus'"):
        assert needle in text, needle


def test_example_config_uses_every_module_and_validates(env):
    import json
    from conftest import ROOT
    example = json.loads((ROOT / "skillwire.example.json").read_text())
    assert set(config.MODULES) <= set(example)
    assert all(example[m]["enabled"] is True for m in config.MODULES)
    env.write_project(example)
    cfg, problems = config.load(env.project)
    assert problems == [] and config.validate(cfg) == []
