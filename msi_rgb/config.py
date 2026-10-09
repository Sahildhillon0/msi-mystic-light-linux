"""Board configuration: which board is this, and what should OpenRGB be told?

OpenRGB identifies MSI motherboards by an *exact* string comparison of
``"MSI " + <DMI board_name>`` against a table compiled into its binary. A board
that is missing from that table is skipped, and the only symptom in the log is::

    Found Board <your board> but does not have valid config

This module figures out which board we are on, which table entry it would need
to look like, and what the zones are physically wired to.
"""

import json
import os
import pathlib

CONFIG_PATH = pathlib.Path(
    os.environ.get("MSI_RGB_CONFIG", "~/.config/msi-rgb/config.json")
).expanduser()

# Boards we know how to present as something OpenRGB recognises.  The key is
# the board_name the firmware reports (i.e. what DMI shows, without the "MSI "
# prefix that OpenRGB adds); the value is the entry to impersonate.
#
# MSI reused MS-7E32 across two different boards, so the model code on its own
# is not a reliable key -- the marketing name in the string is.
KNOWN_BOARDS = {
    "PRO Z890-A WIFI (MS-7E32)": {
        # Upstream has an entry labelled MS-7E32, but names it as the MAG
        # Tomahawk. The PRO Z890-A WIFI is the board that code belongs to, and
        # both expose the same zone set, so borrowing that entry is correct.
        "spoof_as": "MAG Z890 TOMAHAWK WIFI (MS-7E32)",
        "zone_labels": {
            "JAF": "CPU cooler",
            "JARGB 1": "Header 1 (unused)",
            "JARGB 2": "Graphics card",
            "JARGB 3": "Case fans",
        },
        "default_zone": "JARGB 3",
    },
}

# Fallback labels, so the panel is still readable on an unknown board.
GENERIC_ZONE_LABELS = {
    "JAF": "JAF header",
    "JRGB1": "12V RGB header",
    "JARGB 1": "ARGB header 1",
    "JARGB 2": "ARGB header 2",
    "JARGB 3": "ARGB header 3",
    "JPIPE1": "Pipe / strip",
    "JRAINBOW 1": "Rainbow header 1",
    "JRAINBOW 2": "Rainbow header 2",
}

DMI_BOARD_NAME = "/sys/devices/virtual/dmi/id/board_name"
DMI_BOARD_NAME_ALT = "/sys/class/dmi/id/board_name"


def read_dmi_board_name():
    """The board name the firmware reports, or '' if it cannot be read."""
    for path in (DMI_BOARD_NAME, DMI_BOARD_NAME_ALT):
        try:
            with open(path) as fh:
                name = fh.readline().strip()
            if name:
                return name
        except OSError:
            continue
    return ""


def load_config():
    """User config merged over the built-in board table.

    A config file can override any of: ``spoof_as``, ``zone_labels``,
    ``default_zone``. Setting ``board`` pins the entry so the same file works
    even if DMI is unavailable.
    """
    cfg = {"board": read_dmi_board_name(), "spoof_as": None,
           "zone_labels": dict(GENERIC_ZONE_LABELS), "default_zone": None}

    entry = KNOWN_BOARDS.get(cfg["board"])
    if entry:
        cfg["spoof_as"] = entry["spoof_as"]
        cfg["zone_labels"] = dict(entry["zone_labels"])
        cfg["default_zone"] = entry.get("default_zone")

    try:
        user = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return cfg

    if user.get("board") and not KNOWN_BOARDS.get(cfg["board"]):
        entry = KNOWN_BOARDS.get(user["board"])
        if entry:
            cfg["spoof_as"] = entry["spoof_as"]
            cfg["zone_labels"] = dict(entry["zone_labels"])
            cfg["default_zone"] = entry.get("default_zone")

    for key in ("spoof_as", "default_zone"):
        if user.get(key):
            cfg[key] = user[key]
    if user.get("zone_labels"):
        cfg["zone_labels"].update(user["zone_labels"])
    return cfg


def zone_label(raw, index, labels=None):
    """Human label for a zone, falling back to the raw name."""
    raw = (raw or "").strip()
    table = labels if labels is not None else load_config()["zone_labels"]
    return table.get(raw, f"{raw or 'zone'} #{index}")


def default_zone_index(zones, labels=None):
    """Index of the zone most likely to be the one the user wants."""
    cfg_labels = labels if labels is not None else load_config()["zone_labels"]
    wanted = load_config().get("default_zone")
    for i, z in enumerate(zones):
        if (z.get("name") or "").strip() == wanted:
            return i
    # Otherwise prefer an ARGB header, which is what fans plug into.
    for i, z in enumerate(zones):
        if "ARGB" in (z.get("name") or ""):
            return i
    return len(zones) - 1 if zones else 0


def write_example_config(path=None):
    """Write a starter config so `spoof_as` can be tweaked without docs."""
    path = pathlib.Path(path or CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    path.write_text(json.dumps({
        "_comment": "Set spoof_as to a board name from OpenRGB's table, or "
                    "leave null to use the built-in entry for your board.",
        "board": read_dmi_board_name(),
        "spoof_as": None,
        "zone_labels": {},
        "default_zone": None,
    }, indent=2) + "\n")
    return True