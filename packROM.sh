#!/usr/bin/env bash
set -Eeuo pipefail

WORK_DIR=$(cd "$(dirname "$0")" && pwd)
tools_dir="$WORK_DIR/bin/$(uname)/$(uname -m)"
export PATH="$tools_dir:$PATH"
source "$WORK_DIR/functions.sh"
source "$WORK_DIR/scripts/port-lib.sh"

IMAGES="$WORK_DIR/build/baserom/images"
CONFIG="$IMAGES/config"
require_dir "$IMAGES"
mkdir -p "$CONFIG"

device_code=$(cat "$WORK_DIR/bin/ddevice/device_f.txt")
profile_size=$(cat "$WORK_DIR/bin/ddevice/profile_super_size.txt" 2>/dev/null || true)
detected_size=$(cat "$WORK_DIR/bin/ddevice/superSize.txt" 2>/dev/null || true)
if [[ "$profile_size" =~ ^[0-9]+$ ]]; then
    super_size=$profile_size
elif [[ "$detected_size" =~ ^[0-9]+$ ]]; then
    super_size=$detected_size
else
    super_size=$(bash "$WORK_DIR/bin/getSuperSize.sh" "$device_code")
fi
[[ "$super_size" =~ ^[0-9]+$ ]] || die "Unable to determine super partition size"

pack_type=EROFS
if [[ -f "$WORK_DIR/bin/ddevice/fstype.txt" ]]; then
    pack_type=$(tr '[:lower:]' '[:upper:]' < "$WORK_DIR/bin/ddevice/fstype.txt")
fi

partition_list=""
phase "REPACK DYNAMIC PARTITIONS"
for partition in system system_ext product vendor odm mi_ext odm_dlkm system_dlkm vendor_dlkm product_dlkm; do
    directory="$IMAGES/$partition"
    image="$IMAGES/$partition.img"
    if [[ -d "$directory" ]]; then
        size=$(du -sb "$directory" | awk '{print $1}')
        size=$((size + 134217728))
        log REPACK "Preparing SELinux metadata for $partition ($(path_size "$directory"))"
        python3 "$WORK_DIR/bin/fix_selinux.py" "$directory" "$CONFIG/${partition}_fs_config" "$CONFIG/${partition}_file_contexts" >/dev/null 2>&1 || true
        rm -f "$image"
        if [[ "$pack_type" == EXT ]]; then
            run_logged_task REPACK "Build $partition.img (EXT4)" "$image" \
                make_ext4fs -J -T "$(date +%s)" -S "$CONFIG/${partition}_file_contexts" -l "$size" \
                -C "$CONFIG/${partition}_fs_config" -L "$partition" -a "$partition" "$image" "$directory"
        else
            run_logged_task REPACK "Build $partition.img (EROFS)" "$image" \
                mkfs.erofs --quiet -zlz4hc,9 --mount-point "$partition" \
                --fs-config-file="$CONFIG/${partition}_fs_config" \
                --file-contexts="$CONFIG/${partition}_file_contexts" "$image" "$directory"
        fi
        [[ -s "$image" ]] || die "Failed to repack $partition.img"
        rm -rf "$directory"
    fi
    [[ -f "$image" ]] && partition_list+=" $partition"
done
[[ -n "$partition_list" ]] || die "No dynamic partitions available to pack"

group_size=$((super_size - 268435456))
image_total=0
for partition in $partition_list; do
    image_total=$((image_total + $(stat -c%s "$IMAGES/$partition.img")))
done
(( image_total <= group_size )) || die "Dynamic images ($image_total bytes) exceed super group capacity ($group_size bytes)"
is_ab=false
[[ "$(cat "$WORK_DIR/bin/ddevice/slot_type.txt" 2>/dev/null || true)" == VAB ]] && is_ab=true
args=(-F --output "$IMAGES/super.img" --metadata-size 65536 --super-name super --block-size 4096 --device "super:$super_size")
if $is_ab; then
    args+=(--sparse --virtual-ab --metadata-slots 3 --group "qti_dynamic_partitions_a:$group_size" --group "qti_dynamic_partitions_b:$group_size")
    for partition in $partition_list; do
        size=$(stat -c%s "$IMAGES/$partition.img")
        args+=(--partition "${partition}_a:readonly:${size}:qti_dynamic_partitions_a" --image "${partition}_a=$IMAGES/$partition.img" --partition "${partition}_b:readonly:0:qti_dynamic_partitions_b")
    done
else
    args+=(--metadata-slots 2 --group "qti_dynamic_partitions:$group_size")
    for partition in $partition_list; do
        size=$(stat -c%s "$IMAGES/$partition.img")
        args+=(--partition "${partition}:readonly:${size}:qti_dynamic_partitions" --image "${partition}=$IMAGES/$partition.img")
    done
fi

phase "BUILD SUPER IMAGE"
run_logged_task REPACK "Build super.img ($super_size bytes)" "$IMAGES/super.img" lpmake "${args[@]}"
require_file "$IMAGES/super.img"
for partition in $partition_list; do
    rm -f "$IMAGES/$partition.img"
done

output_dir="$WORK_DIR/out/ColorOS_${device_code}"
mkdir -p "$output_dir/images" "$output_dir/super"
mv "$IMAGES/super.img" "$output_dir/super/"
find "$IMAGES" -maxdepth 1 -type f -name '*.img' -exec mv -t "$output_dir/images" {} +
cp -f "$WORK_DIR/bin/script2flash/"*.install "$output_dir/" 2>/dev/null || true
copy_tree "$WORK_DIR/bin/script2flash/META-INF" "$output_dir/META-INF"
chmod 0755 "$output_dir/META-INF/com/google/android/update-binary"
output_archive="$WORK_DIR/out/ColorOS15_${device_code}_$(date +%Y%m%d).zip"
(
    cd "$output_dir"
    run_logged_task REPACK "Create flashable ZIP" "$output_archive" zip -r -1 "$output_archive" ./*
)
output_zip=$(find "$WORK_DIR/out" -maxdepth 1 -type f -name '*.zip' -print -quit)
printf '%s\n' "$(basename "$output_zip")" > "$WORK_DIR/bin/ddevice/output_zip.txt"
log REPACK "Output: $output_zip"
