from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

ASSETS = Path(__file__).resolve().parent.parent.parent / "ai"

SKILL_DIR = Path(".claude") / "skills" / "django-dbs"

AGENTS_MARKER = "## django-dbs"


def shipped_files():
    return {
        SKILL_DIR / "SKILL.md": ASSETS / "SKILL.md",
        **{
            SKILL_DIR / "reference" / source.name: source
            for source in sorted((ASSETS / "reference").glob("*.md"))
        },
    }


class Command(BaseCommand):
    help = "Install the DBS instructions for AI coding assistants into this project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--agents",
            action="store_true",
            help="Also append the DBS section to the project's AGENTS.md.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Report whether the installed copy matches this version and exit non-zero if not.",
        )
        parser.add_argument(
            "--print",
            action="store_true",
            dest="print_only",
            help="Write the skill to standard output instead of the project.",
        )
        parser.add_argument(
            "--root",
            default=".",
            help="Project directory to install into (default: the working directory).",
        )

    def handle(self, *args, **options):
        if not ASSETS.is_dir():
            raise CommandError(
                f"The DBS instruction assets are missing from {ASSETS}. Reinstall django-dbs."
            )
        if options["print_only"]:
            self.stdout.write((ASSETS / "SKILL.md").read_text(encoding="utf-8"))
            return

        root = Path(options["root"]).expanduser().resolve()
        files = shipped_files()
        if options["check"]:
            self._check(root, files)
            return

        for relative, source in files.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {len(files)} files to {root / SKILL_DIR}.")
        )

        if options["agents"]:
            self._append_agents(root)

    def _check(self, root, files):
        stale = [
            str(relative)
            for relative, source in files.items()
            if not (root / relative).is_file()
            or (root / relative).read_text(encoding="utf-8")
            != source.read_text(encoding="utf-8")
        ]
        if stale:
            raise CommandError(
                "These files are missing or out of date; run 'manage.py dbs ai':\n  "
                + "\n  ".join(stale)
            )
        self.stdout.write(self.style.SUCCESS("The installed DBS instructions are current."))

    def _append_agents(self, root):
        section = (ASSETS / "AGENTS.md").read_text(encoding="utf-8").strip()
        target = root / "AGENTS.md"
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        if AGENTS_MARKER in existing:
            self.stdout.write(f"{target} already has a DBS section; left it alone.")
            return
        separator = "\n\n" if existing.strip() else ""
        target.write_text(existing.rstrip() + separator + section + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Appended the DBS section to {target}."))
