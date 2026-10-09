"""Lighting effects, as pure functions of time.

Every effect is ``frame(t, n, colors, speed, reverse) -> [(r, g, b)] * n``.
Nothing here keeps state between frames, so the same call drives the board,
the panel's live preview and the little preview on each effect card, and they
all agree. Effects that look random (twinkle, fire) get their randomness from
a hash of (LED, time slot) instead of a generator for the same reason.

The board itself only exposes "Direct" mode, so it never animates on its own:
whatever runs these frames has to push them, ~30 times a second.
"""

import math

from .color import cycle, hsv_to_rgb, hex_to_rgb

BLACK = (0, 0, 0)


# ------------------------------------------------------------------ helpers
def _rand(*keys):
    """Deterministic pseudo-random float in [0, 1) from integer keys."""
    h = 2166136261
    for k in keys:
        h = ((h ^ (int(k) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0x5BD1E995) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 4294967296.0


def _noise(i, x):
    """Smooth 1-D value noise for LED ``i`` at position ``x``."""
    k = math.floor(x)
    f = x - k
    f = f * f * (3 - 2 * f)
    return _rand(i, k) * (1 - f) + _rand(i, k + 1) * f


def lerp(a, b, f):
    f = 0.0 if f < 0 else 1.0 if f > 1 else f
    return (int(a[0] + (b[0] - a[0]) * f),
            int(a[1] + (b[1] - a[1]) * f),
            int(a[2] + (b[2] - a[2]) * f))


def scale(c, f):
    f = 0.0 if f < 0 else 1.0 if f > 1 else f
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


def palette(colors, x, wrap=True):
    """Colour at position ``x`` along a smooth blend of ``colors``.

    With ``wrap`` the last colour blends back into the first, so a scrolling
    palette has no seam.
    """
    if not colors:
        return BLACK
    if len(colors) == 1:
        return colors[0]
    if wrap:
        x = (x % 1.0) * len(colors)
        i = int(x)
        return lerp(colors[i % len(colors)], colors[(i + 1) % len(colors)],
                    x - i)
    x = min(max(x, 0.0), 1.0) * (len(colors) - 1)
    i = min(int(x), len(colors) - 2)
    return lerp(colors[i], colors[i + 1], x - i)


def _pos(i, n, reverse):
    p = i / n if n else 0.0
    return 1.0 - p if reverse else p


# ------------------------------------------------------------------ effects
def fx_static(t, n, colors, speed, reverse):
    return cycle(colors, n)


def fx_custom(t, n, colors, speed, reverse):
    # Freestyle: ``colors`` is one entry per LED; pad with black.
    out = list(colors[:n])
    return out + [BLACK] * (n - len(out))


def fx_gradient(t, n, colors, speed, reverse):
    return [palette(colors, _pos(i, max(n - 1, 1), reverse), wrap=False)
            for i in range(n)]


def fx_spectrum(t, n, colors, speed, reverse):
    c = hsv_to_rgb(t * 36.0 * speed * (-1 if reverse else 1))
    return [c] * n


def fx_rainbow(t, n, colors, speed, reverse):
    off = t * 72.0 * speed
    sign = 1 if reverse else -1
    return [hsv_to_rgb(sign * off + 360.0 * i / n) for i in range(n)]


def fx_breathing(t, n, colors, speed, reverse):
    period = 4.0 / speed
    k, f = divmod(t / period, 1.0)
    level = (1 - math.cos(2 * math.pi * f)) / 2
    c = colors[int(k) % len(colors)]
    return [scale(c, level ** 1.6)] * n


def fx_fade(t, n, colors, speed, reverse):
    return [palette(colors, t * 0.25 * speed / len(colors))] * n


def fx_wave(t, n, colors, speed, reverse):
    shift = t * 0.35 * speed
    return [palette(colors, _pos(i, n, reverse) - shift) for i in range(n)]


def fx_chase(t, n, colors, speed, reverse):
    step = int(t * 8 * speed)
    out = []
    for i in range(n):
        j = (n - 1 - i) if reverse else i
        on = (j - step) % 3 == 0
        out.append(colors[(j // 3) % len(colors)] if on else BLACK)
    return out


def fx_comet(t, n, colors, speed, reverse):
    lap = t * 0.6 * speed
    head = (lap % 1.0) * n
    c = colors[int(lap) % len(colors)]
    tail = max(n * 0.35, 3)
    out = []
    for i in range(n):
        j = (n - 1 - i) if reverse else i
        d = (head - j) % n
        out.append(scale(c, (1 - d / tail) ** 2) if d < tail else BLACK)
    return out


def fx_scanner(t, n, colors, speed, reverse):
    phase = (t * 0.7 * speed) % 2.0
    head = (phase if phase < 1 else 2 - phase) * (n - 1)
    c = colors[0]
    width = max(n * 0.12, 1.5)
    return [scale(c, max(0.0, 1 - abs(head - i) / width) ** 1.5)
            for i in range(n)]


def fx_twinkle(t, n, colors, speed, reverse):
    slot = 1.6 / speed
    out = []
    for i in range(n):
        x = t / slot + _rand(i, 7)
        k, f = divmod(x, 1.0)
        if _rand(i, int(k)) < 0.4:
            c = colors[int(_rand(i, int(k), 3) * len(colors))]
            out.append(scale(c, math.sin(math.pi * f) ** 2))
        else:
            out.append(BLACK)
    return out


_FIRE = [(0, 0, 0), (120, 8, 0), (230, 40, 0), (255, 110, 0), (255, 190, 40)]


def fx_fire(t, n, colors, speed, reverse):
    pal = colors if len(colors) >= 2 else _FIRE
    out = []
    for i in range(n):
        heat = 0.25 + 0.75 * (0.6 * _noise(i, t * 7 * speed)
                              + 0.4 * _noise(i + 999, t * 17 * speed))
        out.append(palette(pal, heat, wrap=False))
    return out


def fx_strobe(t, n, colors, speed, reverse):
    rate = 6.0 * speed
    k, f = divmod(t * rate, 1.0)
    c = colors[int(k // 2) % len(colors)]
    return [c if f < 0.35 else BLACK] * n


def fx_police(t, n, colors, speed, reverse):
    a, b = (colors + colors)[:2] if len(colors) >= 2 else ((255, 0, 0),
                                                           (0, 40, 255))
    k, f = divmod(t * 2.2 * speed, 1.0)
    side = int(k) % 2
    flash = (f % 0.5) < 0.2
    half = n // 2
    out = []
    for i in range(n):
        left = i < half
        if flash and left == (side == 0):
            out.append(a if left else b)
        else:
            out.append(BLACK)
    return out


def fx_aurora(t, n, colors, speed, reverse):
    s = t * speed
    out = []
    for i in range(n):
        x = _pos(i, n, reverse)
        w = (math.sin(2 * math.pi * (x * 1.3 + s * 0.07))
             + math.sin(2 * math.pi * (x * 0.7 - s * 0.045) + 1.7)) / 4 + 0.5
        lvl = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(
            2 * math.pi * (x * 2.1 + s * 0.11) + 0.6))
        out.append(scale(palette(colors, w, wrap=False), lvl))
    return out


def fx_heartbeat(t, n, colors, speed, reverse):
    period = 1.2 / speed
    k, f = divmod(t / period, 1.0)

    def pulse(at):
        d = (f - at) / 0.07
        return math.exp(-d * d)

    level = max(pulse(0.1), 0.75 * pulse(0.32))
    c = colors[int(k) % len(colors)]
    return [scale(c, 0.06 + 0.94 * level)] * n


def fx_ripple(t, n, colors, speed, reverse):
    centre = (n - 1) / 2
    out = []
    period = 1.5 / speed
    k, f = divmod(t / period, 1.0)
    c = colors[int(k) % len(colors)]
    radius = f * (centre + 3)
    for i in range(n):
        d = abs(abs(i - centre) - radius)
        out.append(scale(c, max(0.0, 1 - d / 2.2) * (1 - f * 0.7)))
    return out


def fx_meteor(t, n, colors, speed, reverse):
    # Several comets in different colours, staggered around the strip.
    k = max(len(colors), 2)
    tail = max(n / (k * 1.6), 2.5)
    head = (t * 0.45 * speed % 1.0) * n
    out = [BLACK] * n
    for m in range(k):
        h = (head + m * n / k) % n
        c = colors[m % len(colors)]
        for i in range(n):
            j = (n - 1 - i) if reverse else i
            d = (h - j) % n
            if d < tail:
                v = scale(c, (1 - d / tail) ** 2)
                o = out[i]
                out[i] = (max(o[0], v[0]), max(o[1], v[1]), max(o[2], v[2]))
    return out


def fx_candle(t, n, colors, speed, reverse):
    c = colors[0]
    out = []
    for i in range(n):
        f = 0.55 + 0.45 * _noise(i // 4, t * 5 * speed) \
            * (0.7 + 0.3 * _noise(77, t * 13 * speed))
        out.append(scale(c, f))
    return out


# ----------------------------------------------------------------- registry
def _hx(*vals):
    return [hex_to_rgb(v) for v in vals]


class Effect:
    def __init__(self, eid, name, fn, blurb, animated=True, colors=None,
                 uses_colors=True, single=False, category="animation"):
        self.id = eid
        self.name = name
        self.fn = fn
        self.blurb = blurb
        self.animated = animated
        self.default_colors = colors or _hx("#00b8fc")
        self.uses_colors = uses_colors
        self.single = single        # only the first colour matters
        self.category = category

    def frame(self, t, n, colors=None, speed=1.0, reverse=False):
        if n <= 0:
            return []
        cols = list(colors) if (colors and self.uses_colors) \
            else list(self.default_colors)
        if not cols:
            cols = list(self.default_colors)
        return self.fn(t, n, cols, max(speed, 0.05), reverse)


EFFECTS = [
    Effect("static", "Fixed", fx_static,
           "Solid colour; several colours repeat LED by LED.",
           animated=False, colors=_hx("#00b8fc"), category="static"),
    Effect("gradient", "Gradient", fx_gradient,
           "A still blend from the first colour to the last.",
           animated=False, colors=_hx("#ff2d55", "#5856d6", "#00b8fc"),
           category="static"),
    Effect("custom", "Freestyle", fx_custom,
           "Every LED painted by hand.", animated=False,
           colors=[(0, 0, 0)], category="freestyle"),
    Effect("rainbow", "Rainbow wave", fx_rainbow,
           "The full spectrum flowing along the fans.", uses_colors=False),
    Effect("spectrum", "Colour cycle", fx_spectrum,
           "Every LED together, slowly through all hues.", uses_colors=False),
    Effect("wave", "Colour wave", fx_wave,
           "Your colours as a gradient that scrolls.",
           colors=_hx("#00b8fc", "#6c5ce7", "#ff2d55")),
    Effect("breathing", "Breathing", fx_breathing,
           "Slow fade in and out, one colour per breath.",
           colors=_hx("#00b8fc", "#af52de")),
    Effect("fade", "Colour fade", fx_fade,
           "The whole zone drifting between your colours.",
           colors=_hx("#ff3b30", "#ffcc00", "#34c759", "#007aff")),
    Effect("aurora", "Aurora", fx_aurora,
           "Northern-lights drift of greens and violets.",
           colors=_hx("#00ff9c", "#00b8fc", "#7a2cff")),
    Effect("comet", "Comet", fx_comet,
           "A bright head with a fading tail, lap after lap.",
           colors=_hx("#00b8fc", "#ff2d55")),
    Effect("meteor", "Meteor shower", fx_meteor,
           "Several comets at once, one per colour.",
           colors=_hx("#ff3b30", "#00b8fc", "#ffcc00")),
    Effect("scanner", "Scanner", fx_scanner,
           "A light that sweeps back and forth.", colors=_hx("#ff1a1a"),
           single=True),
    Effect("chase", "Theatre chase", fx_chase,
           "Marquee lights marching along.",
           colors=_hx("#ffcc00", "#ff3b30")),
    Effect("twinkle", "Starlight", fx_twinkle,
           "Random LEDs glinting on and off.",
           colors=_hx("#ffffff", "#9fd8ff", "#ffd27a")),
    Effect("ripple", "Ripple", fx_ripple,
           "Rings expanding out from the middle.",
           colors=_hx("#00b8fc", "#34c759")),
    Effect("heartbeat", "Heartbeat", fx_heartbeat,
           "A double pulse, like a resting heart.", colors=_hx("#ff1744")),
    Effect("fire", "Fire", fx_fire,
           "Flickering flames. Give two or more colours for your own palette.",
           colors=list(_FIRE)),
    Effect("candle", "Candle", fx_candle,
           "A gentle warm flicker.", colors=_hx("#ff8a1e"), single=True),
    Effect("strobe", "Strobe", fx_strobe,
           "Fast flashes. Not for the photosensitive.",
           colors=_hx("#ffffff")),
    Effect("police", "Police", fx_police,
           "Alternating red and blue flashes.",
           colors=_hx("#ff0000", "#0028ff")),
]

BY_ID = {e.id: e for e in EFFECTS}
ANIMATIONS = [e for e in EFFECTS if e.category == "animation"]


def get(eid):
    return BY_ID.get(eid) or BY_ID["static"]


# Gradient presets shown on the panel's Presets tab.
GRADIENTS = [
    ("Sunset", _hx("#ff5e3a", "#ff2a68", "#5f27cd")),
    ("Ocean", _hx("#00c6ff", "#0072ff", "#00e0b0")),
    ("Cyberpunk", _hx("#ff00c8", "#7a00ff", "#00f0ff")),
    ("Forest", _hx("#0b6623", "#7cfc00", "#2e8b57")),
    ("Lava", _hx("#ff0000", "#ff7300", "#ffd000")),
    ("Ice", _hx("#ffffff", "#9be7ff", "#2196f3")),
    ("Synthwave", _hx("#f72585", "#7209b7", "#4cc9f0")),
    ("Peach", _hx("#ffb88c", "#ff6f91", "#ffc75f")),
]
