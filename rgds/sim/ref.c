// CPU reference for the 2->5 area / nitro-sharp scaler (handoff notes), RGB888 in/out.
// Works in fixed point (horizontal blends x2, vertical x4) and rounds once at the end,
// so colour comparisons are exact like the shader's.
// usage: ref <0|1 sharp> in.ppm out.ppm   (in: W x H, out: 2.5W x 2.5H)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int c[3]; } px;

static int W, H;
static px *S;   /* source, scaled x2 so it compares with horizontally scaled values */

static px src(int x, int y) {
    x = x < 0 ? 0 : x >= W ? W - 1 : x;
    y = y < 0 ? 0 : y >= H ? H - 1 : y;
    return S[y * W + x];
}
static int eq(px a, px b) { return !memcmp(&a, &b, sizeof a); }

/* 2: b takes the blended pixel, 0: a does, 1: undecided */
static int side(px l, px a, px b, px r) {
    int la = eq(l, a), br = eq(b, r);
    if (la && !br) return 2;
    if (br && !la) return 0;
    return 1;
}
static int vote(px nl, px na, px nb, px nr, px a, px b) {
    if (eq(na, nb)) return 0;
    int s = side(nl, na, nb, nr);
    if (s == 1) return 0;
    px c = s ? nb : na;
    return eq(c, b) ? 1 : eq(c, a) ? -1 : 0;
}
static int agree(int v0, int v1) {
    int hi = v0 > v1 ? v0 : v1, lo = v0 < v1 ? v0 : v1;
    if (hi > 0 && lo >= 0) return 2;
    if (lo < 0 && hi <= 0) return 0;
    return 1;
}
static px blend(px a, px b, int s) { /* result x2 relative to inputs */
    px o;
    for (int k = 0; k < 3; k++) o.c[k] = s == 2 ? 2 * b.c[k] : s == 0 ? 2 * a.c[k] : a.c[k] + b.c[k];
    return o;
}

static void hrow(int y, px *d, int sharp) { /* w -> 2.5w, values x2 (x4 vs. original) */
    for (int x = 0; x < W; x += 2, d += 5) {
        px A = src(x, y), B = src(x + 1, y);
        int s = 1;
        if (sharp && !eq(A, B)) {
            s = side(src(x - 1, y), A, B, src(x + 2, y));
            if (s == 1)
                s = agree(vote(src(x - 1, y - 1), src(x, y - 1), src(x + 1, y - 1), src(x + 2, y - 1), A, B),
                          vote(src(x - 1, y + 1), src(x, y + 1), src(x + 1, y + 1), src(x + 2, y + 1), A, B));
        }
        d[0] = d[1] = blend(A, A, 1); d[2] = blend(A, B, s); d[3] = d[4] = blend(B, B, 1);
    }
}

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: ref <0|1> in.ppm out.ppm\n"); return 1; }
    int sharp = atoi(argv[1]);
    FILE *f = fopen(argv[2], "rb");
    if (!f || fscanf(f, "P6 %d %d 255", &W, &H) != 2) return 1;
    fgetc(f);
    S = malloc(W * H * sizeof(px));
    for (int i = 0; i < W * H; i++)
        for (int k = 0; k < 3; k++) S[i].c[k] = 2 * fgetc(f);
    fclose(f);
    int ow = W * 5 / 2, oh = H * 5 / 2;
    px *hs = malloc(ow * H * sizeof(px));     /* horizontally scaled rows */
    for (int y = 0; y < H; y++) hrow(y, hs + y * ow, sharp);
#define E(y, x) hs[((y) < 0 ? 0 : (y) >= H ? H - 1 : (y)) * ow + (x)]
#define R2(x, y) blend(src(x, y), src(x, y), 1) /* raw texel at the hs scale */
    f = fopen(argv[3], "wb");
    fprintf(f, "P6\n%d %d\n255\n", ow, oh);
    for (int oy = 0; oy < oh; oy++) {
        int j = oy / 5 * 2, ph = oy % 5;
        for (int x = 0; x < ow; x++) {
            px A = E(j, x), B = E(j + 1, x), v;
            if (ph < 2) v = blend(A, A, 1);
            else if (ph > 2) v = blend(B, B, 1);
            else {
                int s = 1;
                if (sharp && !eq(A, B)) {
                    s = side(E(j - 1, x), A, B, E(j + 2, x));
                    if (s == 1) {
                        int k = x % 5, c0 = x / 5 * 2, n0, n1;
                        if (k < 2) { n0 = c0 - 1; n1 = c0 + 1; }
                        else if (k > 2) { n0 = c0; n1 = c0 + 2; }
                        else { n0 = c0; n1 = c0 + 1; }
                        s = agree(vote(R2(n0, j - 1), R2(n0, j), R2(n0, j + 1), R2(n0, j + 2), A, B),
                                  vote(R2(n1, j - 1), R2(n1, j), R2(n1, j + 1), R2(n1, j + 2), A, B));
                    }
                }
                v = blend(A, B, s);
            }
            for (int k = 0; k < 3; k++) fputc((v.c[k] + 4) >> 3, f);
        }
    }
    fclose(f);
    return 0;
}
