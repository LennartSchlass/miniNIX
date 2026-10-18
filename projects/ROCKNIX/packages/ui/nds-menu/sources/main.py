#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026-present ROCKNIX (https://github.com/ROCKNIX)

# DS-style launcher for the Anbernic RG DS. One 1280x480 window spans both panels like
# DraStic's does: the left half is the top screen (banner, clock, battery, help), the
# right half the touch screen (a shelf of game cards, settings pages, standby).

import ctypes
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sdl2 as sdl  # noqa: E402

HERE = Path(__file__).resolve().parent
ROMS = Path(os.environ.get("NDS_MENU_ROMS", "/storage/roms/nds"))
CFG = Path(os.environ.get("NDS_MENU_CFG", "/storage/.config/system/configs/system.cfg"))
FONT = str(HERE / "fonts" / "PixelOperator.ttf")
FONT_BOLD = str(HERE / "fonts" / "PixelOperator-Bold.ttf")
APP_ID = "ndsmenu"
TOUCH_ID = "1046:911:Goodix_Capacitive_TouchScreen"
SCREEN_W, SCREEN_H = 640, 480
WIN_W, WIN_H = 2 * SCREEN_W, SCREEN_H
STEP = 170          # distance between cards on the shelf
SHELF_Y = 214       # vertical centre of the shelf
NO_SWAY = bool(os.environ.get("NDS_MENU_NO_SWAY"))
ROW_H, ROW_Y0, ROWS = 54, 72, 6

# DS Lite inspired palette
C_TOP_BG = (236, 241, 246)
C_TOP_BAR = (196, 218, 236)
C_BOTTOM_BG = (221, 231, 240)
C_STRIPE = (255, 255, 255, 90)
C_WHITE = (255, 255, 255)
C_BORDER = (160, 183, 203)
C_SELECT = (54, 138, 222)
C_GLOW = (54, 138, 222, 70)
C_TEXT = (38, 48, 62)
C_TEXT_DIM = (108, 120, 136)
C_SHADOW = (0, 0, 0, 28)
C_GREEN = (82, 176, 94)
C_ORANGE = (236, 150, 48)
C_RED = (224, 72, 72)
C_CARD_NOTCH = (206, 216, 226)
C_TRACK = (200, 212, 224)

DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]

SHADERS = [("nitro-sharp", "nitro-sharp"), ("sharp-shimmerless", "sharp-shimmerless"),
           ("sharp-bilinear", "sharp-bilinear"), ("bilinear", "bilinear (weich)"), ("quilez", "quilez"),
           ("scanlines", "scanlines"), ("lcd3x", "lcd3x"), ("lcd1x-nds-color", "lcd1x + nds-color")]
BOLT = ["....##.", "...##..", "..##...", ".######", "....##.", "...##..", "..##...", ".##...."]


class Game:
    def __init__(self, path, name, image, publisher, playcount):
        self.path, self.name, self.image, self.publisher, self.playcount = path, name, image, publisher, playcount
        self.tex = None

    @property
    def title(self):
        return self.name.split(" - ", 1)[0]


class Item:
    def __init__(self, kind, label, help="", get=None, set=None, do=None, choices=None, lo=0, hi=100, step=5, danger=False):
        self.kind, self.label, self.help = kind, label, help
        self.get, self.set, self.do, self.choices = get, set, do, choices
        self.lo, self.hi, self.step, self.danger = lo, hi, step, danger


class Page:
    def __init__(self, title, items, help=""):
        self.title, self.items, self.help = title, items, help
        self.cursor = 0
        self.scroll = 0


# ---------- system helpers ----------
def load_games(romdir):
    games = []
    try:
        root = ET.parse(romdir / "gamelist.xml").getroot()
    except (ET.ParseError, OSError):
        return games
    for g in root.iter("game"):
        p = (g.findtext("path") or "").strip()
        if not p:
            continue
        full = (romdir / p).resolve() if not os.path.isabs(p) else Path(p)
        if not full.exists() or (g.findtext("hidden") or "").strip() == "true":
            continue
        img = (g.findtext("image") or "").strip()
        img = str(romdir / img) if img and not os.path.isabs(img) else img
        try:
            playcount = int(g.findtext("playcount") or 0)
        except ValueError:
            playcount = 0
        games.append(Game(str(full), (g.findtext("name") or "").strip() or full.stem, img,
                          (g.findtext("publisher") or "").strip(), playcount))
    games.sort(key=lambda g: g.name.lower())
    return games


def battery():
    fake = os.environ.get("NDS_MENU_FAKE_BATTERY")
    if fake:
        return int(fake.rstrip("+")), fake.endswith("+")
    for d in glob.glob("/sys/class/power_supply/[Bb][Aa][Tt]*"):
        try:
            cap = int(open(d + "/capacity").read())
            status = open(d + "/status").read().strip().lower()
            return cap, status in ("charging", "full")
        except (OSError, ValueError):
            pass
    return None, False


def run(cmd, capture=False):
    if NO_SWAY:
        print("would run:", " ".join(cmd), file=sys.stderr)
        return ""
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
        return r.stdout.decode(errors="replace") if capture else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def sway(*args, capture=False):
    return run(["swaymsg", *args], capture)


def window_rect(app_id):
    tree = sway("-t", "get_tree", capture=True)
    try:
        nodes = [json.loads(tree)] if tree else []
    except ValueError:
        return None
    while nodes:
        n = nodes.pop()
        if n.get("app_id") == app_id:
            r = n.get("rect", {})
            return r.get("x"), r.get("y"), r.get("width"), r.get("height")
        nodes.extend(n.get("nodes", []) + n.get("floating_nodes", []))
    return None


def second_output():
    pri = os.environ.get("SDL_VIDEO_DISPLAY_PRIORITY", "")
    return pri.split(",")[1] if "," in pri else ""


def cfg_read():
    d = {}
    try:
        for line in CFG.read_text(errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k] = v
    except OSError:
        pass
    return d


def cfg_set(key, value):
    """Like set_setting / del_setting (value None): one key=value line per setting."""
    try:
        lines = CFG.read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    lines = [l for l in lines if not l.startswith(key + "=")]
    if value is not None:
        lines.append(f"{key}={value}")
    tmp = CFG.with_name(CFG.name + ".ndsmenu")
    try:
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(tmp, CFG)
    except OSError as e:
        print("cannot write", CFG, e, file=sys.stderr)


def backlights():
    devs = sorted(glob.glob("/sys/class/backlight/*"))
    if not devs and os.environ.get("NDS_MENU_FAKE_BACKLIGHTS"):
        return [None] * int(os.environ["NDS_MENU_FAKE_BACKLIGHTS"])
    return devs


def backlight_percent(dev):
    if dev is None:
        return 70
    try:
        return round(100 * int(open(dev + "/brightness").read()) / max(1, int(open(dev + "/max_brightness").read())))
    except (OSError, ValueError):
        return 50


def ip_address():
    out = run(["ip", "-4", "-o", "addr", "show"], capture=True)
    for pref in ("wlan", "eth", "usb", "end"):
        for line in out.splitlines():
            m = re.match(r"\d+:\s+(\S+)\s+inet\s+([\d.]+)", line)
            if m and m.group(1).startswith(pref):
                return m.group(2)
    return "nicht verbunden"


def os_release(key):
    try:
        for line in open("/etc/os-release"):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def free_space(path):
    try:
        st = shutil.disk_usage(path)
        return f"{st.free / 2**30:.1f} GB frei von {st.total / 2**30:.0f} GB"
    except OSError:
        return "?"


