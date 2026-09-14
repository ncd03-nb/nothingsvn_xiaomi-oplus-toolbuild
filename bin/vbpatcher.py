#!/usr/bin/env python3
"""Unpack / repack Android vendor_boot images (boot header v3 and v4).

Header v4 images carry several *independent* ramdisk fragments (typically
"default" plus a "dlkm" fragment holding the vendor kernel modules) that are
concatenated into one section and described by the vendor ramdisk table.
Treating that section as a single compressed stream loses every fragment past
the first one and leaves the table pointing at offsets that no longer exist,
which boot loops the device. Each fragment is therefore unpacked, repacked and
re-described individually here.
"""

import argparse
import json
import os
import struct
import sys

try:
    import lz4.block
    import lz4.frame
except ImportError:
    sys.exit("Error: 'lz4' module not found. Install it using: pip install lz4")

try:
    import zstandard as zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

MAGIC = b"VNDRBOOT"
V3_FMT = "<8s I I I I I 2048s I 16s I I Q"
V4_EXT_FMT = "<I I I I"
V3_HEADER_SIZE = struct.calcsize(V3_FMT)  # 2112
V4_HEADER_SIZE = V3_HEADER_SIZE + struct.calcsize(V4_EXT_FMT)  # 2128

# struct vendor_ramdisk_table_entry_v4
TABLE_ENTRY_FMT = "<I I I 32s 64s"
TABLE_ENTRY_SIZE = struct.calcsize(TABLE_ENTRY_FMT)  # 108

AVB_FOOTER_FMT = ">4sIIQQQ"
AVB_FOOTER_SIZE = 64

CMDLINE_MAX = 2047  # 2048 bytes minus the NUL terminator

LZ4_FRAME_MAGIC = b"\x04\x22\x4d\x18"
LZ4_LEGACY_MAGIC = b"\x02\x21\x4c\x18"
LZ4_LEGACY_BLOCK = 8 * 1024 * 1024
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
GZIP_MAGIC = b"\x1f\x8b"

CPIO_MAGIC = b"070701"
S_IFMT = 0o170000
S_IFDIR = 0o040000
S_IFREG = 0o100000
S_IFLNK = 0o120000


def die(message):
    sys.exit(f"Error: {message}")


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def pad_to(data, boundary):
    return data + b"\x00" * ((boundary - (len(data) % boundary)) % boundary)


# --------------------------------------------------------------------------
# ramdisk compression
# --------------------------------------------------------------------------


def _decompress_lz4_frame(data):
    """Decode every concatenated LZ4 frame, not just the first one."""
    out = bytearray()
    pos = 0
    while pos + 4 <= len(data) and data[pos : pos + 4] == LZ4_FRAME_MAGIC:
        decompressor = lz4.frame.LZ4FrameDecompressor()
        out += decompressor.decompress(data[pos:])
        consumed = len(data) - pos - len(decompressor.unused_data)
        if consumed <= 0:
            break
        pos += consumed
    return bytes(out)


def _decompress_lz4_legacy(data):
    out = bytearray()
    pos = 0
    while pos + 4 <= len(data):
        if data[pos : pos + 4] == LZ4_LEGACY_MAGIC:
            pos += 4
            continue
        (block_size,) = struct.unpack("<I", data[pos : pos + 4])
        if block_size == 0 or block_size > LZ4_LEGACY_BLOCK:
            break
        pos += 4
        chunk = data[pos : pos + block_size]
        if len(chunk) < block_size:
            break
        out += lz4.block.decompress(chunk, uncompressed_size=LZ4_LEGACY_BLOCK)
        pos += block_size
    return bytes(out)


def _decompress_zstd(data):
    out = bytearray()
    chunk = data
    while chunk[:4] == ZSTD_MAGIC:
        decompressor = zstd.ZstdDecompressor().decompressobj()
        out += decompressor.decompress(chunk)
        chunk = decompressor.unused_data
    return bytes(out)


def decompress_ramdisk(data):
    magic = data[:4]
    if magic == LZ4_FRAME_MAGIC:
        return "lz4_frame", _decompress_lz4_frame(data)
    if magic == LZ4_LEGACY_MAGIC:
        return "lz4_legacy", _decompress_lz4_legacy(data)
    if magic == ZSTD_MAGIC:
        if not HAS_ZSTD:
            raise RuntimeError("Zstandard module missing. Run: pip install zstandard")
        return "zstd", _decompress_zstd(data)
    if magic[:2] == GZIP_MAGIC:
        import gzip

        return "gzip", gzip.decompress(data)
    if magic[:4] == CPIO_MAGIC[:4]:
        return "none", data
    raise RuntimeError(f"unsupported ramdisk format (magic {magic.hex()})")


