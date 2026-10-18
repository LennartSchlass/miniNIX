#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026-present ROCKNIX (https://github.com/ROCKNIX)

# DS-style launcher for the Anbernic RG DS. One 1280x480 window spans both panels like
# DraStic's does: the left half is the top screen (banner, clock, battery), the right
# half the touch screen (a shelf of game cards, settings, standby).

import ctypes
import glob
import json
import math
import os
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
FONT = str(HERE / "fonts" / "PixelOperator.ttf")
FONT_BOLD = str(HERE / "fonts" / "PixelOperator-Bold.ttf")
APP_ID = "ndsmenu"
TOUCH_ID = "1046:911:Goodix_Capacitive_TouchScreen"
SCREEN_W, SCREEN_H = 640, 480
WIN_W, WIN_H = 2 * SCREEN_W, SCREEN_H
STEP = 170          # distance between cards on the shelf
SHELF_Y = 214       # vertical centre of the shelf
NO_SWAY = bool(os.environ.get("NDS_MENU_NO_SWAY"))

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

DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]


class Game:
    def __init__(self, path, name, image, publisher, playcount, lastplayed):
        self.path, self.name, self.image = path, name, image
        self.publisher, self.playcount, self.lastplayed = publisher, playcount, lastplayed
        self.tex = None


def load_games(romdir):
    xml = romdir / "gamelist.xml"
    games = []
    try:
        root = ET.parse(xml).getroot()
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
        name = (g.findtext("name") or "").strip() or full.stem
        try:
            playcount = int(g.findtext("playcount") or 0)
        except ValueError:
            playcount = 0
        games.append(Game(str(full), name, img, (g.findtext("publisher") or "").strip(),
                          playcount, (g.findtext("lastplayed") or "").strip()))
    games.sort(key=lambda g: g.name.lower())
    return games


def battery():
    for d in glob.glob("/sys/class/power_supply/[Bb][Aa][Tt]*"):
        try:
            cap = int(open(d + "/capacity").read())
            status = open(d + "/status").read().strip()
            return cap, status.lower() in ("charging", "full")
        except (OSError, ValueError):
            pass
    fake = os.environ.get("NDS_MENU_FAKE_BATTERY")
    return (int(fake), False) if fake else (None, False)


