#!/bin/bash
# Re-extracts the shaders from libdrastouch.c, renders the test pattern (or a 256x192 PPM given
# as $1) through every scaler and checks sharp-shimmerless (= area filter) and nitro-sharp against
# the CPU reference.
set -e
cd "$(dirname "$0")"
HOOK=../../projects/ROCKNIX/packages/emulators/standalone/drastic-sa/sources/libdrastouch.c
export LIBGL_ALWAYS_SOFTWARE=1
python3 extract_shaders.py "$HOOK" shaders.h >/dev/null
gcc -O2 -Wall -Wno-unused-variable -o gles_sim gles_sim.c -ldl
gcc -O2 -Wall -o ref ref.c
mkdir -p out
if [ -n "$1" ]; then IN="$1"; else python3 imgtool.py pattern out/pattern.ppm out/pattern-hires.ppm; IN=out/pattern.ppm; fi

METHODS="nearest bilinear sharp-bilinear sharp-shimmerless nitro-sharp"
for m in $METHODS; do
    ./gles_sim "$m" "$IN" "out/$m.ppm" 2>/dev/null
    ./gles_sim -desktop "$m" "$IN" "out/$m-gl.ppm" 2>/dev/null
    python3 imgtool.py png "out/$m.ppm" "out/$m.png"
done
./ref 0 "$IN" out/ref-area.ppm
./ref 1 "$IN" out/ref-nitro-sharp.ppm

check() { printf '%-44s ' "$1"; python3 imgtool.py diff "$2" "$3" || FAIL=1; }
FAIL=0
check "sharp-shimmerless vs CPU area reference"   out/sharp-shimmerless.ppm out/ref-area.ppm
check "nitro-sharp (GLES2) vs CPU reference"       out/nitro-sharp.ppm  out/ref-nitro-sharp.ppm
check "sharp-shimmerless (desktop GL) vs GLES2"   out/sharp-shimmerless-gl.ppm out/sharp-shimmerless.ppm
check "nitro-sharp (desktop GL) vs GLES2"          out/nitro-sharp-gl.ppm out/nitro-sharp.ppm
if [ -z "$1" ]; then
    # Hi-Res 3D: DraStic doubles 2D layers, 512x384 -> 640x480 must equal 256x192 -> 640x480
    ./gles_sim sharp-shimmerless out/pattern-hires.ppm out/sharp-shimmerless-hires.ppm 2>/dev/null
    ./gles_sim nitro-sharp out/pattern-hires.ppm out/nitro-sharp-hires.ppm 2>/dev/null
    check "shimmerless hires (512x384) vs 256x192"    out/sharp-shimmerless-hires.ppm out/sharp-shimmerless.ppm
    check "nitro-sharp hires = plain area filter"      out/nitro-sharp-hires.ppm out/sharp-shimmerless.ppm
fi

S=""; for m in $METHODS; do S="$S out/$m.ppm $m"; done
python3 imgtool.py sheet out/sheet-text.png 0,0,440,190 2 $S
python3 imgtool.py sheet out/sheet-lines.png 140,180,420,120 3 $S
python3 imgtool.py sheet out/sheet-sphere.png 20,280,280,180 2 $S
python3 imgtool.py sheet out/sheet-sprite.png 230,380,240,90 4 $S
[ $FAIL = 0 ] && echo "ALL CHECKS PASSED" || { echo "CHECKS FAILED"; exit 1; }
