# SPDX-License-Identifier: GPL-2.0-or-later
# Minimal ctypes wrapper around the libSDL2 / libSDL2_image / libSDL2_ttf
# Based on lowerdeck's sdl2.py (https://github.com/bulzipke/lowerdeck), extended with
# game controller, keyboard, batched drawing and read-back entry points for nds-menu.

import ctypes
from ctypes import (
    CDLL, POINTER, Structure,
    c_char_p, c_float, c_int, c_int32, c_int64,
    c_uint8, c_uint32, c_void_p,
)

# ---------- libraries ----------
_sdl  = CDLL("libSDL2-2.0.so.0")
_img  = CDLL("libSDL2_image-2.0.so.0")
_ttf  = CDLL("libSDL2_ttf-2.0.so.0")

# ---------- constants ----------
INIT_VIDEO              = 0x00000020
INIT_JOYSTICK           = 0x00000200
INIT_GAMECONTROLLER     = 0x00002000
INIT_EVENTS             = 0x00004000

WINDOW_FULLSCREEN_DESKTOP = 0x00001001
WINDOW_SHOWN              = 0x00000004
WINDOW_BORDERLESS         = 0x00000010

WINDOWPOS_UNDEFINED       = 0x1FFF0000
RENDERER_ACCELERATED      = 0x00000002
RENDERER_PRESENTVSYNC     = 0x00000004

# SDL_BlendMode
BLENDMODE_NONE            = 0
BLENDMODE_BLEND           = 1

# Texture access / pixel format
TEXTUREACCESS_TARGET      = 2
PIXELFORMAT_ARGB8888      = 0x16362004

EVENT_QUIT                = 0x100
EVENT_WINDOWEVENT         = 0x200
EVENT_KEYDOWN             = 0x300
EVENT_KEYUP               = 0x301
EVENT_JOYAXISMOTION       = 0x600
EVENT_JOYHATMOTION        = 0x602
EVENT_JOYBUTTONDOWN       = 0x603
EVENT_JOYBUTTONUP         = 0x604
EVENT_JOYDEVICEADDED      = 0x605
EVENT_JOYDEVICEREMOVED    = 0x606
EVENT_CONTROLLERAXISMOTION   = 0x650
EVENT_CONTROLLERBUTTONDOWN   = 0x651
EVENT_CONTROLLERBUTTONUP     = 0x652
EVENT_CONTROLLERDEVICEADDED  = 0x653
EVENT_CONTROLLERDEVICEREMOVED = 0x654
EVENT_FINGERDOWN          = 0x700
EVENT_FINGERUP            = 0x701
EVENT_FINGERMOTION        = 0x702
EVENT_MOUSEMOTION         = 0x400
EVENT_MOUSEBUTTONDOWN     = 0x401
EVENT_MOUSEBUTTONUP       = 0x402

IMG_INIT_JPG              = 0x00000001
IMG_INIT_PNG              = 0x00000002

PIXELFORMAT_RGB24         = 0x17101803
PIXELFORMAT_ABGR8888      = 0x16762004
SCALEMODE_NEAREST         = 0
TOUCH_MOUSEID             = 0xFFFFFFFF

CONTROLLER_BUTTON_A, CONTROLLER_BUTTON_B, CONTROLLER_BUTTON_X, CONTROLLER_BUTTON_Y = 0, 1, 2, 3
CONTROLLER_BUTTON_BACK, CONTROLLER_BUTTON_GUIDE, CONTROLLER_BUTTON_START = 4, 5, 6
CONTROLLER_BUTTON_LEFTSHOULDER, CONTROLLER_BUTTON_RIGHTSHOULDER = 9, 10
CONTROLLER_BUTTON_DPAD_UP, CONTROLLER_BUTTON_DPAD_DOWN = 11, 12
CONTROLLER_BUTTON_DPAD_LEFT, CONTROLLER_BUTTON_DPAD_RIGHT = 13, 14
CONTROLLER_AXIS_LEFTX, CONTROLLER_AXIS_LEFTY = 0, 1
HAT_UP, HAT_RIGHT, HAT_DOWN, HAT_LEFT = 1, 2, 4, 8

