"""msirgb-gui -- GTK4 control panel for MSI Mystic Light lighting.

Laid out like Logitech G HUB's lighting page: zones down the left, a live
preview of the selected zone across the top, then Presets / Animations /
Freestyle tabs with the effect's settings beside them.

The panel never writes to the board itself. It edits per-zone *layers* and
hands them to an ``Engine`` thread, which renders and pushes the frames; the
preview draws the very same frames from the same clock, so what is on screen
is what is on the fans.

Requires PyGObject with GTK4 and pycairo; no other third-party packages.
"""

import math
import sys
import threading

import cairo
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from . import effects, runtime, state
from .color import PRESETS, hex_to_rgb, rgb_to_hex
from .config import default_zone_index, load_config, zone_label
from .engine import Engine
from .state import Layer, Lighting

APP_ID = "com.github.sahildhillon0.msi_mystic_light_linux"
ACCENT = (0, 184, 252)
PREVIEW_FPS = 30
CUSTOM = "Custom"

CSS = """
window.ghub, window.ghub.background {
  background: #0d0f13; color: #e6e9ef;
  font-family: "Inter", "Noto Sans", sans-serif;
}
window.ghub headerbar {
  background: #0a0b0e; border-bottom: 1px solid #1d2129;
  box-shadow: none; min-height: 50px; padding: 0 8px;
}
window.ghub .brand { font-weight: 800; letter-spacing: 3px; font-size: 13px; }
window.ghub .brand-dot { color: #00b8fc; font-size: 15px; }
window.ghub .eyebrow {
  font-size: 10px; font-weight: 700; letter-spacing: 2px; color: #7d8696;
}
window.ghub .dim { color: #7d8696; }
window.ghub .zone-title { font-size: 26px; font-weight: 800; letter-spacing: 1px; }
window.ghub .fx-title { font-size: 18px; font-weight: 700; }
window.ghub .pill {
  border-radius: 99px; padding: 3px 12px; font-size: 11px; font-weight: 700;
  letter-spacing: 1px; background: #1a1e25; color: #7d8696;
}
window.ghub .pill.ok { color: #3ddc97; background: rgba(61,220,151,0.10); }
window.ghub .pill.bad { color: #ff4d5e; background: rgba(255,77,94,0.12); }

window.ghub .sidebar { background: #111318; border-right: 1px solid #1d2129; }
window.ghub .sidebar list { background: transparent; }
window.ghub .sidebar row {
  background: #171a20; border-radius: 10px; margin: 4px 12px;
  padding: 10px 12px; border: 1px solid transparent;
  transition: background 150ms, border-color 150ms;
}
window.ghub .sidebar row:hover { background: #1d2129; }
window.ghub .sidebar row:selected {
  background: #1b2430; border-color: #00b8fc;
  box-shadow: inset 3px 0 0 #00b8fc;
}
window.ghub .zone-name { font-weight: 700; font-size: 14px; }

window.ghub .card {
  background: #14171c; border-radius: 14px; border: 1px solid #1d2129;
}
window.ghub .settings { background: #111318; border-left: 1px solid #1d2129; }

window.ghub .tabbar { border-bottom: 1px solid #1d2129; }
window.ghub .tab {
  background: none; border: none; box-shadow: none; border-radius: 0;
  padding: 12px 18px; color: #7d8696; font-weight: 700; letter-spacing: 2px;
  font-size: 12px; border-bottom: 2px solid transparent;
  transition: color 150ms, border-color 200ms;
}
window.ghub .tab:hover { color: #e6e9ef; }
window.ghub .tab:checked { color: #ffffff; border-bottom-color: #00b8fc; }

window.ghub button {
  background: #1c2027; color: #e6e9ef; border: 1px solid #262b34;
  border-radius: 8px; box-shadow: none; text-shadow: none;
  transition: background 120ms, border-color 120ms;
}
window.ghub button:hover { background: #242933; border-color: #333a46; }
window.ghub button.accent {
  background: #00b8fc; color: #04131c; border-color: #00b8fc; font-weight: 700;
}
window.ghub button.accent:hover { background: #33c8ff; }
window.ghub button.danger { color: #ff4d5e; }
window.ghub button.danger:hover { background: rgba(255,77,94,0.12); }

window.ghub button.fx-card {
  background: #171a20; border: 1px solid #222731; border-radius: 12px;
  padding: 8px 8px 10px 8px;
}
window.ghub button.fx-card:hover { background: #1d2129; border-color: #39414e; }
window.ghub button.fx-card.active {
  border-color: #00b8fc; background: #16202b;
  box-shadow: 0 0 0 1px #00b8fc, 0 0 18px rgba(0,184,252,0.25);
}
window.ghub .fx-name { font-weight: 700; font-size: 12px; }
window.ghub button.swatch {
  padding: 0; border-radius: 10px; border: 2px solid #222731;
  background: #14171c;
}
window.ghub button.swatch:hover { border-color: #e6e9ef; }
window.ghub button.swatch.active { border-color: #00b8fc; }
window.ghub flowboxchild { padding: 0; background: none; }
window.ghub flowboxchild:focus, window.ghub flowboxchild:selected {
  background: none; outline: none;
}

window.ghub scale trough {
  background: #232831; min-height: 6px; border-radius: 99px;
}
window.ghub scale highlight {
  background: linear-gradient(to right, #0077b6, #00b8fc);
  border-radius: 99px;
}
window.ghub scale slider {
  background: #ffffff; min-width: 16px; min-height: 16px; margin: -6px;
  border-radius: 99px; border: none;
  box-shadow: 0 0 0 4px rgba(0,184,252,0.25);
}
window.ghub scale value { color: #7d8696; font-size: 11px; }
window.ghub switch { background: #2a2f39; border: none; border-radius: 99px; }
window.ghub switch:checked { background: #00b8fc; }
window.ghub switch slider { background: #ffffff; border-radius: 99px; }
window.ghub entry, window.ghub spinbutton {
  background: #0d0f13; color: #e6e9ef; border: 1px solid #262b34;
  border-radius: 8px; box-shadow: none;
}
window.ghub entry:focus-within, window.ghub spinbutton:focus-within {
  border-color: #00b8fc;
}
window.ghub dropdown > button {
  background: #171a20; min-width: 200px; font-weight: 700;
}
window.ghub popover > contents {
  background: #171a20; color: #e6e9ef; border: 1px solid #262b34;
  border-radius: 12px;
}
window.ghub popover listview row:selected { background: #1b2430; }
window.ghub .statusbar {
  background: #0a0b0e; border-top: 1px solid #1d2129; padding: 6px 16px;
  font-size: 11px; color: #7d8696;
}
window.ghub .statusbar.error { color: #ff4d5e; }
window.ghub scrollbar { background: transparent; }
window.ghub scrollbar slider { background: #2a2f39; border-radius: 99px; min-width: 6px; }
"""


