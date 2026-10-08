import io
import json
import sqlite3
import urllib.request

import pytest

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


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_llm_classifier_adds_matches(env, monkeypatch):
    env.write_project({"router": {"rules": RULES, "llm_classify": True}})
    monkeypatch.setenv(router.API_KEY_ENV, "test-key")
    seen = {}

    def fake_urlopen(req, timeout):
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data)
        seen["headers"] = dict(req.header_items())
        payload = {"stop_reason": "end_turn",
                   "content": [{"type": "text", "text": json.dumps({"skills": ["security-review", "made-up"]})}]}
        return FakeResp(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    text = ctx_of(env.fire("user_prompt_submit", prompt="is this code safe to ship?"))
    assert "security-review" in text and "made-up" not in text
    assert seen["timeout"] == 2.0
    assert seen["body"]["model"] == "claude-haiku-5-5"
    assert seen["headers"]["X-api-key"] == "test-key"


@pytest.mark.parametrize("failure", ["timeout", "refusal", "garbage"])
def test_llm_failure_falls_back_to_regex(env, monkeypatch, failure):
    env.write_project({"router": {"rules": RULES, "llm_classify": True}})
    monkeypatch.setenv(router.API_KEY_ENV, "k")

    def fake_urlopen(req, timeout):
        if failure == "timeout":
            raise TimeoutError("timed out")
        if failure == "refusal":
            return FakeResp(json.dumps({"stop_reason": "refusal", "content": []}).encode())
        return FakeResp(b"<html>")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    text = ctx_of(env.fire("user_prompt_submit", prompt="write tests"))
    assert "tdd" in text


def test_llm_not_called_without_key(env, monkeypatch):
    env.write_project({"router": {"rules": RULES, "llm_classify": True}})
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used"))
    assert "tdd" in ctx_of(env.fire("user_prompt_submit", prompt="write a test"))


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
