from __future__ import annotations

import io
import posixpath
import re
import secrets
import time
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any, Optional
from uuid import UUID

from django.conf import settings

from dbs.manager.activity import job_leases
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.models import Application
from dbs.manager.applications.repositories import ApplicationRepository
from dbs.manager.applications.services import facts as found_facts
from dbs.manager.applications.services import ApplicationService
from dbs.manager.applications.services.discovery_service import (
    Discovery,
    settings_of,
)
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.services.backup_plan_service import BackupPlanService
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.conf import data_dir
from dbs.manager.redeploy import restoring
from dbs.manager.relocation import catalogue, database, inventory, packages
from dbs.manager.relocation.exceptions import (
    DatabaseCredentialsUnknown,
    DatabaseExists,
    DatabaseIsTheSources,
    MoveBlocked,
    MovedApplicationNotFound,
    PackageInstallFailed,
    PrivilegedCommandFailed,
    RepositoryKeyMismatch,
    TargetFileExists,
)
from dbs.manager.relocation.inventory import Choice, Side, Survey
from dbs.manager.relocation.privileged import Privileged, SudoPasswords, sudo_mode
from dbs.manager.relocation.requirements import installed_versions, requirements_of
from dbs.manager.relocation.systems import DEBIAN, System
from dbs.manager.relocation.transfer import (
    FILE,
    FOLDER,
    IMAGE,
    PODMAN_VOLUME,
    VOLUME,
    Carrier,
    Item,
)
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.servers.services.connection_service import STAGING_FOLDER
from dbs.manager.servers.services.pythons import quiet
from dbs.models import AuditEvent

ACTION = "relocation.move"
PREFIX = "relocation."
PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
SKIPPED = "skipped"
DONE_BEFORE = "done_before"
PLAN_STEPS = ("connect", "inventory", "evaluate")
PREPARE_STEPS = ("sudo_check", "repositories", "packages", "engine_setup", "services", "users", "recheck")
APPLICATION_STEPS = (
    "source_backup",
    "carry_folder",
    "carry_extra",
    "carry_bind",
    "carry_image",
    "carry_volume",
    "rewrite_env",
    "backup_dir",
    "python",
    "database_create",
    "networks",
    "start",
    "register",
    "migrate",
    "restore",
    "install_units",
    "install_sites",
    "final_check",
    "copy_plans",
)
PROGRESS_EVERY = 5.0
OWNER_LINE = re.compile(r"^([0-9]{1,10}):([0-9]{1,10}):([0-7]{3,4})$")
FINGERPRINT_LINE = re.compile(r"^fpr:+([0-9A-F]{40}):", re.M)
SUBORDINATE_IDS = "/etc/subuid"
SUBORDINATE_BYTES = 256 * 1024
DOCKER_KEY_FOLDER = "/etc/apt/keyrings"
PG_VERSION_FILE = "/var/lib/pgsql/data/PG_VERSION"
NGINX_AVAILABLE = "/etc/nginx/sites-available"
NGINX_ENABLED = "/etc/nginx/sites-enabled"
NGINX_CONF = "/etc/nginx/conf.d"
OUTPUT_TAIL = 500
RESUMED_BLOCKERS = frozenset(
    {
        "target_folder_not_empty",
        "file_exists_on_target",
        "image_exists_on_target",
        "volume_exists_on_target",
        "unit_exists_on_target",
        "site_exists_on_target",
        "container_exists_on_target",
        "name_taken",
        "port_in_use",
    }
)

Detail = dict[str, Any]
Step = Callable[[Detail, Detail], Optional[Detail]]


def planned(steps: tuple[str, ...] | list[str], status: str = PENDING) -> list[Detail]:
    return [{"step": step, "status": status} for step in steps]


def plan_phase() -> Detail:
    return {"phase": "plan", "status": PENDING, "steps": planned(PLAN_STEPS)}


def step_key(phase: Detail, step: Detail) -> tuple[str, str, str]:
    return (phase.get("application") or phase["phase"], step["step"], step.get("key", ""))