# ------------------------------------------------------------------- drawing
def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_leds(cr, w, h, cols, pad=12, glow=True, reflect=False):
    """LEDs as glowing dots in a row, the way a lit strip actually looks."""
    n = len(cols)
    if not n:
        return
    step = (w - 2 * pad) / n
    r = max(1.6, min(step * 0.34, h * (0.16 if reflect else 0.22)))
    cy = h * (0.42 if reflect else 0.5)
    if glow:
        cr.set_operator(cairo.OPERATOR_ADD)
        for i, c in enumerate(cols):
            if sum(c) < 12:
                continue
            x = pad + step * (i + 0.5)
            R, G, B = (v / 255.0 for v in c)
            rad = r * 4.5
            g = cairo.RadialGradient(x, cy, 0, x, cy, rad)
            g.add_color_stop_rgba(0, R, G, B, 0.45)
            g.add_color_stop_rgba(1, R, G, B, 0)
            cr.set_source(g)
            cr.arc(x, cy, rad, 0, 2 * math.pi)
            cr.fill()
            if reflect:
                ry = h * 0.86
                g = cairo.RadialGradient(x, ry, 0, x, ry, rad * 1.3)
                g.add_color_stop_rgba(0, R, G, B, 0.16)
                g.add_color_stop_rgba(1, R, G, B, 0)
                cr.set_source(g)
                cr.arc(x, ry, rad * 1.3, 0, 2 * math.pi)
                cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)
    for i, c in enumerate(cols):
        x = pad + step * (i + 0.5)
        if sum(c) < 12:
            cr.set_source_rgb(0.15, 0.16, 0.19)
            cr.arc(x, cy, r, 0, 2 * math.pi)
            cr.fill()
            continue
        R, G, B = (v / 255.0 for v in c)
        cr.set_source_rgb(R, G, B)
        cr.arc(x, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.55)
        cr.arc(x, cy, r * 0.42, 0, 2 * math.pi)
        cr.fill()


class LedStrip(Gtk.DrawingArea):
    """A strip of LEDs whose colours come from ``source()`` at draw time."""

    def __init__(self, source, height=40, reflect=False, pad=12, bg=None):
        super().__init__()
        self.source = source
        self.reflect = reflect
        self.pad = pad
        self.bg = bg
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, w, h):
        if self.bg:
            _rounded(cr, 0, 0, w, h, 10)
            cr.set_source_rgb(*self.bg)
            cr.fill()
        draw_leds(cr, w, h, self.source() or [], pad=self.pad,
                  reflect=self.reflect)

    def index_at(self, x):
        n = len(self.source() or [])
        w = self.get_width()
        if not n or w <= 2 * self.pad:
            return None
        i = int((x - self.pad) / ((w - 2 * self.pad) / n))
        return i if 0 <= i < n else None


def swatch(colors, w=40, h=40, radius=8):
    """A drawn colour (or gradient) tile; avoids per-colour CSS classes."""
    area = Gtk.DrawingArea()
    area.set_content_width(w)
    area.set_content_height(h)

    def draw(_a, cr, aw, ah):
        _rounded(cr, 0, 0, aw, ah, radius)
        cols = colors() if callable(colors) else colors
        if len(cols) == 1:
            cr.set_source_rgb(*(v / 255.0 for v in cols[0]))
        else:
            g = cairo.LinearGradient(0, 0, aw, 0)
            for i, c in enumerate(cols):
                g.add_color_stop_rgb(i / (len(cols) - 1),
                                     *(v / 255.0 for v in c))
            cr.set_source(g)
        cr.fill()

    area.set_draw_func(draw)
    return area


def eyebrow(text):
    lbl = Gtk.Label(label=text.upper(), xalign=0.0)
    lbl.add_css_class("eyebrow")
    return lbl


def vbox(spacing=0, *children):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in children:
        b.append(c)
    return b


def hbox(spacing=0, *children):
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in children:
        b.append(c)
    return b


def spacer():
    s = Gtk.Box()
    s.set_hexpand(True)
    return s


def margins(w, top, right=None, bottom=None, left=None):
    right = top if right is None else right
    bottom = top if bottom is None else bottom
    left = right if left is None else left
    w.set_margin_top(top)
    w.set_margin_end(right)
    w.set_margin_bottom(bottom)
    w.set_margin_start(left)
    return w


