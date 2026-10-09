#!/usr/bin/env python3
"""Generate an application icon: a stylised RGB fan/hub glyph.

Kept as a script so the icon can be regenerated rather than hand-edited, and so
the repo carries no binary blob it cannot explain.
"""

import pathlib
import sys

# Radial fan blades over a ring, in the MSI Mystic Light spirit: a dark hub,
# a lit ring, and blades catching the light.
SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128"
     height="128">
  <defs>
    <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%"   stop-color="#ff3b30"/>
      <stop offset="33%"  stop-color="#ffcc00"/>
      <stop offset="66%"  stop-color="#00c7be"/>
      <stop offset="100%" stop-color="#7b5cff"/>
    </linearGradient>
    <radialGradient id="hub" cx="40%" cy="35%" r="70%">
      <stop offset="0%"   stop-color="#3a3f4b"/>
      <stop offset="100%" stop-color="#14161c"/>
    </radialGradient>
  </defs>

  <rect x="4" y="4" width="120" height="120" rx="26" fill="#14161c"/>
  <rect x="4" y="4" width="120" height="120" rx="26" fill="none"
        stroke="url(#ring)" stroke-width="4"/>

  <!-- blades -->
  <g fill="url(#ring)" opacity="0.92">
    <path d="M64 18c11 0 20 9 20 20 0 8-5 15-12 18l-8-38z"/>
    <path d="M110 64c0 11-9 20-20 20-8 0-15-5-18-12l38-8z"/>
    <path d="M64 110c-11 0-20-9-20-20 0-8 5-15 12-18l8 38z"/>
    <path d="M18 64c0-11 9-20 20-20 8 0 15 5 18 12l-38 8z"/>
  </g>

  <!-- hub -->
  <circle cx="64" cy="64" r="17" fill="url(#hub)"
          stroke="url(#ring)" stroke-width="3"/>
  <circle cx="64" cy="64" r="5" fill="#ffcc00"/>
</svg>
"""


def main():
    if len(sys.argv) > 1:
        out = pathlib.Path(sys.argv[1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(SVG)
        print(f"wrote {out}")
    else:
        sys.stdout.write(SVG)


if __name__ == "__main__":
    main()