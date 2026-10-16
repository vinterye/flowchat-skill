#!/usr/bin/env python3
"""Build the full atlas page: capability map SVG on top of the enum-spectrum.

The enum-spectrum page (Chinese filename on the local server) is merged with
the freshly-generated capability-map SVG so the README and the detailed enum
page tell the same story.

Regenerate with:
    python3 tools/build_enum_atlas.py \
        --enum /path/to/flowchat-%E6%9E%9A%E4%B8%BE%E5%85%A8%E8%B0%B1.html \
        --svg docs/capability-map.svg \
        --output docs/enum-spectrum.html
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge capability map SVG with enum spectrum HTML")
    parser.add_argument("--enum", type=Path, required=True)
    parser.add_argument("--svg", type=Path, default=Path("docs/capability-map.svg"))
    parser.add_argument("--output", type=Path, default=Path("docs/enum-spectrum.html"))
    args = parser.parse_args()

    src = args.enum.read_text(encoding="utf-8")
    svg = args.svg.read_text(encoding="utf-8")

    # Extract the inner <svg ...>...</svg> from the standalone SVG file.
    start = svg.find("<svg")
    end = svg.rfind("</svg>") + len("</svg>")
    inner = svg[start:end]

    # Insert right after the first </div>\n<div class="sec">, which is the
    # boundary between the badgebar and the first section in the enum page.
    marker = "</div>\n<div class=\"sec\">"
    idx = src.find(marker)
    if idx == -1:
        print("ERROR: cannot find badgebar/section boundary in enum HTML", file=__import__("sys").stderr)
        return 1

    after_div = idx + len("</div>\n")
    insert = (
        '\n<div class="capability-map-wrap" style="margin:24px 0 28px;padding:0 2px;">'
        f'{inner}'
        '</div>\n'
    )
    out = src[:after_div] + insert + src[after_div:]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(out, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
