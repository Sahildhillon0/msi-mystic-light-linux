"""One diagnostics report, shared by ``msirgb doctor`` and the panel.

The panel's Diagnostics window shows this text so nobody has to open a
terminal to find out why the board is OFFLINE.
"""

import contextlib
import io
import platform
import sys

from . import __version__
from .engine import LOG_PATH
from .sdk import backend_name
from .state import CONFIG_DIR


def report(log_lines=25):
    """Run the doctor for the active backend and return everything as text."""
    from .cli import cmd_doctor

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            rc = cmd_doctor()
        except Exception as e:                      # noqa: BLE001
            rc = -1
            print(f"doctor crashed: {type(e).__name__}: {e}")
    head = [
        f"MSI Mystic Light {__version__} -- {platform.platform()}",
        f"python {sys.version.split()[0]}, backend: {backend_name()}"
        f"{' (frozen build)' if getattr(sys, 'frozen', False) else ''}",
        f"settings: {CONFIG_DIR}",
        "",
    ]
    out = head + buf.getvalue().rstrip().splitlines()
    out += ["", f"result: {'OK' if rc == 0 else f'problem (code {rc})'}"]
    try:
        tail = LOG_PATH.read_text(encoding="utf-8",
                                  errors="replace").splitlines()[-log_lines:]
    except OSError:
        tail = []
    if tail:
        out += ["", f"--- last lines of {LOG_PATH} ---"] + tail
    return rc, "\n".join(out) + "\n"
