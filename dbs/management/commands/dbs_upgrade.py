from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from dbs import extras
from dbs.container import FORMAT_VERSION
from dbs.upgrade import (
    ACTION,
    FIXED,
    OK,
    WARN,
    abandonment_phrase,
    confirm_abandonment,
    confirm_install,
    convert_backup,
    existing_conversion,
    installed_version,
    is_editable_install,
    is_newer,
    is_system_interpreter,
    is_version,
    latest_release,
    pinned_install_command,
    read_backup_states,
    release_exists,
    requirement_files,
    run_steps,
)

MARKS = {OK: "ok", ACTION: "todo", WARN: "warn", FIXED: "done"}


class Command(BaseCommand):
    help = "Bring this project up to date with the installed version of DBS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Report without changing anything; exit non-zero if anything is outstanding.",
        )
        parser.add_argument(
            "--self",
            action="store_true",
            dest="self_update",
            help="Install one exact django-dbs release into this environment: the newest "
            "on PyPI, or the one --to names. Shows the pinned pip command and asks first.",
        )
        parser.add_argument(
            "--to",
            default=None,
            metavar="VERSION",
            dest="target_version",
            help="The django-dbs version --self installs, instead of the newest release.",
        )
        parser.add_argument(
            "--system-python",
            action="store_true",
            dest="system_python",
            help="Let --self change an interpreter outside a virtual environment.",
        )
        parser.add_argument(
            "--backups",
            default=None,
            metavar="DIR",
            help="Also read the backups in DIR and convert any written in an older format.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Run the pip command --self shows without asking.",
        )
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Do not contact PyPI to look for a newer release.",
        )

    def handle(self, *args, **options):
        check_only = options["check"]
        if options.get("target_version") and not options["self_update"]:
            raise CommandError("--to names the version --self installs; add --self.")
        self.stdout.write(self.style.MIGRATE_HEADING(f"DBS {installed_version()}"))

        report = run_steps(apply_fixes=not check_only)
        for finding in report.findings:
            self._render(finding)

        self._release(options, check_only)

        failures = []
        if options["backups"]:
            failures = self._backups(Path(options["backups"]).expanduser(), check_only)

        self.stdout.write("")
        outstanding = report.outstanding
        if failures and check_only:
            raise CommandError(
                f"{len(failures)} backup(s) are not readable by DBS {installed_version()} "
                "as they stand; re-run without --check to convert them."
            )
        if failures:
            raise CommandError(
                f"{len(failures)} backup(s) cannot be read by this version; "
                "nothing was changed or deleted."
            )
        if not outstanding:
            self.stdout.write(self.style.SUCCESS("This project is up to date."))
            return
        if check_only and report.blocked:
            raise CommandError(
                f"{len(outstanding)} item(s) need attention; re-run without --check to "
                "apply what can be applied automatically."
            )
        self.stdout.write(
            self.style.WARNING(f"{len(outstanding)} item(s) need you to act; see above.")
        )

    def _render(self, finding):
        mark = MARKS[finding.level]
        style = {
            OK: self.style.SUCCESS,
            FIXED: self.style.SUCCESS,
            WARN: self.style.WARNING,
            ACTION: self.style.ERROR,
        }[finding.level]
        self.stdout.write(f"{style('[' + mark + ']'):<8} {finding.step:<18} {finding.message}")
        if finding.remedy:
            self.stdout.write(f"         {' ' * 18} {finding.remedy}")

    def _line(self, mark, message):
        style = {
            "ok": self.style.SUCCESS,
            "done": self.style.SUCCESS,
            "warn": self.style.WARNING,
        }[mark]
        self.stdout.write(f"{style('[' + mark + ']'):<8} {'release':<18} {message}")

    def _detail(self, message):
        self.stdout.write(f"         {' ' * 18} {message}")

    def _release(self, options, check_only):
        if options["self_update"] and not check_only:
            self._self_update(options)
            return
        if options["offline"]:
            return
        current = installed_version()
        latest = latest_release()
        if latest is None:
            self._line("warn", "could not reach PyPI to check for a newer version")
            return
        if not is_newer(latest, current):
            self._line("ok", f"{current} is the latest release")
            return
        self._line("warn", f"{latest} is available; you have {current}")
        self._detail(
            f"pin django-dbs=={latest} in your requirements or lock file and reinstall"
            "   (or --self)"
        )

    def _target_version(self, options):
        requested = options.get("target_version")
        if requested:
            if not is_version(requested):
                raise CommandError(f"{requested!r} is not a django-dbs version number.")
            if not options["offline"] and release_exists(requested) is False:
                raise CommandError(f"django-dbs {requested} is not on PyPI.")
            return requested
        if options["offline"]:
            raise CommandError("--self --offline needs the version to install: add --to VERSION.")
        latest = latest_release()
        if latest is None or not is_version(latest):
            raise CommandError(
                "Could not reach PyPI to find the newest release; name one with --to VERSION."
            )
        return latest

    def _self_update(self, options):
        current = installed_version()
        target = self._target_version(options)
        if target == current:
            self._line("ok", f"django-dbs {current} is already installed")
            return
        if is_editable_install():
            self._line("warn", f"django-dbs {target} is available; you have {current}")
            self._detail("refusing --self on a source checkout; update it with git")
            return
        if is_system_interpreter() and not options["system_python"]:
            raise CommandError(
                "--self will not change an interpreter outside a virtual environment, "
                "whose packages the operating system or other programs may share. Update "
                "your project's requirements and reinstall, or add --system-python if this "
                "interpreter is yours to change."
            )
        command = pinned_install_command(target, extras.installed())
        self._line("warn", f"django-dbs {target} replaces {current} with:")
        self._detail(shlex.join(command))
        files = [path.name for path in requirement_files(Path.cwd())]
        where = " and ".join(files) if files else "your project's requirements or lock file"
        self._detail(
            f"Pin django-dbs=={target} in {where} too, so every deploy installs the "
            "version you tested here."
        )
        if not options["yes"] and not confirm_install():
            raise CommandError(
                "Nothing was installed. Answer the question at a terminal, or add --yes "
                "to run the command above."
            )
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise CommandError(f"pip failed: {result.stderr.strip().splitlines()[-1:]}")
        self._line("done", f"installed django-dbs {target}; re-run this command to finish")

    def _backups(self, directory, check_only):
        if not directory.is_dir():
            raise CommandError(f"No such directory: {directory}")
        states = read_backup_states(directory)
        if not states:
            self.stdout.write(
                f"{self.style.SUCCESS('[ok]'):<8} {'backups':<18} "
                f"no .dbs files in {directory}"
            )
            return []

        stale = [s for s in states if not s.current and not s.unreadable]
        broken = [s for s in states if s.unreadable]
        for state in stale:
            state.converted_to = existing_conversion(state.path)
            state.converted_earlier = state.converted_to is not None
            if state.converted_earlier:
                self.stdout.write(
                    f"{self.style.SUCCESS('[ok]'):<8} {'backups':<18} "
                    f"{state.path.name} was converted earlier to {state.converted_to.name}"
                )
        stale = [s for s in stale if not s.converted_earlier]

        if not stale and not broken:
            self.stdout.write(
                f"{self.style.SUCCESS('[ok]'):<8} {'backups':<18} "
                f"{len(states)} backup(s), all at format version {FORMAT_VERSION} "
                "or converted to it"
            )
            return []

        if check_only:
            for state in stale:
                self.stdout.write(
                    f"{self.style.ERROR('[todo]'):<8} {'backups':<18} "
                    f"{state.path.name} is format version {state.version} and needs converting"
                )
            for state in broken:
                self.stdout.write(
                    f"{self.style.ERROR('[todo]'):<8} {'backups':<18} "
                    f"{state.path.name}: {state.error}"
                )
            return stale + broken

        for state in stale:
            converted = convert_backup(state, self._passphrase())
            if converted.error:
                broken.append(converted)
            else:
                self.stdout.write(
                    f"{self.style.SUCCESS('[done]'):<8} {'backups':<18} "
                    f"{state.path.name} -> {converted.converted_to.name} "
                    "(the original is untouched)"
                )

        if not broken:
            return []

        self.stdout.write("")
        self.stdout.write(
            self.style.ERROR(
                f"{len(broken)} backup(s) cannot be read by DBS {installed_version()}:"
            )
        )
        for state in broken:
            self.stdout.write(f"  {state.path}")
            self.stdout.write(f"    {state.error}")
        self.stdout.write("")
        self.stdout.write(
            "You do not have to give these up. Install the version that wrote them in a\n"
            "separate environment and restore from there:\n"
            "\n"
            "    python -m venv /tmp/dbs-old\n"
            '    /tmp/dbs-old/bin/pip install "django-dbs==<the older version>"\n'
            "\n"
            "Nothing here has been deleted, moved or overwritten, and this command will\n"
            "not do so. Continuing means accepting that these files stay unreadable by\n"
            "this version, which may mean losing data that exists nowhere else."
        )
        if check_only:
            return broken

        if not confirm_abandonment(len(broken)):
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Not confirmed at an interactive terminal, so nothing was accepted. "
                    f'A person must type "{abandonment_phrase(len(broken))}" here.'
                )
            )
            return broken

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"Accepted: {len(broken)} backup(s) left unreadable by this version. "
                "The files are still on disk."
            )
        )
        return []

    def _passphrase(self):
        from dbs._cli import resolve_read_passphrase

        return resolve_read_passphrase(None)
