"""Claude, Codex, opencode and Copilot read the same project rules, stability first."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "CLAUDE.md"
COPIES = (ROOT / "AGENTS.md", ROOT / ".github" / "copilot-instructions.md")
COPILOT_REVIEW_READS = 4000


@pytest.mark.parametrize("copy", COPIES, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_every_assistant_reads_the_same_rules(copy):
    assert copy.read_text(encoding="utf-8") == RULES.read_text(encoding="utf-8"), (
        f"copy CLAUDE.md to {copy.relative_to(ROOT).as_posix()}"
    )


def test_the_stability_rules_come_first():
    rules = RULES.read_text(encoding="utf-8")
    start = rules.index("\n## Stability")
    end = rules.index("\n## ", start + 1)

    assert rules.index("\n## ") == start
    assert end <= COPILOT_REVIEW_READS
