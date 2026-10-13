#!/usr/bin/env python3
"""Pack PNG files into a Windows .ico (PNG-compressed entries, Vista+).

    rsvg-convert -w 256 -h 256 icon.svg -o 256.png   # and 48, 32, 16 ...
    tools/make-ico.py out.ico 256.png 48.png 32.png 16.png

Standard library only, so the build needs no imaging package.
"""
import struct
import sys


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("not a PNG")
    return struct.unpack(">II", data[16:24])


def main():
    out, pngs = sys.argv[1], [open(p, "rb").read() for p in sys.argv[2:]]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = len(header) + 16 * len(pngs)
    entries, blobs = b"", b""
    for data in pngs:
        w, h = png_size(data)
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32,
                               len(data), offset + len(blobs))
        blobs += data
    with open(out, "wb") as fh:
        fh.write(header + entries + blobs)
    print(f"wrote {out} ({len(pngs)} sizes)")


if __name__ == "__main__":
    main()
