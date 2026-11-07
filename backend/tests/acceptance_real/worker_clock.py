"""Install the acceptance clock inside Taskiq worker subprocesses."""

import os
from pathlib import Path

from tests.acceptance_real.clock_server import _install_clock

_install_clock(Path(os.environ["PROJECT1_ACCEPTANCE_CLOCK_FILE"]))
