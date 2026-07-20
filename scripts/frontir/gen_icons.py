"""Generate the Frontir Sentry icon set.

Fixes four real defects in the shipped set:
  1. frontir-icon.svg was a 192px PNG inside an <image> tag while
     manifest.json advertised it as sizes:"any" -- it now really is vector.
  2. favicon.ico was still the upstream Hermes caduceus, single 256px frame;
     Windows wants 16/24/32/48 and browsers want a real multi-size file.
  3. The one icon declared purpose:"any maskable" is clipped by Android's
     circular mask (measured: shape reaches r=54.3% of canvas, safe zone is
     40%).  "any" and "maskable" now get separate, correctly-composed assets.
  4. Small sizes reused the large-icon composition, so at 16px the shield's
     internal cutouts turned to mush.  Sizes are now optically scaled.

Pure PIL + stdlib.
"""
import math
from PIL import Image, ImageFilter

import os
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'static') + os.sep
SCRATCH = HERE + os.sep
INK = (9, 9, 11)          # #09090B -- brand canvas, measured off the master
BONE = (249, 248, 250)    # shield fill, measured off the master

# Traced shield geometry, in a 0..256 space (see trace_shield.py).
PATH_LOOPS = None         # filled in by load_geometry()


def load_geometry():
    """Re-run the trace and return loops in 0..256 space."""
    import sys
    sys.setrecursionlimit(20000)
    src = open(SCRATCH + 'trace_shield.py', encoding='utf-8').read().replace('main()\n', '')
    # exec() gets no __file__ of its own; trace_shield.py resolves static/ from it
    ns = {'__file__': os.path.join(HERE, 'trace_shield.py')}
    exec(compile(src, 'trace_shield.py', 'exec'), ns)
    filled, w, h = ns['load_mask'](ns['SRC'], ns['UPSCALE'])
    loops = ns['boundary_loops'](filled, w, h)
    up = ns['UPSCALE']
    simp = [ns['simplify_loop'](l, 0.3 * up) for l in loops]
    simp = [[(x / up, y / up) for x, y in s] for s in simp if len(s) >= 3]
    return simp


def bbox(loops):
    xs = [p[0] for l in loops for p in l]
    ys = [p[1] for l in loops for p in l]
    return min(xs), min(ys), max(xs), max(ys)


def place(loops, canvas, frac):
    """Scale loops so the shield spans `frac` of `canvas`, centred."""
    x0, y0, x1, y1 = bbox(loops)
    s = (canvas * frac) / (x1 - x0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return [[((x - cx) * s + canvas / 2, (y - cy) * s + canvas / 2) for x, y in l]
            for l in loops]


def max_radius(loops, canvas):
    return max(math.hypot(x - canvas / 2, y - canvas / 2) for l in loops for x, y in l)


def fill_mask(loops, size, ss=4):
    """Even-odd scanline fill at `ss`x, downsampled -> antialiased L mask."""
    w = h = size * ss
    sc = [[(x * ss, y * ss) for x, y in l] for l in loops]
    segs = []
    for lp in sc:
        n = len(lp)
        for i in range(n):
            x1, y1 = lp[i]
            x2, y2 = lp[(i + 1) % n]
            if y1 != y2:
                segs.append((x1, y1, x2, y2))
    img = Image.new('L', (w, h), 0)
    px = img.load()
    for y in range(h):
        yc = y + 0.5
        xs = sorted(x1 + (yc - y1) * (x2 - x1) / (y2 - y1)
                    for x1, y1, x2, y2 in segs
                    if (y1 <= yc < y2) or (y2 <= yc < y1))
        for i in range(0, len(xs) - 1, 2):
            a = max(0, int(math.ceil(xs[i] - 0.5)))
            b = min(w - 1, int(math.floor(xs[i + 1] - 0.5)))
            for x in range(a, b + 1):
                px[x, y] = 255
    return img.resize((size, size), Image.LANCZOS)


# The mark is five DISJOINT shapes, not one outline with holes:
#   0 shoulders/arc (top)   1 triangle   2 wide band   3 lens   4 bottom V
# Indices 1 and 3 are the fine detail; below ~32px they resample into grey
# mush and cost legibility rather than adding brand.
DROP_AT_20 = (1, 3)
DROP_AT_24 = (1,)


def detail_for(loops, size):
    """Optical sizing, second axis: shed fine detail before it turns to mush."""
    if size <= 20:
        return [l for i, l in enumerate(loops) if i not in DROP_AT_20]
    if size <= 24:
        return [l for i, l in enumerate(loops) if i not in DROP_AT_24]
    return loops


def tile(loops, size, frac=None, sharpen=None, simplify=True):
    """Composite: bone mark on a full-bleed ink tile, optically sized."""
    if simplify:
        loops = detail_for(loops, size)
    if frac is None:
        frac = frac_for(size)
    if sharpen is None:
        sharpen = size <= 48
    m = fill_mask(place(loops, size, frac), size)
    if sharpen:
        # resampling blur costs the small sizes their edge; a light unsharp
        # restores it without ringing. Push harder where it matters most.
        pct = 150 if size <= 20 else 90
        m = m.filter(ImageFilter.UnsharpMask(radius=1.0, percent=pct, threshold=0))
    im = Image.new('RGBA', (size, size), INK + (255,))
    im.paste(Image.new('RGBA', (size, size), BONE + (255,)), (0, 0), m)
    return im


def frac_for(size):
    """Optical sizing: small tiles need a bigger mark to stay legible."""
    if size <= 32:
        return 0.82
    if size <= 48:
        return 0.74
    if size <= 64:
        return 0.68
    return 0.588        # brand composition, matches the 512 master


def svg(loops, canvas=256, frac=0.588, bg=True):
    pl = place(loops, canvas, frac)

    def f(v):
        s = f'{v:.2f}'.rstrip('0').rstrip('.')
        return s if s not in ('', '-0') else '0'

    d = ''
    for l in pl:
        d += 'M' + f(l[0][0]) + ' ' + f(l[0][1])
        d += ''.join('L' + f(x) + ' ' + f(y) for x, y in l[1:]) + 'Z'
    ink = '#%02X%02X%02X' % INK
    bone = '#%02X%02X%02X' % BONE
    out = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {canvas} {canvas}" '
           f'width="{canvas}" height="{canvas}" role="img" '
           f'aria-label="Frontir Sentry">')
    out += '<title>Frontir Sentry</title>'
    if bg:
        out += f'<rect width="{canvas}" height="{canvas}" fill="{ink}"/>'
    out += f'<path fill="{bone}" fill-rule="evenodd" d="{d}"/></svg>'
    return out


