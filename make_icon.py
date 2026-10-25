#!/usr/bin/env python3
"""Generate icon-512.png — brand §6: eclipse motif on navy
(#0d1b2a), one per-product glyph. Trunk's glyph is the governed
junction: three carrier lines converge into one sealed node —
many rails in, one governed trunk out. PIL only; deterministic."""
from PIL import Image, ImageDraw

S = 512
NAVY = (13, 27, 42, 255)
STOPS = [(15, 246, 247), (0, 212, 255), (123, 44, 191)]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def grad(t):
    return lerp(STOPS[0], STOPS[1], t * 2) if t < 0.5 else \
        lerp(STOPS[1], STOPS[2], (t - 0.5) * 2)


def main():
    img = Image.new("RGBA", (S, S), NAVY)
    d = ImageDraw.Draw(img)
    ring = [54, 54, 458, 458]
    for i in range(72):
        t = i / 72
        d.arc(ring, start=i * 5, end=i * 5 + 6, fill=grad(t), width=13)
    d.ellipse([126, 126, 386, 386], fill=NAVY)
    # Three carrier lines in from the left.
    node = (292, 256)
    for i, y in enumerate((176, 256, 336)):
        d.line([(168, y), node], fill=grad(0.15 + 0.25 * i), width=11)
        d.ellipse([156, y - 9, 174, y + 9], fill=grad(0.15 + 0.25 * i))
    # The governed junction node.
    d.ellipse([272, 236, 312, 276], fill=grad(0.7))
    d.ellipse([284, 248, 300, 264], fill=NAVY)
    # One trunk line out.
    d.line([(312, 256), (356, 256)], fill=grad(0.85), width=11)
    d.ellipse([344, 247, 362, 265], outline=grad(0.85), width=6)
    img.save("icon-512.png")
    print("wrote icon-512.png", img.size, img.mode)


if __name__ == "__main__":
    main()
