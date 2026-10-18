#!/usr/bin/env python3
"""Test pattern, PPM/PNG I/O, diff and comparison sheets for the DraStic scaler simulator."""
import math, struct, sys, zlib

FONT = {  # 5x7, '#' = ink
    'A': ".###.#...##...#######...##...##...#", 'B': "####.#...#####.#...##...##...#####.",
    'C': ".###.#...##....#....#....#...#.###.", 'D': "####.#...##...##...##...##...#####.",
    'E': "######....####.#....#....#....#####", 'F': "######....####.#....#....#....#....",
    'G': ".###.#...##....#.####...##...#.####", 'H': "#...##...#######...##...##...##...#",
    'I': ".###...#....#....#....#....#...###.", 'K': "#...##..#.#.#..##...#.#..#..#.#...#",
    'L': "#....#....#....#....#....#....#####", 'M': "#...###.###.#.##...##...##...##...#",
    'N': "#...###..##.#.##..###...##...##...#", 'O': ".###.#...##...##...##...##...#.###.",
    'P': "####.#...##...#####.#....#....#....", 'R': "####.#...##...#####.#.#..#..#.#...#",
    'S': ".####.....#.....###.....#....#####.", 'T': "#####..#....#....#....#....#....#..",
    'U': "#...##...##...##...##...##...#.###.", 'V': "#...##...##...##...#.#.#..#.#...#..",
    'W': "#...##...##...##.#.##.#.##.#.#.#.#.", 'X': "#...##...#.#.#...#...#.#.#...##...#", 'Y': "#...##...#.#.#...#....#....#....#..",
    '0': ".###.#...##..###.#.###..##...#.###.", '1': "..#...##....#....#....#....#...###.",
    '2': ".###.#...#....#...#...#...#...#####", '3': "#####...#...#.....#.....##...#.###.",
    '4': "...#...##..#.#.#..#.#####...#....#.", '5': "######....####.....#....##...#.###.",
    '6': "..##..#...#....####.#...##...#.###.", '7': "#####....#...#...#...#....#....#...",
    '8': ".###.#...##...#.###.#...##...#.###.", '9': ".###.#...##...#.####....#...#..##..",
    '-': "..........#####.........." + "." * 10, '/': "....#....#...#...#...#...#....#....", ' ': "." * 35, '!': "..#....#....#....#....#.........#..",
}

def q5(v):  # DS 5-bit colour channel, expanded like RGB555 -> RGB888
    c = max(0, min(31, int(round(v * 31))))
    return (c << 3) | (c >> 2)

def q6(v):
    c = max(0, min(63, int(round(v * 63))))
    return (c << 2) | (c >> 4)