def compress_ramdisk(data, fmt):
    """Recompress as tightly as the format allows.

    The image has to fit back into a fixed size partition, so always use the
    strongest setting rather than the library default.
    """
    if fmt == "lz4_frame":
        return lz4.frame.compress(
            data,
            compression_level=getattr(lz4.frame, "COMPRESSIONLEVEL_MAX", 12),
            block_size=lz4.frame.BLOCKSIZE_MAX4MB,
        )
    if fmt == "lz4_legacy":
        out = bytearray(LZ4_LEGACY_MAGIC)
        for i in range(0, len(data), LZ4_LEGACY_BLOCK):
            chunk = data[i : i + LZ4_LEGACY_BLOCK]
            packed = lz4.block.compress(
                chunk, mode="high_compression", compression=12, store_size=False
            )
            out += struct.pack("<I", len(packed))
            out += packed
        return bytes(out)
    if fmt == "zstd":
        if not HAS_ZSTD:
            raise RuntimeError("Zstandard module missing. Run: pip install zstandard")
        return zstd.ZstdCompressor(level=19).compress(data)
    if fmt == "gzip":
        import gzip

        return gzip.compress(data, 9)
    return data


# --------------------------------------------------------------------------
# cpio (newc)
# --------------------------------------------------------------------------


def build_cpio_header(entry, filesize, namesize):
    fields = (
        entry["ino"],
        entry["mode"],
        entry["uid"],
        entry["gid"],
        entry["nlink"],
        entry["mtime"],
        filesize,
        entry["devmajor"],
        entry["devminor"],
        entry["rdevmajor"],
        entry["rdevminor"],
        namesize,
        0,  # check, unused by newc
    )
    return (CPIO_MAGIC + b"".join(b"%08x" % (v & 0xFFFFFFFF) for v in fields))


def unpack_cpio(data, out_dir):
    """Extract a newc archive, returning the metadata needed to rebuild it."""
    os.makedirs(out_dir, exist_ok=True)
    entries = []
    offset = 0
    while offset + 110 <= len(data):
        if data[offset : offset + 6] != CPIO_MAGIC:
            break
        header = data[offset : offset + 110]
        try:
            values = [
                int(header[6 + i * 8 : 14 + i * 8].decode("ascii"), 16) for i in range(13)
            ]
        except ValueError:
            break
        (ino, mode, uid, gid, nlink, mtime, filesize, devmajor, devminor,
         rdevmajor, rdevminor, namesize, _check) = values

        offset += 110
        name = data[offset : offset + namesize - 1].decode("utf-8", "surrogateescape")
        offset += namesize
        offset += (4 - ((110 + namesize) % 4)) % 4
        file_data = data[offset : offset + filesize]
        offset += filesize
        offset += (4 - (filesize % 4)) % 4

        if name == "TRAILER!!!":
            break

        entries.append(
            {
                "name": name,
                "ino": ino,
                "mode": mode,
                "uid": uid,
                "gid": gid,
                "nlink": nlink,
                "mtime": mtime,
                "devmajor": devmajor,
                "devminor": devminor,
                "rdevmajor": rdevmajor,
                "rdevminor": rdevminor,
                "has_data": filesize > 0,
                "_data": file_data,
            }
        )

    trailing = data[offset:]

    # A hard linked file only carries its payload in the last archive entry;
    # remember where that payload lives so the earlier entries stay empty.
    # Only nlink > 1 marks a hard link - archives built reproducibly set every
    # inode number to 0, which would otherwise look like one huge link group.
    data_owner = {}
    for entry in entries:
        if (
            (entry["mode"] & S_IFMT) == S_IFREG
            and entry["has_data"]
            and entry["nlink"] > 1
        ):
            data_owner.setdefault(entry["ino"], entry["name"])

    for entry in entries:
        if (entry["mode"] & S_IFMT) == S_IFDIR:
            os.makedirs(os.path.join(out_dir, entry["name"]), exist_ok=True)

    for entry in entries:
        mode_type = entry["mode"] & S_IFMT
        path = os.path.join(out_dir, entry["name"])
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if mode_type == S_IFLNK:
            entry["symlink_target"] = entry["_data"].decode("utf-8", "surrogateescape")
        elif mode_type == S_IFREG and entry["has_data"]:
            with open(path, "wb") as out:
                out.write(entry["_data"])

    for entry in entries:
        mode_type = entry["mode"] & S_IFMT
        if mode_type != S_IFREG or entry["has_data"]:
            continue
        path = os.path.join(out_dir, entry["name"])
        owner = data_owner.get(entry["ino"]) if entry["nlink"] > 1 else None
        if owner and owner != entry["name"]:
            entry["hardlink_to"] = owner
            try:
                if os.path.lexists(path):
                    os.remove(path)
                os.link(os.path.join(out_dir, owner), path)
                continue
            except OSError:
                pass
        with open(path, "wb") as out:
            out.write(b"")

    for entry in entries:
        entry.pop("_data", None)

    return entries, trailing