# -------------------------------------------------------------------- window
class RGBWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MSI Mystic Light")
        self.set_default_size(1220, 780)
        self.add_css_class("ghub")

        self.cfg = load_config()
        self.labels = self.cfg["zone_labels"]
        saved, self.settings, self.active_profile = state.load_lighting()
        self.saved = saved
        self.master = saved.master
        self.zones = []
        self.layers = {}                 # zone index -> Layer
        self.memory = {}                 # (zone, effect) -> colours
        self.zi = 0
        self.sync_all = False
        self.brush = (255, 255, 255)
        self._quiet = False              # suppress handlers while syncing UI
        self._save_id = 0
        self._closed = False
        self.fx_cards = {}
        self.zone_rows = []

        self.engine = Engine(on_status=self._engine_status, connect_timeout=3)
        self._install_css()
        self._build()
        self._refresh_settings()

        # Take the board from any background player before driving it.
        def boot():
            runtime.stop_background()
            self.engine.start()
            self.engine.ready.wait(15)
            GLib.idle_add(self._on_ready)
        threading.Thread(target=boot, daemon=True).start()
        GLib.timeout_add(1000 // PREVIEW_FPS, self._tick)

    # ------------------------------------------------------------- helpers
    def zlabel(self, zi):
        raw = self.zones[zi]["name"] if 0 <= zi < len(self.zones) else ""
        return zone_label(raw, zi, self.labels)

    def zname(self, zi):
        return (self.zones[zi]["name"] or "").strip() \
            if 0 <= zi < len(self.zones) else ""

    def layer(self, zi=None):
        return self.layers.get(self.zi if zi is None else zi)

    def zone_frame(self, zi):
        layer = self.layers.get(zi)
        n = self.engine.zone_size(zi) if self.zones else 24
        if layer is None:
            return [(0, 0, 0)] * n
        return layer.frame(self.engine.now(), n, self.master)

    def _install_css(self):
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    # ----------------------------------------------------------------- ui
    def _build(self):
        self.set_titlebar(self._header())

        root = vbox(0)
        self.set_child(root)
        body = hbox(0)
        body.set_vexpand(True)
        root.append(body)
        body.append(self._sidebar())

        main = vbox(0)
        main.set_hexpand(True)
        body.append(main)
        main.append(self._stage())

        lower = hbox(0)
        lower.set_vexpand(True)
        main.append(lower)
        lower.append(self._tabs())
        lower.append(self._settings_panel())

        self.status = Gtk.Label(label="Starting...", xalign=0.0)
        self.status.add_css_class("statusbar")
        root.append(self.status)

    def _header(self):
        header = Gtk.HeaderBar()
        brand = hbox(8, Gtk.Label(label="◆"), Gtk.Label(label="MYSTIC LIGHT"))
        brand.get_first_child().add_css_class("brand-dot")
        brand.get_last_child().add_css_class("brand")
        header.pack_start(brand)

        # Profile picker, centred like G HUB's.
        self.profile_dd = Gtk.DropDown.new_from_strings(["Profiles"])
        self.profile_dd.set_tooltip_text("Lighting profile")
        self.profile_dd.connect("notify::selected", self._profile_selected)
        save_btn = Gtk.MenuButton(icon_name="document-save-symbolic")
        save_btn.set_tooltip_text("Save the current lighting as a profile")
        save_btn.set_popover(self._save_popover())
        self.del_btn = Gtk.Button(icon_name="user-trash-symbolic")
        self.del_btn.set_tooltip_text("Delete this profile")
        self.del_btn.connect("clicked", lambda *_: self._delete_profile())
        title = hbox(6, eyebrow("Profile"), self.profile_dd, save_btn,
                     self.del_btn)
        title.get_first_child().set_margin_end(6)
        header.set_title_widget(title)
        self._reload_profiles()

        menu = Gtk.MenuButton(icon_name="emblem-system-symbolic")
        menu.set_tooltip_text("Settings")
        menu.set_popover(self._settings_popover())
        header.pack_end(menu)
        self.conn = Gtk.Label(label="CONNECTING")
        self.conn.add_css_class("pill")
        header.pack_end(self.conn)
        return header

    def _save_popover(self):
        pop = Gtk.Popover()
        self.save_entry = Gtk.Entry(placeholder_text="Profile name")
        self.save_entry.connect("activate", lambda *_: self._save_profile(pop))
        ok = Gtk.Button(label="Save")
        ok.add_css_class("accent")
        ok.connect("clicked", lambda *_: self._save_profile(pop))
        pop.set_child(margins(vbox(8, eyebrow("Save profile"),
                                   hbox(6, self.save_entry, ok)), 12))
        return pop

    def _settings_popover(self):
        pop = Gtk.Popover()
        keep = Gtk.Switch(active=self.settings.get("keep_running", True))
        keep.set_valign(Gtk.Align.CENTER)
        keep.connect("notify::active", self._keep_changed)
        login = ("on" if runtime.unit_installed()
                 else "off (re-run install.sh)")
        note = Gtk.Label(
            label=f"Restore lighting at login: {login}", xalign=0.0)
        note.add_css_class("dim")
        reload_btn = Gtk.Button(label="Re-read zones from the board")
        reload_btn.connect("clicked", lambda *_: self._reread())
        box = vbox(10, eyebrow("Settings"),
                   hbox(12, Gtk.Label(label="Keep effects running after "
                                            "closing", xalign=0.0),
                        spacer(), keep),
                   note, reload_btn)
        box.set_size_request(320, -1)
        pop.set_child(margins(box, 14))
        return pop

    def _sidebar(self):
        side = vbox(0)
        side.add_css_class("sidebar")
        side.set_size_request(290, -1)
        side.append(margins(eyebrow("Lighting zones"), 18, 16, 8, 16))

        self.zone_list = Gtk.ListBox()
        self.zone_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.zone_list.connect("row-selected", self._zone_selected)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.zone_list)
        side.append(scroll)

        foot = vbox(12)
        margins(foot, 14, 16, 16, 16)
        self.sync_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.sync_sw.connect("notify::active", self._sync_changed)
        foot.append(hbox(8, vbox(2, Gtk.Label(label="Sync all zones",
                                              xalign=0.0),
                                 self._dim("Edits apply to every zone")),
                         spacer(), self.sync_sw))

        foot.append(eyebrow("Master brightness"))
        self.master_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.master_scale.set_value(self.master)
        self.master_scale.set_draw_value(True)
        self.master_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.master_scale.connect("value-changed", self._master_changed)
        foot.append(self.master_scale)

        off = Gtk.Button(label="All zones off")
        off.add_css_class("danger")
        off.connect("clicked", lambda *_: self._all_off())
        foot.append(off)
        side.append(foot)
        return side

    def _stage(self):
        """Zone title and the big live preview."""
        stage = vbox(14)
        margins(stage, 22, 26, 14, 26)

        self.zone_title = Gtk.Label(label="--", xalign=0.0)
        self.zone_title.add_css_class("zone-title")
        self.zone_sub = self._dim("")
        self.leds_spin = Gtk.SpinButton.new_with_range(1, 240, 1)
        self.leds_spin.set_valign(Gtk.Align.CENTER)
        self.leds_spin.connect("value-changed", self._leds_changed)
        leds_box = vbox(4, eyebrow("LEDs in zone"), self.leds_spin)
        stage.append(hbox(12, vbox(2, self.zone_title, self.zone_sub),
                          spacer(), leds_box))

        self.preview = LedStrip(lambda: self.zone_frame(self.zi), height=150,
                                reflect=True, pad=26,
                                bg=(0.055, 0.063, 0.078))
        self.preview.add_css_class("card")
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._paint_begin)
        drag.connect("drag-update", self._paint_update)
        self.preview.add_controller(drag)
        stage.append(self.preview)
        return stage

    def _tabs(self):
        col = vbox(0)
        col.set_hexpand(True)
        bar = hbox(0)
        bar.add_css_class("tabbar")
        margins(bar, 0, 26, 0, 26)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(
            Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(220)
        self.stack.set_vexpand(True)
        self.tab_btns = {}
        group = None
        for name, title, page in (("presets", "PRESETS", self._presets_page()),
                                  ("animations", "ANIMATIONS",
                                   self._animations_page()),
                                  ("freestyle", "FREESTYLE",
                                   self._freestyle_page())):
            b = Gtk.ToggleButton(label=title)
            b.add_css_class("tab")
            if group is None:
                group = b
            else:
                b.set_group(group)
            b.connect("toggled", self._tab_toggled, name)
            bar.append(b)
            self.tab_btns[name] = b
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_child(margins(page, 18, 26, 22, 26))
            self.stack.add_named(scroll, name)
        col.append(bar)
        col.append(self.stack)
        self.tab_btns["animations"].set_active(True)
        return col

    def _flow(self, min_per_line=4, max_per_line=8, spacing=10):
        f = Gtk.FlowBox()
        f.set_selection_mode(Gtk.SelectionMode.NONE)
        f.set_homogeneous(True)
        f.set_min_children_per_line(min_per_line)
        f.set_max_children_per_line(max_per_line)
        f.set_column_spacing(spacing)
        f.set_row_spacing(spacing)
        f.set_valign(Gtk.Align.START)
        return f

    def _presets_page(self):
        page = vbox(12)
        page.append(eyebrow("Solid colours"))
        solids = self._flow(6, 12)
        for hexval, name in PRESETS:
            rgb = hex_to_rgb(hexval)
            b = Gtk.Button(child=swatch([rgb], 52, 44))
            b.add_css_class("swatch")
            b.set_tooltip_text(f"{name}  {hexval}")
            b.connect("clicked", lambda _b, c=rgb: self._apply_solid(c))
            solids.append(b)
        page.append(solids)

        page.append(margins(eyebrow("Gradients"), 10, 0, 0, 0))
        grads = self._flow(2, 4)
        for name, cols in effects.GRADIENTS:
            card = vbox(8, swatch(cols, 150, 40, 8),
                        Gtk.Label(label=name, xalign=0.0))
            card.get_last_child().add_css_class("fx-name")
            b = Gtk.Button(child=card)
            b.add_css_class("fx-card")
            b.set_tooltip_text("Still gradient. Pick Colour wave on the "
                               "Animations tab to make it move.")
            b.connect("clicked", lambda _b, c=cols: self._apply_effect(
                "gradient", list(c)))
            grads.append(b)
        page.append(grads)

        page.append(margins(eyebrow("Animated looks"), 10, 0, 0, 0))
        looks = self._flow(2, 4)
        for name, cols in effects.GRADIENTS[:4]:
            strip = LedStrip(lambda c=cols: effects.get("wave").frame(
                self.engine.now(), 18, c, 0.8), height=36, pad=8)
            card = vbox(6, strip, Gtk.Label(label=f"{name} wave", xalign=0.0))
            card.get_last_child().add_css_class("fx-name")
            b = Gtk.Button(child=card)
            b.add_css_class("fx-card")
            b.connect("clicked", lambda _b, c=cols: self._apply_effect(
                "wave", list(c), speed=0.8))
            looks.append(b)
        page.append(looks)
        return page

    def _animations_page(self):
        page = vbox(12)
        page.append(eyebrow(f"{len(effects.ANIMATIONS)} effects"))
        grid = self._flow(3, 6)
        for fx in effects.ANIMATIONS:
            strip = LedStrip(lambda f=fx: self._card_frame(f), height=34,
                             pad=6)
            name = Gtk.Label(label=fx.name, xalign=0.0)
            name.add_css_class("fx-name")
            b = Gtk.Button(child=vbox(6, strip, name))
            b.add_css_class("fx-card")
            b.set_tooltip_text(fx.blurb)
            b.connect("clicked", lambda _b, f=fx: self._apply_effect(f.id))
            b.set_size_request(150, -1)
            grid.append(b)
            self.fx_cards[fx.id] = b
        page.append(grid)
        return page

    def _card_frame(self, fx):
        layer = self.layer()
        cols = layer.colors if layer and layer.effect == fx.id else \
            self.memory.get((self.zi, fx.id))
        speed = layer.speed if layer and layer.effect == fx.id else 1.0
        return fx.frame(self.engine.now(), 16, cols, speed)

    def _freestyle_page(self):
        page = vbox(14)
        page.append(eyebrow("Brush"))
        self.brush_tile = swatch(lambda: [self.brush], 64, 64, 12)
        brush_pick = Gtk.Button(label="Brush colour…")
        brush_pick.connect("clicked", lambda *_: self._choose_color(
            self.brush, self._set_brush))
        hint = self._dim("Click or drag across the LEDs in the preview above "
                         "to paint them one by one.")
        hint.set_wrap(True)
        page.append(hbox(14, self.brush_tile,
                         vbox(8, hint, hbox(8, brush_pick)), ))

        quick = self._flow(8, 16, 8)
        for hexval, name in PRESETS:
            rgb = hex_to_rgb(hexval)
            b = Gtk.Button(child=swatch([rgb], 34, 30, 6))
            b.add_css_class("swatch")
            b.set_tooltip_text(name)
            b.connect("clicked", lambda _b, c=rgb: self._set_brush(c))
            quick.append(b)
        page.append(quick)

        page.append(margins(eyebrow("Tools"), 6, 0, 0, 0))
        fill = Gtk.Button(label="Fill zone with brush")
        fill.connect("clicked", lambda *_: self._paint_fill())
        rain = Gtk.Button(label="Rainbow fill")
        rain.connect("clicked", lambda *_: self._paint_rainbow())
        alt = Gtk.Button(label="Alternate with brush")
        alt.connect("clicked", lambda *_: self._paint_alternate())
        clear = Gtk.Button(label="Clear")
        clear.add_css_class("danger")
        clear.connect("clicked", lambda *_: self._paint_fill((0, 0, 0)))
        page.append(hbox(8, fill, rain, alt, clear))
        return page

    def _settings_panel(self):
        panel = vbox(16)
        panel.add_css_class("settings")
        panel.set_size_request(320, -1)
        inner = vbox(16)
        margins(inner, 18, 20, 18, 20)
        panel.append(inner)

        inner.append(eyebrow("Effect"))
        self.fx_title = Gtk.Label(label="--", xalign=0.0)
        self.fx_title.add_css_class("fx-title")
        self.fx_blurb = self._dim("")
        self.fx_blurb.set_wrap(True)
        self.fx_blurb.set_max_width_chars(34)
        inner.append(vbox(4, self.fx_title, self.fx_blurb))

        # Colours
        self.colors_box = vbox(8)
        self.colors_box.append(eyebrow("Colours"))
        self.chip_box = self._flow(6, 8, 6)
        self.colors_box.append(self.chip_box)
        self.hex_entry = Gtk.Entry(placeholder_text="#00b8fc")
        self.hex_entry.set_width_chars(9)
        self.hex_entry.connect("activate", lambda *_: self._add_hex())
        add = Gtk.Button(label="Add")
        add.connect("clicked", lambda *_: self._add_hex())
        pick = Gtk.Button(label="Pick colour…")
        pick.add_css_class("accent")
        pick.connect("clicked", lambda *_: self._pick_color())
        self.colors_box.append(hbox(6, self.hex_entry, add, pick))
        self.colors_hint = self._dim("Click a colour to remove it.")
        self.colors_box.append(self.colors_hint)
        inner.append(self.colors_box)

        # Speed / direction
        self.speed_box = vbox(8)
        self.speed_box.append(eyebrow("Speed"))
        self.speed_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.1, 4.0, 0.05)
        self.speed_scale.set_draw_value(True)
        self.speed_scale.set_digits(2)
        self.speed_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.speed_scale.add_mark(1.0, Gtk.PositionType.BOTTOM, None)
        self.speed_scale.connect("value-changed", self._speed_changed)
        self.speed_box.append(self.speed_scale)
        self.reverse_sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.reverse_sw.connect("notify::active", self._reverse_changed)
        self.speed_box.append(hbox(8, Gtk.Label(label="Reverse direction"),
                                   spacer(), self.reverse_sw))
        inner.append(self.speed_box)

        # Brightness
        inner.append(eyebrow("Zone brightness"))
        self.bright_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.bright_scale.set_draw_value(True)
        self.bright_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.bright_scale.connect("value-changed", self._bright_changed)
        inner.append(self.bright_scale)
        return panel

    @staticmethod
    def _dim(text):
        lbl = Gtk.Label(label=text, xalign=0.0)
        lbl.add_css_class("dim")
        return lbl

    # ------------------------------------------------------- backend glue
    def _engine_status(self, ok, msg):
        GLib.idle_add(self._show_conn, ok, msg)

    def _show_conn(self, ok, msg):
        self.conn.set_label("CONNECTED" if ok else "OFFLINE")
        for c in ("ok", "bad"):
            self.conn.remove_css_class(c)
        self.conn.add_css_class("ok" if ok else "bad")
        self._set_status(msg, error=not ok)
        if ok and not self.zones and self.engine.ready.is_set():
            self._on_ready()
        return False

    def _on_ready(self):
        if not self.engine.ready.is_set() or self.zones:
            return False
        self.zones = self.engine.zones
        # Restore the saved lighting so the panel picks up where the
        # background player (or the last session) left off.
        for zi in range(len(self.zones)):
            layer = self.saved.layer_for(self.zname(zi))
            if layer is not None:
                self.layers[zi] = layer.copy()
                self.engine.set_layer(zi, layer)
        self.engine.set_master(self.master)
        self._build_zone_rows()
        self.zi = default_zone_index(self.zones, self.labels)
        self.zone_list.select_row(self.zone_list.get_row_at_index(self.zi))
        return False

    def _build_zone_rows(self):
        child = self.zone_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.zone_list.remove(child)
            child = nxt
        self.zone_rows = []
        for zi in range(len(self.zones)):
            title = Gtk.Label(label=self.zlabel(zi), xalign=0.0)
            title.add_css_class("zone-name")
            sub = self._dim("")
            strip = LedStrip(lambda z=zi: self.zone_frame(z)[:40], height=22,
                             pad=2)
            row = Gtk.ListBoxRow()
            row.set_child(vbox(6, hbox(8, title, spacer(), sub), strip))
            self.zone_list.append(row)
            self.zone_rows.append((row, sub, strip))
        self._refresh_zone_subs()

    def _refresh_zone_subs(self):
        for zi, (_row, sub, _strip) in enumerate(self.zone_rows):
            layer = self.layers.get(zi)
            sub.set_label(layer.fx.name if layer else "not set")

    def _tick(self):
        if self._closed:
            return False
        self.preview.queue_draw()
        for _row, _sub, strip in self.zone_rows:
            strip.queue_draw()
        page = self.stack.get_visible_child_name()
        if page == "animations":
            for b in self.fx_cards.values():
                b.get_child().get_first_child().queue_draw()
        elif page == "presets":
            self.stack.get_visible_child().queue_draw()
        return True

    def _set_status(self, text, error=False):
        self.status.set_label(text)
        if error:
            self.status.add_css_class("error")
        else:
            self.status.remove_css_class("error")

    def _schedule_save(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(600, self._save_now)

    def _save_now(self):
        self._save_id = 0
        state.save_lighting(self.current_lighting(), self.settings,
                            self.active_profile)
        return False

    def current_lighting(self):
        zones = {self.zname(zi): l.copy() for zi, l in self.layers.items()}
        return Lighting(zones, self.master)

    # -------------------------------------------------------------- edits
    def _targets(self):
        return list(range(len(self.zones))) if self.sync_all else [self.zi]

    def _edit(self, fn, status=None):
        """Apply ``fn(layer, zone)`` to the target zones and push them."""
        if not self.zones:
            return
        for zi in self._targets():
            layer = self.layers.get(zi)
            if layer is None:
                layer = Layer("static", [ACCENT])
            fn(layer, zi)
            self.layers[zi] = layer
            self.engine.set_layer(zi, layer)
        self._schedule_save()
        self._refresh_zone_subs()
        self._refresh_settings()
        if status:
            where = "all zones" if self.sync_all else self.zlabel(self.zi)
            self._set_status(f"{where}: {status}")

    def _apply_effect(self, eid, colors=None, speed=None):
        fx = effects.get(eid)

        def fn(layer, zi):
            if layer.effect != eid and fx.uses_colors:
                self.memory[(zi, layer.effect)] = list(layer.colors)
            layer.effect = eid
            if colors is not None:
                layer.colors = list(colors)
            elif fx.uses_colors:
                layer.colors = list(self.memory.get((zi, eid))
                                    or fx.default_colors)
            if speed is not None:
                layer.speed = speed
        self._edit(fn, fx.name)

    def _apply_solid(self, rgb):
        self._apply_effect("static", [rgb])

    def _set_colors(self, cols):
        def fn(layer, zi):
            if not layer.fx.uses_colors or layer.effect == "custom":
                layer.effect = "static"
            layer.colors = list(cols)
            self.memory[(zi, layer.effect)] = list(cols)
        self._edit(fn, " ".join(rgb_to_hex(c) for c in cols))

    def _add_color(self, rgb):
        layer = self.layer()
        cur = list(layer.colors) if layer else []
        if layer is None or layer.fx.single or layer.effect == "custom" \
                or not layer.fx.uses_colors:
            cur = []
        self._set_colors(cur + [rgb])

    def _remove_color(self, index):
        layer = self.layer()
        if layer and len(layer.colors) > 1 and 0 <= index < len(layer.colors):
            cols = list(layer.colors)
            cols.pop(index)
            self._set_colors(cols)

    def _add_hex(self):
        try:
            self._add_color(hex_to_rgb(self.hex_entry.get_text()))
            self.hex_entry.set_text("")
        except ValueError:
            self._set_status("Not a valid colour -- use RRGGBB, e.g. 00b8fc",
                             error=True)

    def _choose_color(self, initial, on_done):
        dialog = Gtk.ColorDialog()
        # GTK 4.22's ColorDialog has no set_with_rgba(); set_with_alpha() only
        # controls whether an alpha channel is shown. The opening colour is
        # passed to choose_rgba() instead.
        dialog.set_with_alpha(False)
        start = Gdk.RGBA()
        start.red, start.green, start.blue = (c / 255.0 for c in initial)
        start.alpha = 1.0

        def done(dlg, result):
            try:
                rgba = dlg.choose_rgba_finish(result)
            except GLib.Error:
                return
            on_done((int(rgba.red * 255), int(rgba.green * 255),
                     int(rgba.blue * 255)))

        # choose_rgba(self, parent, initial_color, cancellable, callback)
        dialog.choose_rgba(self, start, None, done)

    def _pick_color(self):
        layer = self.layer()
        seed = layer.colors[-1] if layer and layer.colors else ACCENT
        self._choose_color(seed, self._add_color)

    def _speed_changed(self, scale):
        if not self._quiet:
            v = scale.get_value()
            self._edit(lambda l, _z: setattr(l, "speed", v))

    def _reverse_changed(self, sw, _p):
        if not self._quiet:
            v = sw.get_active()
            self._edit(lambda l, _z: setattr(l, "reverse", v))

    def _bright_changed(self, scale):
        if not self._quiet:
            v = int(scale.get_value())
            self._edit(lambda l, _z: setattr(l, "brightness", v))

    def _master_changed(self, scale):
        self.master = int(scale.get_value())
        self.engine.set_master(self.master)
        self._schedule_save()

    def _leds_changed(self, spin):
        if self._quiet or not self.zones:
            return
        n = int(spin.get_value())
        layer = self.layer()
        if layer is None:
            return
        layer.leds = n
        if layer.effect == "custom":
            layer.colors = (layer.colors + [(0, 0, 0)] * n)[:n]
        self.engine.set_layer(self.zi, layer)
        self._schedule_save()
        self._refresh_zone_header()

    def _sync_changed(self, sw, _p):
        self.sync_all = sw.get_active()
        self._set_status("Edits now apply to every zone" if self.sync_all
                         else f"Edits apply to {self.zlabel(self.zi)} only")

    def _all_off(self):
        old = self.sync_all
        self.sync_all = True
        self._apply_effect("static", [(0, 0, 0)])
        self.sync_all = old
        self._set_status("All zones off")

    # ----------------------------------------------------------- freestyle
    def _set_brush(self, rgb):
        self.brush = rgb
        self.brush_tile.queue_draw()
        self._set_status(f"Brush {rgb_to_hex(rgb)}")

    def _custom_layer(self):
        """The selected zone's layer as a Freestyle canvas."""
        if not self.zones:
            return None
        layer = self.layers.get(self.zi)
        n = self.engine.zone_size(self.zi)
        if layer is None or layer.effect != "custom":
            # Start from what is showing so painting feels like touching up.
            seen = layer.frame(self.engine.now(), n) if layer else \
                [(0, 0, 0)] * n
            leds = layer.leds if layer else 0
            bright = layer.brightness if layer else 100
            layer = Layer("custom", seen, brightness=bright, leds=leds)
            self.layers[self.zi] = layer
        if len(layer.colors) < n:
            layer.colors += [(0, 0, 0)] * (n - len(layer.colors))
        return layer

    def _paint_at(self, x, prev=None):
        """Paint the LED under ``x``, and every LED back to ``prev``.

        Drag events arrive far apart when the pointer moves fast; filling the
        run between them stops a quick stroke from leaving gaps.
        """
        if self.stack.get_visible_child_name() != "freestyle":
            return None
        i = self.preview.index_at(x)
        layer = self._custom_layer()
        if i is None or layer is None:
            return prev
        lo, hi = (i, i) if prev is None else (min(i, prev), max(i, prev))
        changed = False
        for k in range(lo, hi + 1):
            if layer.colors[k] != self.brush:
                layer.colors[k] = self.brush
                changed = True
        if changed:
            self.engine.set_layer(self.zi, layer)
            self._schedule_save()
            self._refresh_zone_subs()
            self._refresh_settings()
        return i

    def _paint_begin(self, gesture, x, _y):
        self._drag_x = x
        self._drag_led = self._paint_at(x)

    def _paint_update(self, gesture, dx, _dy):
        self._drag_led = self._paint_at(self._drag_x + dx, self._drag_led)

    def _paint_with(self, make):
        layer = self._custom_layer()
        if layer is None:
            return
        n = self.engine.zone_size(self.zi)
        layer.colors = make(n)
        self.engine.set_layer(self.zi, layer)
        self._schedule_save()
        self._refresh_zone_subs()
        self._refresh_settings()

    def _paint_fill(self, rgb=None):
        c = rgb or self.brush
        self._paint_with(lambda n: [c] * n)

    def _paint_rainbow(self):
        self._paint_with(lambda n: effects.get("rainbow").frame(0, n))

    def _paint_alternate(self):
        layer = self._custom_layer()
        if layer is None:
            return
        old = list(layer.colors)
        self._paint_with(lambda n: [self.brush if i % 2 == 0 else old[i]
                                    for i in range(n)])

    # ---------------------------------------------------------- selection
    def _zone_selected(self, _box, row):
        if row is None:
            return
        self.zi = row.get_index()
        self._refresh_settings()

    def _tab_toggled(self, btn, name):
        if btn.get_active():
            self.stack.set_visible_child_name(name)
            painting = name == "freestyle"
            self.preview.set_cursor_from_name(
                "crosshair" if painting else None)
            if painting:
                self._set_status("Freestyle: paint LEDs in the preview")

    def _refresh_zone_header(self):
        if not self.zones:
            return
        z = self.zones[self.zi]
        n = self.engine.zone_size(self.zi)
        self.zone_title.set_label(self.zlabel(self.zi).upper())
        self.zone_sub.set_label(f"{self.zname(self.zi)}  ·  {n} LEDs  "
                                f"·  max {z['leds_max']}")
        self._quiet = True
        self.leds_spin.set_range(1, max(z["leds_max"], 1))
        self.leds_spin.set_value(n)
        self._quiet = False

    def _refresh_settings(self):
        """Bring every control in line with the selected zone's layer."""
        self._refresh_zone_header()
        layer = self.layer()
        fx = layer.fx if layer else None
        self.fx_title.set_label(fx.name if fx else "Nothing set")
        self.fx_blurb.set_label(fx.blurb if fx else
                                "Pick a preset or an animation to light "
                                "this zone.")
        for eid, card in self.fx_cards.items():
            if layer and layer.effect == eid:
                card.add_css_class("active")
            else:
                card.remove_css_class("active")

        show_cols = fx is None or (fx.uses_colors and fx.id != "custom")
        self.colors_box.set_visible(show_cols)
        self.speed_box.set_visible(bool(fx and fx.animated))
        self.colors_hint.set_label(
            "Only the first colour is used." if fx and fx.single
            else "Click a colour to remove it.")

        self._quiet = True
        self.speed_scale.set_value(layer.speed if layer else 1.0)
        self.reverse_sw.set_active(layer.reverse if layer else False)
        self.bright_scale.set_value(layer.brightness if layer else 100)
        self._quiet = False
        self._render_chips(layer.colors if layer and show_cols else [])

    def _render_chips(self, cols):
        child = self.chip_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.chip_box.remove(child)
            child = nxt
        for i, rgb in enumerate(cols):
            b = Gtk.Button(child=swatch([rgb], 30, 30, 6))
            b.add_css_class("swatch")
            # FlowBox stretches children along the cross axis; pin both axes
            # so chips stay swatch-sized instead of filling the row.
            b.set_halign(Gtk.Align.START)
            b.set_valign(Gtk.Align.START)
            b.set_tooltip_text(f"{rgb_to_hex(rgb)} -- click to remove")
            b.connect("clicked", lambda _b, k=i: self._remove_color(k))
            self.chip_box.append(b)

    # ------------------------------------------------------------ profiles
    def _reload_profiles(self, select=None):
        self.profiles = state.all_profiles()
        # Row 0 stands for "whatever is set now", which no profile matches.
        names = [CUSTOM] + list(self.profiles)
        self._profile_names = names
        self._quiet = True
        self.profile_dd.set_model(Gtk.StringList.new(names))
        want = select or self.active_profile
        self.profile_dd.set_selected(names.index(want) if want in names
                                     else 0)
        self._quiet = False
        self._refresh_delete()

    def _refresh_delete(self):
        self.del_btn.set_sensitive(bool(
            self.active_profile
            and self.active_profile not in state.BUILTIN_PROFILES))

    def _profile_selected(self, dd, _p):
        if self._quiet:
            return
        i = dd.get_selected()
        if not 0 <= i < len(self._profile_names):
            return
        name = self._profile_names[i]
        if name == CUSTOM:
            return
        lighting = self.profiles[name]
        self.active_profile = name
        self.master = lighting.master
        self._quiet = True
        self.master_scale.set_value(self.master)
        self._quiet = False
        self.engine.set_master(self.master)
        for zi in range(len(self.zones)):
            layer = lighting.layer_for(self.zname(zi))
            if layer is not None:
                keep = self.layers[zi].leds if zi in self.layers else 0
                self.layers[zi] = layer.copy()
                if not self.layers[zi].leds:
                    self.layers[zi].leds = keep
                self.engine.set_layer(zi, self.layers[zi])
        self._schedule_save()
        self._refresh_zone_subs()
        self._refresh_settings()
        self._refresh_delete()
        self._set_status(f"Profile: {name}")

    def _save_profile(self, pop):
        name = self.save_entry.get_text().strip()
        if not name or name == CUSTOM:
            return
        state.save_profile(name, self.current_lighting())
        self.active_profile = name
        self.save_entry.set_text("")
        pop.popdown()
        self._reload_profiles(name)
        self._schedule_save()
        self._set_status(f"Saved profile “{name}”")

    def _delete_profile(self):
        name = self.active_profile
        if name and state.delete_profile(name):
            self.active_profile = None
            self._reload_profiles()
            self._schedule_save()
            self._set_status(f"Deleted profile “{name}”")

    # ------------------------------------------------------------- settings
    def _keep_changed(self, sw, _p):
        self.settings["keep_running"] = sw.get_active()
        self._schedule_save()

    def _reread(self):
        self.engine.stop()
        self.engine.join(2)
        self.zones = []
        self.saved = self.current_lighting()
        self.engine = Engine(on_status=self._engine_status, connect_timeout=3)
        self.engine.start()
        self._set_status("Re-reading zones from the board...")

    # ------------------------------------------------------------ shutdown
    def shutdown(self, handoff=True):
        """Save, release the board and, if wanted, hand it to the player."""
        if self._closed:
            return
        self._closed = True
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = 0
        lighting = self.current_lighting()
        state.save_lighting(lighting, self.settings, self.active_profile)
        self.engine.stop()
        self.engine.join(2)
        animated = any(l.fx.animated for l in self.layers.values())
        if handoff and animated and self.settings.get("keep_running", True):
            runtime.start_background()

    def do_close_request(self):                     # noqa: N802 (GTK API)
        self.shutdown()
        return False


class RGBApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):                          # noqa: N802 (GTK API)
        wins = self.get_windows()
        if wins:
            wins[0].present()
            return
        RGBWindow(self).present()