def application_steps(plan: Detail) -> list[Detail]:
    kind = plan["kind"]
    steps: list[Detail] = [{"step": "source_backup"}]
    if plan["folder"].get("path"):
        steps.append({"step": "carry_folder", "key": plan["folder"]["target"], "bytes": plan["folder"].get("bytes")})
    steps += [
        {"step": "carry_extra", "key": extra["target"], "bytes": extra.get("bytes")}
        for extra in plan["extras"]
    ]
    steps += [
        {"step": "carry_bind", "key": bind["target"], "bytes": bind.get("bytes")}
        for bind in plan["binds"]
        if bind["selected"]
    ]
    steps += [
        {"step": "carry_image", "key": image["ref"], "bytes": image.get("bytes")}
        for image in plan["images"]
        if not image["on_target"]
    ]
    steps += [
        {"step": "carry_volume", "key": volume["name"], "bytes": volume.get("bytes")}
        for volume in plan["volumes"]
        if volume["selected"]
    ]
    if plan["env"].get("rewrite"):
        steps.append({"step": "rewrite_env", "key": plan["env"]["rewrite"]})
    if plan["backup_dir"].get("create"):
        steps.append({"step": "backup_dir", "key": plan["backup_dir"]["target"]})
    if kind == Application.Kind.HOST:
        steps.append({"step": "python"})
        if plan["database"].get("placement") == "host_package":
            steps.append({"step": "database_create"})
    if kind == Application.Kind.CONTAINER and plan["networks"]:
        steps.append({"step": "networks"})
    if kind != Application.Kind.HOST:
        steps.append({"step": "start"})
    steps.append({"step": "register"})
    shared = plan["database"].get("action") == "shared"
    steps.append({"step": "migrate", "status": SKIPPED if shared else PENDING})
    steps.append({"step": "restore", "status": SKIPPED if shared else PENDING})
    if kind == Application.Kind.HOST:
        if plan["units"]:
            steps.append({"step": "install_units"})
        if plan["sites"]:
            steps.append({"step": "install_sites"})
    steps.append({"step": "final_check"})
    steps.append({"step": "copy_plans", "status": PENDING if plan["copy_plans"] else SKIPPED})
    for step in steps:
        step.setdefault("status", PENDING)
        if step.get("bytes") is None:
            step.pop("bytes", None)
    return steps


def prepare_steps(inventory_detail: Detail) -> list[Detail]:
    package_plan = inventory_detail["packages"]
    plans = inventory_detail["applications"]
    needs = set(inventory_detail["needs"])
    runs = {
        "sudo_check": inventory_detail["needs_sudo"]["target"] or inventory_detail["needs_sudo"]["source"],
        "repositories": bool(package_plan["repositories"]),
        "packages": bool(package_plan["packages"] or package_plan["modules"]),
        "engine_setup": bool(needs & {"docker", "podman"}),
        "services": bool(package_plan["services"]),
        "users": any(plan["users"] for plan in plans),
        "recheck": bool(package_plan["packages"]),
    }
    return [
        {"step": step, "status": PENDING if runs[step] else SKIPPED} for step in PREPARE_STEPS
    ]


def still_blocking(blocker: Detail, done: set[tuple[str, str, str]]) -> bool:
    if blocker["code"] not in RESUMED_BLOCKERS:
        return True
    return not done