def pack_cpio(in_dir, entries):
    """Rebuild a newc archive from the extracted tree and its metadata."""
    known = set(entry["name"] for entry in entries)
    extra = []
    for root, dirs, files in os.walk(in_dir):
        for name in sorted(dirs) + sorted(files):
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, in_dir).replace(os.sep, "/")
            if rel_path in known:
                continue
            is_dir = os.path.isdir(full_path) and not os.path.islink(full_path)
            extra.append(
                {
                    "name": rel_path,
                    "ino": None,  # filled in with a fresh number below
                    "mode": 0o040755 if is_dir else 0o100644,
                    "uid": 0,
                    "gid": 0,
                    "nlink": 2 if is_dir else 1,
                    "mtime": 0,
                    "devmajor": 0,
                    "devminor": 0,
                    "rdevmajor": 0,
                    "rdevminor": 0,
                    "has_data": not is_dir,
                }
            )
            known.add(rel_path)

    out = bytearray()
    next_ino = max((e["ino"] or 0) for e in entries) + 1 if entries else 1
    for entry in entries + extra:
        mode_type = entry["mode"] & S_IFMT
        path = os.path.join(in_dir, entry["name"])

        if mode_type == S_IFLNK:
            file_data = entry.get("symlink_target", "").encode("utf-8", "surrogateescape")
        elif mode_type == S_IFREG and entry.get("has_data", False):
            if not os.path.isfile(path):
                continue  # removed from the tree on purpose
            with open(path, "rb") as f:
                file_data = f.read()
        else:
            # Directories, hard link entries, device nodes and fifos carry no
            # payload in the archive.
            file_data = b""

        record = dict(entry)
        if record["ino"] is None:
            record["ino"] = next_ino
            next_ino += 1
        name_bytes = entry["name"].encode("utf-8", "surrogateescape") + b"\x00"

        out += build_cpio_header(record, len(file_data), len(name_bytes))
        out += name_bytes
        out += b"\x00" * ((4 - ((110 + len(name_bytes)) % 4)) % 4)
        out += file_data
        out += b"\x00" * ((4 - (len(file_data) % 4)) % 4)

    trailer = {
        "ino": 0, "mode": 0, "uid": 0, "gid": 0, "nlink": 1, "mtime": 0,
        "devmajor": 0, "devminor": 0, "rdevmajor": 0, "rdevminor": 0,
    }
    name_bytes = b"TRAILER!!!\x00"
    out += build_cpio_header(trailer, 0, len(name_bytes))
    out += name_bytes
    out += b"\x00" * ((4 - ((110 + len(name_bytes)) % 4)) % 4)
    return bytes(out)


# --------------------------------------------------------------------------
# vendor ramdisk table
# --------------------------------------------------------------------------


def parse_table(data, entry_num, entry_size):
    entries = []
    for i in range(entry_num):
        raw = data[i * entry_size : (i + 1) * entry_size]
        if len(raw) < TABLE_ENTRY_SIZE:
            die("vendor ramdisk table is truncated")
        size, offset, rtype, name, board_id = struct.unpack(
            TABLE_ENTRY_FMT, raw[:TABLE_ENTRY_SIZE]
        )
        entries.append(
            {
                "ramdisk_size": size,
                "ramdisk_offset": offset,
                "ramdisk_type": rtype,
                "ramdisk_name": name.split(b"\x00")[0].decode("utf-8", "ignore"),
                "board_id": board_id.hex(),
                "entry_padding": raw[TABLE_ENTRY_SIZE:].hex(),
            }
        )
    return entries


