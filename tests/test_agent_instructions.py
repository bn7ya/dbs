"""Claude, Codex, opencode, Copilot and Gemini read the same project rules, stability first."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "CLAUDE.md"
COPIES = (
    ROOT / "AGENTS.md",
    ROOT / "GEMINI.md",
    ROOT / ".github" / "copilot-instructions.md",
)
COPILOT_REVIEW_READS = 4000
BACKUP_AND_BLOCK_CODE = ("dbs/engine/", "dbs/container/", "dbs/crypto/")


def section_after(rules, heading):
    start = rules.index(f"\n## {heading}")
    end = rules.index("\n## ", start + 1)
    return start, end


@pytest.mark.parametrize("copy", COPIES, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_every_assistant_reads_the_same_rules(copy):
    assert copy.read_text(encoding="utf-8") == RULES.read_text(encoding="utf-8"), (
        f"copy CLAUDE.md to {copy.relative_to(ROOT).as_posix()}"
    )


def test_the_stability_rules_come_first():
    rules = RULES.read_text(encoding="utf-8")
    start, end = section_after(rules, "Stability")

    assert rules.index("\n## ") == start
    assert end <= COPILOT_REVIEW_READS


def test_how_a_change_is_made_follows_stability():
    rules = RULES.read_text(encoding="utf-8")
    _, stability_end = section_after(rules, "Stability")
    start, end = section_after(rules, "How a change is made")
    working_rules = rules[start:end]

    assert start == stability_end
    for folder in BACKUP_AND_BLOCK_CODE:
        assert f"`{folder}`" in working_rules
    for rule in ("Plan, then wait", "Ask, never assume", "Find the target"):
        assert rule in working_rules