def _self_test():
    """Prove the panel constructs, reads zones and opens the colour picker.

    Constructing the window is not enough -- the picker bug only appeared when
    the button was pressed. So this clicks the real button rather than calling
    the handler directly, which is what let two broken versions of
    _pick_color() pass an earlier check. It also visits every tab and draws
    every effect card, so a broken effect shows up here too.

    Needs a display, since the picker dialog is parented to a mapped window.

    Run with:  msirgb-gui --self-test
    """
    results = {"player_was_running": runtime.player_running()}

    class _App(Gtk.Application):
        def do_activate(self):                      # noqa: N802 (GTK API)
            win = RGBWindow(self)
            win.present()

            def find_btn(node, text):
                if isinstance(node, Gtk.Button):
                    if text in (node.get_label() or ""):
                        return node
                child = node.get_first_child()
                while child:
                    hit = find_btn(child, text)
                    if hit:
                        return hit
                    child = child.get_next_sibling()
                return None

            def check():
                results["zones"] = [win.zlabel(i)
                                    for i in range(len(win.zones))]
                results["leds"] = win.leds_spin.get_value()
                try:
                    for name in ("presets", "freestyle", "animations"):
                        win.tab_btns[name].set_active(True)
                    for fx in effects.EFFECTS:
                        assert len(fx.frame(win.engine.now(), 30)) == 30
                    results["tabs"] = "ok"
                except Exception as e:                # noqa: BLE001
                    results["tabs"] = f"{type(e).__name__}: {e}"
                btn = find_btn(win.get_child(), "Pick colour")
                results["picker_button_found"] = btn is not None
                if btn is not None:
                    try:
                        btn.emit("clicked")
                        results["picker"] = "ok"
                    except Exception as e:            # noqa: BLE001
                        results["picker"] = f"{type(e).__name__}: {e}"
                print("zones: " + ", ".join(results.get("zones", [])))
                print(f"leds in selected zone: {results.get('leds')}")
                print(f"tabs and effects: {results.get('tabs')}")
                print(f"picker button found: {results.get('picker_button_found')}")
                print(f"picker: {results.get('picker', 'NOT REACHED')}")
                # Leave the background player as it was found: a test must not
                # start one behind a panel the user has open.
                win.shutdown(handoff=results["player_was_running"])
                self.quit()
                return False

            GLib.timeout_add(2500, check)

    app = _App(application_id=APP_ID + ".selftest")
    app.run([])
    ok = results.get("picker") == "ok" and results.get("tabs") == "ok" \
        and bool(results.get("zones"))
    if not ok:
        print("SELF-TEST FAILED")
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        print("self-test: constructs the panel, reads zones, visits every tab "
              "and clicks the colour picker.")
        return _self_test()
    return RGBApp().run(argv)


if __name__ == "__main__":
    sys.exit(main())
