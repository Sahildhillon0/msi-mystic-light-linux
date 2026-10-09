"""Colour helpers shared by the CLI and the panel."""

PRESETS = [
    ("#ff3b30", "Red"), ("#ff9500", "Orange"), ("#ffcc00", "Yellow"),
    ("#34c759", "Green"), ("#00c7be", "Teal"), ("#32ade6", "Light blue"),
    ("#007aff", "Blue"), ("#5856d6", "Indigo"), ("#af52de", "Purple"),
    ("#ff2d55", "Pink"), ("#ffffff", "White"), ("#8e8e93", "Grey"),
    ("#000000", "Black"), ("#ff6b00", "Ember"), ("#00b894", "Mint"),
    ("#6c5ce7", "Violet"),
]


def hex_to_rgb(text):
    """'#ff3b30', 'ff3b30' or 'f53' -> (r, g, b). Raises ValueError."""
    t = text.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError("expected RRGGBB, got %r" % text)
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def hsv_to_rgb(h, s=1.0, v=1.0):
    """h in degrees [0, 360); s, v in [0, 1]."""
    h %= 360.0
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x),
               (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return (int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))


# Default LEDs to request when a zone has not been sized yet. It has to be
# generous: the controller addresses up to 240 LEDs per zone, addresses past
# the end of the hardware are ignored, and *undersizing* is what leaves part of
# a strip or fan dark. 30 covers a full ARGB header of RGB fans plus a GPU and
# a CPU cooler sharing the same board.
DEFAULT_LEDS = 30


def rainbow_gradient(leds, offset=0.0, sat=1.0, val=1.0):
    """One frame of a hue gradient spanning `leds` LEDs."""
    if leds <= 0:
        return []
    return [hsv_to_rgb(offset + 360.0 * i / leds, sat, val)
            for i in range(leds)]


def cycle(colors, count):
    """Repeat `colors` until `count` entries -- how per-LED colours are filled."""
    colors = list(colors) or [(0, 0, 0)]
    return [colors[i % len(colors)] for i in range(count)]