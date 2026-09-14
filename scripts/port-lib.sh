#!/usr/bin/env bash

log() { printf '[%s] %s\n' "$1" "$2"; }
die() { log ERROR "$1" >&2; exit 1; }

bool() {
    case "${1,,}" in true|1|yes|y|on) return 0 ;; *) return 1 ;; esac
}

require_file() { [[ -f "$1" ]] || die "Missing file: $1"; }
require_dir() { [[ -d "$1" ]] || die "Missing directory: $1"; }

set_prop() {
    local file="$1" key="$2" value="$3"
    mkdir -p "$(dirname "$file")"
    touch "$file"
    if grep -q -E "^${key//./\\.}=" "$file"; then
        python3 "$WORK_DIR/scripts/set_prop.py" "$file" "$key" "$value"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

first_prop() {
    local root="$1" key="$2"
    grep -Rhs -m1 --include='*.prop' --include='build.prop' "^${key}=" "$root" 2>/dev/null |
        head -n1 | cut -d= -f2- | tr -d '\r'
}

rom_filename() {
    local clean="${1%%\?*}"
    clean="${clean%%#*}"; clean="${clean%/}"
    local name
    name=$(basename "$clean")
    [[ "$name" == download ]] && name="$(basename "${clean%/download}")"
    printf '%s' "${name:-rom.zip}"
}

obtain_rom() {
    local source="$1" label="$2" destination="$3"
    mkdir -p "$(dirname "$destination")"
    if [[ -f "$source" ]]; then
        ln -f "$source" "$destination" 2>/dev/null || cp -f "$source" "$destination"
    elif [[ "$source" =~ ^https?:// ]]; then
        log DOWNLOAD "$label: $(rom_filename "$source")"
        aria2c --file-allocation=none -x10 -s10 --continue=true --max-tries=5 \
            --retry-wait=10 --allow-overwrite=true --auto-file-renaming=false \
            -o "$(basename "$destination")" -d "$(dirname "$destination")" "$source"
    else
        die "$label must be a local file or HTTP(S) URL"
    fi
    require_file "$destination"
}

extract_payload_rom() {
    local archive="$1" destination="$2" label="$3"
    mkdir -p "$destination/images"
    7z l "$archive" | grep -q 'payload.bin' || die "$label is not a payload OTA"
    log UNPACK "Extracting $label payload.bin"
    7z x -y -mmt=on "$archive" payload.bin -o"$destination" >/dev/null
    # New payload-extract releases support JSON; the bundled legacy binary only
    # prints text. Keep one metadata file and let detect-device.py parse either.
    if ! payload-extract metadata "$destination/payload.bin" --json \
        > "$destination/payload_metadata.json" 2>/dev/null; then
        if ! payload-extract metadata "$destination/payload.bin" \
            > "$destination/payload_metadata.json"; then
            : > "$destination/payload_metadata.json"
            log WARN "Could not read payload metadata for $label"
        fi
    fi
    payload-extract extract -o "$destination/images" "$destination/payload.bin"
    rm -f "$destination/payload.bin"
}

extract_image() {
    local image="$1" destination="$2"
    [[ -f "$image" ]] || return 0
    local type
    type=$(gettype -i "$image")
    case "$type" in
        ext)
            python3 "$WORK_DIR/bin/imgextractor/imgextractor.py" "$image" "$destination" >/dev/null
            ;;
        erofs)
            extract.erofs -x -i "$image" -o "$destination" >/dev/null
            ;;
        *) die "Unsupported filesystem for $(basename "$image"): $type" ;;
    esac
}

copy_tree() {
    local source="$1" destination="$2"
    [[ -d "$source" ]] || return 0
    mkdir -p "$destination"
    cp -a "$source/." "$destination/"
}

merge_config() {
    local source="$1" destination="$2"
    [[ -f "$source" ]] || return 0
    touch "$destination"
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" ]] && continue
        grep -Fqx -- "$line" "$destination" || printf '%s\n' "$line" >> "$destination"
    done < "$source"
}

find_odm_root() {
    local images="$1"
    if [[ -d "$images/odm" ]]; then printf '%s' "$images/odm"
    elif [[ -d "$images/vendor/odm" ]]; then printf '%s' "$images/vendor/odm"
    else return 1
    fi
}

patch_property_contexts() {
    local root="$1" patch_file="$2"
    [[ -n "$patch_file" && -f "$patch_file" ]] || return 0
    local contexts
    contexts=$(find "$root/system_ext/etc/selinux" -type f -name 'system_ext_property_contexts' -print -quit 2>/dev/null || true)
    [[ -n "$contexts" ]] || die "system_ext_property_contexts not found"
    while read -r property context rest; do
        [[ -z "$property" || "$property" == \#* ]] && continue
        [[ -z "$context" || -n "$rest" ]] && die "Invalid property-context line for $property"
        grep -Fq "$property " "$contexts" || printf '%s %s\n' "$property" "$context" >> "$contexts"
    done < "$patch_file"
}