class Move:
    def __init__(self, job: AuditEvent, detail: Detail, passwords: SudoPasswords) -> None:
        self.job = job
        self.detail = detail
        self.passwords = passwords
        self.actor = job.actor
        self.jobs = ActivityService(None)
        self.connections = ServerConnectionService(self.actor)
        servers = ServerRepository()
        self.source_server = servers.find(UUID(detail["source_server"]))
        self.target_server = servers.find(UUID(detail["target_server"]))
        self.stack = ExitStack()
        self.target_stack = ExitStack()
        self.source: Side | None = None
        self.target: Side | None = None
        self.source_root: Privileged | None = None
        self.target_root: Privileged | None = None
        self.carrier: Carrier | None = None
        self.last_progress = 0.0
        self.done: set[tuple[str, str, str]] = {
            tuple(key) for key in detail.get("done_before", [])
        }

    def run(self) -> None:
        try:
            index = 0
            while index < len(self.detail["phases"]):
                phase = self.detail["phases"][index]
                if self.detail.get("rehearsal") and phase["phase"] != "plan":
                    break
                self.run_phase(phase)
                index += 1
        finally:
            self.target_stack.close()
            self.stack.close()
            if self.carrier is not None:
                self.detail["leftovers"] = sorted(set(self.detail.get("leftovers", []) + self.carrier.leftovers))

    def run_phase(self, phase: Detail) -> None:
        phase["status"] = RUNNING
        self.progress()
        for step in phase["steps"]:
            if step["status"] == SKIPPED:
                continue
            if step_key(phase, step) in self.done:
                step["status"] = SKIPPED
                step["reason"] = DONE_BEFORE
                continue
            step["status"] = RUNNING
            self.detail["current"] = {"phase": phase.get("name") or phase["phase"], "step": step["step"], "key": step.get("key", "")}
            self.progress(force=True)
            job_leases.hold(self.job.pk)
            try:
                with ActivityService(self.actor).track(
                    f"{PREFIX}{step['step']}",
                    subject=self.subject(phase),
                    target=self.label(phase, step),
                ) as entry:
                    outcome = self.work(phase, step)
                    entry.detail = outcome or {}
            except BaseException:
                step["status"] = FAILED
                phase["status"] = FAILED
                self.detail["failed_step"] = {"phase": phase.get("name") or phase["phase"], "step": step["step"], "key": step.get("key", "")}
                for later_phase in self.detail["phases"]:
                    for later in later_phase["steps"]:
                        if later["status"] == PENDING:
                            later["status"] = SKIPPED
                self.detail.pop("current", None)
                raise
            step["status"] = SKIPPED if outcome is None else SUCCEEDED
            if outcome and outcome.get("warning"):
                step["warning"] = outcome["warning"]
            self.progress(force=True)
        phase["status"] = SUCCEEDED
        self.detail.pop("current", None)
        self.progress(force=True)

    def progress(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last_progress >= PROGRESS_EVERY:
            self.last_progress = now
            self.jobs.progress(self.job.pk, self.detail)

    def moved(self, key: str, sent: int, total: int | None) -> None:
        current = self.detail.get("current") or {}
        current.update({"bytes": sent, "total": total})
        self.detail["current"] = current
        if time.monotonic() - self.last_progress >= PROGRESS_EVERY:
            job_leases.hold(self.job.pk)
        self.progress()

    def subject(self, phase: Detail) -> Any:
        if phase.get("target_application"):
            found = ApplicationRepository().find(UUID(phase["target_application"]))
            if found is not None:
                return found
        return self.target_server

    def label(self, phase: Detail, step: Detail) -> str:
        name = phase.get("name") or f"{self.source_server.name} → {self.target_server.name}"
        return f"{name}: {step['key']}" if step.get("key") else name

    def work(self, phase: Detail, step: Detail) -> Detail | None:
        handler = getattr(self, f"step_{step['step']}")
        return handler(phase, step)

    def plan_of(self, phase: Detail) -> Detail:
        return next(
            plan
            for plan in self.detail["inventory"]["applications"]
            if plan["application"] == phase["application"]
        )

    def source_application(self, phase: Detail) -> Application:
        return ApplicationService(self.actor).get(UUID(phase["application"]))

    def step_connect(self, phase: Detail, step: Detail) -> Detail:
        source_remote = self.stack.enter_context(self.connections.open(self.source_server))
        self.source = inventory.learn(Side(source_remote, self.source_server, sudo_mode(source_remote)))
        self.open_target()
        return {
            "source": self.source.describe()["system"],
            "target": self.target.describe()["system"] if self.target else None,
        }

    def open_target(self) -> None:
        self.target_stack.close()
        self.target_stack = ExitStack()
        remote = self.target_stack.enter_context(self.connections.open(self.target_server))
        self.target = inventory.learn(Side(remote, self.target_server, sudo_mode(remote)))
        self.source_root = Privileged(self.source.remote, self.source.mode, self.passwords.source)
        self.target_root = Privileged(remote, self.target.mode, self.passwords.target)
        if self.carrier is not None:
            self.target_root.verified = True
        staging = posixpath.join(self.target.home, STAGING_FOLDER, f"relocation-{self.job.pk}")
        leftovers = self.carrier.leftovers if self.carrier is not None else []
        self.carrier = Carrier(
            source=self.source_root,
            target=self.target_root,
            spool=data_dir() / "relocation" / str(self.job.pk),
            staging=staging,
            source_ids=(self.source.uid, self.source.gid),
            target_ids=(self.target.uid, self.target.gid),
            progress=self.moved,
            selinux=self.target.selinux.lower() == "enforcing",
            leftovers=leftovers,
        )

    def choices(self) -> list[Choice]:
        service = ApplicationService(self.actor)
        return [
            Choice(
                application=service.get(UUID(choice["application"])),
                name=choice["name"],
                folder=choice["folder"],
                skip_volumes=frozenset(choice.get("skip_volumes", [])),
                copy_plans=choice.get("copy_plans", True),
            )
            for choice in self.detail["choices"]
        ]

    def step_inventory(self, phase: Detail, step: Detail) -> Detail:
        found = Survey(self.source, self.target, self.connections).collect(self.choices())
        self.detail["inventory"] = found
        previous = {p.get("application") or p["phase"]: p for p in self.detail.get("previous_phases", [])}
        phases = [self.detail["phases"][0], {"phase": "prepare", "status": PENDING, "steps": prepare_steps(found)}]
        for plan in found["applications"]:
            earlier = previous.get(plan["application"], {})
            phases.append(
                {
                    "phase": "application",
                    "application": plan["application"],
                    "name": plan["name"],
                    "target_name": plan["target_name"],
                    "status": PENDING,
                    "steps": application_steps(plan),
                    **{
                        key: earlier[key]
                        for key in ("backup", "target_application")
                        if earlier.get(key)
                    },
                }
            )
        self.detail["phases"] = phases
        return {"applications": len(found["applications"]), "bytes": found["totals"]["bytes"]}

    def step_evaluate(self, phase: Detail, step: Detail) -> Detail:
        blockers = [
            blocker
            for blocker in inventory.blocked(self.detail["inventory"])
            if still_blocking(blocker, self.done)
        ]
        self.detail["blockers"] = blockers
        if blockers:
            raise MoveBlocked()
        return {"blockers": 0}

    def step_sudo_check(self, phase: Detail, step: Detail) -> Detail:
        needs = self.detail["inventory"]["needs_sudo"]
        if needs["target"]:
            self.target_root.verify()
        if needs["source"] and self.source.mode != catalogue.MISSING:
            self.source_root.verify()
        return {"target": self.target.mode, "source": self.source.mode}

    def system(self) -> System:
        assert self.target is not None and self.target.system is not None
        return self.target.system

    def staged(self, content: bytes, name: str, mode: int = 0o600) -> str:
        self.target.remote.ensure_folder(self.carrier.staging)
        entry = self.target.remote.write_new(
            io.BytesIO(content), self.carrier.staging, f"{name}-{secrets.token_hex(4)}", mode=mode
        )
        return entry.path

    def unstage(self, path: str) -> None:
        self.carrier.remove_staged(path)

    def step_repositories(self, phase: Detail, step: Detail) -> Detail:
        system = self.system()
        added = []
        for need in self.detail["inventory"]["needs"]:
            if need != "docker":
                continue
            repository = packages.docker_repository(system)
            key = self.fetched_key(repository)
            try:
                if system.family == DEBIAN:
                    self.install_apt_key(key)
                else:
                    self.target_root.run(catalogue.rpm_import(key))
            finally:
                self.unstage(key)
            self.install_file(repository.content.encode(), repository.path, mode=0o644, keep_existing=True)
            added.append(repository.path)
        return {"repositories": added}

    def fetched_key(self, repository: packages.Repository) -> str:
        self.target.remote.ensure_folder(self.carrier.staging)
        key = posixpath.join(self.carrier.staging, f"docker-key-{secrets.token_hex(4)}")
        self.target_root.run(catalogue.fetch_key(repository.key_url, key))
        home = posixpath.join(self.carrier.staging, f"gnupg-{secrets.token_hex(4)}")
        self.target.remote.ensure_folder(home)
        shown = self.target_root.run(catalogue.key_fingerprints(key, home), check=False)
        if repository.fingerprint not in FINGERPRINT_LINE.findall(shown.stdout):
            self.unstage(key)
            raise RepositoryKeyMismatch()
        return key

    def install_apt_key(self, key: str) -> None:
        if not self.target.remote.exists(DOCKER_KEY_FOLDER):
            self.target_root.run(catalogue.make_folder(DOCKER_KEY_FOLDER, "0755", "0", "0"))
        destination = packages.DOCKER_KEYRING
        if self.target.remote.lexists(destination):
            home = posixpath.join(self.carrier.staging, f"gnupg-{secrets.token_hex(4)}")
            self.target.remote.ensure_folder(home)
            shown = self.target_root.run(catalogue.key_fingerprints(destination, home), check=False)
            if packages.DOCKER_DEBIAN_KEY not in FINGERPRINT_LINE.findall(shown.stdout):
                raise RepositoryKeyMismatch()
            return
        self.target_root.run(catalogue.make_readable(key))
        self.target_root.run(catalogue.copy_new(key, destination))

    def install_file(self, content: bytes, destination: str, *, mode: int, keep_existing: bool = False) -> bool:
        remote = self.target.remote
        if remote.lexists(destination):
            current = quiet(remote.read_small, destination, len(content) + 1)
            if current == content or keep_existing:
                return False
            raise TargetFileExists()
        staged = self.staged(content, posixpath.basename(destination), mode=mode)
        try:
            self.target_root.run(catalogue.copy_new(staged, destination))
            if quiet(remote.read_small, destination, len(content) + 1) != content:
                raise TargetFileExists()
        finally:
            self.unstage(staged)
        return True

    def step_packages(self, phase: Detail, step: Detail) -> Detail:
        plan = self.detail["inventory"]["packages"]
        timeout = settings.BACKUP_EXEC_TIMEOUT
        try:
            if self.system().family == DEBIAN:
                self.target_root.run(catalogue.apt_update(), timeout=timeout)
                if plan["packages"]:
                    self.target_root.run(catalogue.apt_install(plan["packages"]), timeout=timeout)
            else:
                for stream in plan["modules"]:
                    self.target_root.run(catalogue.dnf_module_enable(stream), timeout=timeout)
                if plan["packages"]:
                    self.target_root.run(catalogue.dnf_install(plan["packages"]), timeout=timeout)
        except PrivilegedCommandFailed as exc:
            raise PackageInstallFailed(output=exc.output) from exc
        return {"packages": plan["packages"], "modules": plan["modules"]}

    def step_engine_setup(self, phase: Detail, step: Detail) -> Detail:
        needs = set(self.detail["inventory"]["needs"])
        done: Detail = {}
        user = self.target.user
        if "docker" in needs:
            self.target_root.run(catalogue.systemctl("enable", "docker", now=True))
            if self.target.uid != "0":
                self.target_root.run(catalogue.add_to_group(user, "docker"))
                done["group"] = "docker"
        if "podman" in needs and self.target.uid != "0":
            ids = quiet(self.target.remote.read_small, SUBORDINATE_IDS, SUBORDINATE_BYTES) or b""
            if not any(line.startswith(f"{user}:") for line in ids.decode(errors="replace").splitlines()):
                self.target_root.run(catalogue.add_subordinate_ids(user))
                done["subordinate_ids"] = True
            self.target_root.run(catalogue.enable_linger(user))
            done["linger"] = True
        self.open_target()
        return done

    def step_services(self, phase: Detail, step: Detail) -> Detail:
        started = []
        system = self.system()
        for service in self.detail["inventory"]["packages"]["services"]:
            if service == "docker":
                continue
            if service == "postgresql" and system.family != DEBIAN and not self.target.remote.exists(PG_VERSION_FILE):
                self.target_root.run(catalogue.postgresql_init())
            self.target_root.run(catalogue.systemctl("enable", service, now=True))
            started.append(service)
        return {"services": started}

    def step_users(self, phase: Detail, step: Detail) -> Detail:
        added = []
        for plan in self.detail["inventory"]["applications"]:
            for user in plan["users"]:
                if user not in added and not inventory.user_exists(self.target, user):
                    self.target_root.run(catalogue.add_system_user(user))
                    added.append(user)
        return {"users": added}

    def step_recheck(self, phase: Detail, step: Detail) -> Detail:
        checked = ServerService(self.actor).check(self.target_server.pk)
        return {"status": checked.last_check_status}

    def step_source_backup(self, phase: Detail, step: Detail) -> Detail:
        source = self.source_application(phase)
        locks = TakeLock()
        if not locks.hold(source.pk, self.job.pk):
            raise locks.refusal(source.pk)
        try:
            file = BackupRunService().back_up(self.job, source, keep_remote=0)
        finally:
            locks.release(source.pk, self.job.pk)
        phase["backup"] = str(file.pk)
        return {"backup": str(file.pk), "size": file.size}

    def step_carry_folder(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        folder = plan["folder"]
        root = folder.get("unreadable", False) and self.source.mode != catalogue.MISSING
        return self.carrier.carry(
            Item(
                key=step["key"],
                kind=FOLDER,
                read=catalogue.tar_create(folder["path"], folder["excluded"], root=root),
                target=folder["target"],
                numeric=plan["kind"] != Application.Kind.HOST,
                size=folder.get("bytes"),
                owner=self.owner_of(folder["path"], root),
            )
        )

    def owner_of(self, folder: str, root: bool) -> tuple[str, str, str]:
        found = self.source_root.run(catalogue.folder_owner(folder, root=root), check=False)
        matched = OWNER_LINE.match(found.stdout.strip()) if found.ok else None
        return (matched.group(1), matched.group(2), matched.group(3)) if matched else ()

    def step_carry_extra(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        extra = next(item for item in plan["extras"] if item["target"] == step["key"])
        parent, name = posixpath.split(extra["path"])
        return self.carrier.carry(
            Item(
                key=step["key"],
                kind=FILE,
                read=catalogue.tar_create_member(parent, name, root=self.source.mode != catalogue.MISSING),
                target=extra["target"],
                numeric=False,
            )
        )

    def step_carry_bind(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        bind = next(item for item in plan["binds"] if item["target"] == step["key"])
        root = bind.get("unreadable", False) and self.source.mode != catalogue.MISSING
        return self.carrier.carry(
            Item(
                key=step["key"],
                kind=FOLDER,
                read=catalogue.tar_create(bind["source"], root=root),
                target=bind["target"],
                numeric=True,
                size=bind.get("bytes"),
                owner=self.owner_of(bind["source"], root),
            )
        )

    def step_carry_image(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        image = next(item for item in plan["images"] if item["ref"] == step["key"])
        return self.carrier.carry(
            Item(
                key=step["key"],
                kind=IMAGE,
                read=catalogue.image_save(plan["engine"], image["ref"]),
                target=image["ref"],
                engine=plan["engine"],
                expected_id=image.get("id", ""),
                size=image.get("bytes"),
            )
        )

    def step_carry_volume(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        volume = next(item for item in plan["volumes"] if item["name"] == step["key"])
        labels = (
            (("com.docker.compose.project", volume["project"]), ("com.docker.compose.volume", volume["volume"]))
            if volume.get("project")
            else ()
        )
        if plan["engine"] == "podman":
            return self.carrier.carry(
                Item(
                    key=step["key"],
                    kind=PODMAN_VOLUME,
                    read=catalogue.volume_export(volume["name"]),
                    target=volume["name"],
                    engine="podman",
                    labels=labels,
                    size=volume.get("bytes"),
                )
            )
        found = self.source.run(catalogue.volume_mountpoint(plan["engine"], volume["name"]))
        mountpoint = found.stdout.strip() if found is not None and found.ok else ""
        return self.carrier.carry(
            Item(
                key=step["key"],
                kind=VOLUME,
                read=catalogue.tar_create(mountpoint, root=self.source.uid != "0"),
                target=volume["name"],
                engine=plan["engine"],
                labels=labels,
                size=volume.get("bytes"),
            )
        )

    def step_backup_dir(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        target = plan["backup_dir"]["target"]
        if self.target.remote.exists(target):
            return {"exists": target}
        self.target_root.run(catalogue.make_folder(target, "0750", self.target.uid, self.target.gid))
        return {"created": target}

    def target_application(self, phase: Detail, *, folder_only: bool = False) -> Application:
        if phase.get("target_application") and not folder_only:
            return ApplicationService(self.actor).get(UUID(phase["target_application"]))
        plan = self.plan_of(phase)
        source = self.source_application(phase)
        python = source.python_path
        if plan["kind"] == Application.Kind.HOST and plan["python"].get("venv"):
            python = inventory.mapped(python, plan["python"]["venv"], plan["python"]["target_venv"])
        return Application(
            server=self.target_server,
            name=plan["target_name"],
            kind=source.kind,
            engine=source.engine,
            compose_project=source.compose_project,
            compose_service=source.compose_service,
            compose_files=list(source.compose_files),
            container_name=source.container_name,
            project_dir=plan["folder"]["target"],
            workdir=source.workdir,
            python_path=python,
            manage_path=source.manage_path,
            settings_module=source.settings_module,
            mounts=source.mounts,
            backup_passphrase_sealed=source.backup_passphrase_sealed,
        )

    def step_python(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        python = plan["python"]
        if python["action"] != "rebuild":
            return {"action": python["action"]}
        source = self.source_application(phase)
        frozen = self.source.run(catalogue.pip_freeze(source.python_path))
        if frozen is None or not frozen.ok:
            raise PrivilegedCommandFailed(output=(frozen.stderr if frozen else "")[-OUTPUT_TAIL:])
        listed = self.source.run(catalogue.pip_list(source.python_path))
        lines, left_out = requirements_of(
            frozen.stdout,
            installed_versions(listed.stdout if listed is not None and listed.ok else ""),
            self.reachable_on_target,
        )
        requirements = self.staged(("\n".join(lines) + "\n").encode(), "requirements.txt")
        interpreter = packages.python_command(self.system(), python.get("version", ""))
        try:
            self.target_root.run(catalogue.make_venv(interpreter, python["target_venv"]))
            venv_python = posixpath.join(python["target_venv"], "bin", "python")
            self.target_root.run(
                catalogue.pip_install(venv_python, requirements, plan["folder"]["target"]),
                timeout=settings.BACKUP_EXEC_TIMEOUT,
            )
        finally:
            self.unstage(requirements)
        return {"action": "rebuild", "packages": len(lines), "left_out": left_out}

    def reachable_on_target(self, local: str) -> bool:
        return local.startswith("/") and bool(quiet(self.target.remote.exists, local, default=False))

    def step_database_create(self, phase: Detail, step: Detail) -> Detail:
        application = self.target_application(phase, folder_only=True)
        profile = self.connections.dbs_profile(application)
        result = self.target.remote.run_manage(profile, ["shell", "-c", database.DATABASE_SECRET])
        found = database.credentials_of(result.stdout) if result.ok else None
        if found is None:
            raise DatabaseCredentialsUnknown()
        if found.vendor == database.POSTGRESQL:
            exists = self.target_root.run(catalogue.postgresql_query(database.postgres_exists(found.name)))
            if exists.stdout.strip():
                raise DatabaseExists()
            role = self.target_root.run(catalogue.postgresql_query(database.postgres_role_exists(found.user)))
            self.target_root.feed(
                catalogue.postgresql_shell(),
                database.postgres_statements(found, create_role=not role.stdout.strip()),
            )
        elif found.vendor == database.MYSQL:
            exists = self.target_root.run(catalogue.mysql_query(database.mysql_exists(found.name)))
            if exists.stdout.strip():
                raise DatabaseExists()
            self.target_root.feed(catalogue.mysql_shell(), database.mysql_statements(found))
        else:
            raise DatabaseCredentialsUnknown()
        return {"vendor": found.vendor, "database": found.name, "user": found.user}

    def step_networks(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        made = []
        for network in plan["networks"]:
            exists = self.target_root.run(catalogue.network_exists(plan["engine"], network), check=False)
            if not exists.ok:
                self.target_root.run(catalogue.network_create(plan["engine"], network))
                made.append(network)
        return {"networks": made}

    def step_start(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        application = self.target_application(phase, folder_only=True)
        if plan["kind"] == Application.Kind.COMPOSE:
            target = inventory.compose_target(application)
            self.target_root.run(
                catalogue.compose_up(target.argv(), plan["services"], plan["folder"]["target"]),
                timeout=settings.BACKUP_EXEC_TIMEOUT,
            )
            return {"services": plan["services"]}
        started = []
        rows = {inventory.name_of(row): row for row in inventory.inspected(self.source, plan["engine"])}
        ordered = sorted(plan["containers"], key=lambda item: not item["companion"])
        for container in ordered:
            row = rows.get(container["name"])
            if row is None:
                continue
            image = inventory.image_config(self.source, plan["engine"], container["image"])
            lines = inventory.env_lines(row, image)
            env_file = self.staged(("\n".join(lines) + "\n").encode(), f"{container['name']}.env") if lines else ""
            try:
                spec = inventory.spec_of(plan["engine"], row, image, env_file=env_file)
                self.target_root.run(catalogue.container_run(spec), timeout=settings.BACKUP_EXEC_TIMEOUT)
            finally:
                if env_file:
                    self.unstage(env_file)
            started.append(container["name"])
        return {"containers": started}

    def step_register(self, phase: Detail, step: Detail) -> Detail:
        if phase.get("target_application"):
            return {"application": phase["target_application"]}
        plan = self.plan_of(phase)
        source = self.source_application(phase)
        report = Discovery(self.target.remote, source.deployment).run(plan["folder"]["target"])
        candidate = next(
            (
                found
                for found in report["candidates"]
                if found["kind"] == source.kind
                and (source.kind != Application.Kind.COMPOSE or found["compose_service"] == source.compose_service)
                and (source.kind != Application.Kind.CONTAINER or found["container_name"] == source.container_name)
            ),
            None,
        )
        if candidate is None:
            raise MovedApplicationNotFound()
        fields = settings_of(candidate, plan["target_name"])
        created = ApplicationService(self.actor).create(
            server=self.target_server.pk,
            found_by_discovery=True,
            discovered=True,
            deployment=dict(source.deployment),
            backup_passphrase=self.connections.backup_passphrase(source),
            **fields,
        )
        phase["target_application"] = str(created.pk)
        self.detail.setdefault("created_applications", []).append(
            {"source": str(source.pk), "target": str(created.pk), "name": created.name}
        )
        return {"application": str(created.pk), "name": created.name}

    def step_rewrite_env(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        remote = self.target.remote
        found = remote.read_small(step["key"], inventory.ENV_BYTES)
        text = found.decode("utf-8", errors="replace")
        changed = inventory.rewritten(text, plan["folder"]["path"], plan["folder"]["target"])
        if changed == text:
            return {"rewritten": False}
        permissions = remote.lstat(step["key"]).permissions
        remote.replace_file(step["key"], changed.encode(), mode=(permissions or 0o600) & 0o777)
        return {"rewritten": True}

    def own_database(self, phase: Detail) -> None:
        if self.source_server.host_key != self.target_server.host_key:
            return
        said = self.plan_of(phase)["database"]
        target = self.target_application(phase)
        found = found_facts.database_facts(self.target.remote, self.connections.dbs_profile(target))
        if not found:
            raise DatabaseCredentialsUnknown()
        if all(found.get(key, "") == said.get(key, "") for key in ("vendor", "host", "name")):
            raise DatabaseIsTheSources()

    def step_migrate(self, phase: Detail, step: Detail) -> Detail:
        target = self.target_application(phase)
        self.own_database(phase)
        result = restoring.manage(target, self.actor, "migrate", "--noinput")
        if not result.ok:
            raise PrivilegedCommandFailed(output=(result.stderr or result.stdout).strip()[-OUTPUT_TAIL:])
        return {"migrated": True}

    def step_restore(self, phase: Detail, step: Detail) -> Detail:
        target = self.target_application(phase)
        self.own_database(phase)
        file = restoring.stored(phase["backup"])
        return restoring.restore_file(file, target, self.actor, flush=True, dry_run=False)

    def step_install_units(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        source_folder, target_folder = plan["folder"]["path"], plan["folder"]["target"]
        installed = []
        user_units = False
        for unit in plan["units"]:
            text = quiet(self.source.remote.read_small, unit["path"], 64 * 1024)
            if text is None:
                continue
            content = inventory.rewritten(text.decode("utf-8", errors="replace"), source_folder, target_folder).encode()
            if unit["scope"] == "system":
                self.install_file(content, unit["target_path"], mode=0o644)
            else:
                folder = posixpath.join(self.target.home, ".config/systemd/user")
                self.target.remote.ensure_folder(folder)
                self.target.remote.write_new(io.BytesIO(content), folder, unit["name"], mode=0o644)
                user_units = True
            installed.append(unit["name"])
        system_units = [unit["name"] for unit in plan["units"] if unit["scope"] == "system"]
        if system_units:
            self.target_root.run(catalogue.systemctl("daemon-reload"))
            for name in system_units:
                if name.endswith((".service", ".socket", ".timer")):
                    self.target_root.run(catalogue.systemctl("enable", name, now=True))
        if user_units:
            self.target_root.run(catalogue.enable_linger(self.target.user))
            runtime = f"/run/user/{self.target.uid}"
            self.target_root.run(catalogue.systemctl_user("daemon-reload", "", runtime))
            for unit in plan["units"]:
                if unit["scope"] == "user":
                    self.target_root.run(catalogue.systemctl_user("enable", unit["name"], runtime, now=True))
        return {"units": installed}

    def step_install_sites(self, phase: Detail, step: Detail) -> Detail:
        plan = self.plan_of(phase)
        source_folder, target_folder = plan["folder"]["path"], plan["folder"]["target"]
        remote = self.target.remote
        debian_layout = remote.exists(NGINX_AVAILABLE)
        enabled, disabled = [], []
        for site in plan["sites"]:
            text = quiet(self.source.remote.read_small, site["path"], 64 * 1024)
            if text is None:
                continue
            content = inventory.rewritten(text.decode("utf-8", errors="replace"), source_folder, target_folder).encode()
            ready = site["enabled"] and not site["certificates_missing"]
            name = site["name"]
            if debian_layout:
                available = posixpath.join(NGINX_AVAILABLE, name)
                self.install_file(content, available, mode=0o644)
                if ready:
                    link = posixpath.join(NGINX_ENABLED, name)
                    self.target_root.run(catalogue.link_new(available, link))
                    if not self.target_root.run(catalogue.nginx_test(), check=False).ok:
                        self.target_root.run(catalogue.remove_own_link(link))
                        ready = False
            else:
                conf = name if name.endswith(".conf") else f"{name}.conf"
                destination = posixpath.join(NGINX_CONF, conf if ready else f"{conf}.disabled")
                self.install_file(content, destination, mode=0o644)
                if ready and not self.target_root.run(catalogue.nginx_test(), check=False).ok:
                    self.target_root.run(catalogue.place(destination, f"{destination}.disabled"))
                    ready = False
            (enabled if ready else disabled).append(name)
        if enabled:
            self.target_root.run(catalogue.systemctl("enable", "nginx", now=True))
            self.target_root.run(catalogue.systemctl("reload", "nginx"))
        return {"enabled": enabled, "disabled": disabled}

    def step_final_check(self, phase: Detail, step: Detail) -> Detail:
        target = self.target_application(phase)
        checked = ApplicationService(self.actor).check(target.pk)
        outcome: Detail = {"status": checked.last_check_status}
        if checked.last_check_status != Application.CheckStatus.OK:
            outcome["warning"] = "target_check_problem"
        return outcome

    def step_copy_plans(self, phase: Detail, step: Detail) -> Detail:
        source = self.source_application(phase)
        target = self.target_application(phase)
        service = BackupPlanService(self.actor)
        copied, left = [], []
        for plan in service.list(source.pk):
            if plan.kind != BackupPlan.Kind.DBS:
                left.append(plan.name)
                continue
            service.create(
                application=target.pk,
                kind=plan.kind,
                name=plan.name,
                interval_minutes=plan.interval_minutes,
                keep=plan.keep,
                keep_remote=plan.keep_remote,
                time_zone=plan.time_zone,
                enabled=False,
            )
            copied.append(plan.name)
        outcome: Detail = {"copied": copied}
        if left:
            outcome["left"] = left
            outcome["warning"] = "plan_not_copied"
        return outcome