def main():
    loops = load_geometry()
    print(f'geometry: {len(loops)} loops, {sum(len(l) for l in loops)} vertices')

    # ── 1. true vector icon, composed to match the 512 raster master ──
    s = svg(loops)
    open(OUT + 'frontir-icon.svg', 'w', encoding='utf-8').write(s)
    print(f'frontir-icon.svg      {len(s):>7,} bytes  (was 21,664 PNG-in-SVG)')
    # upstream-named copy so anything still pointing at favicon.svg is branded
    open(OUT + 'favicon.svg', 'w', encoding='utf-8').write(s)
    open(OUT + 'favicon-512.svg', 'w', encoding='utf-8').write(s)

    # ── 2. maskable: shield inside Android's 40%-radius safe circle ──
    #    solve the scale that puts the farthest vertex exactly on 0.38r
    #    (0.40 is the spec limit; 0.38 keeps a hair of margin)
    probe = place(loops, 512, 0.588)
    r = max_radius(probe, 512)
    frac = 0.588 * (0.38 * 512) / r
    mk = tile(loops, 512, frac=frac)
    mk.save(OUT + 'frontir-icon-maskable-512.png')
    chk = max_radius(place(loops, 512, frac), 512) / 512
    print(f'maskable-512.png      shield {frac*100:.1f}% of canvas, '
          f'max radius {chk*100:.1f}% (limit 40.0%)  {"OK" if chk<=0.40 else "FAIL"}')

    # ── 3. raster sizes, optically scaled ──
    for size, name in [(16, 'frontir-icon-16.png'),
                       (180, 'frontir-icon-180.png')]:
        tile(loops, size).save(OUT + name)
        print(f'{name:<22}{size}x{size}')

    # ── 4. rebrand the upstream Hermes rasters other code still points at ──
    #    messages.js uses favicon-192/favicon-32 for push notification icon
    #    and badge; sw.js precaches favicon-32.  Leaving them stock ships the
    #    caduceus in every push notification.
    for size, name in [(32, 'favicon-32.png'), (192, 'favicon-192.png'),
                       (512, 'favicon-512.png'), (512, 'apple-touch-icon.png')]:
        tile(loops, size).save(OUT + name)
        print(f'{name:<22}{size}x{size}  (was Hermes caduceus)')

    # ── 5. real multi-size .ico ──
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [tile(loops, n) for n in sizes]
    base = frames[-1]
    base.save(OUT + 'favicon.ico', format='ICO',
              sizes=[(n, n) for n in sizes],
              append_images=frames[:-1])
    ico = Image.open(OUT + 'favicon.ico')
    got = sorted(ico.info.get('sizes', []))
    print(f'favicon.ico           frames {got}')


main()
