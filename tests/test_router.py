import json
import sqlite3

from conftest import ctx_of
from skillwire.modules import router

RULES = [
    {"skill": "security-review", "keywords": ["security", "vulnerability"], "priority": "required",
     "intent_examples": ["is this code safe?"]},
    {"skill": "tdd", "regex": [r"\bwrite (a )?tests?\b"], "priority": "suggested"},
    {"skill": "cpp", "keywords": ["c++"]},
]


def test_keyword_and_regex_matching():
    assert [r["skill"] for r in router.match_rules("Check for SECURITY holes", RULES)] == ["security-review"]
    assert [r["skill"] for r in router.match_rules("please write tests for x", RULES)] == ["tdd"]
    assert [r["skill"] for r in router.match_rules("modern c++ idioms", RULES)] == ["cpp"]
    assert router.match_rules("insecurity is a feeling", RULES) == []  # word boundary


def test_context_separates_required_and_suggested(env):
    env.write_project({"router": {"rules": RULES}})
    text = ctx_of(env.fire("user_prompt_submit", prompt="security audit, then write tests"))
    assert "Required skills" in text and "security-review" in text.split("Suggested")[0]
    assert "Suggested skills" in text and "tdd" in text.split("Suggested")[1]


def test_no_match_no_output(env):
    env.write_project({"router": {"rules": RULES}})
    out = env.fire("user_prompt_submit", prompt="hello there")
    assert out is None


def test_routed_rows_recorded_by_telemetry(env):
    env.write_project({"router": {"rules": RULES}})
    env.fire("user_prompt_submit", prompt="security please")
    conn = sqlite3.connect(env.data / "skillwire.db")
    got = conn.execute("SELECT skill, outcome, detail FROM events WHERE outcome='routed'").fetchall()
    assert got == [("security-review", "routed", "required")]


def test_bad_regex_is_logged_not_fatal(env):
    env.write_project({"router": {"rules": [{"skill": "x", "regex": ["(unclosed"]}, RULES[0]]}})
    assert "security-review" in ctx_of(env.fire("user_prompt_submit", prompt="security"))
    assert "bad regex" in env.errors()


def test_init_generates_and_merges(env):
    from skillwire.cli import main
    env.make_skill("pdf-tools", 'Extract text from PDF files. Use when the user mentions "fill a form" or PDFs.')
    env.make_skill("nodesc", "")
    env.write_project({"router": {"rules": [{"skill": "keep-me", "keywords": ["x"]}]}, "chaos": {"rate": 0.5}})
    assert main(["init"]) == 0
    cfg = json.loads((env.project / ".claude" / "skillwire.json").read_text())
    skills_ = [r["skill"] for r in cfg["router"]["rules"]]
    assert skills_ == ["keep-me", "pdf-tools"]
    rule = cfg["router"]["rules"][1]
    assert "pdf tools" in rule["keywords"] and "fill a form" in rule["keywords"]
    assert rule["intent_examples"][0] == "Extract text from PDF files."
    assert cfg["chaos"] == {"rate": 0.5}  # untouched
    assert list((env.data / "backups").iterdir())
    # idempotent
    assert main(["init"]) == 0
    cfg2 = json.loads((env.project / ".claude" / "skillwire.json").read_text())
    assert len(cfg2["router"]["rules"]) == 2


def test_init_refuses_corrupt_config(env, capsys):
    from skillwire.cli import main
    env.make_skill("a", "desc here")
    env.write_project("{nope")
    assert main(["init"]) == 2
    assert (env.project / ".claude" / "skillwire.json").read_text() == "{nope"


def test_removed_classifier_keys_are_flagged(env):
    from skillwire import config
    env.write_project({"router": {"llm_classify": True, "llm_timeout": 2, "rules": RULES}})
    cfg, _ = config.load(env.project)
    text = "\n".join(config.validate(cfg))
    assert "router.llm_classify was removed" in text and "router.llm_timeout was removed" in text
    # and routing still works on rules alone
    assert "tdd" in ctx_of(env.fire("user_prompt_submit", prompt="write tests"))
