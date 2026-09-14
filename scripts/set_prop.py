#!/usr/bin/env python3
"""Set one Android property without sed escaping hazards or duplicate keys."""

from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: set_prop.py FILE KEY VALUE", file=sys.stderr)
        return 2
    path, key, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not replaced:
                output.append(f"{key}={value}")
                replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8", errors="surrogateescape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
