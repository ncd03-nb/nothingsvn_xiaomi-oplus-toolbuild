#!/usr/bin/env bash
set -Eeuo pipefail

BASE_ROM=${1:-}
OPLUS_ROM=${2:-}
LOCAL_BUILD=${3:-n}
REPO_NAME=${4:-local/xiaomi-oplus-port}
PREFIX_ID=${5:-xiaomi-oplus}
BUILDER_NAME=${6:-local}
BUILDER_ID=${7:-}
OVERLAY_OVERRIDE=${ENABLE_OPLUS_OVERLAYS:-}
CRYPTOENG_OVERRIDE=${ENABLE_CRYPTOENG_HAL:-}

WORK_DIR=$(cd "$(dirname "$0")" && pwd)
export WORK_DIR builder_name="$BUILDER_NAME"
tools_dir="$WORK_DIR/bin/$(uname)/$(uname -m)"
export PATH="$tools_dir:$PATH"
source "$WORK_DIR/functions.sh"
source "$WORK_DIR/scripts/port-lib.sh"

[[ -n "$BASE_ROM" && -n "$OPLUS_ROM" ]] || die "Usage: bash build.sh <xiaomi-stock-ota> <oplus-ota> [y|n] [repo] [prefix] [builder] [telegram-id]"
ENABLE_OPLUS_OVERLAYS=${OVERLAY_OVERRIDE:-false}
ENABLE_CRYPTOENG_HAL=${CRYPTOENG_OVERRIDE:-false}
ENABLE_VNDK_APEX=${ENABLE_VNDK_APEX:-true}
ENABLE_BLUETOOTH_QTI_FIX=${ENABLE_BLUETOOTH_QTI_FIX:-false}
EXTRAS_DIR=${EXTRAS_DIR:-$WORK_DIR/assets/local}

notify() {
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHANNEL_ID:-}" ]]; then
        python3 "$WORK_DIR/notify.py" "$@" || log WARN "Telegram notification failed"
    fi
}

on_error() {
    local code=$?
    log ERROR "Build stopped at line ${BASH_LINENO[0]} (exit $code)"
    exit "$code"
}
trap on_error ERR

for command in 7z aria2c bc curl gettype lpmake mkfs.erofs payload-extract python3 zip; do
    command -v "$command" >/dev/null || die "Required command is missing: $command"
done

rm -rf "$WORK_DIR/build" "$WORK_DIR/downloads" "$WORK_DIR/out"
mkdir -p "$WORK_DIR/build/baserom/images" "$WORK_DIR/build/portrom/images" "$WORK_DIR/downloads"

notify download "$REPO_NAME" "$BASE_ROM" "$PREFIX_ID" "$BUILDER_NAME" "$BUILDER_ID"
obtain_rom "$BASE_ROM" "Xiaomi base ROM" "$WORK_DIR/downloads/base.zip"
obtain_rom "$OPLUS_ROM" "OPlus port ROM" "$WORK_DIR/downloads/oplus.zip"

notify unpack "$REPO_NAME" "$BASE_ROM" "$PREFIX_ID" "$BUILDER_NAME" "$BUILDER_ID"
extract_payload_rom "$WORK_DIR/downloads/base.zip" "$WORK_DIR/build/baserom" "Xiaomi base ROM"
rm -f "$WORK_DIR/downloads/base.zip"
# Only OPlus framework/compatibility partitions are consumed below. Extracting
# every firmware and boot partition from a 60+ partition payload wastes runner
# disk and can leave payload-extract doing hours of unnecessary I/O.
OPLUS_PARTITIONS="system,product,system_ext,vendor,odm,my_product,my_engineering,my_stock,my_carrier,my_region,my_bigball,my_heytap,my_manifest"
extract_payload_rom "$WORK_DIR/downloads/oplus.zip" "$WORK_DIR/build/portrom" "OPlus port ROM" "$OPLUS_PARTITIONS"
rm -f "$WORK_DIR/downloads/oplus.zip"

base_images="$WORK_DIR/build/baserom/images"
port_images="$WORK_DIR/build/portrom/images"
base_super="$base_images/super.img"

for required_port_part in system product system_ext; do
    [[ -f "$port_images/$required_port_part.img" ]] || die "OPlus payload is missing required partition: $required_port_part"
done

# Capture the original super size before unpacking if the OTA exposes super.img.
if [[ -f "$base_super" ]]; then
    stat -c%s "$base_super" > "$WORK_DIR/bin/ddevice/superSize.txt"
fi

log UNPACK "Extracting Xiaomi hardware partitions"
for candidate in system product system_ext vendor; do
    if [[ -f "$base_images/$candidate.img" ]]; then
        fs_type=$(gettype -i "$base_images/$candidate.img")
        [[ "$fs_type" == ext ]] && printf '%s\n' EXT > "$WORK_DIR/bin/ddevice/fstype.txt"
        [[ "$fs_type" == erofs ]] && printf '%s\n' EROFS > "$WORK_DIR/bin/ddevice/fstype.txt"
        break
    fi
done
for part in system product system_ext vendor odm mi_ext; do
    [[ -f "$base_images/$part.img" ]] && extract_image "$base_images/$part.img" "$base_images"
