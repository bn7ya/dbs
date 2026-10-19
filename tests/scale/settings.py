from tests.settings import *  # noqa: F401,F403
from tests.settings import INSTALLED_APPS

INSTALLED_APPS = [*INSTALLED_APPS, "tests.scale.scaleapp"]
MIGRATION_MODULES = {"scaleapp": None}
