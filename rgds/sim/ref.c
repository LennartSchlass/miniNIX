// CPU reference for the 2->5 area / area-sharp scaler (handoff notes), RGB888 in/out.
// Works in fixed point (horizontal blends x2, vertical x4) and rounds once at the end,
// so colour comparisons are exact like the shader's.
// usage: ref <0|1 sharp> in.ppm out.ppm   (in: W x H, out: 2.5W x 2.5H)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int c[3]; } px;

static int eq(px a, px b) { return !memcmp(&a, &b, sizeof a); }
static px mix(px a, px b, int sharp, px l, px r) {
    if (sharp && !eq(a, b)) {
        if (eq(l, a) && !eq(b, r)) a = b;
        else if (eq(r, b) && !eq(a, l)) b = a;
    }
    px o;
    for (int k = 0; k < 3; k++) o.c[k] = a.c[k] + b.c[k];
    return o;
}
static px dbl(px a) { for (int k = 0; k < 3; k++) a.c[k] *= 2; return a; }

static void hrow(const px *s, int w, px *d, int sharp) { /* w -> 2.5w, values x2 */
    for (int x = 0; x < w; x += 2, d += 5) {
        px L = s[x ? x - 1 : 0], A = s[x], B = s[x + 1], R = s[x + 2 < w ? x + 2 : w - 1];
        d[0] = d[1] = dbl(A); d[2] = mix(A, B, sharp, L, R); d[3] = d[4] = dbl(B);
    }
}
int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: ref <0|1> in.ppm out.ppm\n"); return 1; }
    int w, h, sharp = atoi(argv[1]);
    FILE *f = fopen(argv[2], "rb");
    if (!f || fscanf(f, "P6 %d %d 255", &w, &h) != 2) return 1;
    fgetc(f);
    px *src = malloc(w * h * sizeof(px));
    for (int i = 0; i < w * h; i++)
        for (int k = 0; k < 3; k++) src[i].c[k] = fgetc(f);
    fclose(f);
    int ow = w * 5 / 2, oh = h * 5 / 2;
    px *hs = malloc(ow * h * sizeof(px));     /* horizontally scaled rows, x2 */
    for (int y = 0; y < h; y++) hrow(src + y * w, w, hs + y * ow, sharp);
    f = fopen(argv[3], "wb");
    fprintf(f, "P6\n%d %d\n255\n", ow, oh);
    for (int oy = 0; oy < oh; oy++) {
        int j = oy / 5 * 2, ph = oy % 5;
        for (int x = 0; x < ow; x++) {
            px A = hs[j * ow + x], B = hs[(j + 1) * ow + x], v;
            if (ph < 2) v = dbl(A);
            else if (ph > 2) v = dbl(B);
            else v = mix(A, B, sharp, hs[(j ? j - 1 : 0) * ow + x], hs[(j + 2 < h ? j + 2 : h - 1) * ow + x]);
            for (int k = 0; k < 3; k++) fputc((v.c[k] + 2) >> 2, f);
        }
    }
    fclose(f);
    return 0;
}
