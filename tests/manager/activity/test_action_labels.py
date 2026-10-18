from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dbs.manager import transfer
from dbs.manager.accounts.services import (
    account_management_service,
    account_service,
    setup_service,
    sign_in_service,
)
from dbs.manager.applications.services import application_service, discovery_service
from dbs.manager.backups.services import actions as backup_actions
from dbs.manager.envfiles.services import env_file_service
from dbs.manager.files.services import file_service
from dbs.manager.redeploy import deploy as deploys
from dbs.manager.redeploy import services as redeploy
from dbs.manager.redeploy.catalogue import KINDS
from dbs.manager.servers.services import (
    host_key_confirmation_service,
    server_service,
)
from dbs.manager.console import service as console
from dbs.manager.shell import service as shell

ACTIVITY_UI = (
    Path(__file__).resolve().parents[3] / "manager-ui" / "src" / "app" / "features" / "activity"
)
QUOTED_CODE = re.compile(r"'([a-z_]+\.[a-z_]+)'")
ACTION_HOLDERS = (
    backup_actions.Action,
    file_service.Action,
    server_service.Action,
    application_service.Action,
    host_key_confirmation_service.Action,
    account_management_service.Action,
    account_service.Action,
    env_file_service.Action,
)


def recordable() -> set[str]:
    codes = {
        value
        for holder in ACTION_HOLDERS
        for name, value in vars(holder).items()
        if name.isupper()
    }
    codes |= {
        setup_service.SETUP_ACTION,
        sign_in_service.ENROLLED,
        sign_in_service.RECOVERY_CODE_USED,
        discovery_service.DISCOVER,
        transfer.EXPORT,
        transfer.IMPORT,
        redeploy.RUN,
        redeploy.REVERT,
        deploys.DEPLOY,
        shell.OPEN,
        console.RUN,
    }
    codes |= {f"redeploy.{step}" for step in redeploy.MOVE_STEPS}
    codes |= {f"{redeploy.REVERT}_{step}" for step in redeploy.REVERT_STEPS}
    codes |= {
        f"deploy.{step}"
        for step in (*deploys.OPENING_STEPS, *KINDS, deploys.CLOSING_STEP)
    }
    return codes


def offered() -> set[str]:
    source = (ACTIVITY_UI / "data" / "activity.types.ts").read_text(encoding="utf-8")
    listed = source.split("ACTIVITY_ACTIONS", 1)[1].split("];", 1)[0]
    return set(QUOTED_CODE.findall(listed))


def label(bundle: dict, code: str):
    node = bundle["activity"]["actions"]
    for key in code.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, str) and node else None


def test_the_activity_page_offers_every_action_the_manager_records():
    assert sorted(recordable() - offered()) == []


@pytest.mark.parametrize("language", ["en", "ar"])
def test_every_action_the_manager_records_has_a_label(language):
    bundle = json.loads((ACTIVITY_UI / "i18n" / f"{language}.json").read_text(encoding="utf-8"))

    assert sorted(code for code in recordable() if label(bundle, code) is None) == []
