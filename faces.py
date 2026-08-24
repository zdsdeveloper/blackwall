import math

RAMP = " .:-=+*#%@"      # preview ramp
BLOCKS = " ░▒▓█"  # ' ', light, medium, dark, full

def ellipse(x, y, cx, cy, rx, ry):
    """Signed-ish falloff: 1.0 at centre, 0.0 at the rim, <0 outside."""
    if rx <= 0 or ry <= 0: return -1.0
    d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
    return 1.0 - math.sqrt(d) if d >= 0 else -1.0

def build(w, h, head, eyes, mouth, brow=None, tilt=0.0):
    grid = []
    for y in range(h):
        row = []
        for x in range(w):
            # Tilt shears the head horizontally by row, so a face can lean.
            xs = x + (y - h / 2.0) * tilt
            v = ellipse(xs, y, *head)
            if v <= 0:
                row.append(0); continue
            # Soft rim, solid core: the halo is what makes it read as ghost
            # rather than as a sticker.
            d = min(4, max(1, int(round(v * 5.2))))
            if brow:
                for (bx, by, brx, bry) in brow:
                    if ellipse(xs, y, bx, by, brx, bry) > 0:
                        d = min(4, d + 1)
            for (ex, ey, erx, ery) in eyes:
                if ellipse(xs, y, ex, ey, erx, ery) > 0:
                    d = 0
            for (mx, my, mrx, mry) in mouth:
                if ellipse(xs, y, mx, my, mrx, mry) > 0:
                    d = 0
            row.append(d)
        grid.append(row)
    return grid

def preview(grid):
    return "\n".join("".join(BLOCKS[c] for c in row) for row in grid)

W, H = 26, 13

# A — the watcher: wide, symmetric, level gaze, thin mouth.
A = build(W, H,
          head=(12.5, 6.0, 11.5, 6.6),
          eyes=[(7.5, 5.2, 2.6, 1.5), (17.5, 5.2, 2.6, 1.5)],
          mouth=[(12.5, 9.1, 3.4, 0.95)],
          brow=[(7.5, 3.4, 3.4, 0.9), (17.5, 3.4, 3.4, 0.9)])

# B — the caller: narrower, eyes closer, mouth open. Reads as mid-speech.
B = build(W, H,
          head=(12.5, 6.0, 9.2, 6.7),
          eyes=[(9.0, 4.9, 2.1, 1.7), (16.0, 4.9, 2.1, 1.7)],
          mouth=[(12.5, 9.2, 2.2, 1.5)])

# C — the presser: leaning in, one eye wider, jaw set. The one that feels
# like it is actually pushing on the glass.
C = build(W, H,
          head=(12.5, 6.2, 10.4, 6.4),
          eyes=[(8.2, 5.4, 3.0, 1.9), (17.4, 5.6, 2.0, 1.2)],
          mouth=[(12.8, 9.4, 3.0, 0.95)],
          brow=[(8.2, 3.5, 3.6, 1.0)],
          tilt=0.16)

for name, g in (("A watcher", A), ("B caller", B), ("C presser", C)):
    print("=== %s ===" % name)
    print(preview(g))
    print()

import json
print("WIDTHS", [len(set(len(r) for r in g)) for g in (A, B, C)])
open("/tmp/claude-1000/-home-zds-Work/d5488a6d-5a16-4401-a04c-ed440410ba3d/scratchpad/faces.json","w").write(
    json.dumps({"A": A, "B": B, "C": C}))
