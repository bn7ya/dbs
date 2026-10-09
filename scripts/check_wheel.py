from __future__ import annotations

import re
import sys
import zipfile

BUNDLE = "dbs/manager/static/dbs_manager/"
REQUIRED = (
    re.compile(re.escape(BUNDLE) + r"index\.html$"),
    re.compile(re.escape(BUNDLE) + r"main-[A-Za-z0-9_-]+\.js$"),
    re.compile(re.escape(BUNDLE) + r"media/fa-solid-900-[A-Za-z0-9_-]+\.woff2$"),
    re.compile(re.escape(BUNDLE) + r"3rdpartylicenses\.txt$"),
    re.compile(r"dbs/manager/templates/dbs_manager/missing_ui\.html$"),
    re.compile(r"dbs/migrations/0004_schedule_lease\.py$"),
)
FORBIDDEN = (b"kit.fontawesome.com", b"primeng")


def problems(path):
    found = []
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        for pattern in REQUIRED:
            if not any(pattern.search(name) for name in names):
                found.append(f"missing {pattern.pattern}")
        for name in names:
            if not name.startswith(BUNDLE) or not name.endswith((".js", ".html", ".css")):
                continue
            content = wheel.read(name)
            for marker in FORBIDDEN:
                if marker in content:
                    found.append(f"{name} mentions {marker.decode()}")
    return found


def main(paths):
    if not paths:
        print("usage: check_wheel.py dist/django_dbs-*.whl", file=sys.stderr)
        return 2
    failures = 0
    for path in paths:
        for problem in problems(path):
            print(f"{path}: {problem}", file=sys.stderr)
            failures += 1
    if not failures:
        print("wheel carries the manager interface")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