def sway(*args, capture=False):
    if NO_SWAY:
        return ""
    try:
        r = subprocess.run(["swaymsg", *args], stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        return r.stdout.decode(errors="replace") if capture else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def window_rect(app_id):
    tree = sway("-t", "get_tree", capture=True)
    if not tree:
        return None
    try:
        nodes = [json.loads(tree)]
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
        self.drag = None          # (x0, pos0, moved, samples)
        self.held = 0
        self.held_since = 0.0
        self.next_repeat = 0.0
        self.axis_dir = 0
        self.controllers = {}
        self.joysticks = {}
        self.textures = {}        # text cache
        self.shapes = {}          # corner textures per radius
        self.stripe_rects = {}
        self.fonts = {}
        self.dirty = True
        self.quit = False
        self.gamelist_mtime = 0
        self.last_check = 0.0
        self.busy = None          # overlay text while a child runs
        self.touch_log = 0

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

        # Span both panels like DraStic. Sway centres the floating window on the seam first,
        # which changes its workspace, so the move is issued twice (same as the Duo Lite rule).
        sway("for_window", f'[app_id="{APP_ID}"]', "floating", "enable,", "border", "none,",
             "resize", "set", str(WIN_W), str(WIN_H) + ",", "move", "absolute", "position", "0", "0,",
             "move", "absolute", "position", "0", "0")
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
            raw = (ctypes.c_uint8 * len(buf)).from_buffer(buf)
            surf = sdl.CreateRGBSurfaceWithFormatFrom(raw, size, size, 32, size * 4, sdl.PIXELFORMAT_ABGR8888)
            tex = sdl.CreateTextureFromSurface(self.renderer, surf)
            sdl.FreeSurface(surf)
            sdl.SetTextureBlendMode(tex, sdl.BLENDMODE_BLEND)
            self.shapes[r] = tex
        return tex

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
        key = (s, size, bold, color[:3], max_w)
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
            if len(self.textures) > 300:
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

    def line(self, x1, y1, x2, y2, color):
        sdl.SetRenderDrawColor(self.renderer, color[0], color[1], color[2], color[3] if len(color) > 3 else 255)
        sdl.RenderDrawLine(self.renderer, int(x1), int(y1), int(x2), int(y2))

    # ---------- screens ----------
    def draw(self):
        sdl.SetRenderDrawColor(self.renderer, *C_TOP_BG, 255)
        sdl.RenderClear(self.renderer)
        self.draw_top()
        self.draw_bottom()
        if self.busy:
            # Only the bottom screen stays visible behind a child; the top is covered by it
            self.rect(SCREEN_W, 0, SCREEN_W, SCREEN_H, (255, 255, 255, 170))
            self.text(self.busy, SCREEN_W + SCREEN_W // 2, SCREEN_H // 2 - 28, 32, C_TEXT, True, "center", SCREEN_W - 40)
            self.text("Zurück im DS-Menü, sobald das Programm beendet wird", SCREEN_W + SCREEN_W // 2, SCREEN_H // 2 + 20, 16, C_TEXT_DIM, False, "center")
        sdl.RenderPresent(self.renderer)
        self.dirty = False

    def stripes(self, x0, y0):
        key = (x0, y0)
        arr = self.stripe_rects.get(key)
        if arr is None:
            ys = list(range(y0, SCREEN_H, 24))
            arr = (sdl.Rect * len(ys))(*[sdl.Rect(x0, y, SCREEN_W, 1) for y in ys])
            self.stripe_rects[key] = arr
        sdl.SetRenderDrawColor(self.renderer, *C_STRIPE)
        sdl.RenderFillRects(self.renderer, arr, len(arr))

    def draw_top(self):
        self.stripes(0, 44)
        self.rect(0, 0, SCREEN_W, 44, C_TOP_BAR)
        self.rect(0, 44, SCREEN_W, 2, C_BORDER)
        now = datetime.now()
        self.text(f"{DAYS[now.weekday()]}, {now.day}. {MONTHS[now.month - 1]}", 16, 12, 16, C_TEXT)
        self.text(now.strftime("%H:%M"), SCREEN_W // 2, 6, 32, C_TEXT, True, "center")
        self.draw_battery(SCREEN_W - 16, 15)

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
        name, sub = g.name, ""
        if " - " in name:
            name, sub = name.split(" - ", 1)
        self.text(name, tx, iy + 2, 32, C_TEXT, True, max_w=bw - 200)
        self.text(sub, tx, iy + 44, 16, C_TEXT, max_w=bw - 200)
        self.text(g.publisher, tx, iy + 72, 16, C_TEXT_DIM, max_w=bw - 200)
        if g.playcount:
            self.text(f"{g.playcount}× gespielt", tx, iy + 104, 16, C_TEXT_DIM)
        self.draw_dots(SCREEN_W // 2, by + bh + 26)
        self.text("<  >  Auswahl      A  Start      SELECT  Einstellungen", SCREEN_W // 2, SCREEN_H - 36, 16, C_TEXT_DIM, False, "center")

    def draw_dots(self, cx, cy):
        n = len(self.games)
        if n <= 1:
            return
        if n <= 24:
            x0 = cx - (n - 1) * 7
            for i in range(n):
                c = C_SELECT if i == self.sel else C_BORDER
                self.rect(x0 + i * 14 - 3, cy - 3, 6, 6, c, 3)
        else:
            w = 300
            self.rect(cx - w // 2, cy - 2, w, 4, C_BORDER, 2)
            self.rect(cx - w // 2 + int((w - 24) * self.sel / (n - 1)), cy - 4, 24, 8, C_SELECT, 4)

    def draw_battery(self, right, y):
        cap, charging = battery()
        w, h = 30, 14
        x = right - w
        if cap is not None:
            self.text(f"{cap}%", x - 8, y - 2, 16, C_TEXT, align="right")
        self.rect(x, y, w, h, C_TEXT, 3)
        self.rect(x + 2, y + 2, w - 4, h - 4, C_TOP_BAR, 2)
        self.rect(x + w, y + 4, 3, h - 8, C_TEXT, 1)
        if cap is not None:
            c = C_GREEN if cap > 40 else C_ORANGE if cap > 15 else C_RED
            self.rect(x + 3, y + 3, max(1, int((w - 6) * cap / 100)), h - 6, c, 1)
        if charging:
            self.text("+", x + w // 2, y - 4, 16, C_TEXT, True, "center")

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
            self.draw_pill(x + w // 2 - 60, y + h + 12, 120, 36, "Start", "start", True)

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
        else:
            self.text(label, x + w // 2, y + h // 2 - 8, 16, color, True, "center")

    def draw_sliders_icon(self, cx, cy, color):
        for k, knob in enumerate((0.7, 0.3, 0.55)):
            yy = cy - 7 + k * 7
            self.rect(cx - 10, yy, 20, 2, color)
            self.rect(cx - 10 + int(16 * knob), yy - 2, 5, 6, color, 2)

    def draw_moon_icon(self, cx, cy, color):
        self.rect(cx - 8, cy - 8, 16, 16, color, 8)
        self.rect(cx - 2, cy - 10, 16, 16, C_WHITE, 8)

    # ---------- input ----------
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
            self.next_repeat = time.monotonic() + 0.09

    def handle_event(self, ev):
        t = ev.type
        if t == sdl.EVENT_QUIT:
            self.quit = True
        elif t == sdl.EVENT_WINDOWEVENT:
            self.dirty = True
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
        elif t == sdl.EVENT_JOYBUTTONDOWN and not self.controllers:
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.JoyButtonEvent)).contents
            print("joystick button", e.button, file=sys.stderr)
            if e.button in (0, 1):
                self.start_game()
        elif t in (sdl.EVENT_KEYDOWN, sdl.EVENT_KEYUP):
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.KeyboardEvent)).contents
            self.key(e.sym, t == sdl.EVENT_KEYDOWN, e.repeat)
        elif t in (sdl.EVENT_FINGERDOWN, sdl.EVENT_FINGERUP, sdl.EVENT_FINGERMOTION):
            e = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(sdl.TouchFingerEvent)).contents
            self.finger(t, e.x * WIN_W, e.y * WIN_H)

    def button(self, b, down):
        B = sdl
        if b in (B.CONTROLLER_BUTTON_DPAD_LEFT, B.CONTROLLER_BUTTON_DPAD_RIGHT):
            d = -1 if b == B.CONTROLLER_BUTTON_DPAD_LEFT else 1
            self.press_direction(d if down else (0 if self.held == d else self.held))
        elif not down:
            return
        elif b in (B.CONTROLLER_BUTTON_A, B.CONTROLLER_BUTTON_START):
            self.start_game()
        elif b in (B.CONTROLLER_BUTTON_BACK, B.CONTROLLER_BUTTON_Y):
            self.settings()
        elif b == B.CONTROLLER_BUTTON_LEFTSHOULDER:
            self.move(-5)
        elif b == B.CONTROLLER_BUTTON_RIGHTSHOULDER:
            self.move(5)

    def key(self, sym, down, repeat):
        if sym in (sdl.KEY_LEFT, sdl.KEY_RIGHT):
            d = -1 if sym == sdl.KEY_LEFT else 1
            if not repeat:
                self.press_direction(d if down else (0 if self.held == d else self.held))
        elif not down or repeat:
            return
        elif sym in (sdl.KEY_RETURN, sdl.KEY_SPACE):
            self.start_game()
        elif sym == sdl.KEY_PAGEUP:
            self.move(-5)
        elif sym == sdl.KEY_PAGEDOWN:
            self.move(5)
        elif sym == sdl.KEY_ESCAPE:
            self.settings()
        elif sym == ord("q"):
            self.quit = True

    def finger(self, t, x, y):
        now = time.monotonic()
        if self.touch_log < 12:
            self.touch_log += 1
            print(f"touch {t:#x} {x:.0f},{y:.0f}", file=sys.stderr)
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
            if moved and self.games and y > 60 and y < SCREEN_H - 90:
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

    def tap(self, x, y):
        ox = SCREEN_W
        if x < ox:
            return
        if ox + 24 <= x <= ox + 224 and SCREEN_H - 72 <= y <= SCREEN_H - 24:
            self.settings()
            return
        if ox + SCREEN_W - 224 <= x <= ox + SCREEN_W - 24 and SCREEN_H - 72 <= y <= SCREEN_H - 24:
            self.sleep()
            return
        if not self.games:
            return
        for i in range(max(0, self.sel - 3), min(len(self.games), self.sel + 4)):
            d, cx, cy, w, h, _ = self.card_geometry(i)
            extra = 52 if i == self.sel else 0
            if cx <= x <= cx + w and cy <= y <= cy + h + extra:
                if i == self.sel and abs(d) < 0.5:
                    self.start_game()
                else:
                    self.select(i)
                return

    # ---------- actions ----------
    def run_child(self, label, cmd, extra_env=None):
        self.held = 0
        self.drag = None
        self.busy = label
        self.draw()
        env = {k: v for k, v in os.environ.items() if k not in ("SDL_VIDEO_WAYLAND_WMCLASS", "SDL_APP_ID")}
        env.update(extra_env or {})
        try:
            subprocess.run(cmd, env=env)
        except OSError as e:
            print("launch failed:", e, file=sys.stderr)
        self.busy = None
        ev = sdl.Event()
        while sdl.PollEvent(ctypes.byref(ev)):
            pass
        self.show_both_screens()
        self.reload_games()

    def start_game(self):
        if not self.games or self.animating:
            return
        g = self.games[self.sel]
        self.run_child(f"{g.name.split(' - ')[0]} läuft …",
                       ["/usr/bin/runemu.sh", g.path, "-Pnds", "--core=drastic-sa", "--emulator=drastic"], {"NDS_MENU": "1"})

    def settings(self):
        self.run_child("Einstellungen sind oben geöffnet",
                       ["bash", "-c", ". /usr/bin/es_settings; exec emulationstation --log-path /var/log --no-splash"])

    def sleep(self):
        subprocess.run(["systemctl", "suspend"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
