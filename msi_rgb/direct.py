"""Drive the MSI Mystic Light controller over HID, without OpenRGB.

Windows needs this: OpenRGB reads the board name from WMI there, so the
``LD_PRELOAD`` shim that gets an unlisted board past its name table has no
Windows equivalent. This module speaks the controller's protocol itself and
presents the same interface as ``sdk.OpenRGB``, so the engine, CLI and panel
do not care which one they are given.

The byte sequences are copied from what OpenRGB 1.0rc3 sends to this board,
captured with an ioctl logger, not from reading its source alone::

    GET  0x52  (200)            probe, as OpenRGB's detector does
    GET  0x50  (290)            "enables subsequent reads"
    SET  0x51  (761, zeroed)    detector probe
    GET  0x51  (500)            read settings
    SET  0x50  (290)            configuration: headers on, direct mode
    SET  0x51  (727) per zone   0x51 09 <hdr0> <hdr1> 00 00 f0 + 240 x RGB

Only the 761-byte controller (USB 0db0:0076) is handled.

Talks to hidapi through ctypes, the same library OpenRGB uses, so it behaves
the same on Windows (``hidapi.dll``) and Linux (``libhidapi-hidraw.so.0``).
"""

import ctypes
import ctypes.util
import json
import os
import pathlib
import sys

from .color import DEFAULT_LEDS
from .sdk import SDKError

VID, PID = 0x0DB0, 0x0076
LEDS_MAX = 240

# (zone name, hdr0, hdr1) in the order OpenRGB lists them for this board.
ZONES = [("JAF", 0x08, 0x00), ("JARGB 1", 0x04, 0x00),
         ("JARGB 2", 0x04, 0x01), ("JARGB 3", 0x04, 0x02)]

_ROW_ON = bytes.fromhex("09ff000000ff000000ffffffff031578")
_ROW_OFF = bytes(15) + b"\x1e"
_ROW_ALL = bytes.fromhex("09ff000000ff000000ffffffff03951e")
# JARGB 1-3 and JAF on, the other 13 rows off, then "select all".
CONFIG = b"\x50" + _ROW_ON * 4 + _ROW_OFF * 13 + _ROW_ALL + b"\x00"
assert len(CONFIG) == 290

CACHE_PATH = pathlib.Path(os.environ.get(
    "MSI_RGB_CONFIG_DIR", "~/.config/msi-rgb")).expanduser() / "direct.json"


class _DeviceInfo(ctypes.Structure):
    pass


_DeviceInfo._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(_DeviceInfo)),
]


def _candidates():
    here = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    if sys.platform == "win32":
        names = ["hidapi.dll", "libhidapi-0.dll"]
        return [str(here / n) for n in names] + names
    found = ctypes.util.find_library("hidapi-hidraw")
    return [n for n in ("libhidapi-hidraw.so.0", found,
                        "libhidapi-hidraw.so") if n]


def _load_hidapi():
    errors = []
    for name in _candidates():
        try:
            lib = ctypes.CDLL(name)
        except OSError as e:
            errors.append(f"{name}: {e}")
            continue
        lib.hid_init.restype = ctypes.c_int
        lib.hid_enumerate.restype = ctypes.POINTER(_DeviceInfo)
        lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
        lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_DeviceInfo)]
        lib.hid_open_path.restype = ctypes.c_void_p
        lib.hid_open_path.argtypes = [ctypes.c_char_p]
        lib.hid_close.argtypes = [ctypes.c_void_p]
        lib.hid_error.restype = ctypes.c_wchar_p
        lib.hid_error.argtypes = [ctypes.c_void_p]
        lib.loaded_from = name
        for fn in (lib.hid_send_feature_report, lib.hid_get_feature_report):
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.hid_init()
        return lib
    raise SDKError("hidapi library not found (" + "; ".join(errors) + ")")


def hid_error(lib, dev=None):
    """hidapi's text for the last failure (``dev=None``: the last open)."""
    try:
        return lib.hid_error(dev) or ""
    except (AttributeError, OSError, ValueError):
        return ""


# On Windows a feature-report read must be given a buffer of the collection's
# full feature length (761 here), or the HID class driver rejects it before
# anything reaches the board. Linux takes the exact sizes OpenRGB uses.
FEATURE_LEN = 761


def find_paths(lib=None):
    """HID paths of the controller, best match first."""
    lib = lib or _load_hidapi()
    head = lib.hid_enumerate(VID, PID)
    found, node = [], head
    while node:
        d = node.contents
        # Windows lists one path per top-level collection; OpenRGB drives
        # the vendor one (usage page 0xFF00). Linux has a single hidraw node.
        found.append((d.usage_page != 0xFF00, d.path))
        node = d.next
    if head:
        lib.hid_free_enumeration(head)
    return [p for _, p in sorted(found)]