class Img:
    def __init__(s, w, h, fill=(0, 0, 0)):
        s.w, s.h = w, h
        s.p = [list(fill) for _ in range(w * h)]
    def set(s, x, y, c):
        if 0 <= x < s.w and 0 <= y < s.h:
            s.p[y * s.w + x] = list(c)
    def get(s, x, y):
        return s.p[y * s.w + x]
    def rect(s, x0, y0, w, h, c):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                s.set(x, y, c)
    def text(s, x0, y0, txt, c, shadow=None, scale=1):
        for n, ch in enumerate(txt):
            g = FONT[ch]
            for gy in range(7):
                for gx in range(5):
                    if g[gy * 5 + gx] == '#':
                        for sy in range(scale):
                            for sx in range(scale):
                                X, Y = x0 + n * 6 * scale + gx * scale + sx, y0 + gy * scale + sy
                                if shadow:
                                    for dx, dy in ((1, 0), (0, 1), (1, 1)):
                                        if s.get(X + dx, Y + dy) != list(c):
                                            s.set(X + dx, Y + dy, shadow)
                                s.set(X, Y, c)
    def save_ppm(s, path):
        with open(path, 'wb') as f:
            f.write(b'P6\n%d %d\n255\n' % (s.w, s.h))
            f.write(bytes(v for px in s.p for v in px))
    def save_png(s, path):
        raw = b''.join(b'\0' + bytes(v for px in s.p[y * s.w:(y + 1) * s.w] for v in px) for y in range(s.h))
        def chunk(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        with open(path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', s.w, s.h, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))

def load_ppm(path):
    data = open(path, 'rb').read()
    parts = data.split(maxsplit=4)
    w, h = int(parts[1]), int(parts[2])
    body = parts[4]
    img = Img(w, h)
    img.p = [list(body[i:i + 3]) for i in range(0, w * h * 3, 3)]
    return img

def pattern():
    W, H = 256, 192
    im = Img(W, H, (q5(.55), q5(.75), q5(.9)))
    white, ink, shade = (q5(1), q5(1), q5(1)), (q5(.25), q5(.25), q5(.25)), (q5(.8), q5(.8), q5(.75))
    # Pokemon-style dialog box: dark text with light shadow on white
    im.rect(4, 4, 168, 40, (q5(.3), q5(.5), q5(.8)))
    im.rect(6, 6, 164, 36, white)
    im.text(10, 10, "HP 42/57 LV 36", ink, shadow=shade)
    im.text(10, 26, "WILD PIKACHU!", ink, shadow=shade)
    # plain 1px black text on light background
    im.rect(4, 48, 168, 22, (q5(.95), q5(.95), q5(.85)))
    im.text(8, 51, "MARIO KART DS 1/2", (0, 0, 0))
    im.text(8, 61, "FINAL FANTASY IV", (q5(.6), 0, 0))
    # lines: 1px/2px horizontal and vertical, 1px grid, diagonals
    for i, x in enumerate(range(180, 252, 6)):
        im.rect(x, 4, 1 + (i % 2), 40, (0, 0, 0))
    for i, y in enumerate(range(48, 72, 4)):
        im.rect(180, y, 72, 1 + (i % 2), (q5(.9), 0, 0))
    for y in range(76, 116):
        for x in range(4, 60):
            if (x - 4) % 5 == 0 or (y - 76) % 5 == 0:
                im.set(x, y, (q5(.1), q5(.4), q5(.1)))
            else:
                im.set(x, y, white)
    for t in range(40):
        im.set(64 + t, 76 + t, (0, 0, 0))            # 45 degrees
        im.set(64 + t, 76 + t // 2, (0, 0, q5(.7)))  # ~27 degrees
        im.set(110 + t // 3, 76 + t, (q5(.7), 0, 0))  # steep
    # dithering: 1px checkerboard and 2x2 checkerboard
    for y in range(76, 116):
        for x in range(150, 184):
            im.set(x, y, (q5(.9), q5(.6), q5(.2)) if (x + y) % 2 else (q5(.4), q5(.2), q5(.5)))
        for x in range(186, 220):
            im.set(x, y, white if ((x // 2) + (y // 2)) % 2 else (0, 0, 0))
    # 3D-like shaded sphere (6-bit, every pixel slightly different) with a hard silhouette
    cx, cy, r = 50, 152, 34
    for y in range(cy - r, cy + r):
        for x in range(cx - r, cx + r):
            dx, dy = (x + .5 - cx) / r, (y + .5 - cy) / r
            d2 = dx * dx + dy * dy
            if d2 < 1:
                nz = math.sqrt(1 - d2)
                l = max(0, -.4 * dx - .5 * dy + .77 * nz)
                im.set(x, y, (q6(.15 + .8 * l), q6(.1 + .4 * l), q6(.05 + .2 * l)))
    # smooth gradient
    for y in range(120, 150):
        for x in range(96, 252):
            t = (x - 96) / 155
            im.set(x, y, (q5(t), q5(1 - t), q5(.5)))
    # pixel art sprite (mushroom), 16x16 at 1x and the large text at 2x
    spr = [".....######.....", "...##RRRRRR##...", "..#RRWWRRRRRR#..", ".#RRWWWWRRWWRR#.",
           ".#RRWWWWRRWWWR#.", "#RRRRWWRRRRRRRR#", "#RRRRRRRRRRRRRR#", "#RRWWRRRRRRWWRR#",
           "#RWWWWRRRRWWWWR#", ".#############..", "...#WW#WW#WW#...", "...#WW#WW#WW#...",
           "...#WWWWWWWWW#..", "....#WWWWWWW#...", ".....#######....", "................"]
    cols = {'#': (0, 0, 0), 'R': (q5(.85), q5(.1), q5(.1)), 'W': white}
    for sy, row in enumerate(spr):
        for sx, ch in enumerate(row):
            if ch in cols:
                im.set(100 + sx, 160 + sy, cols[ch])
    im.text(124, 156, "SAVE", (q5(.1), q5(.1), q5(.4)), scale=2)
    im.text(124, 176, "GAME 2X", (0, 0, 0))
    return im

def double(im):  # emulate DraStic Hi-Res 3D: 2D layers nearest-doubled to 512x384
    o = Img(im.w * 2, im.h * 2)
    for y in range(o.h):
        for x in range(o.w):
            o.p[y * o.w + x] = im.p[(y // 2) * im.w + x // 2]
    return o

def diff(a, b, tol=1):
    a, b = load_ppm(a), load_ppm(b)
    assert (a.w, a.h) == (b.w, b.h)
    m, n = 0, 0
    for p, q in zip(a.p, b.p):
        d = max(abs(p[i] - q[i]) for i in range(3))
        m = max(m, d)
        n += d > tol
    return m, n

def sheet(out, files, labels, crop, zoom):
    """Side-by-side crops (x, y, w, h in output pixels), nearest-zoomed, with labels."""
    x0, y0, cw, ch = crop
    cols = 2
    rows = (len(files) + cols - 1) // cols
    pad, lab = 6, 12
    S = Img(cols * (cw * zoom + pad) + pad, rows * (ch * zoom + pad + lab) + pad, (40, 40, 40))
    for k, (f, l) in enumerate(zip(files, labels)):
        im = load_ppm(f)
        ox = pad + (k % cols) * (cw * zoom + pad)
        oy = pad + (k // cols) * (ch * zoom + pad + lab)
        S.text(ox, oy, l.upper(), (230, 230, 230))
        oy += lab
        for y in range(ch * zoom):
            for x in range(cw * zoom):
                S.p[(oy + y) * S.w + ox + x] = im.get(x0 + x // zoom, y0 + y // zoom)
    S.save_png(out)

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'pattern':
        p = pattern()
        p.save_ppm(sys.argv[2])
        double(p).save_ppm(sys.argv[3])
    elif cmd == 'diff':
        tol = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        m, n = diff(sys.argv[2], sys.argv[3], tol)
        print(f"max channel diff {m}, pixels off by >{tol}: {n}")
        sys.exit(0 if n == 0 else 1)
    elif cmd == 'png':
        load_ppm(sys.argv[2]).save_png(sys.argv[3])
    elif cmd == 'sheet':
        out, crop, zoom = sys.argv[2], tuple(map(int, sys.argv[3].split(','))), int(sys.argv[4])
        files = sys.argv[5::2]
        labels = sys.argv[6::2]
        sheet(out, files, labels, crop, zoom)
