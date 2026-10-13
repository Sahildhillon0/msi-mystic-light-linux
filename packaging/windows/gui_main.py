"""Entry point for ``MSI Mystic Light.exe`` (windowed).

Also runs ``play`` without a console: the panel hands animations to a
background copy of itself, and the login Run value starts it the same way.
"""
import sys
import traceback

from msi_rgb.engine import log


def _excepthook(kind, value, tb):
    # Windowed exe: no console, so an uncaught error would vanish silently.
    log("uncaught: " + "".join(traceback.format_exception(kind, value, tb)))
    sys.__excepthook__(kind, value, tb)


sys.excepthook = _excepthook

if len(sys.argv) > 1 and sys.argv[1] == "play":
    from msi_rgb.cli import main as cli_main
    sys.exit(cli_main(sys.argv[1:]))

from msi_rgb.gui import main

sys.exit(main(sys.argv[1:]))