class Direct:
    """Same surface as ``sdk.OpenRGB`` for the parts this project uses."""

    def __init__(self, trace=None):
        self.lib = _load_hidapi()
        paths = find_paths(self.lib)
        if not paths:
            raise SDKError("no MSI Mystic Light controller (USB 0db0:0076) "
                           "found")
        self.dev = None
        errors = []
        for path in paths:
            self.dev = self.lib.hid_open_path(path)
            if self.dev:
                self.path = path.decode(errors="replace")
                break
            errors.append(hid_error(self.lib) or "no reason given")
        if not self.dev:
            raise SDKError("found the controller but could not open it: "
                           + "; ".join(errors) + ". Close MSI Center / "
                           "Mystic Light, SignalRGB and OpenRGB and retry.")
        self.proto = 0
        self.devices = []
        cache = self._read_cache()
        self.counts = [int(cache.get("counts", {}).get(z, DEFAULT_LEDS))
                       for z, _, _ in ZONES]
        self.colors = [[tuple(c) for c in cache.get("colors", {}).get(z, [])]
                       for z, _, _ in ZONES]
        self._sent = [None] * len(ZONES)
        try:
            self._init_controller(trace)
        except SDKError:
            self.close()
            raise

    # -- hidapi ------------------------------------------------------------
    def _set(self, data):
        n = self.lib.hid_send_feature_report(self.dev, bytes(data), len(data))
        if n < 0:
            raise SDKError(f"HID write of report 0x{data[0]:02x} "
                           f"({len(data)} bytes) failed: "
                           f"{hid_error(self.lib, self.dev) or 'no reason given'}")
        return n

    def _get(self, report_id, size):
        if sys.platform == "win32":
            size = max(size, FEATURE_LEN)
        buf = ctypes.create_string_buffer(bytes([report_id]), size)
        n = self.lib.hid_get_feature_report(self.dev, buf, size)
        return buf.raw[:n] if n > 0 else b""

    def _init_controller(self, trace=None):
        # Reads only matter to the firmware as part of the sequence; their
        # contents are not needed, and a failed read is not fatal.
        trace = trace or (lambda msg: None)
        for step in (("get", 0x52, 200), ("get", 0x50, 290),
                     ("set", b"\x51" + bytes(760)), ("get", 0x51, 500),
                     ("set", CONFIG)):
            if step[0] == "get":
                got = self._get(step[1], step[2])
                trace(f"GET 0x{step[1]:02x}: {len(got)} bytes"
                      + ("" if got else
                         f" ({hid_error(self.lib, self.dev) or 'failed'})"))
            else:
                n = self._set(step[1])
                trace(f"SET 0x{step[1][0]:02x}: {n} bytes")

    # -- cache: the board cannot be read back, so remember what we set ----
    def _read_cache(self):
        try:
            return json.loads(CACHE_PATH.read_text())
        except (OSError, ValueError):
            return {}

    def _write_cache(self):
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps({
                "counts": {z: n for (z, _, _), n in zip(ZONES, self.counts)},
                "colors": {z: [list(c) for c in cols]
                           for (z, _, _), cols in zip(ZONES, self.colors)},
            }))
        except OSError:
            pass

    # -- the sdk.OpenRGB surface -------------------------------------------
    def handshake(self):
        return self.proto

    def load_devices(self):
        zones, flat = [], []
        for i, (name, _, _) in enumerate(ZONES):
            n = self.counts[i]
            zones.append({"name": name, "type": "Linear", "leds_min": 0,
                          "leds_max": LEDS_MAX, "leds_count": n})
            flat += (self.colors[i] + [(0, 0, 0)] * n)[:n]
        self.devices = [{
            "type": 0, "name": "MSI MYSTIC LIGHT", "vendor": "MSI",
            "description": "MSI Mystic Light (direct HID)", "version": "",
            "serial": "", "location": "HID: " + self.path,
            "active_mode": 0,
            "modes": [{"name": "Direct", "value": 0, "flags": 0,
                       "num_colors": 0, "colors": []}],
            "zones": zones,
            "leds": [{"name": f"{z['name']} LED {j}", "value": 0}
                     for z in zones for j in range(z["leds_count"])],
            "colors": flat,
        }]
        return self.devices

    def resize_zone(self, dev, zone, size):
        if 0 <= zone < len(ZONES):
            self.counts[zone] = max(0, min(LEDS_MAX, int(size)))

    def update_mode(self, dev, mode_idx, mode):
        pass                    # Direct is the only mode

    def update_leds(self, dev, colors):
        at = 0
        for i, n in enumerate(self.counts):
            self.colors[i] = list(colors[at:at + n])
            at += n
        self._flush()

    def update_zone_leds(self, dev, zone, colors):
        if 0 <= zone < len(ZONES):
            self.colors[zone] = list(colors)
        self._flush()

    def _flush(self):
        for i, (_, hdr0, hdr1) in enumerate(ZONES):
            n = self.counts[i]
            body = bytearray(LEDS_MAX * 3)
            for j, (r, g, b) in enumerate(self.colors[i][:n]):
                body[3 * j:3 * j + 3] = bytes((r, g, b))
            pkt = bytes((0x51, 0x09, hdr0, hdr1, 0, 0, LEDS_MAX)) + body
            if pkt != self._sent[i]:
                self._set(pkt)
                self._sent[i] = pkt

    def close(self):
        if self.dev:
            self._write_cache()
            self.lib.hid_close(self.dev)
            self.dev = None
