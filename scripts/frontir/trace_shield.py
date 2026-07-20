"""Trace the Frontir shield alpha mask into real SVG paths.

The shipped frontir-icon.svg is a 192px PNG wrapped in an <image> tag, while
manifest.json advertises it as sizes:"any" -- i.e. it claims to be vector and
is not.  This produces genuine geometry from the brand raster and then proves
fidelity by re-rasterising the traced polygons and diffing against the source.

Pure PIL + stdlib (no numpy/cv2 available on this box).
"""
import math
from PIL import Image

import os
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, '..', '..', 'static')
SRC = os.path.join(STATIC, 'frontir-shield.png')
UPSCALE = 4          # trace on a resampled grid so curves land sub-pixel
THRESH = 128


def load_mask(path, upscale):
    im = Image.open(path).convert('RGBA')
    a = im.getchannel('A')
    w, h = a.size
    if upscale != 1:
        a = a.resize((w * upscale, h * upscale), Image.LANCZOS)
    w, h = a.size
    px = a.load()
    filled = [[px[x, y] >= THRESH for x in range(w)] for y in range(h)]
    return filled, w, h


def boundary_loops(filled, w, h):
    """Collect unit boundary edges with consistent winding, chain into loops.

    For each filled pixel every side facing an empty pixel (or the canvas
    edge) contributes one directed edge.  Directing them consistently makes
    the chained loops closed and gives holes the opposite winding to the
    outline automatically -- which is exactly what SVG's evenodd rule wants.
    """
    edges = {}

    def add(p, q):
        edges.setdefault(p, []).append(q)

    for y in range(h):
        row = filled[y]
        up = filled[y - 1] if y > 0 else None
        dn = filled[y + 1] if y + 1 < h else None
        for x in range(w):
            if not row[x]:
                continue
            if up is None or not up[x]:
                add((x + 1, y), (x, y))            # top    <-
            if dn is None or not dn[x]:
                add((x, y + 1), (x + 1, y + 1))    # bottom ->
            if x == 0 or not row[x - 1]:
                add((x, y), (x, y + 1))            # left   v
            if x + 1 >= w or not row[x + 1]:
                add((x + 1, y + 1), (x + 1, y))    # right  ^

    loops = []
    while edges:
        start = next(iter(edges))
        loop = [start]
        cur = start
        while True:
            outs = edges.get(cur)
            if not outs:
                break
            nxt = outs.pop()
            if not outs:
                del edges[cur]
            if nxt == start:
                break
            loop.append(nxt)
            cur = nxt
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def collinear_prune(pts):
    """Drop midpoints of straight runs before DP -- cheap and lossless."""
    out = []
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]
        if (bx - ax) * (cy - by) != (by - ay) * (cx - bx):
            out.append((bx, by))
    return out or pts


def dp(pts, eps):
    """Douglas-Peucker on an open run."""
    if len(pts) < 3:
        return list(pts)
    ax, ay = pts[0]
    bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    den = math.hypot(dx, dy)
    worst, wi = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = (abs(dx * (ay - py) - (ax - px) * dy) / den) if den else math.hypot(px - ax, py - ay)
        if d > worst:
            worst, wi = d, i
    if worst <= eps:
        return [pts[0], pts[-1]]
    return dp(pts[:wi + 1], eps)[:-1] + dp(pts[wi:], eps)


def simplify_loop(loop, eps):
    pts = collinear_prune(loop)
    if len(pts) < 4:
        return pts
    # split at the two extreme points so DP never collapses the whole ring
    far = max(range(len(pts)), key=lambda i: (pts[i][1], pts[i][0]))
    pts = pts[far:] + pts[:far]
    half = len(pts) // 2
    a = dp(pts[:half + 1], eps)
    b = dp(pts[half:] + [pts[0]], eps)
    return a[:-1] + b[:-1]


def rasterise(loops, w, h):
    """Even-odd scanline fill, sampling pixel centres -- the verification."""
    grid = [bytearray(w) for _ in range(h)]
    segs = []
    for lp in loops:
        n = len(lp)
        for i in range(n):
            x1, y1 = lp[i]
            x2, y2 = lp[(i + 1) % n]
            if y1 != y2:
                segs.append((x1, y1, x2, y2))
    for y in range(h):
        yc = y + 0.5
        xs = []
        for x1, y1, x2, y2 in segs:
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                xs.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        row = grid[y]
        for i in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[i] - 0.5)))
            b = min(w - 1, int(math.floor(xs[i + 1] - 0.5)))
            for x in range(a, b + 1):
                row[x] = 1
    return grid


def main():
    filled, w, h = load_mask(SRC, UPSCALE)
    print(f'traced grid {w}x{h} (source x{UPSCALE})')

    loops = boundary_loops(filled, w, h)
    print(f'{len(loops)} closed loop(s); raw vertices {sum(len(l) for l in loops)}')

    eps = 0.6 * UPSCALE / 2          # ~0.3 source px
    simp = [simplify_loop(l, eps) for l in loops]
    simp = [s for s in simp if len(s) >= 3]
    print(f'after simplify: {sum(len(s) for s in simp)} vertices')

    # ---- verification: rasterise the traced polygons, diff vs source ----
    got = rasterise(simp, w, h)
    inter = union = src_n = 0
    for y in range(h):
        fr, gr = filled[y], got[y]
        for x in range(w):
            a, b = fr[x], bool(gr[x])
            if a:
                src_n += 1
            if a and b:
                inter += 1
            if a or b:
                union += 1
    print(f'fidelity: IoU {inter/union*100:.3f}%   source px {src_n}')

    # ---- emit path data in a 0..256 space (source resolution) ----
    def fmt(v):
        s = f'{v:.2f}'.rstrip('0').rstrip('.')
        return s if s not in ('', '-0') else '0'

    parts = []
    for s in simp:
        d = 'M' + ' '.join(f'{fmt(x/UPSCALE)} {fmt(y/UPSCALE)}' for x, y in s[:1])
        d += ''.join(f'L{fmt(x/UPSCALE)} {fmt(y/UPSCALE)}' for x, y in s[1:]) + 'Z'
        parts.append(d)
    path = ''.join(parts)
    print(f'path length {len(path)} chars')
    with open(os.path.join(HERE, 'shield_path.txt'), 'w') as f:
        f.write(path)

    # true worst-case radius of the shape about its own centre (for maskable)
    xs = [x for y in range(h) for x in range(w) if filled[y][x]]
    ys = [y for y in range(h) for x in range(w) if filled[y][x]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    worst = 0.0
    for y in range(h):
        fr = filled[y]
        for x in range(w):
            if fr[x]:
                worst = max(worst, math.hypot(x + .5 - cx, y + .5 - cy))
    print(f'shape bbox {min(xs)/UPSCALE:.1f},{min(ys)/UPSCALE:.1f} -> '
          f'{max(xs)/UPSCALE:.1f},{max(ys)/UPSCALE:.1f}')
    print(f'true max radius about centre: {worst/UPSCALE:.2f} source px '
          f'({worst/UPSCALE/256*100:.1f}% of a 256 canvas)')


main()
