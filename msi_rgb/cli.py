"""msirgb -- control MSI Mystic Light motherboard RGB from the command line.

Talks to a running OpenRGB SDK server on 127.0.0.1:6742. Standard library only.

Usage:
  msirgb doctor                                 # diagnose board + detection
  msirgb list                                   # devices, zones, LED counts
  msirgb zone 3 --color ff0000
  msirgb zone 3 --color ff0000 --color 0000ff   # alternate per LED
  msirgb zone 3 --leds 9 --color 00ff00
  msirgb rainbow --zone 3                       # animated
  msirgb effects                                # list animations
  msirgb effect aurora --zone 3 --speed 0.6     # run one in the foreground
  msirgb profile Calm                           # apply a profile and keep it
  msirgb play                                   # restore the saved lighting
  msirgb off
"""

import argparse
import signal
import sys
import time

from .color import DEFAULT_LEDS, cycle, hex_to_rgb, rainbow_gradient, rgb_to_hex
from .config import (CONFIG_PATH, KNOWN_BOARDS, load_config, read_dmi_board_name,
                     write_example_config, zone_label)
from .sdk import OpenRGB, SDKError
from . import effects, runtime, state


def cmd_doctor():
    """Explain whether OpenRGB can see this board, and what to do about it."""
    cfg = load_config()
    board = read_dmi_board_name()

    print("MSI Mystic Light -- diagnosis")
    print("=" * 46)
    print(f"DMI board_name   : {board or '(could not read)'}")
    print(f"known to msi-rgb: "
          f"{'yes' if board in KNOWN_BOARDS else 'no (generic labels used)'}")
    print(f"config file      : {CONFIG_PATH} "
          f"({'present' if CONFIG_PATH.exists() else 'absent'})")

    if cfg.get("spoof_as"):
        print(f"\nOpenRGB needs to see the board as:\n    {cfg['spoof_as']}")
        print("  Set MSI_SPOOF_BOARD_NAME to that value before starting OpenRGB.")
    else:
        print("\nNo spoof target is known for this board.")
        print("  Find a suitable entry in OpenRGB's board table and set it in")
        print(f"  {CONFIG_PATH}, e.g.:")
        print('    { "spoof_as": "SOME BOARD (MS-XXXX)" }')

    print("\nChecking the running OpenRGB server ...")
    try:
        api = OpenRGB()
    except OSError as e:
        print(f"  cannot reach 127.0.0.1:6742 ({e}).")
        print("  Start it:  systemctl --user start openrgb-msi")
        return 2
    try:
        api.handshake()
        api.load_devices()
    except SDKError as e:
        print(f"  protocol error: {e}")
        return 1
    finally:
        api.close()

    if api.devices:
        print(f"  OK -- OpenRGB sees {len(api.devices)} device(s):")
        for d in api.devices:
            print(f"    {d['name']} at {d['location']}")
        print("\nRun `msirgb list` to see the zones.")
        return 0

    print("  OpenRGB sees 0 devices -- the board is being skipped.")
    print("  Check the OpenRGB log for 'does not have valid config'.")
    print("  Fix: start OpenRGB with the shim loaded (see README).")
    write_example_config()
    return 1