def build_table(fragments, entry_size):
    out = bytearray()
    for fragment in fragments:
        raw = struct.pack(
            TABLE_ENTRY_FMT,
            fragment["ramdisk_size"],
            fragment["ramdisk_offset"],
            fragment["ramdisk_type"],
            fragment["ramdisk_name"].encode("utf-8")[:31].ljust(32, b"\x00"),
            bytes.fromhex(fragment["board_id"])[:64].ljust(64, b"\x00"),
        )
        raw += bytes.fromhex(fragment.get("entry_padding", ""))
        out += raw.ljust(entry_size, b"\x00")[:entry_size]
    return bytes(out)


# --------------------------------------------------------------------------
# unpack
# --------------------------------------------------------------------------


def unpack(args):
    with open(args.image, "rb") as f:
        blob = f.read()

    if blob[:8] != MAGIC:
        die(f"{args.image} is not a vendor_boot image (bad magic)")
    if len(blob) < V3_HEADER_SIZE:
        die(f"{args.image} is truncated")

    out_dir = args.output
    ramdisk_dir = os.path.join(out_dir, "ramdisk")
    os.makedirs(ramdisk_dir, exist_ok=True)

    fields = struct.unpack(V3_FMT, blob[:V3_HEADER_SIZE])
    hdr_version, page_size = fields[1], fields[2]
    if page_size == 0 or page_size & (page_size - 1):
        die(f"invalid page size {page_size}")
    if hdr_version not in (3, 4):
        die(f"unsupported vendor_boot header version {hdr_version}")

    config = {
        "original_image_size": len(blob),
        "header_version": hdr_version,
        "page_size": page_size,
        "kernel_load_addr": fields[3],
        "ramdisk_load_addr": fields[4],
        "cmdline": fields[6].split(b"\x00")[0].decode("utf-8", errors="ignore"),
        "tags_load_addr": fields[7],
        "name": fields[8].split(b"\x00")[0].decode("utf-8", errors="ignore"),
        "dtb_load_addr": fields[11],
    }
    vendor_ramdisk_size, dtb_size = fields[5], fields[10]

    header_size = V3_HEADER_SIZE
    table_size = table_entry_num = table_entry_size = bootconfig_size = 0
    if hdr_version == 4:
        header_size = V4_HEADER_SIZE
        table_size, table_entry_num, table_entry_size, bootconfig_size = struct.unpack(
            V4_EXT_FMT, blob[V3_HEADER_SIZE:V4_HEADER_SIZE]
        )
        config["vendor_ramdisk_table_entry_size"] = table_entry_size

    print(f"> Unpacking vendor_boot v{hdr_version} ({len(blob)} bytes)")

    offset = align(header_size, page_size)
    ramdisk_blob = blob[offset : offset + vendor_ramdisk_size]
    if len(ramdisk_blob) < vendor_ramdisk_size:
        die("vendor ramdisk section is truncated")
    offset += align(vendor_ramdisk_size, page_size)

    dtb_blob = blob[offset : offset + dtb_size]
    offset += align(dtb_size, page_size)

    table_blob = b""
    bootconfig_blob = b""
    if hdr_version == 4:
        table_blob = blob[offset : offset + table_size]
        offset += align(table_size, page_size)
        bootconfig_blob = blob[offset : offset + bootconfig_size]

    with open(os.path.join(out_dir, "dtb.img"), "wb") as out:
        out.write(dtb_blob)
    if hdr_version == 4:
        with open(os.path.join(out_dir, "bootconfig.img"), "wb") as out:
            out.write(bootconfig_blob)

    footer = blob[-AVB_FOOTER_SIZE:] if len(blob) >= AVB_FOOTER_SIZE else b""
    if footer.startswith(b"AVBf"):
        print("> Detected AVB footer, saving it for the repack")
        _, _, _, _, vbmeta_offset, vbmeta_size = struct.unpack(
            AVB_FOOTER_FMT, footer[:36]
        )
        with open(os.path.join(out_dir, "avb_vbmeta.img"), "wb") as out:
            out.write(blob[vbmeta_offset : vbmeta_offset + vbmeta_size])
        with open(os.path.join(out_dir, "avb_footer.bin"), "wb") as out:
            out.write(footer)
        config["has_avb"] = True
    else:
        config["has_avb"] = False

    # Split the ramdisk section into its fragments before touching it.
    if hdr_version == 4 and table_entry_num > 0:
        if table_entry_size < TABLE_ENTRY_SIZE:
            die(f"invalid vendor ramdisk table entry size {table_entry_size}")
        fragments = parse_table(table_blob, table_entry_num, table_entry_size)
    else:
        fragments = [
            {
                "ramdisk_size": vendor_ramdisk_size,
                "ramdisk_offset": 0,
                "ramdisk_type": 0,
                "ramdisk_name": "",
                "board_id": "00" * 64,
                "entry_padding": "",
            }
        ]

    print(f"> Vendor ramdisk fragments: {len(fragments)}")
    for index, fragment in enumerate(fragments):
        start = fragment["ramdisk_offset"]
        end = start + fragment["ramdisk_size"]
        if end > len(ramdisk_blob):
            die(
                f"ramdisk fragment {index} runs past the vendor ramdisk section "
                f"({end} > {len(ramdisk_blob)})"
            )
        piece = ramdisk_blob[start:end]

        label = f"{index:02d}"
        if fragment["ramdisk_name"]:
            label += "_" + fragment["ramdisk_name"]
        fragment["dir"] = label

        try:
            fmt, plain = decompress_ramdisk(piece)
        except Exception as exc:  # noqa: BLE001 - keep the raw fragment instead
            print(f"> Fragment {label}: keeping raw ({exc})")
            fragment["compression"] = "raw"
            with open(os.path.join(ramdisk_dir, label + ".raw"), "wb") as out:
                out.write(piece)
            continue

        entries, trailing = unpack_cpio(plain, os.path.join(ramdisk_dir, label))
        if not entries:
            print(f"> Fragment {label}: not a cpio archive, keeping raw")
            fragment["compression"] = "raw"
            with open(os.path.join(ramdisk_dir, label + ".raw"), "wb") as out:
                out.write(piece)
            continue

        fragment["compression"] = fmt
        if trailing.strip(b"\x00"):
            with open(os.path.join(ramdisk_dir, label + ".trailing.bin"), "wb") as out:
                out.write(trailing)
            fragment["has_trailing"] = True
        with open(os.path.join(ramdisk_dir, label + ".meta.json"), "w") as out:
            json.dump(entries, out, indent=1)
        print(
            f"> Fragment {label}: {fmt}, {len(entries)} entries, "
            f"{fragment['ramdisk_size']} -> {len(plain)} bytes"
        )

    config["ramdisk_fragments"] = fragments

    with open(os.path.join(out_dir, "config.json"), "w") as out:
        json.dump(config, out, indent=4)

    print(f"> Ramdisk path: {ramdisk_dir}")


