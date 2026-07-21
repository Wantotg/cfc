#!/usr/bin/env python3
"""Bake an image into a splash asset. Dev-time only — needs Pillow.

    pip install pillow
    python dev/bake_splash.py <image> <name> [--size WxH] [--colors N]
    python dev/bake_splash.py ~/pics/mittens.png mittens

Writes assets/splash_<name>.raw, which splash.py loads at runtime with nothing
but stdlib. That is the whole point of the format: decoding a PNG means Pillow,
and a launch screen is not worth a runtime image dependency.

Format:
    bytes 0-1  width  (uint16 LE)
    bytes 2-3  height (uint16 LE)
    bytes 4..  width*height*3 raw RGB, row-major

On size: this is NOT the size it displays at. splash.py box-averages the asset
down to whatever the terminal gives it, so the bake is a source of truth, not a
target. The default 96x144 is about 2x a 140x40 terminal, which leaves headroom
for a bigger window without making the file large. Keep the source's aspect
ratio — splash.py preserves it, so a distorted bake stays distorted.

--colors quantizes the palette, which is what makes it read as pixel art rather
than a small photo. Fewer colours, blockier look.
"""
import argparse
import os
import struct
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("needs Pillow: pip install pillow  (dev-time only, not at runtime)")

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def parse_size(text):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WxH, got {text!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="source image (any format Pillow reads)")
    ap.add_argument("name", help="asset name → assets/splash_<name>.raw")
    ap.add_argument("--size", type=parse_size, default=(96, 144),
                    help="bake resolution WxH (default 96x144)")
    ap.add_argument("--colors", type=int, default=40,
                    help="palette size (default 40)")
    ap.add_argument("--preview", action="store_true",
                    help="also write <name>_preview.png at 8x, to eyeball it")
    args = ap.parse_args()

    w, h = args.size
    im = Image.open(args.image).convert("RGBA")

    src_aspect = im.height / im.width
    if abs(src_aspect - h / w) > 0.02:
        print(f"warning: source is {im.width}x{im.height} (aspect {src_aspect:.3f}) "
              f"but --size asks for {h / w:.3f}; the bake will be squashed.",
              file=sys.stderr)

    # Composite onto black rather than dropping alpha: splash.py paints the
    # whole screen black and centres the art, so a transparent background must
    # bake to the same black or the art sits in a visible rectangle.
    flat = Image.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, 255)), im).convert("RGB")
    small = flat.resize((w, h), Image.LANCZOS)
    quantized = small.quantize(colors=args.colors, method=Image.MEDIANCUT).convert("RGB")

    os.makedirs(ASSETS, exist_ok=True)
    out = os.path.join(ASSETS, f"splash_{args.name}.raw")
    pixels = quantized.tobytes()
    with open(out, "wb") as fh:
        fh.write(struct.pack("<HH", w, h))
        fh.write(pixels)
    print(f"wrote {out}: {w}x{h}, {4 + len(pixels)} bytes")

    if args.preview:
        path = os.path.join(ASSETS, f"{args.name}_preview.png")
        quantized.resize((w * 8, h * 8), Image.NEAREST).save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
