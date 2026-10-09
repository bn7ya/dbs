import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = """
import json, sys
import django
from django.core.management import call_command, execute_from_command_line

django.setup()
call_command("migrate", run_syncdb=True, verbosity=0)
execute_from_command_line(
    ["manage.py", "dbs", "backup", sys.argv[1], "--passphrase", "core-alone-pass",
     "--kdf-time", "1", "--kdf-memory", "8192"]
)
loaded = sorted(
    name for name in sys.modules
    if name == "rest_framework" or name.startswith(("dbs.manager", "rest_framework."))
)
print(json.dumps(loaded))
"""


def test_a_backup_never_loads_the_manager_or_rest_framework(tmp_path):
    output = tmp_path / "alone.dbs"
    env = dict(os.environ, DJANGO_SETTINGS_MODULE="tests.settings")

    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(output)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert output.stat().st_size > 0
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []
