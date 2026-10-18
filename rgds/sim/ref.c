// CPU reference for the 2->5 area / nitro-sharp scaler, RGB888 in/out, in the shader's two
// passes: rows are scaled to the output width and rounded to 8 bit, then the columns.
// usage: ref <0|1 sharp> in.ppm out.ppm   (in: W x H, out: 2.5W x 2.5H)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { unsigned char c[3]; } px;

static int W, H, OW;
static px *S, *M;   /* source, horizontally scaled rows (OW x H) */

static int clampi(int v, int hi) { return v < 0 ? 0 : v > hi ? hi : v; }
static px src(int x, int y) { return S[clampi(y, H - 1) * W + clampi(x, W - 1)]; }
static px mid(int x, int y) { return M[clampi(y, H - 1) * OW + clampi(x, OW - 1)]; }
static int eq(px a, px b) { return !memcmp(&a, &b, sizeof a); }

/* 2: b takes the blended pixel, 0: a does, 1: 50/50 */
static int vote(px nl, px na, px nb, px nr, px a, px b) {
    int la = eq(nl, na), br = eq(nb, nr);
    if (la == br || eq(na, nb)) return 0;
    px c = la ? nb : na;
    return eq(c, b) ? 1 : eq(c, a) ? -1 : 0;
}
static int agree(int v0, int v1, int w) {
    int lo = v0 < v1 ? v0 : v1, hi = v0 > v1 ? v0 : v1;
    if (v0 + v1 > 0 && lo >= 0) return 2;
    if (v0 + v1 < 0 && hi <= 0) return 0;
    return w;
}
static px blend(px a, px b, int w) {
    px o;
    for (int k = 0; k < 3; k++) o.c[k] = w == 2 ? b.c[k] : w == 0 ? a.c[k] : (a.c[k] + b.c[k] + 1) >> 1;
    return o;
}
static int pure_col(int c) { return clampi((5 * c + 1) / 2, OW - 1); } /* ceil(2.5 c) */

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: ref <0|1> in.ppm out.ppm\n"); return 1; }
    int sharp = atoi(argv[1]);
    FILE *f = fopen(argv[2], "rb");
    if (!f || fscanf(f, "P6 %d %d 255", &W, &H) != 2) return 1;
    fgetc(f);
    S = malloc(W * H * sizeof(px));
    if (fread(S, sizeof(px), W * H, f) != (size_t)(W * H)) return 1;
    fclose(f);
    OW = W * 5 / 2;
    int OH = H * 5 / 2;
    M = malloc(OW * H * sizeof(px));

    for (int y = 0; y < H; y++)
        for (int x = 0; x < OW; x++) {
            int k = x % 5, c = x / 5 * 2;
            px a = src(c, y), b = src(c + 1, y);
            int w = k < 2 ? 0 : k > 2 ? 2 : 1;
            if (w == 1 && sharp && !eq(a, b)) {
                int la = eq(src(c - 1, y), a), br = eq(b, src(c + 2, y));
                if (la != br) w = la ? 2 : 0;
                else if (la)
                    w = agree(vote(src(c - 1, y - 1), src(c, y - 1), src(c + 1, y - 1), src(c + 2, y - 1), a, b),
                              vote(src(c - 1, y + 1), src(c, y + 1), src(c + 1, y + 1), src(c + 2, y + 1), a, b), w);
            }
            M[y * OW + x] = blend(a, b, w);
        }

    f = fopen(argv[3], "wb");
    fprintf(f, "P6\n%d %d\n255\n", OW, OH);
    for (int oy = 0; oy < OH; oy++)
        for (int x = 0; x < OW; x++) {
            int k = oy % 5, j = oy / 5 * 2;
            px a = mid(x, j), b = mid(x, j + 1);
            int w = k < 2 ? 0 : k > 2 ? 2 : 1;
            if (w == 1 && sharp && !eq(a, b)) {
                int la = eq(mid(x, j - 1), a), br = eq(b, mid(x, j + 2));
                if (la != br) w = la ? 2 : 0;
                else if (la) {
                    int kx = x % 5, c = x / 5 * 2;
                    int xl = pure_col(kx < 2 ? c - 1 : c), xr = pure_col(kx > 2 ? c + 2 : c + 1);
                    w = agree(vote(mid(xl, j - 1), mid(xl, j), mid(xl, j + 1), mid(xl, j + 2), a, b),
                              vote(mid(xr, j - 1), mid(xr, j), mid(xr, j + 1), mid(xr, j + 2), a, b), w);
                }
            }
            px o = blend(a, b, w);
            fwrite(&o, 1, 3, f);
        }
    fclose(f);
    return 0;
}
