import subprocess
import sys

MODULES = (
    "canvas",
    "dialogs",
    "fields",
    "keys",
    "layout",
    "lists",
    "logo",
    "palette",
    "terminal",
    "text",
    "theme",
)
SCRIPT = f"""
import sys
import dbs.manager
before = set(sys.modules)
for name in {MODULES!r}:
    __import__("dbs.manager.menu.kit." + name)
added = sorted(set(sys.modules) - before)
print([name for name in added if name.split(".")[0] in ("dbs", "django", "rest_framework", "paramiko") and not name.startswith("dbs.manager.menu")])
"""


def test_the_kit_loads_nothing_of_django_or_the_manager_but_itself():
    ran = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, check=True
    )

    assert ran.stdout.strip() == "[]"
