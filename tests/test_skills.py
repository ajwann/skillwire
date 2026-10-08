from skillwire import skills

DOC = """---
name: demo
description: "Use when: quoting \\"things\\""
folded: >
  line one
  line two
other: plain value
---
body
"""


def test_parse_frontmatter():
    fm = skills.parse_frontmatter(DOC)
    assert fm["name"] == "demo"
    assert fm["description"] == 'Use when: quoting "things"'
    assert fm["folded"] == "line one line two"
    assert fm["other"] == "plain value"


def test_no_frontmatter():
    assert skills.parse_frontmatter("just text") == {}
    assert skills.description_line_index("just text") is None


def test_description_line_index():
    assert skills.description_line_index(DOC) == (2, True)
    folded = "---\nname: x\ndescription: >\n  a\n  b\n---\n"
    assert skills.description_line_index(folded) == (2, False)
    cont = "---\ndescription: a\n  continued\n---\n"
    assert skills.description_line_index(cont) == (1, False)


def test_discover_project_shadows_user(env):
    env.make_skill("same", "project one")
    env.make_skill("same", "user one", where="user")
    env.make_skill("only-user", "u", where="user")
    found = {s.name: s for s in skills.discover(env.project)}
    assert found["same"].description == "project one" and found["same"].scope == "project"
    assert found["only-user"].scope == "user"


def test_discover_extra_dirs_and_sidecar(env, tmp_path):
    extra = tmp_path / "extra" / "x"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\n")
    (extra / "skillwire.json").write_text('{"skillwire": {"variants": ["a", "b"]}}')
    found = skills.discover(env.project, {"skill_dirs": [str(tmp_path / "extra")]})
    assert found[0].name == "x" and found[0].sidecar == {"variants": ["a", "b"]}
