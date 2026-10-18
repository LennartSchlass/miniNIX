#!/usr/bin/env python3
"""Emulates mediump (fp16, as on Mali Bifrost) for the per-axis sample position of
sharp-shimmerless and area at 256->640, against exact maths. Reports output columns
whose bilinear sample position is off by more than 1/64 texel (visible bleed/blur)."""
import math, struct
def h(v): return struct.unpack('e', struct.pack('e', v))[0]

T, O = 256.0, 640.0
def shimmerless(x, r):
    v = r((x + .5) / O)
    pixel = r(v * O); scale = r(O / T); inv = r(T / O)
    tl = math.floor(pixel); br = math.floor(r(pixel + 1))
    ttl = math.floor(r(inv * tl)); tbr = math.floor(r(inv * br))
    m = r(tbr + .5)
    if tbr > ttl: m = r(m - r(r(scale * tbr) - tl))
    return m
def area(x, r):
    v = r((x + .5) / O)
    p = r(v * T); i = math.floor(r(p + .5))
    w = min(1, max(0, r(r(r(p - i) * r(O / T)) + .5)))
    return r(r(i - .5) + w)
exact = lambda v: v
for name, f in (("sharp-shimmerless", shimmerless), ("area", area)):
    bad = [(x, f(x, exact), f(x, h)) for x in range(640) if abs(f(x, exact) - f(x, h)) > 1 / 64]
    worst = max((abs(a - b) for _, a, b in bad), default=0)
    print(f"{name:18s} mediump: {len(bad):3d}/640 columns off by >1/64 texel, worst {worst:.3f} texel; first: {bad[:3]}")
