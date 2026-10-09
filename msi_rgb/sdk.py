"""OpenRGB SDK client for MSI Mystic Light motherboards.

Pure standard library. Speaks the OpenRGB SDK wire protocol on port 6742, so
that the CLI and the GTK panel share one implementation.

Protocol reference: OpenRGB ``Documentation/OpenRGBSDK.md``.
"""
import socket
import struct

HOST = "127.0.0.1"
PORT = 6742
MAGIC = b"ORGB"
CLIENT_PROTOCOL = 5          # <=5 keeps device IDs as plain indexes

# Packet IDs (Documentation/OpenRGBSDK.md)
PKT_REQUEST_CONTROLLER_COUNT = 0
PKT_REQUEST_CONTROLLER_DATA = 1
PKT_REQUEST_PROTOCOL_VERSION = 40
PKT_DEVICE_LIST_UPDATED = 100
PKT_DETECTION_STARTED = 101
PKT_DETECTION_PROGRESS = 102
PKT_DETECTION_COMPLETE = 103
PKT_RGBCONTROLLER_RESIZEZONE = 1000
PKT_RGBCONTROLLER_UPDATELEDS = 1050
PKT_RGBCONTROLLER_UPDATEZONELEDS = 1051
PKT_RGBCONTROLLER_UPDATESINGLELED = 1052
PKT_RGBCONTROLLER_UPDATEMODE = 1101

# Zone types (RGBController.h)
ZONE_TYPE = {
    0: "None", 1: "SingleLED", 2: "Linear", 3: "Matrix",
}


class SDKError(RuntimeError):
    pass


class Reader:
    """Cursor over a little-endian packet payload."""

    def __init__(self, data):
        self.d = data
        self.o = 0

    def u8(self):
        v = self.d[self.o]
        self.o += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.o)[0]
        self.o += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.o)[0]
        self.o += 4
        return v

    def s(self):
        n = self.u16()
        v = self.d[self.o:self.o + n].split(b"\0")[0].decode("utf-8", "replace")
        self.o += n
        return v

    def colors(self, n):
        out = []
        for _ in range(n):
            out.append((self.u8(), self.u8(), self.u8()))
            self.u8()  # padding
        return out

    def mode(self, proto):
        # Field order must follow the Mode Data table in the SDK docs exactly.
        m = {"name": self.s()}
        if proto < 6:
            m["value"] = self.i32()
        m["flags"] = self.u32()
        m["speed_min"] = self.u32()
        m["speed_max"] = self.u32()
        if proto >= 3:
            m["brightness_min"] = self.u32()
            m["brightness_max"] = self.u32()
        m["colors_min"] = self.u32()
        m["colors_max"] = self.u32()
        m["speed"] = self.u32()
        if proto >= 3:
            m["brightness"] = self.u32()
        m["direction"] = self.u32()
        m["color_mode"] = self.u32()
        n = self.u16()
        m["num_colors"] = n
        m["colors"] = self.colors(n)
        return m


def build_mode(proto, m):
    """Serialise a Mode Data block in the exact documented field order."""
    name = m["name"].encode() + b"\0"
    out = struct.pack("<H", len(name)) + name
    if proto < 6:
        out += struct.pack("<i", m.get("value", 0))
    out += struct.pack("<I", m.get("flags", 0))
    out += struct.pack("<I", m.get("speed_min", 0))
    out += struct.pack("<I", m.get("speed_max", 255))
    if proto >= 3:
        out += struct.pack("<I", m.get("brightness_min", 0))
        out += struct.pack("<I", m.get("brightness_max", 255))
    out += struct.pack("<I", m.get("colors_min", 0))
    out += struct.pack("<I", m.get("colors_max", 1))
    out += struct.pack("<I", m.get("speed", 128))
    if proto >= 3:
        out += struct.pack("<I", m.get("brightness", 255))
    out += struct.pack("<I", m.get("direction", 0))
    out += struct.pack("<I", m.get("color_mode", 0))
    cols = m.get("colors", [])
    out += struct.pack("<H", len(cols))
    for r, g, b in cols:
        out += struct.pack("<BBBB", r, g, b, 0)
    return out