KEY_RETURN, KEY_ESCAPE, KEY_SPACE, KEY_BACKSPACE = 13, 27, 32, 8
KEY_RIGHT, KEY_LEFT, KEY_DOWN, KEY_UP = 0x4000004F, 0x40000050, 0x40000051, 0x40000052
KEY_PAGEUP, KEY_PAGEDOWN = 0x4000004B, 0x4000004E

TTF_HINTING_MONO          = 2

# Hints (for Wayland app_id)
HINT_APP_NAME             = b"SDL_APP_NAME"
HINT_VIDEO_WAYLAND_WMCLASS = b"SDL_VIDEO_WAYLAND_WMCLASS"
HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS = b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"
HINT_TOUCH_MOUSE_EVENTS   = b"SDL_TOUCH_MOUSE_EVENTS"
HINT_MOUSE_TOUCH_EVENTS   = b"SDL_MOUSE_TOUCH_EVENTS"


# ---------- structs ----------
class Rect(Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


class Color(Structure):
    _fields_ = [("r", c_uint8), ("g", c_uint8), ("b", c_uint8), ("a", c_uint8)]


class Surface(Structure):
    _fields_ = [
        ("flags",   c_uint32),
        ("format",  c_void_p),
        ("w",       c_int),
        ("h",       c_int),
        ("pitch",   c_int),
        ("pixels",  c_void_p),
        ("userdata", c_void_p),
        ("locked",  c_int),
        ("list_blitmap", c_void_p),
        ("clip_rect", Rect),
        ("map",     c_void_p),
        ("refcount", c_int),
    ]


class Event(Structure):
    """Opaque 56-byte buffer. Read .type, then cast to a specific event struct."""
    _fields_ = [("data", c_uint8 * 56)]

    @property
    def type(self) -> int:
        return c_uint32.from_buffer(self.data).value


class TouchFingerEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("touchId",   c_int64),
        ("fingerId",  c_int64),
        ("x",         c_float),
        ("y",         c_float),
        ("dx",        c_float),
        ("dy",        c_float),
        ("pressure",  c_float),
        ("windowID",  c_uint32),
    ]


class MouseButtonEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("windowID",  c_uint32),
        ("which",     c_uint32),
        ("button",    c_uint8),
        ("state",     c_uint8),
        ("clicks",    c_uint8),
        ("padding1",  c_uint8),
        ("x",         c_int32),
        ("y",         c_int32),
    ]


class KeyboardEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("windowID",  c_uint32),
        ("state",     c_uint8),
        ("repeat",    c_uint8),
        ("padding2",  c_uint8),
        ("padding3",  c_uint8),
        ("scancode",  c_int32),
        ("sym",       c_int32),
        ("mod",       ctypes.c_uint16),
        ("unused",    c_uint32),
    ]


class ControllerButtonEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("which",     c_int32),
        ("button",    c_uint8),
        ("state",     c_uint8),
    ]


class ControllerAxisEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("which",     c_int32),
        ("axis",      c_uint8),
        ("padding1",  c_uint8),
        ("padding2",  c_uint8),
        ("padding3",  c_uint8),
        ("value",     ctypes.c_int16),
    ]


class JoyHatEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("which",     c_int32),
        ("hat",       c_uint8),
        ("value",     c_uint8),
    ]


class JoyButtonEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("which",     c_int32),
        ("button",    c_uint8),
        ("state",     c_uint8),
    ]


class DeviceEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("which",     c_int32),
    ]


