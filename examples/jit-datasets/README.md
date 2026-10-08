# jit-datasets: an example JIT skill

Copy this folder to `.claude/skills/jit-datasets/` (or `~/.claude/skills/`) and
turn on `"jit": {"enabled": true}`. skillwire then runs `generate.py` at each
session start and renders `SKILL.template.md` into `SKILL.md`.

- Change `--url` in `skillwire.json` to point at your own catalog endpoint.
- If the fetch fails, the previous `SKILL.md` is left as it was.
- Try it by hand: `python3 generate.py --url "https://huggingface.co/api/datasets?limit=5&sort=downloads"`