# --------------------------------------------------------------------------
# repack
# --------------------------------------------------------------------------


def repack(args):
    out_dir = os.path.dirname(os.path.abspath(args.config))
    ramdisk_dir = os.path.join(out_dir, "ramdisk")
    with open(args.config, "r") as f:
        config = json.load(f)

    hdr_version = config["header_version"]
    page_size = config["page_size"]
    print(f"> Repacking vendor_boot v{hdr_version}")

    fragments = config["ramdisk_fragments"]
    ramdisk_blob = bytearray()
    for fragment in fragments:
        label = fragment["dir"]
        fmt = fragment.get("compression", "lz4_legacy")
        raw_path = os.path.join(ramdisk_dir, label + ".raw")

        if fmt == "raw" or not os.path.isdir(os.path.join(ramdisk_dir, label)):
            with open(raw_path, "rb") as f:
                piece = f.read()
        else:
            with open(os.path.join(ramdisk_dir, label + ".meta.json"), "r") as f:
                entries = json.load(f)
            plain = pack_cpio(os.path.join(ramdisk_dir, label), entries)
            if fragment.get("has_trailing"):
                with open(os.path.join(ramdisk_dir, label + ".trailing.bin"), "rb") as f:
                    plain += f.read()
            piece = compress_ramdisk(plain, fmt)
            print(f"> Fragment {label}: {len(plain)} -> {len(piece)} bytes ({fmt})")

        fragment["ramdisk_offset"] = len(ramdisk_blob)
        fragment["ramdisk_size"] = len(piece)
        ramdisk_blob += piece

    with open(os.path.join(out_dir, "dtb.img"), "rb") as f:
        dtb_blob = f.read()

    table_blob = b""
    bootconfig_blob = b""
    if hdr_version == 4:
        entry_size = config.get("vendor_ramdisk_table_entry_size") or TABLE_ENTRY_SIZE
        # Rebuilt from the fragments just written, so the offsets and sizes in
        # the table always describe the ramdisk section that is really there.
        table_blob = build_table(fragments, entry_size)
        with open(os.path.join(out_dir, "bootconfig.img"), "rb") as f:
            bootconfig_blob = f.read()

    cmdline = config["cmdline"].encode("utf-8")
    if len(cmdline) > CMDLINE_MAX:
        die(
            f"kernel cmdline is {len(cmdline)} bytes, the header only holds "
            f"{CMDLINE_MAX}; refusing to truncate it"
        )

    header = struct.pack(
        V3_FMT,
        MAGIC,
        hdr_version,
        page_size,
        config["kernel_load_addr"],
        config["ramdisk_load_addr"],
        len(ramdisk_blob),
        cmdline.ljust(2048, b"\x00"),
        config["tags_load_addr"],
        config["name"].encode("utf-8")[:15].ljust(16, b"\x00"),
        V4_HEADER_SIZE if hdr_version == 4 else V3_HEADER_SIZE,
        len(dtb_blob),
        config["dtb_load_addr"],
    )
    if hdr_version == 4:
        header += struct.pack(
            V4_EXT_FMT,
            len(table_blob),
            len(fragments),
            entry_size,
            len(bootconfig_blob),
        )

    image = bytearray()
    image += pad_to(header, page_size)
    image += pad_to(bytes(ramdisk_blob), page_size)
    image += pad_to(dtb_blob, page_size)
    if hdr_version == 4:
        image += pad_to(table_blob, page_size)
        image += pad_to(bootconfig_blob, page_size)

    payload_size = len(image)
    target_size = config.get("original_image_size", 0)

    if config.get("has_avb", False):
        with open(os.path.join(out_dir, "avb_vbmeta.img"), "rb") as f:
            vbmeta_blob = f.read()
        with open(os.path.join(out_dir, "avb_footer.bin"), "rb") as f:
            footer = f.read()

        needed = payload_size + len(vbmeta_blob) + AVB_FOOTER_SIZE
        if needed > target_size:
            die(
                "the repacked image no longer fits the partition "
                f"({needed} > {target_size} bytes). Shrink the ramdisk contents "
                "instead of flashing an oversized vendor_boot."
            )

        footer_fields = list(struct.unpack(AVB_FOOTER_FMT, footer[:36]))
        footer_fields[3] = payload_size  # original_image_size
        footer_fields[4] = payload_size  # vbmeta_offset
        footer_fields[5] = len(vbmeta_blob)  # vbmeta_size

        image += vbmeta_blob
        image += b"\x00" * (target_size - AVB_FOOTER_SIZE - len(image))
        image += struct.pack(AVB_FOOTER_FMT, *footer_fields) + footer[36:]
        print("> AVB footer re-attached")
    elif target_size > payload_size:
        image += b"\x00" * (target_size - payload_size)
    elif payload_size > target_size:
        print(
            f"> WARNING: image grew from {target_size} to {payload_size} bytes; "
            "make sure the partition is large enough"
        )

    # Write out of place so a failure here never leaves a half written image
    # behind for the packer to pick up.
    tmp_path = args.output + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(image)
    os.replace(tmp_path, args.output)

    print(f"> Image exported to: {args.output} ({len(image)} bytes)")


