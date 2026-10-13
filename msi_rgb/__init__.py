"""Software control of MSI Mystic Light motherboard lighting on Linux and Windows.

The lighting controller on recent MSI boards (Z890, X870, B850 and friends) is
a USB HID device. OpenRGB can drive it, but skips boards missing from its
compiled-in name table. This package runs OpenRGB's SDK server against the board
and puts a CLI and a GTK4 panel on top. On Windows, where that trick is not
available, ``direct`` drives the controller over HID itself.

The protocol knowledge here comes from reading OpenRGB's source, which is
GPL-3.0; this package is MIT-licensed and credits it.
"""

__version__ = "0.3.0"

from .sdk import OpenRGB, SDKError      # noqa: F401

__all__ = ["OpenRGB", "SDKError", "__version__"]