class OpenRGB:
    def __init__(self, host=HOST, port=PORT):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(10)
        self.proto = 0
        self.devices = []

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    # -- framing ---------------------------------------------------------
    def send(self, dev, pkt, payload=b""):
        hdr = MAGIC + struct.pack("<III", dev, pkt, len(payload))
        self.sock.sendall(hdr + payload)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise SDKError("server closed the connection")
            buf += chunk
        return buf

    def recv(self):
        magic = self._recv_exact(4)
        if magic != MAGIC:
            raise SDKError(f"bad packet magic {magic!r}")
        dev, pkt, size = struct.unpack("<III", self._recv_exact(12))
        return dev, pkt, self._recv_exact(size)

    def recv_id(self, want):
        """Read until a packet with the wanted id arrives, skipping chatter."""
        for _ in range(64):
            dev, pkt, data = self.recv()
            if pkt == want:
                return data
            if pkt in (PKT_DEVICE_LIST_UPDATED, PKT_DETECTION_STARTED,
                       PKT_DETECTION_PROGRESS, PKT_DETECTION_COMPLETE):
                continue
            raise SDKError(f"unexpected packet {pkt} while waiting for {want}")
        raise SDKError("too many unexpected packets")

    # -- session ---------------------------------------------------------
    def handshake(self):
        self.send(0, PKT_REQUEST_PROTOCOL_VERSION, struct.pack("<I", CLIENT_PROTOCOL))
        try:
            data = self.recv_id(PKT_REQUEST_PROTOCOL_VERSION)
            server_max = struct.unpack("<I", data)[0]
        except (SDKError, socket.timeout, struct.error):
            server_max = 0
        self.proto = min(CLIENT_PROTOCOL, server_max)
        return self.proto

    def load_devices(self):
        self.send(0, PKT_REQUEST_CONTROLLER_COUNT)
        raw = self.recv_id(PKT_REQUEST_CONTROLLER_COUNT)
        count = struct.unpack("<I", raw[:4])[0]

        self.devices = []
        for i in range(count):
            payload = struct.pack("<I", self.proto) if self.proto >= 1 else b""
            self.send(i, PKT_REQUEST_CONTROLLER_DATA, payload)
            data = self.recv_id(PKT_REQUEST_CONTROLLER_DATA)
            self.devices.append(self._parse_device(data))
        return self.devices

    def _parse_device(self, data):
        r = Reader(data)
        r.u32()                       # block data_size
        d = {"type": r.u32()}
        for key in ("name", "vendor", "description", "version",
                    "serial", "location"):
            d[key] = r.s()
        n_modes = r.u16()
        d["active_mode"] = r.i32()
        d["modes"] = [r.mode(self.proto) for _ in range(n_modes)]

        n_zones = r.u16()
        d["zones"] = []
        for _ in range(n_zones):
            z = {"name": r.s()}
            # NB: do not inline r.u32() as the get() default -- it would be
            # evaluated eagerly and consume a second field.
            ztype = r.u32()
            z["type"] = ZONE_TYPE.get(ztype, str(ztype))
            z["leds_min"] = r.u32()
            z["leds_max"] = r.u32()
            z["leds_count"] = r.u32()
            matrix_len = r.u16()
            r.o += matrix_len
            if self.proto >= 4:
                for _s in range(r.u16()):
                    seg = {}
                    seg["name"] = r.s()
                    seg["type"] = r.i32()
                    seg["start"] = r.u32()
                    seg["leds"] = r.u32()
                    if self.proto >= 6:
                        r.o += r.u16()      # segment matrix map
                        r.u32()             # segment flags
            if self.proto >= 5:
                z["flags"] = r.u32()
            d["zones"].append(z)

        n_leds = r.u16()
        d["leds"] = []
        for _ in range(n_leds):
            name = r.s()
            value = r.u32() if self.proto < 6 else 0
            d["leds"].append({"name": name, "value": value})
        d["colors"] = r.colors(r.u16())
        return d

    # -- control ---------------------------------------------------------
    def resize_zone(self, dev, zone, size):
        body = struct.pack("<ii", zone, size)
        self.send(dev, PKT_RGBCONTROLLER_RESIZEZONE, body)

    def update_mode(self, dev, mode_idx, mode):
        body = struct.pack("<i", mode_idx) + build_mode(self.proto, mode)
        payload = struct.pack("<I", len(body) + 4) + body
        self.send(dev, PKT_RGBCONTROLLER_UPDATEMODE, payload)

    def update_leds(self, dev, colors):
        """Set every LED on the device in one packet.

        Prefer this for animation. OpenRGB only flags the controller for an
        update and returns, and its update thread writes whatever is newest,
        so frames sent faster than the hardware can take are dropped rather
        than queued. ``update_zone_leds`` instead writes to the device before
        the server reads the next packet (~20 ms each on the MSI controller),
        so a stream of them builds a backlog that delays every later change.
        ``colors`` must cover all LEDs, zones in order.
        """
        body = struct.pack("<H", len(colors)) + b"".join(
            struct.pack("<BBBB", r, g, b, 0) for r, g, b in colors)
        self.send(dev, PKT_RGBCONTROLLER_UPDATELEDS,
                  struct.pack("<I", len(body) + 4) + body)

    def update_zone_leds(self, dev, zone, colors):
        body = struct.pack("<IH", zone, len(colors))
        for r, g, b in colors:
            body += struct.pack("<BBBB", r, g, b, 0)
        self.send(dev, PKT_RGBCONTROLLER_UPDATEZONELEDS,
                  struct.pack("<I", len(body) + 4) + body)