class MouseMotionEvent(Structure):
    _fields_ = [
        ("type",      c_uint32),
        ("timestamp", c_uint32),
        ("windowID",  c_uint32),
        ("which",     c_uint32),
        ("state",     c_uint32),
        ("x",         c_int32),
        ("y",         c_int32),
        ("xrel",      c_int32),
        ("yrel",      c_int32),
    ]


# ---------- prototypes ----------
def _bind(lib, name, restype, *argtypes):
    fn = getattr(lib, name)
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


# SDL2 core
Init                   = _bind(_sdl, "SDL_Init",                    c_int, c_uint32)
Quit                   = _bind(_sdl, "SDL_Quit",                    None)
GetError               = _bind(_sdl, "SDL_GetError",                c_char_p)
SetHint                = _bind(_sdl, "SDL_SetHint",                 c_int, c_char_p, c_char_p)
GetTicks               = _bind(_sdl, "SDL_GetTicks",                c_uint32)
Delay                  = _bind(_sdl, "SDL_Delay",                   None,  c_uint32)
PollEvent              = _bind(_sdl, "SDL_PollEvent",               c_int, POINTER(Event))
WaitEventTimeout       = _bind(_sdl, "SDL_WaitEventTimeout",        c_int, POINTER(Event), c_int)

CreateWindow           = _bind(_sdl, "SDL_CreateWindow",            c_void_p,
                               c_char_p, c_int, c_int, c_int, c_int, c_uint32)
DestroyWindow          = _bind(_sdl, "SDL_DestroyWindow",           None,  c_void_p)
GetWindowSize          = _bind(_sdl, "SDL_GetWindowSize",           None,  c_void_p, POINTER(c_int), POINTER(c_int))

CreateRenderer         = _bind(_sdl, "SDL_CreateRenderer",          c_void_p, c_void_p, c_int, c_uint32)
DestroyRenderer        = _bind(_sdl, "SDL_DestroyRenderer",         None,  c_void_p)
SetRenderDrawColor     = _bind(_sdl, "SDL_SetRenderDrawColor",      c_int, c_void_p, c_uint8, c_uint8, c_uint8, c_uint8)
SetRenderDrawBlendMode = _bind(_sdl, "SDL_SetRenderDrawBlendMode",  c_int, c_void_p, c_int)
RenderClear            = _bind(_sdl, "SDL_RenderClear",             c_int, c_void_p)
RenderFillRect         = _bind(_sdl, "SDL_RenderFillRect",          c_int, c_void_p, POINTER(Rect))
RenderFillRects        = _bind(_sdl, "SDL_RenderFillRects",         c_int, c_void_p, POINTER(Rect), c_int)
RenderDrawLine         = _bind(_sdl, "SDL_RenderDrawLine",          c_int, c_void_p, c_int, c_int, c_int, c_int)
RenderReadPixels       = _bind(_sdl, "SDL_RenderReadPixels",        c_int, c_void_p, POINTER(Rect), c_uint32, c_void_p, c_int)
RenderCopy             = _bind(_sdl, "SDL_RenderCopy",              c_int, c_void_p, c_void_p, POINTER(Rect), POINTER(Rect))
RenderSetClipRect      = _bind(_sdl, "SDL_RenderSetClipRect",       c_int, c_void_p, POINTER(Rect))
RenderGetClipRect      = _bind(_sdl, "SDL_RenderGetClipRect",       None,  c_void_p, POINTER(Rect))
RenderIsClipEnabled    = _bind(_sdl, "SDL_RenderIsClipEnabled",     c_int, c_void_p)
RenderPresent          = _bind(_sdl, "SDL_RenderPresent",           None,  c_void_p)

