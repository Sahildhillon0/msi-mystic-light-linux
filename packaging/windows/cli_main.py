"""Entry point for ``msirgb.exe`` (console)."""
import sys

from msi_rgb.cli import main

sys.exit(main(sys.argv[1:]))
