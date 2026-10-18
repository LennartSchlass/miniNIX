#!/bin/bash
# Runs libdrastouch.so on the PC inside a real SDL2 GLES2 renderer (offscreen EGL, Mesa
# llvmpipe) and compares the DS screens it draws with the simulator's output. Builds a
# minimal SDL2 and fetches libGLESv2 into .hooktest/ on first use; no root needed.
# usage: hooktest.sh [shader ...]   (default: nitro-sharp sharp-shimmerless)
set -e
cd "$(dirname "$0")"
HOOK=../../projects/ROCKNIX/packages/emulators/standalone/drastic-sa/sources/libdrastouch.c
D=$PWD/.hooktest
SDL_VER=2.30.9
mkdir -p "$D"

if [ ! -f "$D/inc/SDL2/SDL.h" ]; then
    curl -sSL -o "$D/sdl.tar.gz" "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VER/SDL2-$SDL_VER.tar.gz"
    tar xzf "$D/sdl.tar.gz" -C "$D"
    mkdir -p "$D/inc/SDL2" && cp "$D/SDL2-$SDL_VER/include/"*.h "$D/inc/SDL2/"
fi
if [ ! -f "$D/sdl/lib/libSDL2.so" ]; then
    mkdir -p "$D/sdlbuild" && cd "$D/sdlbuild"
    "$D/SDL2-$SDL_VER/configure" --prefix="$D/sdl" --enable-shared --disable-static \
        --disable-video-wayland --disable-video-x11 --disable-video-kmsdrm --disable-video-vulkan \
        --disable-video-opengl --enable-video-opengles --enable-video-opengles2 --enable-video-offscreen \
        --disable-audio --disable-joystick --disable-haptic --disable-sensor --disable-hidapi \
        --disable-libudev --disable-dbus --disable-ibus --disable-fcitx --disable-power \
        --disable-filesystem --disable-pulseaudio --disable-alsa --disable-pipewire >configure.log 2>&1
    make -j"$(nproc)" >make.log 2>&1 && make install >install.log 2>&1
    cd "$OLDPWD"
fi
if [ ! -f "$D/gles/usr/lib/x86_64-linux-gnu/libGLESv2.so.2" ]; then
    mkdir -p "$D/gles"
    curl -sSL -o "$D/libgles2.deb" http://archive.ubuntu.com/ubuntu/pool/main/libg/libglvnd/libgles2_1.7.0-1build1_amd64.deb
    dpkg-deb -x "$D/libgles2.deb" "$D/gles"
fi

gcc -O2 -Wall -Wno-unused-parameter -shared -fPIC -I"$D/inc" -o "$D/libdrastouch.so" "$HOOK" -ldl
gcc -O1 -Wall -I"$D/inc" -o "$D/hooktest" hooktest.c -L"$D/sdl/lib" -lSDL2 -Wl,-rpath,"$D/sdl/lib"
./run.sh >/dev/null

export LD_LIBRARY_PATH="$D/sdl/lib:$D/gles/usr/lib/x86_64-linux-gnu" EGL_PLATFORM=surfaceless LIBGL_ALWAYS_SOFTWARE=1 SDL_VIDEODRIVER=offscreen
[ $# -eq 0 ] && set -- nitro-sharp sharp-shimmerless
FAIL=0
for sh in "$@"; do
    LD_PRELOAD="$D/libdrastouch.so" DSHOOK_SHADER="$sh" DSHOOK_WINDOW_SIZE=1024x768 "$D/hooktest" out/pattern.ppm "out/hook-$sh.ppm" 2>"$D/hook-$sh.log" || { echo "$sh: hooktest exited with $?"; FAIL=1; }
    ./gles_sim "$sh" out/pattern.ppm "out/$sh-384.ppm" 384 288 2>/dev/null
    python3 - "$sh" <<'PY' || FAIL=1
import sys, imgtool as t
sh = sys.argv[1]
win = t.load_ppm(f'out/hook-{sh}.ppm')
ok = True
for name, (x0, y0, w, h), ref in (('screen A 640x480', (0, 0, 640, 480), f'out/{sh}.ppm'),
                                  ('screen B 384x288', (640, 0, 384, 288), f'out/{sh}-384.ppm')):
    r = t.load_ppm(ref)
    bad = sum(max(abs(win.get(x0 + x, y0 + y)[i] - r.get(x, y)[i]) for i in range(3)) > 1 for y in range(h) for x in range(w))
    print(f'{sh:18s} hook {name} vs simulator: {bad} pixels off by >1')
    ok &= bad == 0
sys.exit(0 if ok else 1)
PY
done
[ $FAIL = 0 ] && echo "HOOK TEST PASSED" || { echo "HOOK TEST FAILED"; exit 1; }
