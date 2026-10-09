"""The frame pump: renders each zone's layer and pushes it to the board.

One thread, one SDK connection of its own, ~30 frames a second while anything
is animated and idle otherwise. The panel and ``msirgb play`` both drive the
board through this, so they cannot disagree about what an effect looks like.

Only one writer should run at a time. Two pumps pushing different frames to the
same zone make it flicker between them, which is why the panel stops the
background player when it opens (see ``runtime``).
"""

import threading
import time

from .color import DEFAULT_LEDS
from .sdk import OpenRGB, SDKError

FPS = 30


class Engine(threading.Thread):
    def __init__(self, on_status=None, connect_timeout=0.0, dev_id=0):
        super().__init__(daemon=True)
        self.dev_id = dev_id
        self.on_status = on_status or (lambda ok, msg: None)
        self.connect_timeout = connect_timeout
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.t0 = time.monotonic()
        self.layers = {}            # zone index -> Layer
        self.master = 100
        self.zones = []
        self.device = None
        self._dirty = set()
        self._shown = {}
        self._sent = None
        self._sizes = {}

    # ----------------------------------------------------------- control
    def now(self):
        return time.monotonic() - self.t0

    def set_layer(self, zi, layer):
        with self.lock:
            self.layers[zi] = layer.copy()
            self._dirty.add(zi)
        self.wake.set()

    def set_master(self, value):
        with self.lock:
            self.master = int(value)
            self._dirty.update(self.layers)
        self.wake.set()

    def zone_size(self, zi):
        """LEDs a zone will be driven with: explicit, else its current size."""
        layer = self.layers.get(zi)
        if layer and layer.leds:
            return layer.leds
        if 0 <= zi < len(self.zones):
            return self.zones[zi]["leds_count"] or DEFAULT_LEDS
        return DEFAULT_LEDS

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    # ------------------------------------------------------------ thread
    def _connect(self):
        deadline = time.monotonic() + self.connect_timeout
        while not self.stop_event.is_set():
            try:
                api = OpenRGB()
                api.handshake()
                api.load_devices()
                if api.devices:
                    return api
                api.close()
                err = "OpenRGB sees no devices (run `msirgb doctor`)"
            except (OSError, SDKError) as e:
                err = f"cannot reach OpenRGB server: {e}"
            if time.monotonic() >= deadline:
                self.on_status(False, err)
                # Keep trying quietly; the server may still be starting.
                deadline = float("inf")
            self.stop_event.wait(2.0)
        return None

    def run(self):
        while not self.stop_event.is_set():
            api = self._connect()
            if api is None:
                return
            self.device = api.devices[self.dev_id]
            self.zones = self.device["zones"]
            self._sizes = {i: z["leds_count"] for i, z in enumerate(self.zones)}
            # What each zone shows now, so zones nobody has set keep their
            # colours when the whole device is rewritten.
            cols, at = self.device.get("colors") or [], 0
            self._shown = {}
            for i in range(len(self.zones)):
                n = self._sizes[i]
                self._shown[i] = (list(cols[at:at + n])
                                  + [(0, 0, 0)] * n)[:n]
                at += n
            self._sent = None
            with self.lock:
                self._dirty.update(self.layers)
            self.ready.set()
            self.on_status(True, f"Connected to {self.device['name']}")
            try:
                self._pump(api)
            except (OSError, SDKError) as e:
                self.ready.clear()
                self.on_status(False, f"lost the OpenRGB server: {e}")
                self.stop_event.wait(2.0)
            finally:
                api.close()

    def _pump(self, api):
        frame_time = 1.0 / FPS
        while not self.stop_event.is_set():
            start = time.monotonic()
            self.wake.clear()
            with self.lock:
                items = list(self.layers.items())
                dirty, self._dirty = self._dirty, set()
                master = self.master
            t = self.now()
            animating = False
            for zi, layer in items:
                if not 0 <= zi < len(self.zones):
                    continue
                anim = layer.fx.animated
                animating |= anim
                if not anim and zi not in dirty:
                    continue
                n = layer.leds or self._sizes.get(zi) or DEFAULT_LEDS
                if n != self._sizes.get(zi):
                    api.resize_zone(self.dev_id, zi, n)
                    self._sizes[zi] = n
                    self.zones[zi]["leds_count"] = n
                self._shown[zi] = layer.frame(t, n, master)
            # One packet for the whole device per frame. OpenRGB coalesces
            # these, so a slow controller drops frames instead of queueing
            # them, and a change made now shows up on the next frame.
            frame = []
            for zi in range(len(self.zones)):
                frame += self._shown.get(zi, [])
            if frame != self._sent:
                api.update_leds(self.dev_id, frame)
                self._sent = frame
            if animating:
                left = frame_time - (time.monotonic() - start)
                if left > 0:
                    self.stop_event.wait(left)
            else:
                self.wake.wait(1.0)