CreateTextureFromSurface = _bind(_sdl, "SDL_CreateTextureFromSurface", c_void_p, c_void_p, POINTER(Surface))
CreateTexture            = _bind(_sdl, "SDL_CreateTexture",            c_void_p, c_void_p, c_uint32, c_int, c_int, c_int)
DestroyTexture           = _bind(_sdl, "SDL_DestroyTexture",           None, c_void_p)
SetTextureAlphaMod       = _bind(_sdl, "SDL_SetTextureAlphaMod",       c_int, c_void_p, c_uint8)
SetTextureColorMod       = _bind(_sdl, "SDL_SetTextureColorMod",       c_int, c_void_p, c_uint8, c_uint8, c_uint8)
SetTextureBlendMode      = _bind(_sdl, "SDL_SetTextureBlendMode",      c_int, c_void_p, c_int)
SetTextureScaleMode      = _bind(_sdl, "SDL_SetTextureScaleMode",      c_int, c_void_p, c_int)
QueryTexture             = _bind(_sdl, "SDL_QueryTexture",             c_int, c_void_p, POINTER(c_uint32), POINTER(c_int), POINTER(c_int), POINTER(c_int))

# Game controllers / joysticks
NumJoysticks             = _bind(_sdl, "SDL_NumJoysticks",             c_int)
IsGameController         = _bind(_sdl, "SDL_IsGameController",         c_int, c_int)
GameControllerOpen       = _bind(_sdl, "SDL_GameControllerOpen",       c_void_p, c_int)
GameControllerClose      = _bind(_sdl, "SDL_GameControllerClose",      None, c_void_p)
GameControllerName       = _bind(_sdl, "SDL_GameControllerName",       c_char_p, c_void_p)
JoystickOpen             = _bind(_sdl, "SDL_JoystickOpen",             c_void_p, c_int)
JoystickClose            = _bind(_sdl, "SDL_JoystickClose",            None, c_void_p)
JoystickNameForIndex     = _bind(_sdl, "SDL_JoystickNameForIndex",     c_char_p, c_int)
SetRenderTarget          = _bind(_sdl, "SDL_SetRenderTarget",          c_int, c_void_p, c_void_p)
FreeSurface              = _bind(_sdl, "SDL_FreeSurface",              None, POINTER(Surface))
CreateRGBSurfaceWithFormatFrom = _bind(_sdl, "SDL_CreateRGBSurfaceWithFormatFrom", POINTER(Surface),
                                       c_void_p, c_int, c_int, c_int, c_int, c_uint32)

# SDL_image
IMG_Init               = _bind(_img, "IMG_Init",                    c_int, c_int)
IMG_Quit               = _bind(_img, "IMG_Quit",                    None)
IMG_Load               = _bind(_img, "IMG_Load",                    POINTER(Surface), c_char_p)
IMG_Load_RW            = _bind(_img, "IMG_Load_RW",                 POINTER(Surface), c_void_p, c_int)
RWFromConstMem         = _bind(_sdl, "SDL_RWFromConstMem",          c_void_p, c_void_p, c_int)

# SDL_ttf
TTF_Init               = _bind(_ttf, "TTF_Init",                    c_int)
TTF_Quit               = _bind(_ttf, "TTF_Quit",                    None)
TTF_OpenFont           = _bind(_ttf, "TTF_OpenFont",                c_void_p, c_char_p, c_int)
TTF_SetFontHinting     = _bind(_ttf, "TTF_SetFontHinting",          None, c_void_p, c_int)
TTF_CloseFont          = _bind(_ttf, "TTF_CloseFont",               None, c_void_p)
TTF_RenderUTF8_Blended = _bind(_ttf, "TTF_RenderUTF8_Blended",      POINTER(Surface), c_void_p, c_char_p, Color)
TTF_SizeUTF8           = _bind(_ttf, "TTF_SizeUTF8",                c_int, c_void_p, c_char_p, POINTER(c_int), POINTER(c_int))
TTF_FontHeight         = _bind(_ttf, "TTF_FontHeight",              c_int, c_void_p)
TTF_FontLineSkip       = _bind(_ttf, "TTF_FontLineSkip",            c_int, c_void_p)


def error() -> str:
    e = GetError()
    return e.decode("utf-8", "replace") if e else ""