def uptime():
    try:
        s = int(float(open("/proc/uptime").read().split()[0]))
        return f"{s // 3600} h {s % 3600 // 60} min"
    except (OSError, ValueError):
        return "?"


def ease(t):
    return 1 - (1 - t) ** 3


class Menu:
    def __init__(self):
        self.games = []
        self.sel = 0
        self.pos = 0.0
        self.anim_from = 0.0
        self.anim_t0 = 0.0
        self.animating = False
        self.drag = None          # [x0, pos0, moved, samples]
        self.slider_drag = None   # (item, x, w) being dragged
        self.held = 0
        self.next_repeat = 0.0
        self.axis_dir = 0
        self.controllers = {}
        self.joysticks = {}
        self.textures = {}        # text cache
        self.shapes = {}          # corner textures per radius
        self.bitmaps = {}
        self.stripe_rects = {}
        self.fonts = {}
        self.dirty = True
        self.quit = False
        self.gamelist_mtime = 0
        self.last_check = 0.0
        self.child = None         # Popen of the running game or EmulationStation
        self.child_kind = ""
        self.child_label = ""
        self.child_seen = 0.0
        self.bottom_restore = False
        self.pages = []           # settings page stack, empty = the shelf
        self.confirm = None       # [message, callback, cursor]
        self.touch_log = 0
        self.pads = False

    # ---------- setup ----------
    def run(self):
        # SDL takes the Wayland app id from the environment; children (DraStic,
        # EmulationStation) get it scrubbed again so sway's rules still recognise them
        os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
        os.environ["SDL_VIDEO_WAYLAND_WMCLASS"] = APP_ID
        os.environ["SDL_APP_ID"] = APP_ID
        sdl.SetHint(sdl.HINT_APP_NAME, APP_ID.encode())
        sdl.SetHint(sdl.HINT_VIDEO_WAYLAND_WMCLASS, APP_ID.encode())
        sdl.SetHint(sdl.HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")
        sdl.SetHint(sdl.HINT_TOUCH_MOUSE_EVENTS, b"0")
        sdl.SetHint(sdl.HINT_MOUSE_TOUCH_EVENTS, b"1")
        self.pads = sdl.Init(sdl.INIT_VIDEO | sdl.INIT_EVENTS | sdl.INIT_JOYSTICK | sdl.INIT_GAMECONTROLLER) == 0
        if not self.pads:
            print("no controller support:", sdl.error(), file=sys.stderr)
            if sdl.Init(sdl.INIT_VIDEO | sdl.INIT_EVENTS) != 0:
                print("SDL_Init:", sdl.error(), file=sys.stderr)
                return 1
        sdl.IMG_Init(sdl.IMG_INIT_PNG)
        sdl.TTF_Init()

        sway("for_window", f'[app_id="{APP_ID}"]', "floating", "enable,", "border", "none,",
             "resize", "set", str(WIN_W), str(WIN_H) + ",", "move", "absolute", "position", "0", "0")
        self.window = sdl.CreateWindow(APP_ID.encode(), 0, 0, WIN_W, WIN_H, sdl.WINDOW_SHOWN | sdl.WINDOW_BORDERLESS)
        if not self.window:
            print("SDL_CreateWindow:", sdl.error(), file=sys.stderr)
            return 1
        self.renderer = sdl.CreateRenderer(self.window, -1, sdl.RENDERER_ACCELERATED | sdl.RENDERER_PRESENTVSYNC)
        if not self.renderer:
            print("SDL_CreateRenderer:", sdl.error(), file=sys.stderr)
            return 1
        sdl.SetRenderDrawBlendMode(self.renderer, sdl.BLENDMODE_BLEND)
        self.show_both_screens()
        self.reload_games()
        self.open_controllers()

        shot = os.environ.get("NDS_MENU_SHOT")
        if shot:
            self.select(int(os.environ.get("NDS_MENU_SEL", "0")), False)
            panel = os.environ.get("NDS_MENU_PANEL")
            if panel in ("settings", "game"):
                self.child, self.child_kind, self.child_label = True, panel, "Testspiel läuft …"
            elif panel == "confirm":
                self.ask("Gerät ausschalten?", lambda: None)
            elif panel:
                self.open_page("settings" if panel == "menu" else panel)
            self.draw()
            self.screenshot(shot)
            return 0
        self.draw()
        self.place_window()
        if os.environ.get("NDS_MENU_BENCH"):
            self.bench()
        self.loop()
        return 0

    def show_both_screens(self):
        second = second_output()
        if second:
            sway("output", second, "power", "on")
        sway("input", TOUCH_ID, "map_to_region", "0", "0", str(WIN_W), str(WIN_H))
        self.place_window()

    def place_window(self):
        """Sway centres the floating window on the seam between the panels; two separate
        moves put it at the origin (the first one changes its workspace)."""
        if NO_SWAY:
            return
        for _ in range(30):
            r = window_rect(APP_ID)
            if r:
                if r[:2] != (0, 0):
                    sway(f'[app_id="{APP_ID}"]', "move", "absolute", "position", "0", "0")
                    sway(f'[app_id="{APP_ID}"]', "move", "absolute", "position", "0", "0")
                return
            time.sleep(0.1)

    def font(self, size, bold=False):
        key = (size, bold)
        f = self.fonts.get(key)
        if f is None:
            f = sdl.TTF_OpenFont((FONT_BOLD if bold else FONT).encode(), size)
            if f:
                sdl.TTF_SetFontHinting(f, sdl.TTF_HINTING_MONO)
            self.fonts[key] = f
        return f

    def open_controllers(self):
        if not self.pads:
            return
        for i in range(sdl.NumJoysticks()):
            self.open_controller(i)

    def open_controller(self, index):
        if sdl.IsGameController(index):
            c = sdl.GameControllerOpen(index)
            if c:
                self.controllers[index] = c
                name = sdl.GameControllerName(c)
                print("controller:", name.decode(errors="replace") if name else "?", file=sys.stderr)
                return
        j = sdl.JoystickOpen(index)
        if j:
            self.joysticks[index] = j
            name = sdl.JoystickNameForIndex(index)
            print("joystick without mapping:", name.decode(errors="replace") if name else "?", file=sys.stderr)

    # ---------- data ----------
    def reload_games(self):
        current = self.games[self.sel].path if self.games else None
        for g in self.games:
            if g.tex:
                sdl.DestroyTexture(g.tex)
        self.games = load_games(ROMS)
        try:
            self.gamelist_mtime = os.stat(ROMS / "gamelist.xml").st_mtime
        except OSError:
            self.gamelist_mtime = 0
        self.sel = next((i for i, g in enumerate(self.games) if g.path == current), 0)
        self.pos = float(self.sel)
        self.animating = False
        self.dirty = True

    def icon(self, game):
        if game.tex is None:
            game.tex = 0
            if game.image and os.path.exists(game.image):
                surf = sdl.IMG_Load(game.image.encode())
                if surf:
                    tex = sdl.CreateTextureFromSurface(self.renderer, surf)
                    sdl.FreeSurface(surf)
                    if tex:
                        sdl.SetTextureScaleMode(tex, sdl.SCALEMODE_NEAREST)
                        game.tex = tex
        return game.tex or None

    # ---------- settings pages ----------
    def setting(self, key, default=""):
        return cfg_read().get(key, default)

    def game_key(self, game, key):
        return f'nds["{os.path.basename(game.path)}"].{key}'

    def open_page(self, name, game=None):
        builders = {"settings": self.page_settings, "display": self.page_display, "drastic": self.page_drastic,
                    "network": self.page_network, "info": self.page_info}
        if name in builders:
            self.pages.append(builders[name](game) if name == "drastic" else builders[name]())
            self.dirty = True

    def page_settings(self):
        return Page("Einstellungen", [
            Item("action", "Standby", "Gerät schlafen legen. Aufwecken mit der Power-Taste oder durch Aufklappen.", do=self.sleep),
            Item("action", "Neustart", "Gerät neu starten.", do=lambda: self.ask("Gerät neu starten?", lambda: run(["systemctl", "reboot"]))),
            Item("action", "Ausschalten", "Gerät herunterfahren und ausschalten.",
                 do=lambda: self.ask("Gerät ausschalten?", lambda: run(["systemctl", "poweroff"])), danger=True),
            Item("submenu", "Anzeige & Ton", "Helligkeit der Bildschirme und Lautstärke.", do=lambda: self.open_page("display")),
            Item("submenu", "DraStic", "Voreinstellungen für alle Spiele: Bildfilter, Hi-Res 3D, Threaded 3D.", do=lambda: self.open_page("drastic")),
            Item("submenu", "Netzwerk", "SSH, Samba-Freigabe, IP-Adresse. WLAN wird in EmulationStation eingerichtet.", do=lambda: self.open_page("network")),
            Item("submenu", "Info", "Version, Akku, Speicherplatz.", do=lambda: self.open_page("info")),
            Item("submenu", "Erweitert: EmulationStation", "Öffnet die vollständige ROCKNIX-Oberfläche oben, z. B. für WLAN, Bluetooth, Zeitzone.", do=self.emulationstation),
        ])

    def page_display(self):
        items = []
        devs = backlights()
        names = {0: "unten", 1: "oben"} if len(devs) == 2 else {}
        for i, dev in sorted(enumerate(devs), reverse=len(devs) == 2):   # top screen first
            label = "Helligkeit " + names.get(i, str(i + 1)) if len(devs) > 1 else "Helligkeit"
            items.append(Item("slider", label, "Helligkeit dieses Bildschirms in Prozent.",
                              get=lambda d=dev: backlight_percent(d),
                              set=lambda v, n=i + 1: run(["brightness", "set", str(n), str(v)]), lo=5, hi=100, step=5))
        items.append(Item("slider", "Lautstärke", "Lautstärke des Lautsprechers und Kopfhörers.",
                          get=lambda: int(self.setting("audio.volume", "50") or 50),
                          set=lambda v: run(["volume", str(v)]), lo=0, hi=100, step=5))
        return Page("Anzeige & Ton", items)

    def page_drastic(self, game=None):
        key = (lambda k: self.game_key(game, k)) if game else (lambda k: "nds." + k)
        inherit = [("", "wie Voreinstellung")] if game else []
        onoff = inherit + [("1", "an"), ("0", "aus")]

        def getter(k, default):
            return lambda: self.setting(key(k), "" if game else default)

        def setter(k):
            return lambda v: cfg_set(key(k), v if v != "" else None)
        return Page(game.title if game else "DraStic", [
            Item("choice", "Bildfilter", "nitro-sharp: scharf mit gleichmäßig dicken Linien. sharp-shimmerless: scharf, weiche Übergänge. bilinear: weich.",
                 get=getter("shader", "nitro-sharp"), set=setter("shader"), choices=inherit + SHADERS),
            Item("choice", "Hi-Res 3D", "3D in doppelter Auflösung. Auf dem RG DS meist zu langsam.",
                 get=getter("hires_3d", "0"), set=setter("hires_3d"), choices=onoff),
            Item("choice", "Threaded 3D", "3D-Berechnung auf einem eigenen Prozessorkern. Empfohlen: an.",
                 get=getter("threaded_3d", "1"), set=setter("threaded_3d"), choices=onoff),
        ], help="Gilt nur für dieses Spiel." if game else "Voreinstellung für alle Spiele.")

    def page_network(self):
        def service(setting, marker, units):
            def get():
                return self.setting(setting) == "1"

            def set_(on):
                cfg_set(setting, "1" if on else "0")
                for u in units:
                    run(["systemctl", "start" if on else "stop", u])
                run(["systemctl", "enable" if on else "disable", units[0]])
                run(["mkdir", "-p", os.path.dirname(marker)])
                run(["touch", marker] if on else ["rm", "-f", marker])
            return get, set_
        ssh_get, ssh_set = service("ssh.enabled", "/storage/.cache/services/sshd.conf", ["sshd"])
        smb_get, smb_set = service("samba.enabled", "/storage/.cache/services/smb.conf", ["smbd", "nmbd"])
        return Page("Netzwerk", [
            Item("info", "IP-Adresse", "Adresse im WLAN, z. B. für SSH oder die Freigabe \\\\<Adresse>\\roms.", get=ip_address),
            Item("toggle", "SSH", "Zugriff per Terminal (Benutzer root).", get=ssh_get, set=ssh_set),
            Item("toggle", "Samba-Freigabe", "ROMs und Spielstände im Netzwerk freigeben.", get=smb_get, set=smb_set),
            Item("action", "WLAN einrichten (EmulationStation)", "Netzwerk auswählen und Passwort eingeben, oben in EmulationStation.", do=self.emulationstation),
        ])

    def page_info(self):
        cap, charging = battery()
        return Page("Info", [
            Item("info", "Gerät", "", get=lambda: os.environ.get("QUIRK_DEVICE", "Anbernic RG DS")),
            Item("info", "Version", "", get=lambda: f"{os_release('VERSION')}  ({os_release('BUILD_ID')[:7]})"),
            Item("info", "Akku", "", get=lambda: f"{cap}%" + (" (lädt)" if charging else "") if cap is not None else "?"),
            Item("info", "Speicher", "", get=lambda: free_space(str(ROMS))),
            Item("info", "Laufzeit", "", get=uptime),
            Item("info", "Spiele", "", get=lambda: str(len(self.games))),
        ])

    def ask(self, message, callback):
        self.confirm = [message, callback, 1]
        self.dirty = True

    # ---------- drawing primitives ----------
    def corner_tex(self, r):
        """Tiny white rounded square with anti-aliased corners; rounded rectangles of any
        size are drawn from its nine slices, so sizes can animate without new textures."""
        tex = self.shapes.get(r)
        if tex is None:
            size = 2 * r + 2
            buf = bytearray(size * size * 4)
            for y in range(size):
                for x in range(size):
                    cx = r - x - 1 if x < r else x - (size - r) if x >= size - r else -1
                    cy = r - y - 1 if y < r else y - (size - r) if y >= size - r else -1
                    if cx < 0 or cy < 0:
                        a = 255
                    else:
                        a = int(255 * min(1.0, max(0.0, r + 0.5 - math.hypot(cx + 0.5, cy + 0.5))))
                    i = (y * size + x) * 4
                    buf[i:i + 4] = b"\xff\xff\xff" + bytes((a,))
            tex = self.texture_from(buf, size, size)
            self.shapes[r] = tex
        return tex

    def texture_from(self, buf, w, h):
        raw = (ctypes.c_uint8 * len(buf)).from_buffer(buf)
        surf = sdl.CreateRGBSurfaceWithFormatFrom(raw, w, h, 32, w * 4, sdl.PIXELFORMAT_ABGR8888)
        tex = sdl.CreateTextureFromSurface(self.renderer, surf)
        sdl.FreeSurface(surf)
        sdl.SetTextureBlendMode(tex, sdl.BLENDMODE_BLEND)
        sdl.SetTextureScaleMode(tex, sdl.SCALEMODE_NEAREST)
        return tex

    def bitmap(self, name, rows):
        tex = self.bitmaps.get(name)
        if tex is None:
            w, h = len(rows[0]), len(rows)
            buf = bytearray()
            for row in rows:
                for ch in row:
                    buf += b"\xff\xff\xff\xff" if ch == "#" else b"\0\0\0\0"
            tex = self.bitmaps[name] = (self.texture_from(buf, w, h), w, h)
        return tex

    def draw_bitmap(self, name, rows, x, y, scale, color):
        tex, w, h = self.bitmap(name, rows)
        sdl.SetTextureColorMod(tex, color[0], color[1], color[2])
        sdl.SetTextureAlphaMod(tex, 255)
        sdl.RenderCopy(self.renderer, tex, None, sdl.Rect(int(x), int(y), w * scale, h * scale))

    def rect(self, x, y, w, h, color, r=0):
        x, y, w, h = int(x), int(y), int(w), int(h)
        if w <= 0 or h <= 0:
            return
        a = color[3] if len(color) > 3 else 255
        sdl.SetRenderDrawColor(self.renderer, color[0], color[1], color[2], a)
        r = min(r, w // 2, h // 2)
        if r <= 0:
            sdl.RenderFillRect(self.renderer, sdl.Rect(x, y, w, h))
            return
        tex = self.corner_tex(r)
        sdl.SetTextureColorMod(tex, color[0], color[1], color[2])
        sdl.SetTextureAlphaMod(tex, a)
        cols = ((0, r, x, r), (r, 2, x + r, w - 2 * r), (r + 2, r, x + w - r, r))
        rows = ((0, r, y, r), (r, 2, y + r, h - 2 * r), (r + 2, r, y + h - r, r))
        for sy, sh, dy, dh in rows:
            if dh <= 0:
                continue
            for sx, sw, dx, dw in cols:
                if dw > 0:
                    sdl.RenderCopy(self.renderer, tex, sdl.Rect(sx, sy, sw, sh), sdl.Rect(dx, dy, dw, dh))

    def box(self, x, y, w, h, fill, border, bw=2, r=12, alpha=255):
        self.rect(x, y, w, h, (*border[:3], alpha), r)
        self.rect(x + bw, y + bw, w - 2 * bw, h - 2 * bw, (*fill[:3], alpha), max(1, r - bw))

    def text(self, s, x, y, size=16, color=C_TEXT, bold=False, align="left", max_w=None):
        if not s:
            return 0, 0
        key = (s, size, bold, max_w)
        entry = self.textures.get(key)
        if entry is None:
            f = self.font(size, bold)
            if not f:
                return 0, 0
            txt = s
            if max_w:
                while txt and self.measure(f, txt)[0] > max_w:
                    txt = txt[:-1].rstrip()
                if txt != s:
                    txt += "…"
                    while txt[:-1] and self.measure(f, txt)[0] > max_w:
                        txt = txt[:-2].rstrip() + "…"
            surf = sdl.TTF_RenderUTF8_Blended(f, txt.encode(), sdl.Color(255, 255, 255, 255))
            if not surf:
                return 0, 0
            tex = sdl.CreateTextureFromSurface(self.renderer, surf)
            w, h = surf.contents.w, surf.contents.h
            sdl.FreeSurface(surf)
            sdl.SetTextureBlendMode(tex, sdl.BLENDMODE_BLEND)
            if len(self.textures) > 400:
                for t in self.textures.values():
                    sdl.DestroyTexture(t[0])
                self.textures.clear()
            entry = self.textures[key] = (tex, w, h)
        tex, w, h = entry
        if align == "center":
            x -= w // 2
        elif align == "right":
            x -= w
        sdl.SetTextureColorMod(tex, color[0], color[1], color[2])
        sdl.SetTextureAlphaMod(tex, color[3] if len(color) > 3 else 255)
        sdl.RenderCopy(self.renderer, tex, None, sdl.Rect(int(x), int(y), w, h))
        return w, h

    def measure(self, f, s):
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        sdl.TTF_SizeUTF8(f, s.encode(), ctypes.byref(w), ctypes.byref(h))
        return w.value, h.value

    def wrap(self, s, size, max_w, bold=False):
        f = self.font(size, bold)
        lines, cur = [], ""
        for word in s.split():
            trial = (cur + " " + word).strip()
            if cur and f and self.measure(f, trial)[0] > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def stripes(self, x0, y0):
        key = (x0, y0)
        arr = self.stripe_rects.get(key)
        if arr is None:
            ys = list(range(y0, SCREEN_H, 24))
            arr = (sdl.Rect * len(ys))(*[sdl.Rect(x0, y, SCREEN_W, 1) for y in ys])
            self.stripe_rects[key] = arr
        sdl.SetRenderDrawColor(self.renderer, *C_STRIPE)
        sdl.RenderFillRects(self.renderer, arr, len(arr))

    # ---------- screens ----------
    def draw(self):
        sdl.SetRenderDrawColor(self.renderer, *C_TOP_BG, 255)
        sdl.RenderClear(self.renderer)
        self.draw_top()
        self.draw_bottom()
        sdl.RenderPresent(self.renderer)
        self.dirty = False

    def draw_status_bar(self):
        self.rect(0, 0, SCREEN_W, 44, C_TOP_BAR)
        self.rect(0, 44, SCREEN_W, 2, C_BORDER)
        now = datetime.now()
        self.text(f"{DAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}", 16, 12, 16, C_TEXT)
        self.text(now.strftime("%H:%M"), SCREEN_W // 2, 6, 32, C_TEXT, True, "center")
        self.draw_battery(SCREEN_W - 16, 15, C_TOP_BAR)

    def draw_top(self):
        self.stripes(0, 44)
        self.draw_status_bar()
        if self.pages or self.confirm:
            self.draw_help()
            return
        if not self.games:
            self.text("Keine Spiele gefunden", SCREEN_W // 2, 190, 32, C_TEXT, True, "center")
            self.text("ROMs nach roms/nds kopieren und neu starten", SCREEN_W // 2, 240, 16, C_TEXT_DIM, False, "center")
            return
        g = self.games[self.sel]
        bx, by, bw, bh = 60, 92, 520, 216
        self.rect(bx + 4, by + 6, bw, bh, C_SHADOW, 16)
        self.box(bx, by, bw, bh, C_WHITE, C_BORDER, 2, 16)
        ix, iy = bx + 28, by + 44
        self.box(ix - 6, iy - 6, 140, 140, C_WHITE, C_BORDER, 2, 8)
        tex = self.icon(g)
        if tex:
            sdl.RenderCopy(self.renderer, tex, None, sdl.Rect(ix, iy, 128, 128))
        tx = ix + 160
        name, sub = (g.name.split(" - ", 1) + [""])[:2]
        self.text(name, tx, iy + 2, 32, C_TEXT, True, max_w=bw - 200)
        self.text(sub, tx, iy + 44, 16, C_TEXT, max_w=bw - 200)
        self.text(g.publisher, tx, iy + 72, 16, C_TEXT_DIM, max_w=bw - 200)
        if g.playcount:
            self.text(f"{g.playcount}× gespielt", tx, iy + 104, 16, C_TEXT_DIM)
        self.draw_dots(SCREEN_W // 2, by + bh + 26)
        self.text("<  >  Auswahl      A  Start      SELECT  Einstellungen", SCREEN_W // 2, SCREEN_H - 36, 16, C_TEXT_DIM, False, "center")

    def draw_help(self):
        bx, by, bw, bh = 60, 92, 520, 216
        self.rect(bx + 4, by + 6, bw, bh, C_SHADOW, 16)
        self.box(bx, by, bw, bh, C_WHITE, C_BORDER, 2, 16)
        if self.confirm:
            title, help = "Bitte bestätigen", self.confirm[0]
        else:
            page = self.pages[-1]
            title = page.title
            item = page.items[page.cursor] if page.items else None
            help = (item.help if item and item.help else page.help) or ""
        self.text(title, bx + 24, by + 24, 32, C_TEXT, True, max_w=bw - 48)
        y = by + 80
        for line in self.wrap(help, 16, bw - 48)[:5]:
            self.text(line, bx + 24, y, 16, C_TEXT)
            y += 24
        self.text("A  Wählen      B  Zurück      <  >  Ändern", SCREEN_W // 2, SCREEN_H - 36, 16, C_TEXT_DIM, False, "center")

    def draw_dots(self, cx, cy):
        n = len(self.games)
        if n <= 1:
            return
        if n <= 24:
            x0 = cx - (n - 1) * 7
            for i in range(n):
                self.rect(x0 + i * 14 - 3, cy - 3, 6, 6, C_SELECT if i == self.sel else C_BORDER, 3)
        else:
            w = 300
            self.rect(cx - w // 2, cy - 2, w, 4, C_BORDER, 2)
            self.rect(cx - w // 2 + int((w - 24) * self.sel / (n - 1)), cy - 4, 24, 8, C_SELECT, 4)

    def draw_battery(self, right, y, bg, scale=1):
        cap, charging = battery()
        w, h = 30 * scale, 14 * scale
        x = right - w - 3 * scale
        label = (f"{cap}%" if cap is not None else "") + ("  lädt" if charging else "")
        if label:
            self.text(label, x - 8 * scale, y - 2 * scale, 16 * scale, C_GREEN if charging else C_TEXT, charging, "right")
        self.rect(x, y, w, h, C_TEXT, 3 * scale)
        self.rect(x + 2 * scale, y + 2 * scale, w - 4 * scale, h - 4 * scale, bg, 2 * scale)
        self.rect(x + w, y + 4 * scale, 3 * scale, h - 8 * scale, C_TEXT, scale)
        if cap is not None:
            c = C_GREEN if charging or cap > 40 else C_ORANGE if cap > 15 else C_RED
            self.rect(x + 3 * scale, y + 3 * scale, max(1, int((w - 6 * scale) * cap / 100)), h - 6 * scale, c, scale)
        if charging:
            self.draw_bitmap("bolt", BOLT, x + w // 2 - 7 * scale, y - 1 * scale, 2 * scale, C_TEXT)

    def card_geometry(self, i):
        d = i - self.pos
        t = min(1.0, abs(d))
        w = int(152 - 40 * t)
        h = int(184 - 48 * t)
        icon = int(96 - 32 * t)
        cx = SCREEN_W + SCREEN_W // 2 + d * STEP
        cy = SHELF_Y - (1 - t) * 10
        return d, int(cx - w // 2), int(cy - h // 2), w, h, icon

    def draw_bottom(self):
        ox = SCREEN_W
        self.rect(ox, 0, SCREEN_W, SCREEN_H, C_BOTTOM_BG)
        self.stripes(ox, 8)
        if self.child:
            self.draw_child_panel()
        elif self.confirm:
            self.draw_confirm()
        elif self.pages:
            self.draw_page(self.pages[-1])
        else:
            self.draw_shelf()

    def draw_shelf(self):
        ox = SCREEN_W
        n = len(self.games)
        if n:
            self.text(f"{self.sel + 1} / {n}", ox + SCREEN_W - 16, 12, 16, C_TEXT_DIM, align="right")
            order = sorted(range(max(0, int(self.pos) - 3), min(n, int(self.pos) + 4)), key=lambda i: -abs(i - self.pos))
            sdl.RenderSetClipRect(self.renderer, sdl.Rect(ox, 0, SCREEN_W, SCREEN_H))
            for i in order:
                self.draw_card(i)
            sdl.RenderSetClipRect(self.renderer, None)
        else:
            self.text("Spielkarte einlegen …", ox + SCREEN_W // 2, SHELF_Y - 16, 32, C_TEXT_DIM, True, "center")
        self.draw_pill(ox + 24, SCREEN_H - 72, 200, 48, "Einstellungen", "settings")
        self.draw_pill(ox + SCREEN_W - 224, SCREEN_H - 72, 200, 48, "Standby", "sleep")

    def draw_card(self, i):
        d, x, y, w, h, isz = self.card_geometry(i)
        if x + w < SCREEN_W - 20 or x > WIN_W + 20:
            return
        fade = max(0.0, min(1.0, 2.4 - abs(d)))
        alpha = int(255 * fade)
        selected = i == self.sel and abs(d) < 0.5 and not self.animating
        if selected:
            self.rect(x - 8, y - 8, w + 16, h + 16, C_GLOW, 20)
        self.rect(x + 3, y + 5, w, h, (0, 0, 0, int(28 * fade)), 14)
        self.box(x, y, w, h, C_WHITE, C_SELECT if selected else C_BORDER, 3 if selected else 2, 14, alpha)
        self.rect(x + w // 4, y + 8, w // 2, 7, (*C_CARD_NOTCH, alpha), 3)
        tex = self.icon(self.games[i])
        ix, iy = x + (w - isz) // 2, y + (h - isz) // 2 + 6
        if tex:
            sdl.SetTextureAlphaMod(tex, alpha)
            sdl.RenderCopy(self.renderer, tex, None, sdl.Rect(ix, iy, isz, isz))
            sdl.SetTextureAlphaMod(tex, 255)
        else:
            self.rect(ix, iy, isz, isz, (*C_CARD_NOTCH, alpha), 6)
        if selected:
            cx = x + w // 2
            self.draw_pill(cx - 134, y + h + 12, 150, 36, "Start", "start", True)
            self.draw_pill(cx + 24, y + h + 12, 110, 36, "Optionen", "options")

    def draw_child_panel(self):
        """Bottom screen while EmulationStation or a game runs on the top screen. DraStic
        shrinks to the top screen while its own menu is open, so this doubles as an info
        panel there (touch stays with DraStic, so nothing here is interactive)."""
        ox = SCREEN_W
        cx = ox + SCREEN_W // 2
        bx, by, bw, bh = ox + 60, 70, SCREEN_W - 120, 260
        self.rect(bx + 4, by + 6, bw, bh, C_SHADOW, 16)
        self.box(bx, by, bw, bh, C_WHITE, C_BORDER, 2, 16)
        if self.child_kind == "settings":
            self.text("Einstellungen", cx, by + 28, 32, C_TEXT, True, "center")
            self.text("EmulationStation ist auf dem oberen Bildschirm geöffnet.", cx, by + 84, 16, C_TEXT, False, "center", bw - 40)
            self.text("Dort öffnet START das Hauptmenü.", cx, by + 110, 16, C_TEXT_DIM, False, "center", bw - 40)
            self.draw_pill(cx - 150, by + bh - 84, 300, 56, "Zurück zum DS-Menü", "back", True)
            return
        self.text(self.child_label, cx, by + 22, 32, C_TEXT, True, "center", bw - 40)
        now = datetime.now()
        self.text(now.strftime("%H:%M"), bx + 40, by + 96, 32, C_TEXT, True)
        self.text(f"{DAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}", bx + 40, by + 136, 16, C_TEXT_DIM)
        self.draw_battery(bx + bw - 40, by + 102, C_WHITE, 2)
        self.text("Helligkeit und Ton: DS-Menü, Anzeige & Ton", cx, by + bh - 44, 16, C_TEXT_DIM, False, "center", bw - 40)

    def draw_confirm(self):
        ox = SCREEN_W
        cx = ox + SCREEN_W // 2
        bx, by, bw, bh = ox + 60, 110, SCREEN_W - 120, 220
        self.rect(bx + 4, by + 6, bw, bh, C_SHADOW, 16)
        self.box(bx, by, bw, bh, C_WHITE, C_BORDER, 2, 16)
        self.text(self.confirm[0], cx, by + 40, 32, C_TEXT, True, "center", bw - 40)
        for k, (label, dx) in enumerate((("Ja", -170), ("Nein", 10))):
            self.draw_pill(cx + dx, by + bh - 90, 160, 56, label, "confirm", self.confirm[2] == k)

    def draw_page(self, page):
        ox = SCREEN_W
        self.draw_pill(ox + 16, 10, 120, 44, "Zurück", "back")
        self.text(page.title, ox + SCREEN_W // 2 + 30, 14, 32, C_TEXT, True, "center", SCREEN_W - 200)
        if page.cursor < page.scroll:
            page.scroll = page.cursor
        if page.cursor >= page.scroll + ROWS:
            page.scroll = page.cursor - ROWS + 1
        for k, item in enumerate(page.items[page.scroll:page.scroll + ROWS]):
            i = page.scroll + k
            y = ROW_Y0 + k * ROW_H
            x, w, h = ox + 16, SCREEN_W - 32, ROW_H - 8
            selected = i == page.cursor
            self.box(x, y, w, h, C_WHITE, C_SELECT if selected else C_BORDER, 3 if selected else 2, 10)
            color = C_RED if item.danger else C_TEXT
            self.text(item.label, x + 16, y + h // 2 - 8, 16, color, selected, max_w=w - 40 if item.kind in ("action", "submenu") else w - 260)
            right = x + w - 16
            if item.kind == "toggle":
                self.draw_switch(right - 52, y + h // 2 - 13, bool(item.get()))
            elif item.kind == "choice":
                value = item.get()
                label = next((l for v, l in item.choices if v == value), value or "?")
                self.text(f"<  {label}  >", right, y + h // 2 - 8, 16, C_SELECT if selected else C_TEXT, align="right")
            elif item.kind == "slider":
                v = item.get()
                self.text(f"{v} %", right - 196, y + h // 2 - 8, 16, C_TEXT, align="right")
                self.draw_slider(right - 180, y + h // 2 - 4, 180, v, item.lo, item.hi, selected)
            elif item.kind == "info":
                self.text(str(item.get()), right, y + h // 2 - 8, 16, C_TEXT_DIM, align="right", max_w=w - 160)
            elif item.kind == "submenu":
                self.text(">", right, y + h // 2 - 8, 16, C_TEXT_DIM, True, "right")
        if len(page.items) > ROWS:
            th = (SCREEN_H - 120) * ROWS // len(page.items)
            ty = ROW_Y0 + (SCREEN_H - 120 - th) * page.scroll // max(1, len(page.items) - ROWS)
            self.rect(ox + SCREEN_W - 10, ROW_Y0, 4, SCREEN_H - 120, C_TRACK, 2)
            self.rect(ox + SCREEN_W - 10, ty, 4, th, C_SELECT, 2)

    def draw_switch(self, x, y, on):
        self.rect(x, y, 52, 26, C_SELECT if on else C_TRACK, 13)
        self.rect(x + (28 if on else 2), y + 2, 22, 22, C_WHITE, 11)

    def draw_slider(self, x, y, w, value, lo, hi, selected):
        self.rect(x, y, w, 8, C_TRACK, 4)
        f = (value - lo) / max(1, hi - lo)
        self.rect(x, y, max(8, int(w * f)), 8, C_SELECT, 4)
        kx = x + int((w - 20) * f)
        self.box(kx, y - 6, 20, 20, C_WHITE, C_SELECT if selected else C_BORDER, 2, 10)

    def draw_pill(self, x, y, w, h, label, kind, primary=False):
        self.rect(x + 2, y + 3, w, h, C_SHADOW, h // 2)
        self.box(x, y, w, h, C_SELECT if primary else C_WHITE, C_SELECT if primary else C_BORDER, 2, h // 2)
        color = C_WHITE if primary else C_TEXT
        if kind == "settings":
            self.draw_sliders_icon(x + 22, y + h // 2, color)
            self.text(label, x + 52, y + h // 2 - 8, 16, color)
        elif kind == "sleep":
            self.draw_moon_icon(x + 24, y + h // 2, color)
            self.text(label, x + 52, y + h // 2 - 8, 16, color)
        elif kind == "back" and h > 44:
            self.text(label, x + w // 2, y + h // 2 - 16, 32, color, True, "center")
        elif kind == "back":
            self.text("<  " + label, x + w // 2, y + h // 2 - 8, 16, color, True, "center")
        elif kind == "confirm":
            self.text(label, x + w // 2, y + h // 2 - 16, 32, color, True, "center")
        elif label:
            self.text(label, x + w // 2, y + h // 2 - 8, 16, color, True, "center")

    def draw_sliders_icon(self, cx, cy, color):
        for k, knob in enumerate((0.7, 0.3, 0.55)):
            yy = cy - 7 + k * 7
            self.rect(cx - 10, yy, 20, 2, color)
            self.rect(cx - 10 + int(16 * knob), yy - 2, 5, 6, color, 2)

    def draw_moon_icon(self, cx, cy, color):
        self.rect(cx - 8, cy - 8, 16, 16, color, 8)
        self.rect(cx - 2, cy - 10, 16, 16, C_WHITE, 8)

    # ---------- shelf input ----------
    def select(self, i, animate=True):
        n = len(self.games)
        if not n:
            return
        i = max(0, min(n - 1, i))
        if i == self.sel and not self.animating:
            return
        self.sel = i
        if animate:
            self.anim_from = self.pos
            self.anim_t0 = time.monotonic()
            self.animating = True
        else:
            self.pos = float(i)
        self.dirty = True

    def move(self, delta):
        if self.confirm:
            self.confirm[2] = 0 if delta < 0 else 1
            self.dirty = True
        elif self.pages:
            self.adjust(self.pages[-1], delta)
        else:
            self.select(self.sel + delta)

    def press_direction(self, direction):
        if direction == self.held:
            return
        self.held = direction
        if direction:
            self.move(direction)
            self.next_repeat = time.monotonic() + 0.35

    def tick_repeat(self):
        if self.held and time.monotonic() >= self.next_repeat:
            self.move(self.held)
            self.next_repeat = time.monotonic() + (0.15 if self.pages else 0.09)

    # ---------- settings input ----------
    def page_up_down(self, delta):
        page = self.pages[-1]
        if page.items:
            page.cursor = max(0, min(len(page.items) - 1, page.cursor + delta))
            self.dirty = True

    def adjust(self, page, delta):
        if not page.items:
            return
        item = page.items[page.cursor]
        if item.kind == "slider":
            item.set(max(item.lo, min(item.hi, item.get() + delta * item.step)))
        elif item.kind == "choice":
            values = [v for v, _ in item.choices]
            cur = item.get()
            k = values.index(cur) if cur in values else 0
            item.set(values[(k + delta) % len(values)])
        elif item.kind == "toggle":
            item.set(not item.get())
        else:
            return
        self.dirty = True

    def activate(self, page):
        if not page.items:
            return
        item = page.items[page.cursor]
        if item.kind in ("action", "submenu"):
            item.do()
        elif item.kind in ("toggle", "choice"):
            self.adjust(page, 1)
        self.dirty = True

    def back(self):
        if self.confirm:
            self.confirm = None
        elif self.pages:
            self.pages.pop()
        self.slider_drag = None
        self.dirty = True

    # ---------- events ----------
    def handle_event(self, ev):
        t = ev.type
        if t == sdl.EVENT_QUIT:
            self.quit = True
        elif t == sdl.EVENT_WINDOWEVENT:
            self.dirty = True
        elif t in (sdl.EVENT_FINGERDOWN, sdl.EVENT_FINGERUP, sdl.EVENT_FINGERMOTION):
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.TouchFingerEvent)).contents
            self.finger(t, e.x * WIN_W, e.y * WIN_H)
        elif self.child:
            return  # the pad belongs to the game or EmulationStation now
        elif t == sdl.EVENT_CONTROLLERDEVICEADDED:
            self.open_controller(ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.DeviceEvent)).contents.which)
        elif t == sdl.EVENT_JOYDEVICEADDED:
            idx = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.DeviceEvent)).contents.which
            if idx not in self.controllers and idx not in self.joysticks:
                self.open_controller(idx)
        elif t in (sdl.EVENT_CONTROLLERBUTTONDOWN, sdl.EVENT_CONTROLLERBUTTONUP):
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.ControllerButtonEvent)).contents
            self.button(e.button, t == sdl.EVENT_CONTROLLERBUTTONDOWN)
        elif t == sdl.EVENT_CONTROLLERAXISMOTION:
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.ControllerAxisEvent)).contents
            if e.axis == sdl.CONTROLLER_AXIS_LEFTX:
                d = 1 if e.value > 16000 else -1 if e.value < -16000 else 0 if abs(e.value) < 8000 else self.axis_dir
                if d != self.axis_dir:
                    self.axis_dir = d
                    self.press_direction(d)
        elif t == sdl.EVENT_JOYHATMOTION and not self.controllers:
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.JoyHatEvent)).contents
            self.press_direction(1 if e.value & sdl.HAT_RIGHT else -1 if e.value & sdl.HAT_LEFT else 0)
        elif t in (sdl.EVENT_KEYDOWN, sdl.EVENT_KEYUP):
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.KeyboardEvent)).contents
            self.key(e.sym, t == sdl.EVENT_KEYDOWN, e.repeat)

    def button(self, b, down):
        B = sdl
        if b in (B.CONTROLLER_BUTTON_DPAD_LEFT, B.CONTROLLER_BUTTON_DPAD_RIGHT):
            d = -1 if b == B.CONTROLLER_BUTTON_DPAD_LEFT else 1
            self.press_direction(d if down else (0 if self.held == d else self.held))
        elif not down:
            return
        elif b in (B.CONTROLLER_BUTTON_DPAD_UP, B.CONTROLLER_BUTTON_DPAD_DOWN):
            if self.pages and not self.confirm:
                self.page_up_down(-1 if b == B.CONTROLLER_BUTTON_DPAD_UP else 1)
        # Nintendo layout: SDL's "B" (east) is the button labelled A on the RG DS
        elif b in (B.CONTROLLER_BUTTON_B, B.CONTROLLER_BUTTON_START):
            self.primary()
        elif b == B.CONTROLLER_BUTTON_A:
            self.back()
        elif b == B.CONTROLLER_BUTTON_BACK:
            if self.pages or self.confirm:
                self.back()
            else:
                self.open_page("settings")
        elif b == B.CONTROLLER_BUTTON_LEFTSHOULDER and not self.pages:
            self.move(-5)
        elif b == B.CONTROLLER_BUTTON_RIGHTSHOULDER and not self.pages:
            self.move(5)

    def key(self, sym, down, repeat):
        if sym in (sdl.KEY_LEFT, sdl.KEY_RIGHT):
            d = -1 if sym == sdl.KEY_LEFT else 1
            if not repeat:
                self.press_direction(d if down else (0 if self.held == d else self.held))
        elif not down or repeat:
            return
        elif sym in (sdl.KEY_UP, sdl.KEY_DOWN):
            if self.pages and not self.confirm:
                self.page_up_down(-1 if sym == sdl.KEY_UP else 1)
        elif sym in (sdl.KEY_RETURN, sdl.KEY_SPACE):
            self.primary()
        elif sym == sdl.KEY_BACKSPACE:
            self.back()
        elif sym == sdl.KEY_ESCAPE:
            if self.pages or self.confirm:
                self.back()
            else:
                self.open_page("settings")
        elif sym == sdl.KEY_PAGEUP and not self.pages:
            self.move(-5)
        elif sym == sdl.KEY_PAGEDOWN and not self.pages:
            self.move(5)
        elif sym == ord("q"):
            self.quit = True

    def primary(self):
        if self.confirm:
            message, callback, cursor = self.confirm
            self.confirm = None
            self.dirty = True
            if cursor == 0:
                callback()
        elif self.pages:
            self.activate(self.pages[-1])
        else:
            self.start_game()

    def finger(self, t, x, y):
        now = time.monotonic()
        if self.touch_log < 12:
            self.touch_log += 1
            print(f"touch {t:#x} {x:.0f},{y:.0f}", file=sys.stderr)
        if self.child or self.pages or self.confirm:
            if t == sdl.EVENT_FINGERDOWN:
                self.slider_down(x, y)
            elif t == sdl.EVENT_FINGERMOTION:
                self.slider_motion(x)
            elif t == sdl.EVENT_FINGERUP:
                if self.slider_drag:
                    self.slider_drag = None
                else:
                    self.tap(x, y)
            return
        if t == sdl.EVENT_FINGERDOWN:
            self.drag = [x, self.pos, False, [(now, x)]]
            self.animating = False
            return
        if self.drag is None:
            return
        x0, pos0, moved, samples = self.drag
        if t == sdl.EVENT_FINGERMOTION:
            if abs(x - x0) > 8:
                self.drag[2] = moved = True
            if moved and self.games and 60 < y < SCREEN_H - 90:
                n = len(self.games)
                self.pos = max(-0.4, min(n - 0.6, pos0 - (x - x0) / STEP))
                self.sel = max(0, min(n - 1, int(round(self.pos))))
                samples.append((now, x))
                del samples[:-4]
                self.dirty = True
            return
        self.drag = None
        if moved:
            v = 0.0
            if len(samples) >= 2 and now - samples[0][0] > 0.01:
                v = (samples[-1][1] - samples[0][1]) / (now - samples[0][0]) / STEP
            self.select(int(round(self.pos - v * 0.18)))
            if not self.animating:
                self.select(self.sel, True)
                self.animating = abs(self.pos - self.sel) > 0.001
            return
        self.tap(x, y)

    def slider_rects(self):
        """(item, x, y, w, h[, row]) of the sliders currently on screen, for touch."""
        ox = SCREEN_W
        if self.pages and not self.confirm:
            page = self.pages[-1]
            out = []
            for k, item in enumerate(page.items[page.scroll:page.scroll + ROWS]):
                if item.kind == "slider":
                    y = ROW_Y0 + k * ROW_H
                    out.append((item, ox + 16 + SCREEN_W - 32 - 16 - 180, y, 180, ROW_H - 8, page.scroll + k))
            return out
        return []

    def slider_down(self, x, y):
        for entry in self.slider_rects():
            item, sx, sy, sw, sh = entry[:5]
            if sx - 12 <= x <= sx + sw + 12 and sy <= y <= sy + sh:
                self.slider_drag = (item, sx, sw)
                if len(entry) > 5 and self.pages:
                    self.pages[-1].cursor = entry[5]
                self.slider_motion(x)
                return

    def slider_motion(self, x):
        if not self.slider_drag:
            return
        item, sx, sw = self.slider_drag
        f = max(0.0, min(1.0, (x - sx) / sw))
        v = item.lo + round((item.hi - item.lo) * f / item.step) * item.step
        if v != item.get():
            item.set(int(v))
            self.dirty = True

    def tap(self, x, y):
        ox = SCREEN_W
        if x < ox:
            return
        cx = ox + SCREEN_W // 2
        if self.child:
            if self.child_kind == "settings" and cx - 150 <= x <= cx + 150 and 246 <= y <= 302:
                self.end_child()
            return
        if self.confirm:
            if 240 <= y <= 296:
                if cx - 170 <= x <= cx - 10:
                    self.confirm[2] = 0
                    self.primary()
                elif cx + 10 <= x <= cx + 170:
                    self.back()
            return
        if self.pages:
            page = self.pages[-1]
            if 10 <= y <= 54 and ox + 16 <= x <= ox + 136:
                self.back()
                return
            for k, item in enumerate(page.items[page.scroll:page.scroll + ROWS]):
                ry = ROW_Y0 + k * ROW_H
                if ry <= y <= ry + ROW_H - 8:
                    page.cursor = page.scroll + k
                    if item.kind == "choice":
                        self.adjust(page, 1 if x > ox + SCREEN_W // 2 else -1)
                    elif item.kind != "slider":
                        self.activate(page)
                    self.dirty = True
                    return
            return
        if ox + 24 <= x <= ox + 224 and SCREEN_H - 72 <= y <= SCREEN_H - 24:
            self.open_page("settings")
            return
        if ox + SCREEN_W - 224 <= x <= ox + SCREEN_W - 24 and SCREEN_H - 72 <= y <= SCREEN_H - 24:
            self.sleep()
            return
        if not self.games:
            return
        for i in range(max(0, self.sel - 3), min(len(self.games), self.sel + 4)):
            d, cxx, cy, w, h, _ = self.card_geometry(i)
            if i == self.sel and abs(d) < 0.5 and cy + h + 12 <= y <= cy + h + 48:
                mid = cxx + w // 2
                if mid - 134 <= x <= mid + 16:
                    self.start_game()
                elif mid + 24 <= x <= mid + 134:
                    self.open_page("drastic", self.games[i])
                return
            if cxx <= x <= cxx + w and cy <= y <= cy + h:
                if i == self.sel and abs(d) < 0.5:
                    self.start_game()
                else:
                    self.select(i)
                return

    # ---------- actions ----------
    def launch(self, kind, label, cmd, extra_env=None):
        if self.child:
            return
        self.held = 0
        self.drag = None
        env = {k: v for k, v in os.environ.items() if k not in ("SDL_VIDEO_WAYLAND_WMCLASS", "SDL_APP_ID")}
        env.update(extra_env or {})
        try:
            self.child = subprocess.Popen(cmd, env=env)
        except OSError as e:
            print("launch failed:", e, file=sys.stderr)
            return
        self.child_kind, self.child_label = kind, label
        self.child_seen = 0.0
        self.bottom_restore = kind == "settings"
        self.dirty = True

    def start_game(self):
        if not self.games or self.animating:
            return
        g = self.games[self.sel]
        self.launch("game", g.title, ["/usr/bin/runemu.sh", g.path, "-Pnds", "--core=drastic-sa", "--emulator=drastic"], {"NDS_MENU": "1"})

    def emulationstation(self):
        self.pages.clear()
        self.launch("settings", "Einstellungen",
                    ["bash", "-c", ". /usr/bin/es_settings; exec emulationstation --log-path /var/log --no-splash"])

    def end_child(self):
        # SDL turns SIGTERM into a normal quit, so EmulationStation saves and exits
        if self.child and self.child.poll() is None:
            self.child.terminate()
            self.child_seen = -time.monotonic()

    def tick_child(self):
        if not self.child or self.child is True:
            return
        now = time.monotonic()
        if self.child.poll() is not None:
            self.child = None
            ev = sdl.Event()
            while sdl.PollEvent(ctypes.byref(ev)):
                pass
            self.show_both_screens()
            self.reload_games()
            return
        if self.child_seen < 0 and now + self.child_seen > 8:
            self.child.kill()
        elif self.bottom_restore:
            # sway's EmulationStation rules may switch the bottom screen off once its
            # window appears; put it back on for the panel a moment later
            if not self.child_seen and window_rect("emulationstation"):
                self.child_seen = now
            elif self.child_seen and now - self.child_seen > 1.5:
                self.bottom_restore = False
                second = second_output()
                if second:
                    sway("output", second, "power", "on")
                self.dirty = True

    def sleep(self):
        run(["systemctl", "suspend"])
        self.dirty = True

    # ---------- main loop ----------
    def loop(self):
        ev = sdl.Event()
        minute = -1
        while not self.quit:
            active = self.animating or self.drag is not None or self.held
            if sdl.WaitEventTimeout(ctypes.byref(ev), 0 if active else 250):
                self.handle_event(ev)
                while sdl.PollEvent(ctypes.byref(ev)):
                    self.handle_event(ev)
            self.tick_repeat()
            self.tick_child()
            if self.animating:
                t = min(1.0, (time.monotonic() - self.anim_t0) / 0.22)
                self.pos = self.anim_from + (self.sel - self.anim_from) * ease(t)
                if t >= 1.0:
                    self.pos = float(self.sel)
                    self.animating = False
                self.dirty = True
            now = time.monotonic()
            if now - self.last_check > 5:
                self.last_check = now
                try:
                    if os.stat(ROMS / "gamelist.xml").st_mtime != self.gamelist_mtime:
                        self.reload_games()
                except OSError:
                    pass
                if self.child and self.child_kind == "game":
                    self.dirty = True   # battery and clock on the info panel
            m = datetime.now().minute
            if m != minute:
                minute = m
                self.dirty = True
            if self.dirty:
                self.draw()
            elif not active:
                sdl.Delay(10)

    def bench(self):
        frames, t0 = 0, time.monotonic()
        while time.monotonic() - t0 < 3.0 and len(self.games) > 1:
            if not self.animating:
                self.select((self.sel + 1) % len(self.games))
            t = min(1.0, (time.monotonic() - self.anim_t0) / 0.22)
            self.pos = self.anim_from + (self.sel - self.anim_from) * ease(t)
            self.animating = t < 1.0
            self.draw()
            frames += 1
        print(f"bench: {frames / (time.monotonic() - t0):.1f} fps", file=sys.stderr)

    def screenshot(self, path):
        buf = (ctypes.c_uint8 * (WIN_W * WIN_H * 3))()
        sdl.RenderReadPixels(self.renderer, None, sdl.PIXELFORMAT_RGB24, buf, WIN_W * 3)
        with open(path, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (WIN_W, WIN_H))
            f.write(bytes(buf))


if __name__ == "__main__":
    sys.exit(Menu().run())