# --------------------------------------------------------------------------
# cmdline
# --------------------------------------------------------------------------


def edit_cmdline(args):
    with open(args.config, "r") as f:
        config = json.load(f)

    parts = config["cmdline"].split()
    for prefix in args.remove_prefix or []:
        parts = [p for p in parts if not p.startswith(prefix)]
    if args.prepend:
        parts = args.prepend.split() + parts

    cmdline = " ".join(parts)
    if len(cmdline.encode("utf-8")) > CMDLINE_MAX:
        die(f"cmdline would be {len(cmdline)} bytes, the limit is {CMDLINE_MAX}")

    config["cmdline"] = cmdline
    with open(args.config, "w") as f:
        json.dump(config, f, indent=4)
    print(f"> cmdline: {cmdline}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_unpack = subparsers.add_parser("unpack")
    p_unpack.add_argument("-i", "--image", required=True)
    p_unpack.add_argument("-o", "--output", required=True)

    p_repack = subparsers.add_parser("repack")
    p_repack.add_argument("-c", "--config", required=True)
    p_repack.add_argument("-o", "--output", required=True)

    p_cmdline = subparsers.add_parser("cmdline")
    p_cmdline.add_argument("-c", "--config", required=True)
    p_cmdline.add_argument("--prepend")
    p_cmdline.add_argument("--remove-prefix", action="append")

    parsed = parser.parse_args()
    if parsed.command == "unpack":
        unpack(parsed)
    elif parsed.command == "repack":
        repack(parsed)
    else:
        edit_cmdline(parsed)
