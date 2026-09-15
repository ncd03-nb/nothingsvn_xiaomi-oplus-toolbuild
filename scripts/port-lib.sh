#!/usr/bin/env bash

log() { printf '%(%H:%M:%S)T [%s] %s\n' -1 "$1" "$2"; }
die() { log ERROR "$1" >&2; exit 1; }

phase() {
    printf '\n========== %s ==========\n' "$1"
}

path_size() {
    local path="$1"
    [[ -e "$path" ]] || { printf '0'; return; }
    du -sh "$path" 2>/dev/null | awk '{print $1}'
}

run_logged_task() {
    local category="$1" label="$2" watch_path="$3"
    shift 3
    local log_dir="${WORK_DIR:-$(pwd)}/build/task-logs"
    mkdir -p "$log_dir"
    local task_log
    task_log=$(mktemp "$log_dir/task.XXXXXX.log")
    local started=$SECONDS pid status=0 elapsed next_report=30

    log "$category" "START $label"
    "$@" >"$task_log" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 2
        elapsed=$((SECONDS - started))
        if kill -0 "$pid" 2>/dev/null && ((elapsed >= next_report)); then
            local disk_path="$watch_path" free_space
            [[ -e "$disk_path" ]] || disk_path=$(dirname "$disk_path")
            [[ -e "$disk_path" ]] || disk_path="${WORK_DIR:-$(pwd)}"
            free_space=$(df -h "$disk_path" 2>/dev/null | awk 'NR==2 {print $4}' || true)
            log "$category" "RUNNING $label (${elapsed}s, data=$(path_size "$watch_path"), free=${free_space:-unknown})"
            next_report=$((next_report + 30))
        fi
    done
    wait "$pid" || status=$?
    elapsed=$((SECONDS - started))
    if ((status != 0)); then
        log ERROR "$label failed (exit $status); last tool output:"
        tail -n 100 "$task_log" >&2 || true
        rm -f "$task_log"
        return "$status"
    fi
    rm -f "$task_log"
    log "$category" "DONE $label (${elapsed}s, data=$(path_size "$watch_path"))"
}

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
    local archive="$1" destination="$2" label="$3" partitions="${4:-}"
    mkdir -p "$destination/images"
    7z l "$archive" | grep -q 'payload.bin' || die "$label is not a payload OTA"
    log UNPACK "Extracting $label payload.bin"
    7z e -so "$archive" META-INF/com/android/metadata \
        > "$destination/ota_metadata.txt" 2>/dev/null || : > "$destination/ota_metadata.txt"
    7z x -y -mmt=on "$archive" payload.bin -o"$destination" >/dev/null
    # payload.bin is now standalone. Dropping the OTA archive before expanding
    # images saves 5-12 GiB on GitHub-hosted runners.
    rm -f "$archive"
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
    local extract_args=(extract -o "$destination/images")
    if [[ -n "$partitions" ]]; then
        extract_args+=(-p "$partitions")
        log UNPACK "$label selected partitions: $partitions"
    fi
    extract_args+=("$destination/payload.bin")

    # The extractor renders progress only on an interactive terminal. Run it
    # in the background and emit a periodic heartbeat for Actions and Telegram
    # diagnosis instead of appearing frozen for hours.
    payload-extract "${extract_args[@]}" &
    local extract_pid=$! extract_started=$SECONDS elapsed=0 next_report=30
    while kill -0 "$extract_pid" 2>/dev/null; do
        sleep 5
        elapsed=$((SECONDS - extract_started))
        if kill -0 "$extract_pid" 2>/dev/null && ((elapsed >= next_report)); then
            local image_size free_space
            image_size=$(du -sh "$destination/images" 2>/dev/null | awk '{print $1}')
            free_space=$(df -h "$destination" | awk 'NR==2 {print $4}')
            log UNPACK "$label still extracting (${elapsed}s, images=${image_size:-0}, free=${free_space:-unknown})"
            next_report=$((next_report + 30))
        fi
    done
    wait "$extract_pid" || {
        local status=$?
        die "$label payload extraction failed (exit $status)"
    }
    rm -f "$destination/payload.bin"
}

extract_image() {
    local image="$1" destination="$2"
    [[ -f "$image" ]] || return 0
    local type partition input_size
    type=$(gettype -i "$image")
    partition=$(basename "$image" .img)
    input_size=$(path_size "$image")
    case "$type" in
        ext)
            run_logged_task UNPACK "$partition.img ($type, $input_size)" "$destination/$partition" \
                python3 "$WORK_DIR/bin/imgextractor/imgextractor.py" "$image" "$destination"
            ;;
        erofs)
            run_logged_task UNPACK "$partition.img ($type, $input_size)" "$destination/$partition" \
                extract.erofs -x -i "$image" -o "$destination" -f
            ;;
        *) die "Unsupported filesystem for $(basename "$image"): $type" ;;
    esac
    rm -f "$image"
}

extract_metadata_image() {
    local image="$1" destination="$2"
    shift 2
    [[ -f "$image" ]] || return 0
    local type partition target extracted=0
    type=$(gettype -i "$image")
    partition=$(basename "$image" .img)
    if [[ "$type" != erofs ]]; then
        log UNPACK "$partition.img is $type; selective extraction unavailable, using full extraction"
        extract_image "$image" "$destination"
        return
    fi
    for target in "$@"; do
        if run_logged_task UNPACK "$partition.img metadata $target" "$destination/$partition" \
            extract.erofs -i "$image" -o "$destination" -X "$target" -f \
            && [[ -e "$destination/$partition/${target#/}" ]]; then
            extracted=1
        else
            log WARN "$partition.img does not expose optional metadata path $target"
        fi
    done
    rm -f "$image"
    ((extracted == 1)) || log WARN "No optional metadata extracted from $partition.img"
}

remove_tree() {
    local path="$1" label="$2"
    [[ -e "$path" ]] || return 0
    run_logged_task PORT "$label" "$(dirname "$path")" rm -rf "$path"
}

copy_tree() {
    local source="$1" destination="$2"
    [[ -d "$source" ]] || return 0
    mkdir -p "$destination"
    cp -a "$source/." "$destination/"
}

copy_matching_files() {
    local source="$1" destination="$2"
    shift 2
    [[ -d "$source" ]] || return 0
    local pattern file relative
    for pattern in "$@"; do
        while IFS= read -r -d '' file; do
            relative=${file#"$source/"}
            mkdir -p "$destination/$(dirname "$relative")"
            cp -af "$file" "$destination/$relative"
        done < <(find "$source" -type f -path "$source/$pattern" -print0)
    done
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
