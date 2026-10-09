"""Allow `python -m msi_rgb` to reach both front ends."""
import sys

from .cli import main as cli_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        from .gui import main as gui_main
        sys.exit(gui_main(sys.argv[2:]))
    sys.exit(cli_main(sys.argv[1:]))