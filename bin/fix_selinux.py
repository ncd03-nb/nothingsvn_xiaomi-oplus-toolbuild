#!/usr/bin/env python3
import os
import re
import sys

MAP_RULE_A = {
    r"^(/.*)?/lost\+found": "u:object_r:rootfs:s0",
    r"^/odm(/.*)?": "u:object_r:vendor_file:s0",
    r"^/vendor(/.*)?": "u:object_r:vendor_file:s0",
    r"^/product(/.*)?": "u:object_r:system_file:s0",
    r"^/system_ext/xbin/xeutoolbox": "u:object_r:xeutoolbox_exec:s0",
    r"^/system_ext(/.*)?": "u:object_r:system_file:s0",
    r"^/mi_ext(/.*)?": "u:object_r:system_file:s0",
    r"^/system(/.*)?": "u:object_r:system_file:s0",
    r"^/oem(/.*)?": "u:object_r:oemfs:s0",
    r"^/system_dlkm(/.*)?": "u:object_r:system_dlkm_file:s0",
    r"^/vendor_dlkm(/.*)?": "u:object_r:vendor_dlkm_file:s0",
    r"^/odm_dlkm(/.*)?": "u:object_r:odm_dlkm_file:s0",
}

MAP_RULE_B = {
    "vendor": "u:object_r:vendor_file:s0",
    "odm": "u:object_r:vendor_file:s0",
    "oem": "u:object_r:oemfs:s0",
    "system_dlkm": "u:object_r:system_dlkm_file:s0",
    "vendor_dlkm": "u:object_r:vendor_dlkm_file:s0",
    "odm_dlkm": "u:object_r:odm_dlkm_file:s0",
}


def check_lnk(p):
    if os.name == "nt" and not os.path.isdir(p):
        try:
            with open(p, "rb") as f:
                if f.read(10) == b"!<symlink>":
                    return f.read().decode("utf-16")[:-1]
        except Exception:
            pass
    elif os.name == "posix" and os.path.islink(p):
        return os.readlink(p)
    return ""


def match_hw(p):
    if "/bin/hw/" in p:
        m_hidl = re.search(r"\.hardware\.([^@]+)@", p)
        if m_hidl:
            return f"u:object_r:hal_{m_hidl.group(1).replace('.', '_')}_default_exec:s0"
        m_aidl = re.search(r"\.hardware\.([^-]+)-service", p)
        if m_aidl:
            return f"u:object_r:hal_{m_aidl.group(1).replace('.', '_')}_default_exec:s0"
    return ""


def load_db(f_fs, f_ctx):
    d_fs, d_ctx = {}, {}
    if os.path.exists(f_fs):
        with open(f_fs, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        d_fs[parts[0]] = parts[1:]
    if os.path.exists(f_ctx):
        with open(f_ctx, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        d_ctx[parts[0].replace(r"\@", "@")] = parts[1]
    return d_fs, d_ctx


def main(d_path, f_fs, f_ctx):
    p_name = os.path.basename(os.path.normpath(d_path))
    fallback = MAP_RULE_B.get(p_name, "u:object_r:system_file:s0")
    db_fs, db_ctx = load_db(f_fs, f_ctx)

    out_fs, out_ctx = {}, {}
    c_fs, c_ctx = 0, 0

    print(f"[INFO] - Processing: {p_name}")

    essential = [
        ("/", True),
        ("/lost+found", True),
        (f"/{p_name}", True),
        (f"/{p_name}/", True),
        (f"/{p_name}/lost+found", True),
    ]

    def scan():
        yield from essential
        for root, dirs, files in os.walk(d_path, topdown=True):
            for d in dirs:
                yield os.path.join(root, d), False
            for f in files:
                yield os.path.join(root, f), False

    for path, is_virt in scan():
        if is_virt:
            a_path = path
            fs_path = path.lstrip("/") if path != "/" else "/"
            is_dir = True
            l_path = ""
        else:
            l_path = path
            r_path = os.path.relpath(l_path, d_path)
            a_path = f"/{p_name}/{r_path}".replace("\\", "/")
            fs_path = a_path.lstrip("/")
            is_dir = os.path.isdir(l_path)

        if fs_path in db_fs:
            out_fs[fs_path] = db_fs[fs_path]
        else:
            is_bin = "bin" in fs_path.split("/") or "xbin" in fs_path.split("/")
            gid = "2000" if is_bin else "0"
            lnk = ""
            if is_dir:
                mode = "0700" if "lost+found" in fs_path else "0755"
                cfg = ["0", gid, mode]
            else:
                lnk = check_lnk(l_path)
                mode = "0755" if is_bin else ("0750" if fs_path.endswith(".sh") else "0644")
                cfg = ["0", gid, mode, lnk] if lnk else ["0", gid, mode]
            out_fs[fs_path] = cfg
            c_fs += 1
            log_lnk = f" | Target: {lnk}" if lnk else ""
            print(f"[FS] - Added: {fs_path} | UID: 0 | GID: {gid} | Mode: {mode}{log_lnk}")

        ctx_path = a_path if is_virt and a_path.endswith("(/.*)?") else re.escape(a_path).replace("\\-", "-")
        if ctx_path in db_ctx:
            out_ctx[ctx_path] = db_ctx[ctx_path]
        else:
            assigned = next((ctx for pat, ctx in MAP_RULE_A.items() if re.search(pat, a_path)), None)
            if not assigned:
                assigned = match_hw(a_path)
                if assigned:
                    print(f"[HAL] - Auto: {a_path} -> Context: {assigned}")
            if not assigned:
                assigned = fallback
            out_ctx[ctx_path] = assigned
            c_ctx += 1
            print(f"[SELINUX] - Added: {ctx_path} -> Context: {assigned}")

    catch_all = f"/{p_name}(/.*)?"
    if catch_all not in out_ctx:
        out_ctx[catch_all] = fallback
        c_ctx += 1
        print(f"[SELINUX] - Added: {catch_all} -> Context: {fallback}")

    with open(f_fs, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(f"{k} {' '.join(v)}\n" for k, v in sorted(out_fs.items()))

    with open(f_ctx, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(f"{k} {v}\n" for k, v in sorted(out_ctx.items()))

    print(f"\n[INFO] - Success: {c_fs} FS entries and {c_ctx} Context entries for '{p_name}'.")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