done

device_json="$WORK_DIR/build/device.json"
python3 "$WORK_DIR/scripts/detect-device.py" \
    --root "$base_images" \
    --payload-metadata "$WORK_DIR/build/baserom/payload_metadata.json" \
    --output "$device_json"
json_value() {
    python3 - "$device_json" "$1" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream).get(sys.argv[2], "")
print(value if value is not None else "")
PY
}
DEVICE_CODENAME=$(json_value device_codename)
DEVICE_MODEL=$(json_value device_model)
DEVICE_NAME=$(json_value device_name)
SOC_MODEL=$(json_value soc_model)
FIRST_API_LEVEL=$(json_value first_api_level)
AB_UPDATE=$(json_value ab_update)
FRONT_CAMERA_MP=$(json_value front_camera_mp)
BACK_CAMERA_MP=$(json_value back_camera_mp)
SCREEN_SIZE_INCHES=$(json_value screen_size_inches)
DISPLAY_DENSITY=$(json_value display_density)
BATTERY_CAPACITY_MAH=$(json_value battery_capacity_mah)
SUPER_SIZE=$(json_value super_size)
DYNAMIC_GROUP_SIZE=$(json_value dynamic_group_size)
export DEVICE_CODENAME DEVICE_MODEL DEVICE_NAME SOC_MODEL FIRST_API_LEVEL AB_UPDATE
export FRONT_CAMERA_MP BACK_CAMERA_MP SCREEN_SIZE_INCHES DISPLAY_DENSITY BATTERY_CAPACITY_MAH
export SUPER_SIZE DYNAMIC_GROUP_SIZE ENABLE_OPLUS_OVERLAYS ENABLE_CRYPTOENG_HAL
export ENABLE_VNDK_APEX ENABLE_BLUETOOTH_QTI_FIX EXTRAS_DIR

[[ -n "$DEVICE_CODENAME" ]] || die "Could not detect Xiaomi codename from extracted ROM properties"
[[ "$FIRST_API_LEVEL" =~ ^[0-9]+$ ]] || die "Could not detect ro.product.first_api_level from Xiaomi ROM"
[[ "$SUPER_SIZE" =~ ^[0-9]+$ ]] || die "Could not derive super size from Xiaomi payload dynamic-partition metadata"
log DETECT "Device=$DEVICE_NAME codename=$DEVICE_CODENAME SoC=${SOC_MODEL:-unknown} first_api=$FIRST_API_LEVEL super=$SUPER_SIZE"

log UNPACK "Extracting OPlus framework and compatibility data"
for part in system product system_ext vendor odm my_product my_engineering my_stock my_carrier my_region my_bigball my_heytap my_manifest; do
    [[ -f "$port_images/$part.img" ]] && extract_image "$port_images/$part.img" "$port_images"
done

export BASE_IMAGES="$base_images" PORT_IMAGES="$port_images"
bash "$WORK_DIR/scripts/apply-oplus-port.sh"

# Metadata used by packROM.sh, uploadROM.sh and notify.py.
mkdir -p "$WORK_DIR/bin/ddevice"
printf '%s\n' "$DEVICE_CODENAME" > "$WORK_DIR/bin/ddevice/device_f.txt"
printf '%s\n' "$DEVICE_CODENAME" > "$WORK_DIR/bin/ddevice/device_code.txt"
printf '%s\n' "$DEVICE_NAME" > "$WORK_DIR/bin/ddevice/name_devices.txt"
printf '%s\n' "${OPLUS_VERSION:-ColorOS15}" > "$WORK_DIR/bin/ddevice/base_rom_code.txt"
printf '%s\n' "ColorOS" > "$WORK_DIR/bin/ddevice/rom_os.txt"
printf '%s\n' "OPlus" > "$WORK_DIR/bin/ddevice/os_type.txt"
printf '%s\n' "Global" > "$WORK_DIR/bin/ddevice/device_type.txt"
printf '%s\n' "payload" > "$WORK_DIR/bin/ddevice/romtype.txt"
android_version=$(first_prop "$base_images" ro.build.version.release || true)
printf '%s\n' "${android_version:-15}" > "$WORK_DIR/bin/ddevice/androidver.txt"
printf '%s\n' "${FIRST_API_LEVEL}" > "$WORK_DIR/bin/ddevice/sdkLevel.txt"
printf '%s\n' "$SUPER_SIZE" > "$WORK_DIR/bin/ddevice/profile_super_size.txt"
if [[ "${AB_UPDATE,,}" == true ]]; then
    printf '%s\n' VAB > "$WORK_DIR/bin/ddevice/slot_type.txt"
else
    printf '%s\n' AONLY > "$WORK_DIR/bin/ddevice/slot_type.txt"
fi
bash "$WORK_DIR/bin/ddevice/genInstall.sh"

notify build "$REPO_NAME" "$BASE_ROM" "$PREFIX_ID" "$BUILDER_NAME" "$BUILDER_ID"
log BUILD "Composition ready for $DEVICE_NAME ($DEVICE_CODENAME)"

if [[ "$LOCAL_BUILD" == y ]]; then
    bash "$WORK_DIR/packROM.sh"
fi
