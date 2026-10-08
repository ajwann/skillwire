import json
import time

from skillwire import db, rotator
from skillwire.cli import main

BODY = "# Body\n\nkeep: me\ndescription: this body line must not change\n"
VARIANTS = ["Use when reviewing code for bugs.", 'Use for "code review" requests: PRs, diffs.']


def ab_skill(env, description=VARIANTS[0], variants=VARIANTS, extra_fm="allowed-tools: Read\n"):
    d = env.project / ".claude" / "skills" / "reviewer"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: reviewer\ndescription: {description}\n{extra_fm}---\n{BODY}")
    (d / "skillwire.json").write_text(json.dumps({"variants": variants}))
    env.write_project({"ab": {"enabled": True}})
    return d


def test_rotate_edits_only_description_and_backs_up(env, capsys):
    d = ab_skill(env)
    before = (d / "SKILL.md").read_text()
    assert main(["rotate"]) == 0
    after = (d / "SKILL.md").read_text()
    diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert diff == [(f"description: {VARIANTS[0]}", 'description: "Use for \\"code review\\" requests: PRs, diffs."')]
    assert after.endswith(BODY)
    backups = list((env.data / "backups").glob("reviewer.*.SKILL.md"))
    assert len(backups) == 1 and backups[0].read_text() == before
    assert "variant B" in capsys.readouterr().out


def test_rotate_cycles_and_parser_reads_back(env):
    from skillwire import skills
    d = ab_skill(env)
    main(["rotate"])
    assert skills.parse_frontmatter((d / "SKILL.md").read_text())["description"] == VARIANTS[1]
    main(["rotate"])
    assert skills.parse_frontmatter((d / "SKILL.md").read_text())["description"] == VARIANTS[0]
    conn = db.connect()
    assert [r[0] for r in conn.execute("SELECT variant FROM ab_rotations ORDER BY id")] == ["B", "A"]


def test_rotate_requires_enabled_and_dry_run(env, capsys):
    d = ab_skill(env)
    env.write_project({})
    before = (d / "SKILL.md").read_text()
    assert main(["rotate"]) == 1
    assert main(["rotate", "--dry-run"]) == 0
    assert "would switch to variant B" in capsys.readouterr().out
    assert (d / "SKILL.md").read_text() == before


def test_rotate_refuses_multiline_description(env, capsys):
    d = ab_skill(env, description=">\n  folded\n  text")
    before = (d / "SKILL.md").read_text()
    assert main(["rotate"]) == 0
    assert "skipped" in capsys.readouterr().out
    assert (d / "SKILL.md").read_text() == before
    assert not list((env.data / "backups").glob("*"))


def test_rotate_unknown_skill(env):
    ab_skill(env)
    assert main(["rotate", "--skill", "nope"]) == 2


def test_telemetry_stamps_active_variant(env):
    ab_skill(env)
    main(["rotate"])
    env.skill("reviewer")
    row = db.connect().execute("SELECT variant FROM events WHERE outcome='loaded'").fetchone()
    assert row[0] == "B"


def seed_ab(n_a, k_a, n_b, k_b):
    conn = db.connect()
    t0 = time.time() - 10 * 86400
    t1 = t0 + 5 * 86400
    conn.execute("INSERT INTO ab_rotations (skill, variant, description, started_at) VALUES ('reviewer','A','a',?)", (t0,))
    conn.execute("INSERT INTO ab_rotations (skill, variant, description, started_at) VALUES ('reviewer','B','b',?)", (t1,))
    for label, start, n, k in (("A", t0, n_a, k_a), ("B", t1, n_b, k_b)):
        for i in range(n):
            sid = f"{label}{i}"
            db.insert_event(conn, ts=start + 60 + i, session_id=sid, event="UserPromptSubmit", outcome="prompt")
            if i < k:
                db.insert_event(conn, ts=start + 61 + i, session_id=sid, event="PostToolUse", skill="reviewer",
                                outcome="loaded", variant=label)
    conn.commit()
    conn.close()


def test_ab_report_not_enough_data(env, capsys):
    ab_skill(env)
    seed_ab(40, 10, 12, 6)
    assert main(["ab-report"]) == 0
    out = capsys.readouterr().out
    assert "| A | 40 | 10 | 25.0% |" in out and "| B | 12 | 6 | 50.0% |" in out
    assert "Not enough data to call a winner: B has 12 session(s) (need at least 30" in out


def test_ab_report_clear_winner(env, capsys):
    ab_skill(env)
    seed_ab(100, 20, 100, 45)
    main(["ab-report"])
    out = capsys.readouterr().out
    assert "Variant B leads: 45% vs 20% for A" in out


def test_ab_report_no_significant_difference(env, capsys):
    ab_skill(env)
    seed_ab(50, 20, 50, 22)
    main(["ab-report"])
    assert "No clear winner yet" in capsys.readouterr().out


def test_ab_report_single_variant_and_none(env, capsys):
    main(["ab-report"])
    assert "No skills with A/B variants" in capsys.readouterr().out
    ab_skill(env)
    main(["rotate"])
    main(["ab-report"])
    assert "only variant B has been active" in capsys.readouterr().out


def test_p_value():
    assert rotator.two_proportion_p(20, 100, 45, 100) < 0.001
    assert rotator.two_proportion_p(20, 50, 22, 50) > 0.5
    assert rotator.two_proportion_p(0, 0, 1, 1) == 1.0