def hexcolor(text):
    """argparse type: RRGGBB -> (r, g, b)."""
    try:
        return hex_to_rgb(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def pick_mode(dev, spec):
    if spec is None:
        return dev["active_mode"], dev["modes"][dev["active_mode"]]
    if spec.isdigit():
        idx = int(spec)
        if not 0 <= idx < len(dev["modes"]):
            raise SDKError(f"mode index {idx} out of range")
        return idx, dev["modes"][idx]
    want = spec.lower()
    for i, m in enumerate(dev["modes"]):
        if m["name"].lower() == want:
            return i, m
    hits = [(i, m["name"]) for i, m in enumerate(dev["modes"])
            if want in m["name"].lower()]
    if len(hits) == 1:
        return hits[0][0], dev["modes"][hits[0][0]]
    names = ", ".join(m["name"] for m in dev["modes"])
    raise SDKError(f"no mode matching {spec!r}. Available: {names}")


def cmd_list(api, labels=None):
    if not api.devices:
        print("No devices. Is the OpenRGB server running?")
        return 1
    for di, d in enumerate(api.devices):
        print(f"[{di}] {d['name']}")
        print(f"    vendor={d['vendor']!r} version={d['version']!r} "
              f"location={d['location']!r}")
        print(f"    active mode: {d['modes'][d['active_mode']]['name']} "
              f"(index {d['active_mode']})")
        print("    modes: " + ", ".join(
            f"{i}:{m['name']}" for i, m in enumerate(d["modes"])))
        print(f"    zones ({len(d['zones'])}):")
        for zi, z in enumerate(d["zones"]):
            print(f"      [{zi}] {z['name']:<12} -> "
                  f"{zone_label(z['name'], zi, labels):<20} "
                  f"{z['type']:<10} leds={z['leds_count']} "
                  f"(max {z['leds_max']})")
        print(f"    total LEDs: {len(d['leds'])}")
    return 0


def apply_zone(api, dev_id, dev, zi, args):
    zone = dev["zones"][zi]
    leds = args.leds if args.leds is not None else zone["leds_count"]
    if leds <= 0:
        raise SDKError(
            f"zone {zi} ({zone['name']}) reports 0 LEDs -- pass --leds N "
            f"(max {zone['leds_max']})"
        )
    if leds > zone["leds_max"]:
        raise SDKError(
            f"zone {zi} ({zone['name']}) allows at most {zone['leds_max']} LEDs")
    # Undersizing is what leaves part of a strip or fan dark. Addresses past
    # the end of the hardware are ignored, so oversizing is harmless -- so when
    # the caller did not ask for a specific count, size the zone generously.
    if args.leds is None and leds < DEFAULT_LEDS:
        leds = min(DEFAULT_LEDS, zone["leds_max"])
    if leds != zone["leds_count"]:
        api.resize_zone(dev_id, zi, leds)
        print(f"  resized zone {zi} -> {leds} LEDs")

    mode_idx, mode = pick_mode(dev, args.mode)
    if args.speed is not None:
        mode["speed"] = args.speed
    if args.brightness is not None:
        mode["brightness"] = args.brightness
    api.update_mode(dev_id, mode_idx, mode)

    user = list(args.color) if args.color else []
    if args.color2:
        user.append(args.color2)
    if not user:
        user = [(0, 0, 0)]

    if mode.get("num_colors"):
        # A real effect mode: the board animates, one colour per mode slot.
        colors = (user + [(0, 0, 0)] * mode["num_colors"])[:mode["num_colors"]]
    else:
        # "Direct" mode (MSI_MODE_DIRECT_DUMMY): colours are pushed per LED,
        # cycling the supplied colours across the zone.
        colors = cycle(user, leds)

    api.update_zone_leds(dev_id, zi, colors)
    return zone_label(zone["name"], zi), mode["name"], user


def cmd_rainbow(api, dev_id, dev, args):
    """Rotate a hue gradient across one or more zones until interrupted.

    The MSI 761-byte controller is only exposed in 'Direct' mode, so the board
    never animates on its own -- the host has to push each frame.
    """
    targets = ([args.zone] if args.zone is not None
               else list(range(len(dev["zones"]))))
    for zi in targets:
        if not 0 <= zi < len(dev["zones"]):
            raise SDKError(f"no zone {zi}")

    # Resolve LED counts up front and resize once, not every frame.
    plan = []
    for zi in targets:
        zone = dev["zones"][zi]
        leds = args.leds if args.leds is not None else zone["leds_count"]
        if leds <= 0:
            raise SDKError(f"zone {zi} ({zone['name']}) has 0 LEDs -- pass --leds N")
        if leds > zone["leds_max"]:
            raise SDKError(f"zone {zi} allows at most {zone['leds_max']} LEDs")
        if leds != zone["leds_count"]:
            api.resize_zone(dev_id, zi, leds)
            print(f"  resized zone {zi} ({zone['name']}) -> {leds} LEDs")
        plan.append((zi, zone["name"], leds))

    sat = min(max(args.sat, 0.0), 1.0)

    def frame(offset):
        for zi, _name, leds in plan:
            api.update_zone_leds(dev_id, zi, rainbow_gradient(leds, offset, sat))

    if args.once:
        frame(args.offset)
        print("rainbow set (static): " + ", ".join(
            f"{zi} {name}" for zi, name, _ in plan))
        return 0

    step = max(args.step, 0.05)
    print(f"cycling rainbow on {', '.join(f'{zi} ({n})' for zi, n, _ in plan)} "
          f"-- one full turn every {args.period}s. Ctrl-C to stop.", flush=True)
    try:
        while True:
            for i in range(max(int(args.period / step), 1)):
                frame(args.offset + 360.0 * i / max(int(args.period / step), 1))
                time.sleep(step)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def cmd_effects():
    width = max(len(e.id) for e in effects.EFFECTS)
    for e in effects.EFFECTS:
        kind = "animated" if e.animated else "static  "
        print(f"  {e.id:<{width}}  {kind}  {e.name}: {e.blurb}")
    return 0


def run_lighting(lighting, wait=60.0, once=False):
    """Drive the board with ``lighting`` until interrupted.

    Static lighting is pushed once and the call returns; anything animated
    keeps this process running, which is the whole point of ``play``.
    """
    from .engine import Engine

    errors = []
    eng = Engine(on_status=lambda ok, msg: None if ok else errors.append(msg),
                 connect_timeout=wait)
    eng.start()
    if not eng.ready.wait(wait):
        eng.stop()
        print(f"error: {errors[-1] if errors else 'OpenRGB server not ready'}",
              file=sys.stderr)
        return 2

    animated = False
    eng.set_master(lighting.master)
    for zi, z in enumerate(eng.zones):
        layer = lighting.layer_for((z["name"] or "").strip())
        if layer is None:
            continue
        eng.set_layer(zi, layer)
        animated |= layer.fx.animated

    if once or not animated:
        # Let the pump push the static frames, then leave.
        for _ in range(40):
            if not eng._dirty:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        eng.stop()
        eng.join(2)
        return 0

    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    runtime.write_pidfile()
    try:
        while not stop and eng.is_alive():
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.remove_pidfile()
        eng.stop()
        eng.join(2)
    return 0


def cmd_play(args):
    lighting, _settings, active = state.load_lighting()
    if args.profile:
        profiles = state.all_profiles()
        if args.profile not in profiles:
            print(f"error: no profile {args.profile!r}. Have: "
                  + ", ".join(profiles), file=sys.stderr)
            return 1
        lighting = profiles[args.profile]
        state.save_lighting(lighting, profile=args.profile)
    if not lighting.zones:
        print("nothing saved yet -- set something up in msirgb-gui first")
        return 0
    return run_lighting(lighting, wait=args.wait)


def cmd_effect(args):
    fx = effects.BY_ID.get(args.name)
    if fx is None:
        print(f"error: no effect {args.name!r}; see `msirgb effects`",
              file=sys.stderr)
        return 1
    layer = state.Layer(fx.id, list(args.color) if args.color else None,
                        args.speed, args.brightness, args.reverse,
                        args.leds or 0)
    key = "*"
    if args.zone is not None:
        key = None
    lighting = state.Lighting({key: layer} if key else {})
    if key is None:
        # Zones are keyed by name; resolve the index once we can see them.
        api = OpenRGB()
        try:
            api.handshake()
            api.load_devices()
            zones = api.devices[0]["zones"] if api.devices else []
        finally:
            api.close()
        if not 0 <= args.zone < len(zones):
            print(f"error: no zone {args.zone}", file=sys.stderr)
            return 1
        lighting.zones[(zones[args.zone]["name"] or "").strip()] = layer
    print(f"{fx.name} on {'zone %d' % args.zone if key is None else 'every zone'}"
          + (" -- Ctrl-C to stop" if fx.animated else ""), flush=True)
    return run_lighting(lighting, wait=5.0)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="msirgb", description="Control MSI Mystic Light RGB via OpenRGB.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="diagnose board detection and setup")
    sub.add_parser("list", help="show devices, zones and modes")

    z = sub.add_parser("zone", help="set one zone")
    z.add_argument("index", type=int)
    z.add_argument("--color", type=hexcolor, action="append",
                   help="RRGGBB (repeat for more colours; they cycle per LED)")
    z.add_argument("--color2", type=hexcolor, help="second colour, shorthand")
    z.add_argument("--mode", help="mode name or index (default: current)")
    z.add_argument("--leds", type=int, help="set the zone's LED count")
    z.add_argument("--speed", type=int)
    z.add_argument("--brightness", type=int)

    a = sub.add_parser("all", help="set every zone")
    a.add_argument("--color", type=hexcolor, action="append")
    a.add_argument("--color2", type=hexcolor)
    a.add_argument("--mode")
    a.add_argument("--leds", type=int)
    a.add_argument("--speed", type=int)
    a.add_argument("--brightness", type=int)

    r = sub.add_parser("rainbow", help="cycle a hue gradient (animated)")
    r.add_argument("--zone", type=int, help="only this zone (default: all)")
    r.add_argument("--leds", type=int)
    r.add_argument("--period", type=float, default=8.0,
                   help="seconds for one full hue turn")
    r.add_argument("--step", type=float, default=0.1, help="frame interval")
    r.add_argument("--offset", type=float, default=0.0, help="starting hue")
    r.add_argument("--sat", type=float, default=1.0, help="saturation 0..1")
    r.add_argument("--once", action="store_true",
                   help="set one static rainbow frame and exit")

    sub.add_parser("off", help="turn every zone off")

    sub.add_parser("effects", help="list the available effects")

    e = sub.add_parser("effect", help="run one effect in the foreground")
    e.add_argument("name", help="effect id, see `msirgb effects`")
    e.add_argument("--zone", type=int, help="only this zone (default: all)")
    e.add_argument("--color", type=hexcolor, action="append",
                   help="RRGGBB, repeat for more (default: the effect's own)")
    e.add_argument("--speed", type=float, default=1.0,
                   help="speed multiplier, 1 = normal")
    e.add_argument("--brightness", type=int, default=100, help="0..100")
    e.add_argument("--reverse", action="store_true", help="run backwards")
    e.add_argument("--leds", type=int, help="LEDs in the zone")

    pl = sub.add_parser("play", help="restore the saved lighting "
                        "(keeps running while anything is animated)")
    pl.add_argument("--profile", help="apply this profile instead")
    pl.add_argument("--wait", type=float, default=60.0,
                    help="seconds to wait for the OpenRGB server")

    pr = sub.add_parser("profile", help="list profiles, or apply one")
    pr.add_argument("name", nargs="?")

    args = p.parse_args(argv)
    cfg = load_config()
    labels = cfg["zone_labels"]

    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "effects":
        return cmd_effects()
    if args.cmd == "play":
        return cmd_play(args)
    if args.cmd == "profile" and not args.name:
        active = state.load_lighting()[2]
        for name in state.all_profiles():
            tag = "built-in" if name in state.BUILTIN_PROFILES else "saved"
            print(f"  {'*' if name == active else ' '} {name:<20} {tag}")
        return 0

    # Everything below writes to the board; a background player would
    # immediately paint over it, so take the board back first.
    runtime.stop_background()

    if args.cmd == "profile":
        profiles = state.all_profiles()
        if args.name not in profiles:
            print(f"error: no profile {args.name!r}. Have: "
                  + ", ".join(profiles), file=sys.stderr)
            return 1
        lighting = profiles[args.name]
        state.save_lighting(lighting, profile=args.name)
        if any(l.fx.animated for l in lighting.zones.values()):
            # Hand it to the background player so the shell is not held.
            runtime.start_background()
            print(f"{args.name}: running in the background")
            return 0
        rc = run_lighting(lighting, wait=10.0)
        if rc == 0:
            print(f"{args.name}: applied")
        return rc
    if args.cmd == "effect":
        return cmd_effect(args)

    try:
        api = OpenRGB()
    except OSError as e:
        print(f"cannot reach the OpenRGB server ({e}).", file=sys.stderr)
        print("Start it with: systemctl --user start openrgb-msi",
              file=sys.stderr)
        return 2

    try:
        api.handshake()
        api.load_devices()

        if not api.devices:
            print("OpenRGB found no devices.", file=sys.stderr)
            print("Run `msirgb doctor` to find out why.", file=sys.stderr)
            return 1
        dev_id, dev = 0, api.devices[0]

        if args.cmd == "list":
            return cmd_list(api, labels)

        if args.cmd == "rainbow":
            return cmd_rainbow(api, dev_id, dev, args)

        if args.cmd == "off":
            # The off subparser declares no --mode/--leds/--speed.
            args.color, args.color2 = [(0, 0, 0)], None
            args.mode, args.leds = None, None
            args.speed, args.brightness = None, None
            targets = range(len(dev["zones"]))
            # Make "off" what comes back at login, too.
            state.save_lighting(state.Lighting(
                {"*": state.Layer("static", [(0, 0, 0)])}), profile=None)
        elif args.cmd == "zone":
            if not 0 <= args.index < len(dev["zones"]):
                raise SDKError(f"no zone {args.index} "
                               f"(0..{len(dev['zones']) - 1})")
            targets = [args.index]
        else:
            targets = range(len(dev["zones"]))

        for zi in targets:
            name, mode_name, colors = apply_zone(api, dev_id, dev, zi, args)
            hexes = " ".join(rgb_to_hex(c) for c in colors)
            print(f"zone {zi} ({name}): mode={mode_name} color={hexes}")

        return 0
    except SDKError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())