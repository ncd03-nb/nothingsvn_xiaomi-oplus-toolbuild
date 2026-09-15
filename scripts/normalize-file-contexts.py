#!/usr/bin/env python3
"""Make Android file_contexts acceptable to strict EROFS tooling.

SELinux paths are byte-oriented regular expressions.  Some OPlus partitions
contain UTF-8 filenames, while mkfs.erofs rejects any non-ASCII byte in its
file-contexts input.  Escaping those UTF-8 bytes as ``\\xNN`` keeps the regex
semantics and produces a completely ASCII configuration file.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def escape_non_ascii(data: bytes) -> tuple[bytes, int]:
    output = bytearray()
    replaced = 0
    for value in data:
        if value < 0x80:
            output.append(value)
        else:
            output.extend(f"\\x{value:02x}".encode("ascii"))
            replaced += 1
    return bytes(output), replaced


def normalize(path: Path) -> int:
    original = path.read_bytes()
    normalized, replaced = escape_non_ascii(original)
    if replaced:
        path.write_bytes(normalized)
    return replaced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    replaced = normalize(args.file)
    print(replaced)


if __name__ == "__main__":
    main()
