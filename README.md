# msi-mystic-light-linux

Control MSI Mystic Light motherboard lighting — case fans, CPU cooler, GPU — from
Linux. Includes a GTK4 panel and a CLI.

Built for the **MSI PRO Z890-A WIFI (MS-7E32)** on Arch/Omarchy, and written so
other recent MSI boards can be added by editing one config entry.

## Why this exists

MSI's own **Mystic Light** has no Linux build. A Windows VM with USB passthrough
does not help either: MSI checks the DMI vendor and silently hides the lighting
panel when it does not see an MSI board.

[OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) *does* support these
controllers — but it skips boards missing from its compiled-in name table. On an
unlisted board the only symptom is one line in its log:

```
[MSI Mystic Light X870] is enabled
Read 290 bytes from read enable packet, subsequent get reports should work
Found Board MSI PRO Z890-A WIFI (MS-7E32) but does not have valid config
```

That `Read 290 bytes` line means the HID conversation already succeeded. The
controller is talking; only the name lookup failed.

Detection builds `"MSI " + <DMI board_name>` and compares it to a table with
**string equality**:

| | |
| --- | --- |
| this board reports | `MSI PRO Z890-A WIFI (MS-7E32)` |
| OpenRGB's table has | `MSI MAG Z890 TOMAHAWK WIFI (MS-7E32)` |

`MS-7E32` really is the PRO Z890-A WIFI; upstream labelled that entry as the
Tomahawk, and the PRO Z890-A WIFI has no entry at all. So it is skipped.

## How it works

A small `LD_PRELOAD` shim substitutes a matching board name **for the OpenRGB
process only**. The system DMI table, the BIOS and every other program are
untouched, and dropping the environment variable reverts it completely.

Everything then runs through OpenRGB's own SDK, which is upstream-maintained and
carries the firmware caveats for this controller. This project does not talk to
the HID device directly for writes.

```
msirgb-gui  ─┐
             ├─▶ OpenRGB SDK (127.0.0.1:6742) ─▶ openrgb --server ─▶ MSI controller
msirgb CLI ─┘         (LD_PRELOAD shim)              (USB HID)
```

## Install

```bash
git clone https://github.com/Sahildhillon0/msi-mystic-light-linux
cd msi-mystic-light-linux
./install.sh
```

No root. Everything goes under `~/.local`, plus a systemd **user** unit that
starts the server at login.

Requires `openrgb` and `gcc`. The panel additionally needs PyGObject with GTK4;
the CLI needs nothing beyond the standard library.

```bash
msirgb doctor        # does OpenRGB see the board?
msirgb list          # zones, LED counts
```

## Using it

The panel is the main interface. Search **MSI Mystic Light** in your app
launcher, or run `msirgb-gui`.

It has a zone picker (labelled with what each header is actually wired to), a
colour chooser, preset swatches, per-zone LED count, and a rainbow
start/stop with a period slider. Colours you pick stack up as chips and cycle
across the zone's LEDs, so two or more give you a gradient.

From a terminal:

```bash
# a zone solid
msirgb zone 3 --color ff0000

# colours cycle across the LEDs, so this is a gradient
msirgb zone 3 --color ff0000 --color 0000ff

# set how many LEDs the header has, then colour it
msirgb zone 3 --leds 12 --color 00ff88

# animated rainbow on one zone (Ctrl-C to stop)
msirgb rainbow --zone 3 --period 20
msirgb rainbow --zone 3 --once        # one static frame
msirgb rainbow --zone 3 --sat 0.4     # pastel

msirgb off                            # everything dark
```

To keep a rainbow running after you close the terminal:

```bash
nohup msirgb rainbow --zone 3 --period 30 >/dev/null 2>&1 &
```

`install.sh` offers to open the panel when it finishes.

## Zones

OpenRGB exposes `JAF`, `JARGB 1..3`. What those *physically drive* is board
specific — on this machine, established by lighting each zone a different colour
and looking at the case:

| Zone | Header | Drives |
| --- | --- | --- |
| 0 | JAF | CPU cooler |
| 1 | JARGB 1 | nothing connected |
| 2 | JARGB 2 | graphics card |
| 3 | JARGB 3 | case RGB fans |

Your mapping lives in `msi_rgb/config.py` (`KNOWN_BOARDS`) and can be overridden
without touching code — see below.

## Adding your board

If `msirgb doctor` says the board is not known, you need the name of some board
OpenRGB *does* have, from `board_names[]` in:

```
Controllers/MSIMotherboardController/
    MSIMotherboard761Controller/MSIMotherboard761Controller.cpp
```

Use a board with the same chipset generation and the same zone set — the names
are matched exactly, so it is the whole string that matters, model code included.

Set it in `~/.config/msi-rgb/config.json` (`msirgb doctor` creates a starter
file):

```json
{
  "spoof_as": "MAG Z890 TOMAHAWK WIFI (MS-7E32)",
  "zone_labels": { "JARGB 3": "Case fans" },
  "default_zone": "JARGB 3"
}
```

Then reinstall the unit so it picks up the name:

```bash
systemctl --user daemon-reload
systemctl --user restart openrgb-msi
```

A board whose zone set differs from the one you impersonate will mis-map zones.
Verify with one colour per zone before trusting a long animation.

## LED counts

A zone has to be told how many LEDs are on it before colours mean anything —
zones start at 0. **Undersizing leaves part of your hardware dark**: a fan or
strip further along the header simply gets no address.

Addresses *past* the end of the hardware are ignored, so oversizing costs
nothing. Both front ends therefore default to **30 LEDs** per zone, which covers
a full ARGB header of RGB fans plus a GPU and an AIO cooler on one board. Lower
it in the panel's "LEDs in zone" field if you want to be exact.

## Limitations

Worth knowing before you rely on it:

- **Only `Direct` mode is exposed** for this controller. Colours are pushed per
  LED, which is what makes gradients possible, but the board never animates on
  its own — anything moving is the host pushing frames. Kill the rainbow process
  and the LEDs freeze on the last frame.
- **The board's own onboard LEDs go dark.** They are not in the zone set OpenRGB
  uses for this board, and OpenRGB takes over the lighting configuration.
- **A too-low LED count silently leaves hardware unlit** — see above.
- OpenRGB's own CLI cannot parse options that take a value in some builds, which
  is why this talks to the SDK directly.

## Credits

The protocol understanding here comes from reading the OpenRGB source, which is
GPL-3.0. This project is MIT-licensed and its code is original, but the packet
layouts and board tables are OpenRGB's work.

- [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) — the controller drivers
  and SDK that this drives
- [OpenRGB SDK docs](https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/OpenRGBSDK.md)
  — the wire protocol implemented in `msi_rgb/sdk.py`

## Licence

MIT. See [LICENSE](LICENSE).