"""msirgb-gui -- GTK4 control panel for MSI Mystic Light lighting.

Front end for the same OpenRGB SDK client the `msirgb` CLI uses.

Requires PyGObject with GTK4; no other third-party packages.
"""

import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from .color import PRESETS, cycle, hex_to_rgb, rainbow_gradient, rgb_to_hex
from .config import default_zone_index, load_config, zone_label
from .sdk import OpenRGB, SDKError

APP_ID = "com.github.sahildhillon0.msi_mystic_light_linux"


class Animator(threading.Thread):
    """Pushes rainbow frames on its own SDK connection so the UI never blocks."""

    def __init__(self, zone_idx, leds, period, sat=1.0):
        super().__init__(daemon=True)
        self.zone_idx = zone_idx
        self.leds = leds
        self.period = max(period, 0.5)
        self.sat = sat
        self.stop_event = threading.Event()

    def run(self):
        try:
            api = OpenRGB()
            api.handshake()
            api.load_devices()
        except (OSError, SDKError):
            return
        try:
            frames = max(int(self.period / 0.08), 2)
            while not self.stop_event.is_set():
                for i in range(frames):
                    if self.stop_event.is_set():
                        break
                    cols = rainbow_gradient(self.leds, 360.0 * i / frames,
                                            self.sat)
                    try:
                        api.update_zone_leds(0, self.zone_idx, cols)
                    except (OSError, SDKError):
                        return
                    time.sleep(self.period / frames)
        finally:
            api.close()

    def stop(self):
        self.stop_event.set()


class RGBWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MSI Mystic Light")
        self.set_default_size(940, 620)
        self.api = None
        self.dev = None
        self.zones = []
        self.cfg = load_config()
        self.labels = self.cfg["zone_labels"]
        self.colors = [(255, 59, 48)]          # colour chips, cycled per LED
        self.anim = None
        self._css_provider = None
        self._css_rules = []

        self._build()
        GLib.idle_add(self._connect_async)

    def zlabel(self, zi):
        raw = self.zones[zi]["name"] if 0 <= zi < len(self.zones) else ""
        return zone_label(raw, zi, self.labels)

    # ---------------------------------------------------------------- ui
    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        header = Gtk.HeaderBar()
        header.set_title_widget(Gtk.Label(label="MSI Mystic Light"))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text("Re-read zones from the board")
        refresh.connect("clicked", lambda *_: GLib.idle_add(self._reload))
        header.pack_start(refresh)
        self.conn_label = Gtk.Label(label="connecting...")
        self.conn_label.add_css_class("dim-label")
        header.pack_end(self.conn_label)
        self.set_titlebar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        body.set_margin_top(14)
        body.set_margin_bottom(14)
        body.set_margin_start(14)
        body.set_margin_end(14)
        root.append(body)

        body.append(self._left_panel())
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        body.append(sep)
        body.append(self._right_panel())

        self.status = Gtk.Label(label="Ready")
        self.status.set_xalign(0.0)
        self.status.set_margin_top(8)
        self.status.set_margin_bottom(10)
        self.status.set_margin_start(14)
        self.status.add_css_class("dim-label")
        root.append(self.status)

    def _left_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_size_request(260, -1)

        box.append(self._heading("Zone"))
        self.zone_dd = Gtk.DropDown.new_from_strings(["(loading...)"])
        self.zone_dd.connect("notify::selected", lambda *_: self._zone_changed())
        box.append(self.zone_dd)

        leds_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        leds_row.append(Gtk.Label(label="LEDs in zone"))
        self.leds_spin = Gtk.SpinButton.new_with_range(1, 240, 1)
        self.leds_spin.set_value(12)
        self.leds_spin.set_numeric(True)
        leds_row.append(self.leds_spin)
        box.append(leds_row)

        apply_btn = Gtk.Button(label="Apply to zone")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", lambda *_: self._apply())
        box.append(apply_btn)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        off_btn = Gtk.Button(label="Zone off")
        off_btn.connect("clicked", lambda *_: self._apply((0, 0, 0)))
        all_off = Gtk.Button(label="All off")
        all_off.add_css_class("destructive-action")
        all_off.connect("clicked", lambda *_: self._all_off())
        row.append(off_btn)
        row.append(all_off)
        box.append(row)

        box.append(Gtk.Separator())
        box.append(self._heading("Animation"))
        self.rainbow_switch = Gtk.Switch()
        self.rainbow_switch.set_active(True)
        sw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sw_row.append(Gtk.Label(label="Cycling rainbow"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        sw_row.append(spacer)
        sw_row.append(self.rainbow_switch)
        box.append(sw_row)

        self.period_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 2, 60, 1)
        self.period_scale.set_value(10)
        self.period_scale.set_draw_value(True)
        box.append(self.period_scale)

        anim_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.start_btn = Gtk.Button(label="Start")
        self.start_btn.connect("clicked", lambda *_: self._toggle_anim())
        anim_row.append(self.start_btn)
        box.append(anim_row)

        return box

    def _right_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_hexpand(True)

        box.append(self._heading("Colours (cycled across the zone's LEDs)"))

        # Current chips
        chip_scroll = Gtk.ScrolledWindow()
        chip_scroll.set_size_request(-1, 76)
        chip_scroll.set_min_content_height(64)
        chip_scroll.set_max_content_height(76)
        chip_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.chip_box = Gtk.FlowBox()
        self.chip_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.chip_box.set_homogeneous(False)
        self.chip_box.set_valign(Gtk.Align.START)
        chip_scroll.set_child(self.chip_box)
        box.append(chip_scroll)

        # Custom colour
        custom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.hex_entry = Gtk.Entry()
        self.hex_entry.set_placeholder_text("#ff3b30")
        self.hex_entry.set_width_chars(9)
        self.hex_entry.set_max_width_chars(9)
        self.hex_entry.connect("activate", lambda *_: self._add_hex())
        add_hex = Gtk.Button(label="Add")
        add_hex.connect("clicked", lambda *_: self._add_hex())
        pick = Gtk.Button(label="Pick colour…")
        pick.connect("clicked", lambda *_: self._pick_color())
        custom.append(self.hex_entry)
        custom.append(add_hex)
        custom.append(pick)
        box.append(custom)

        box.append(self._heading("Presets"))
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        for i, (hexval, name) in enumerate(PRESETS):
            b = Gtk.Button()
            b.set_tooltip_text(f"{name}  {hexval}")
            b.set_size_request(40, 28)
            b.add_css_class(f"swatch-{i}")
            self._css_rules.append(f".swatch-{i} "
                                   f"{{ background: {hexval}; "
                                   f"border-radius: 6px; }}")
            b.connect("clicked", lambda _w, c=hex_to_rgb(hexval),
                      n=name: self._add_color(c, n))
            grid.attach(b, i % 8, i // 8, 1, 1)
        box.append(grid)
        self._rebuild_css()

        return box

    def _rebuild_css(self):
        """Install swatch colours display-wide (per-widget CSS is deprecated)."""
        display = Gdk.Display.get_default()
        if display is None or not self._css_rules:
            return
        if self._css_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(
                display, self._css_provider)
        provider = Gtk.CssProvider()
        provider.load_from_data("".join(self._css_rules).encode())
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_provider = provider

    @staticmethod
    def _heading(text):
        l = Gtk.Label(label=text)
        l.set_xalign(0.0)
        l.add_css_class("heading")
        return l

    # ------------------------------------------------------------ backend
    def _connect_async(self):
        try:
            self.api = OpenRGB()
            self.api.handshake()
            self.api.load_devices()
        except (OSError, SDKError) as e:
            self._set_status(f"Cannot reach OpenRGB server: {e}", error=True)
            self.conn_label.set_label("disconnected")
            self.conn_label.remove_css_class("dim-label")
            self.conn_label.add_css_class("error")
            return False
        self.conn_label.set_label("connected")
        self.conn_label.remove_css_class("error")
        self.conn_label.add_css_class("dim-label")
        self._populate_zones()
        self._set_status(f"Connected to {self.dev['name']}")
        return False

    def _populate_zones(self):
        self.dev = self.api.devices[0]
        self.zones = self.dev["zones"]
        labels = [self.zlabel(i) for i in range(len(self.zones))]
        self.zone_dd.set_model(Gtk.StringList.new(labels))
        self.zone_dd.set_selected(default_zone_index(self.zones, self.labels))
        self._zone_changed()

    def _reload(self):
        try:
            self.api.load_devices()
            self._populate_zones()
            self._set_status("Zones re-read from the board")
        except (OSError, SDKError) as e:
            self._set_status(f"Reload failed: {e}", error=True)
        return False

    def _zone_changed(self):
        idx = self.zone_dd.get_selected()
        if 0 <= idx < len(self.zones):
            z = self.zones[idx]
            n = z["leds_count"] or 12
            self.leds_spin.set_range(1, max(z["leds_max"], 1))
            self.leds_spin.set_value(max(1, min(n, z["leds_max"])))
        self._render_chips()

    def _set_status(self, text, error=False):
        self.status.set_text(text)
        self.status.remove_css_class("error")
        if error:
            self.status.add_css_class("error")

    # -------------------------------------------------------------- edits
    def _add_color(self, rgb, name=""):
        self.colors.append(rgb)
        self._render_chips()
        self._set_status(
            f"{len(self.colors)} colour(s); they repeat across the zone's LEDs")

    def _add_hex(self):
        try:
            self._add_color(hex_to_rgb(self.hex_entry.get_text()))
            self.hex_entry.set_text("")
        except ValueError:
            self._set_status("Not a valid colour -- use RRGGBB, e.g. ff3b30",
                             error=True)

    def _pick_color(self):
        dialog = Gtk.ColorDialog()
        start = Gdk.RGBA()
        start.red, start.green, start.blue = (
            (c / 255.0 for c in self.colors[-1]))
        start.alpha = 1.0
        dialog.set_with_rgba(start)

        def done(dlg, result):
            try:
                rgba = dlg.choose_rgba_finish(result)
            except GLib.Error:
                return
            self._add_color((int(rgba.red * 255), int(rgba.green * 255),
                             int(rgba.blue * 255)))

        dialog.choose_rgba(self, None, done)

    def _render_chips(self):
        child = self.chip_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.chip_box.remove(child)
            child = nxt

        # Chip swatches get their own rule set; presets are untouched.
        preset_rules = len(PRESETS)
        self._css_rules = self._css_rules[:preset_rules]

        for i, rgb in enumerate(self.colors):
            hexv = rgb_to_hex(rgb)
            b = Gtk.Button()
            b.set_size_request(34, 30)
            # FlowBox stretches children along the cross axis; pin both axes
            # so chips stay swatch-sized instead of filling the row.
            b.set_halign(Gtk.Align.START)
            b.set_valign(Gtk.Align.START)
            b.add_css_class(f"chip-{i}")
            self._css_rules.append(f".chip-{i} {{ background: {hexv}; "
                                   f"border-radius: 6px; }}")
            b.set_tooltip_text(f"{hexv} -- click to remove")
            b.connect("clicked", self._remove_color, i)
            self.chip_box.append(b)

        if not self.colors:
            l = Gtk.Label(label="(no colours yet -- add one below)")
            l.add_css_class("dim-label")
            self.chip_box.append(l)

        self._rebuild_css()

    def _remove_color(self, _btn, index):
        if 0 <= index < len(self.colors):
            self.colors.pop(index)
            self._render_chips()

    # -------------------------------------------------------------- apply
    def _apply(self, colors=None):
        idx = self.zone_dd.get_selected()
        if not (0 <= idx < len(self.zones)) or self.api is None:
            return
        cols = colors if colors else self.colors
        leds = int(self.leds_spin.get_value())
        zone = self.zones[idx]

        try:
            if leds != zone["leds_count"]:
                self.api.resize_zone(0, idx, leds)
            self.api.update_zone_leds(0, idx, cycle(cols, leds))
        except (OSError, SDKError) as e:
            self._set_status(f"Apply failed: {e}", error=True)
            return
        label = self.zlabel(idx)
        if colors == [(0, 0, 0)]:
            self._set_status(f"{label} turned off")
        else:
            hexes = " ".join(rgb_to_hex(c) for c in cols)
            self._set_status(f"{label}: {len(cols)} colour(s) {hexes} "
                             f"over {leds} LEDs")

    def _all_off(self):
        self._stop_anim()
        for i, z in enumerate(self.zones):
            try:
                n = z["leds_count"] or 1
                self.api.update_zone_leds(0, i, [(0, 0, 0)] * n)
            except (OSError, SDKError) as e:
                self._set_status(f"Failed on zone {i}: {e}", error=True)
                return
        self._set_status("All zones off")

    # --------------------------------------------------------- animation
    def _toggle_anim(self):
        if self.anim and self.anim.is_alive():
            self._stop_anim()
        else:
            self._start_anim()

    def _start_anim(self):
        idx = self.zone_dd.get_selected()
        if not (0 <= idx < len(self.zones)) or self.api is None:
            return
        if not self.rainbow_switch.get_active():
            self._set_status("Rainbow switch is off", error=True)
            return
        leds = int(self.leds_spin.get_value())
        period = float(self.period_scale.get_value())
        try:
            if leds != self.zones[idx]["leds_count"]:
                self.api.resize_zone(0, idx, leds)
        except (OSError, SDKError):
            pass
        self.anim = Animator(idx, leds, period)
        self.anim.start()
        self.start_btn.set_label("Stop")
        self._set_status(
            f"Rainbow cycling on {self.zlabel(idx)} "
            f"-- one turn every {period:g}s")

    def _stop_anim(self):
        if self.anim:
            self.anim.stop()
            self.anim = None
        self.start_btn.set_label("Start")
        self._set_status("Animation stopped")

    def do_close_request(self):                     # noqa: N802 (GTK API)
        self._stop_anim()
        if self.api:
            self.api.close()
        return False


class RGBApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):                          # noqa: N802 (GTK API)
        win = RGBWindow(self)
        win.present()


def main(argv=None):
    return RGBApp().run(argv or [])


if __name__ == "__main__":
    import sys
    sys.exit(main())