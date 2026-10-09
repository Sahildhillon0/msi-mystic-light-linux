"""What each zone is showing, named profiles, and where both are saved.

A *layer* is everything needed to light one zone: an effect, its colours,
speed, brightness and LED count. A *lighting* is a master brightness plus one
layer per zone, keyed by the zone's raw name (``"JARGB 3"``) so it survives
zones being re-enumerated in a different order. The key ``"*"`` applies to
every zone without an entry of its own, which is how the built-in profiles
stay board-agnostic.

The current lighting is saved on every change, so ``msirgb play`` can put it
back after the panel closes or at the next login.
"""

import json
import os
import pathlib

from .color import hex_to_rgb, rgb_to_hex
from . import effects

CONFIG_DIR = pathlib.Path(
    os.environ.get("MSI_RGB_CONFIG_DIR", "~/.config/msi-rgb")).expanduser()
LIGHTING_PATH = CONFIG_DIR / "lighting.json"
PROFILES_PATH = CONFIG_DIR / "profiles.json"


class Layer:
    __slots__ = ("effect", "colors", "speed", "brightness", "reverse", "leds")

    def __init__(self, effect="static", colors=None, speed=1.0,
                 brightness=100, reverse=False, leds=0):
        self.effect = effect
        self.colors = list(colors) if colors is not None \
            else list(effects.get(effect).default_colors)
        self.speed = float(speed)
        self.brightness = int(brightness)
        self.reverse = bool(reverse)
        self.leds = int(leds)          # 0: keep whatever the zone is sized to

    def copy(self):
        return Layer(self.effect, list(self.colors), self.speed,
                     self.brightness, self.reverse, self.leds)

    @property
    def fx(self):
        return effects.get(self.effect)

    def frame(self, t, n, master=100):
        out = self.fx.frame(t, n, self.colors, self.speed, self.reverse)
        f = self.brightness * master / 10000.0
        if f >= 0.999:
            return out
        return [effects.scale(c, f) for c in out]

    def to_json(self):
        return {"effect": self.effect,
                "colors": [rgb_to_hex(c) for c in self.colors],
                "speed": round(self.speed, 3), "brightness": self.brightness,
                "reverse": self.reverse, "leds": self.leds}

    @classmethod
    def from_json(cls, d):
        cols = []
        for c in d.get("colors") or []:
            try:
                cols.append(hex_to_rgb(c))
            except (ValueError, AttributeError):
                pass
        eff = d.get("effect", "static")
        if eff not in effects.BY_ID:
            eff = "static"
        return cls(eff, cols or None, d.get("speed", 1.0),
                   d.get("brightness", 100), d.get("reverse", False),
                   d.get("leds", 0))


class Lighting:
    def __init__(self, zones=None, master=100):
        self.zones = dict(zones or {})     # zone name or "*" -> Layer
        self.master = int(master)

    def layer_for(self, name):
        return self.zones.get(name) or self.zones.get("*")

    def to_json(self):
        return {"master": self.master,
                "zones": {k: v.to_json() for k, v in self.zones.items()}}

    @classmethod
    def from_json(cls, d):
        d = d or {}
        return cls({k: Layer.from_json(v)
                    for k, v in (d.get("zones") or {}).items()},
                   d.get("master", 100))


# ---------------------------------------------------------------- built-ins
def _all(layer, master=100):
    return Lighting({"*": layer}, master)


BUILTIN_PROFILES = {
    "Gaming": _all(Layer("rainbow", speed=1.2)),
    "Calm": _all(Layer("aurora", speed=0.6)),
    "Focus": _all(Layer("static", [(0, 184, 252)], brightness=70)),
    "Night": _all(Layer("breathing", [(255, 110, 20)], speed=0.5,
                        brightness=35)),
    "Cyberpunk": _all(Layer("wave", effects.GRADIENTS[2][1], speed=0.8)),
    "Lights off": _all(Layer("static", [(0, 0, 0)])),
}


# --------------------------------------------------------------- disk i/o
def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def load_lighting():
    """(lighting, settings, active profile name) as last saved."""
    d = _read(LIGHTING_PATH)
    settings = {"keep_running": True}
    settings.update(d.get("settings") or {})
    return Lighting.from_json(d.get("lighting")), settings, d.get("profile")


def save_lighting(lighting, settings=None, profile=None):
    old = _read(LIGHTING_PATH)
    _write(LIGHTING_PATH, {
        "lighting": lighting.to_json(),
        "settings": settings if settings is not None
        else old.get("settings", {}),
        "profile": profile,
    })


def user_profiles():
    return {k: Lighting.from_json(v)
            for k, v in (_read(PROFILES_PATH).get("profiles") or {}).items()}


def all_profiles():
    out = {k: v for k, v in BUILTIN_PROFILES.items()}
    out.update(user_profiles())
    return out


def save_profile(name, lighting):
    d = _read(PROFILES_PATH)
    d.setdefault("profiles", {})[name] = lighting.to_json()
    _write(PROFILES_PATH, d)


def delete_profile(name):
    d = _read(PROFILES_PATH)
    if name in (d.get("profiles") or {}):
        del d["profiles"][name]
        _write(PROFILES_PATH, d)
        return True
    return False
