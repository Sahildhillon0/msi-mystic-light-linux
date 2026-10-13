"""Entry point for ``MSI Mystic Light.exe`` (windowed).

Also runs ``play`` without a console: the panel hands animations to a
background copy of itself, and the login Run value starts it the same way.
"""
import sys

if len(sys.argv) > 1 and sys.argv[1] == "play":
    from msi_rgb.cli import main as cli_main
    sys.exit(cli_main(sys.argv[1:]))

from msi_rgb.gui import main

sys.exit(main(sys.argv[1:]))
