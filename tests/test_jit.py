import json
import shutil
import time

import pytest

from conftest import ROOT
from skillwire.modules import jit

TEMPLATE = "---\nname: live\ndescription: Live data skill\n---\nItems:\n{{ items }}\nCount: {{ meta.count }}\n"


def make_jit_skill(env, generator, template=TEMPLATE, existing=None):
    d = env.project / ".claude" / "skills" / "live"
    d.mkdir(parents=True)
    (d / "SKILL.template.md").write_text(template)
    (d / "skillwire.json").write_text(json.dumps({"generator": generator}))
    if existing is not None:
        (d / "SKILL.md").write_text(existing)
    return d


def write_gen(d, body):
    (d / "gen.py").write_text(body)


def test_render_lists_dicts_and_missing():
    assert jit.render("---\na: 1\n---\n{{ x }}|{{ y.z }}", {"x": ["a", "b"], "y": {"z": 3}}) == "---\na: 1\n---\n- a\n- b|3"
    with pytest.raises(jit.RenderError, match="no value"):
        jit.render("---\na: 1\n---\n{{ nope }}", {})
    with pytest.raises(jit.RenderError, match="frontmatter"):
        jit.render("{{ x }}", {"x": "no frontmatter"})


def test_session_start_renders(env):
    env.write_project({"jit": {"enabled": True}})
    d = make_jit_skill(env, "{python} gen.py")
    write_gen(d, 'import json; print(json.dumps({"items": ["one", "two"], "meta": {"count": 2}}))')
    assert env.fire("session_start") is None
    text = (d / "SKILL.md").read_text()
    assert "- one\n- two" in text and "Count: 2" in text


def test_failing_generator_keeps_last_good(env):
    env.write_project({"jit": {"enabled": True}})
    good = "---\nname: live\ndescription: d\n---\nlast good\n"
    d = make_jit_skill(env, "{python} gen.py", existing=good)
    write_gen(d, 'import sys; print("upstream 503", file=sys.stderr); sys.exit(3)')
    out = env.fire("session_start")
    assert (d / "SKILL.md").read_text() == good
    assert "exited 3" in out["systemMessage"] and "kept the last good SKILL.md" in out["systemMessage"]
    assert "upstream 503" in env.errors()


@pytest.mark.parametrize("case", ["missing_key", "bad_command", "timeout"])
def test_other_failures_keep_last_good(env, case):
    env.write_project({"jit": {"enabled": True, "timeout": 1}})
    good = "---\nname: live\ndescription: d\n---\nlast good\n"
    gen = {"missing_key": "{python} gen.py", "bad_command": "definitely-not-a-binary-xyz",
           "timeout": "{python} gen.py"}[case]
    d = make_jit_skill(env, gen, existing=good)
    write_gen(d, {"missing_key": 'print("{}")',
                  "timeout": "import time; time.sleep(5)",
                  "bad_command": ""}[case])
    t0 = time.time()
    out = env.fire("session_start")
    assert time.time() - t0 < 4
    assert (d / "SKILL.md").read_text() == good
    assert "skillwire JIT" in out["systemMessage"]


def test_non_json_output_and_disabled(env):
    d = make_jit_skill(env, "{python} gen.py", template="---\nname: live\ndescription: d\n---\n{{ output }}\n")
    write_gen(d, 'print("plain text body")')
    env.fire("session_start")
    assert not (d / "SKILL.md").exists()  # jit off by default
    env.write_project({"jit": {"enabled": True}})
    env.fire("session_start")
    assert "plain text body" in (d / "SKILL.md").read_text()


def test_skips_compact_and_dry_run(env, monkeypatch):
    env.write_project({"jit": {"enabled": True}})
    d = make_jit_skill(env, "{python} gen.py", template="---\nname: live\ndescription: d\n---\n{{ output }}\n")
    write_gen(d, 'print("x")')
    env.fire("session_start", source="compact")
    assert not (d / "SKILL.md").exists()
    monkeypatch.setenv("SKILLWIRE_DRY_RUN", "1")
    env.fire("session_start")
    assert not (d / "SKILL.md").exists()


def test_rotated_variant_survives_rerender(env):
    from skillwire import db
    env.write_project({"jit": {"enabled": True}})
    d = make_jit_skill(env, "{python} gen.py", template="---\nname: live\ndescription: template desc\n---\n{{ output }}\n")
    write_gen(d, 'print("x")')
    conn = db.connect()
    conn.execute("INSERT INTO ab_rotations (skill, variant, description, started_at) VALUES ('live','B','variant b',1)")
    conn.commit()
    conn.close()
    env.fire("session_start")
    assert 'description: "variant b"' in (d / "SKILL.md").read_text()


def test_example_generator_with_file_url(env, tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text(json.dumps({"results": [{"id": "census-2020", "description": "  US   census\n data "},
                                            {"name": "weather"}, {"nothing": 1}]}))
    dest = env.project / ".claude" / "skills" / "jit-datasets"
    shutil.copytree(ROOT / "examples" / "jit-datasets", dest)
    (dest / "skillwire.json").write_text(json.dumps({"generator": ["{python}", "generate.py", "--url", feed.as_uri()]}))
    env.write_project({"jit": {"enabled": True}})
    assert env.fire("session_start") is None, env.errors()
    text = (dest / "SKILL.md").read_text()
    assert "- **census-2020**: US census data" in text and "- **weather**" in text
    assert "(2 datasets above)" in text
    assert text.startswith("---\nname: jit-datasets\n")
