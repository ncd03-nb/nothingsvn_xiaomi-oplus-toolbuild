#!/usr/bin/env python3
"""Report whether a ramdisk cpio archive carries an /avb directory.

The GSI avbpubkeys that the fstab chains to live in /avb, so a ramdisk holding
that directory belongs to a device whose vbmeta partitions have to be patched.

Reads the archive without extracting anything and without any third party
module, so it also works on the plain ramdisk.cpio magiskboot writes out.
Prints the matching paths and exits 0 when found, exits 1 when not.
"""

import gzip
import os
import sys

CPIO_MAGIC = b"070701"
S_IFMT = 0o170000
S_IFDIR = 0o040000


def entries(data):
    """Yield (mode, name) for every record, across concatenated archives."""
    offset = 0
    while offset + 110 <= len(data):
        if data[offset : offset + 6] != CPIO_MAGIC:
            break
        header = data[offset : offset + 110]
        try:
            mode = int(header[14:22], 16)
            filesize = int(header[54:62], 16)
            namesize = int(header[94:102], 16)
        except ValueError:
            break

        offset += 110
        name = data[offset : offset + namesize - 1].decode("utf-8", "replace")
        offset += namesize
        offset += (4 - ((110 + namesize) % 4)) % 4
        offset += filesize + (4 - (filesize % 4)) % 4

        if name == "TRAILER!!!":
            # A ramdisk can be several archives glued together.
            nxt = data.find(CPIO_MAGIC, offset)
            if nxt < 0:
                break
            offset = nxt
            continue

        yield mode, name.lstrip("./")


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python3 {os.path.basename(__file__)} <ramdisk.cpio>")

    with open(sys.argv[1], "rb") as f:
        data = f.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)

    found = []
    for mode, name in entries(data):
        if (mode & S_IFMT) == S_IFDIR and os.path.basename(name) == "avb":
            found.append(name)
        elif name.startswith("avb/") or "/avb/" in name:
            # the directory record itself is sometimes missing
            found.append(os.path.dirname(name))

    if not found:
        return 1
    for name in sorted(set(found)):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
