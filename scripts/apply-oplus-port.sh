#!/usr/bin/env bash
set -Eeuo pipefail

WORK_DIR=${WORK_DIR:-$(pwd)}
source "$WORK_DIR/scripts/port-lib.sh"

BASE_IMAGES=${BASE_IMAGES:-$WORK_DIR/build/baserom/images}
PORT_IMAGES=${PORT_IMAGES:-$WORK_DIR/build/portrom/images}
EXTRAS_DIR=${EXTRAS_DIR:-$WORK_DIR/assets/local}

require_dir "$BASE_IMAGES/vendor"
require_dir "$PORT_IMAGES/system"

base_first_api=$(first_prop "$BASE_IMAGES" ro.product.first_api_level || true)
FIRST_API_LEVEL=${FIRST_API_LEVEL:-$base_first_api}
[[ "$FIRST_API_LEVEL" =~ ^[0-9]+$ ]] || die "FIRST_API_LEVEL is required and must be numeric"

log PORT "Keeping Xiaomi vendor/odm/dlkm; importing OPlus framework partitions"
for part in system product system_ext; do
    [[ -d "$PORT_IMAGES/$part" ]] || continue
    log PORT "Replacing Xiaomi $part with OPlus $part"
    remove_tree "${BASE_IMAGES:?}/$part" "Remove old Xiaomi $part tree"
    mv "$PORT_IMAGES/$part" "$BASE_IMAGES/$part"
    for suffix in fs_config file_contexts size; do
        [[ -f "$PORT_IMAGES/config/${part}_${suffix}" ]] || continue
        cp -f "$PORT_IMAGES/config/${part}_${suffix}" "$BASE_IMAGES/config/${part}_${suffix}"
    done
    log PORT "Imported $part ($(path_size "$BASE_IMAGES/$part"))"
done

require_dir "$BASE_IMAGES/system"
for part in my_product my_engineering my_stock my_carrier my_region my_bigball my_heytap my_manifest; do
    [[ -d "$PORT_IMAGES/$part" ]] || continue
    log PORT "Merging OPlus /$part into system"
    remove_tree "$BASE_IMAGES/system/$part" "Remove existing /$part tree"
    mv "$PORT_IMAGES/$part" "$BASE_IMAGES/system/$part"
    merge_config "$PORT_IMAGES/config/${part}_fs_config" "$BASE_IMAGES/config/system_fs_config"
    merge_config "$PORT_IMAGES/config/${part}_file_contexts" "$BASE_IMAGES/config/system_file_contexts"
done

log PORT "Applying reference-port debloat set"
prune_file="$WORK_DIR/devices/reference-port-prune.txt"
if [[ -f "$prune_file" ]]; then
    while IFS= read -r relative || [[ -n "$relative" ]]; do
        [[ -z "$relative" || "$relative" == \#* ]] && continue
        if [[ -e "$BASE_IMAGES/system/$relative" ]]; then
            log PORT "Debloat /system/$relative"
            rm -rf -- "$BASE_IMAGES/system/$relative"
        fi
    done < "$prune_file"
fi

# SIM2 and OPlus account services expect OPlus passwd/group entries. The rest of
# the vendor remains the Xiaomi stock vendor for hardware compatibility.
log PORT "Synchronizing OPlus passwd/group for SIM2 and account services"
if [[ -f "$PORT_IMAGES/vendor/etc/passwd" ]]; then
    cp -f "$PORT_IMAGES/vendor/etc/passwd" "$BASE_IMAGES/vendor/etc/passwd"
fi
if [[ -f "$PORT_IMAGES/vendor/etc/group" ]]; then
    cp -f "$PORT_IMAGES/vendor/etc/group" "$BASE_IMAGES/vendor/etc/group"
fi

odm_root=$(find_odm_root "$BASE_IMAGES") || die "Xiaomi ODM not found (standalone or vendor/odm)"
log PORT "Importing the OPlus ODM compatibility layer over Xiaomi hardware ODM"
copy_matching_files "$PORT_IMAGES/odm" "$odm_root" \
    'bin/hw/vendor-oplus-*' \
    'bin/hw/vendor.oplus.*' \
    'etc/aac_richtap.config' \
    'etc/custom_power.cfg' \
    'etc/default.cfg' \
    'etc/Diag.cfg' \
    'etc/devices_config/*' \
    'etc/init/*oplus*' \
    'etc/init/*orms*' \
    'etc/normalize/*' \
    'etc/orms/*' \
    'etc/permissions/com.oplus.*' \
    'etc/permissions/vendor-oplus-*' \
    'etc/power_profile/power_monitor_config.xml' \
    'etc/vintf/manifest/*oplus*' \
    'etc/vintf/manifest/*performance*' \
    'etc/vintf/manifest/*powermonitor*' \
    'etc/vintf/manifest/*orms*' \
    'etc/vintf/manifest/*urcc*' \
    'lib*/liboplus-*' \
    'lib*/liborms*' \
    'lib*/libosense*' \
    'lib*/libuah*' \
    'lib64/liburcccore.so' \
    'lib*/vendor.oplus.*'
odm_prop="$odm_root/build.prop"
if [[ -f "$PORT_IMAGES/odm/build.prop" ]]; then
    cp -f "$PORT_IMAGES/odm/build.prop" "$odm_prop"
else
    touch "$odm_prop"
fi

# The shipping reference imports merged my_* trees from /system via ODM. This
# preserves ColorOS' own system build.prop and matches Android mount paths.
odm_imports="$odm_root/etc/build.prop"
mkdir -p "$(dirname "$odm_imports")"
cat > "$odm_imports" <<'EOF'
import /odm/etc/${ro.boot.prjname}/build.gsi.prop
import /odm/etc/${ro.boot.prjname}/build.${ro.boot.flag}.prop
import /mnt/vendor/my_product/etc/${ro.boot.prjname}/build.${ro.boot.flag}.prop
EOF
for part in my_bigball my_carrier my_engineering my_heytap my_manifest my_product my_region my_stock; do
    [[ -f "$BASE_IMAGES/system/$part/build.prop" ]] && printf 'import /system/%s/build.prop\n' "$part" >> "$odm_imports"
done
printf '%s\n' 'import /odm/build.prop' >> "$odm_imports"
remove_tree "$PORT_IMAGES/odm" "Remove extracted donor ODM after compatibility import"

for required in DEVICE_CODENAME DEVICE_MODEL DEVICE_NAME; do
    [[ -n "${!required:-}" ]] || die "$required could not be detected from the Xiaomi ROM"
done

log PORT "Writing detected device properties to Xiaomi ODM"
if [[ -n "${SOC_ID:-${SOC_MODEL:-}}" ]]; then
    set_prop "$odm_prop" ro.build.device_family "OP${SOC_ID:-$SOC_MODEL}"
    set_prop "$odm_prop" ro.product.oplus.cpuinfo "${SOC_ID:-$SOC_MODEL}"
else
    log WARN "SoC model was not present in Xiaomi properties; CPU display props were left unchanged"
fi
set_prop "$odm_prop" ro.product.brand OPPO
set_prop "$odm_prop" ro.product.manufacturer OPPO
set_prop "$odm_prop" ro.product.model "${OPLUS_DEVICE_MODEL:-$DEVICE_CODENAME}"
set_prop "$odm_prop" ro.product.odm.brand OPPO
set_prop "$odm_prop" ro.product.odm.manufacturer OPPO
set_prop "$odm_prop" ro.vendor.oplus.market.name "$DEVICE_NAME"
if [[ -n "${FRONT_CAMERA_MP:-}" ]]; then
    set_prop "$odm_prop" ro.vendor.oplus.camera.frontCamSize "$FRONT_CAMERA_MP"
else
    log WARN "Front camera size not found in Xiaomi ROM"
fi
if [[ -n "${BACK_CAMERA_MP:-}" ]]; then
    set_prop "$odm_prop" ro.vendor.oplus.camera.backCamSize "$BACK_CAMERA_MP"
else
    log WARN "Back camera size not found in Xiaomi ROM"
fi
if [[ -n "${SCREEN_SIZE_INCHES:-}" ]]; then
    set_prop "$odm_prop" ro.oplus.display.screenSizeInches.primary "$SCREEN_SIZE_INCHES"
else
    log WARN "Screen diagonal not found in Xiaomi ROM"
fi
set_prop "$odm_prop" ro.vendor.audio.policy.engine.odm true

# Xiaomi sometimes ships a second codename-specific ODM property file.
while IFS= read -r -d '' prop; do
    set_prop "$prop" ro.product.odm.brand OPPO
    set_prop "$prop" ro.product.odm.manufacturer OPPO
done < <(find "$odm_root/etc" -maxdepth 2 -type f -name '*build.prop' -print0 2>/dev/null)

while IFS= read -r -d '' prop; do
    set_prop "$prop" ro.product.first_api_level "$FIRST_API_LEVEL"
done < <(find "$BASE_IMAGES" -type f -name 'build.prop' -print0)

manifest_prop="$BASE_IMAGES/system/my_manifest/build.prop"
if [[ -f "$manifest_prop" ]]; then
    set_prop "$manifest_prop" ro.vendor.oplus.market.name "$DEVICE_NAME"
    set_prop "$manifest_prop" ro.vendor.oplus.market.enname "$DEVICE_NAME"
fi

# OPlus ROMs commonly carry source-device display overrides in my_product.
# Replace only values discoverable from Xiaomi and drop resolution-specific
# zoom toggles that are unsafe to copy across devices.
my_product_prop="$BASE_IMAGES/system/my_product/build.prop"
if [[ -f "$my_product_prop" ]]; then
    for key in \
        ro.density.screenzoom.fdh ro.density.screenzoom.qdh \
        ro.oplus.density.fhd_default ro.oplus.density.qhd_default \
        ro.oplus.resolution.low ro.oplus.resolution.high; do
        sed -i "\|^${key//./\\.}=|d" "$my_product_prop"
    done
    sed -i '/^[^#]*screenhole[^=]*=/Id' "$my_product_prop"
    if [[ "${DISPLAY_DENSITY:-}" =~ ^[0-9]+$ ]]; then
        set_prop "$my_product_prop" ro.sf.lcd_density "$DISPLAY_DENSITY"
    else
        log WARN "Display density not found in Xiaomi ROM; OPlus density was left unchanged"
    fi
fi

if [[ -n "${BATTERY_CAPACITY_MAH:-}" ]]; then
    log PORT "Updating battery capacity to ${BATTERY_CAPACITY_MAH}mAh"
    while IFS= read -r -d '' power_profile; do
        python3 - "$power_profile" "$BATTERY_CAPACITY_MAH" <<'PY'
from pathlib import Path
import re, sys
p, capacity = Path(sys.argv[1]), sys.argv[2]
s = p.read_text(encoding="utf-8", errors="surrogateescape")
s = re.sub(r'(<item\s+name="battery\.capacity"\s*>)[^<]*(</item>)', rf'\g<1>{capacity}\g<2>', s)
p.write_text(s, encoding="utf-8", errors="surrogateescape")
PY
    done < <(find "$odm_root/etc/power_profile" -type f -name '*.xml' -print0 2>/dev/null)
fi

# Optional AyuGram-derived extras. They are never required for a minimal port.
log PORT "Applying enabled compatibility assets"
if bool "${ENABLE_VNDK_APEX:-true}" && [[ -d "$EXTRAS_DIR/system_ext/apex" ]]; then
    copy_tree "$EXTRAS_DIR/system_ext/apex" "$BASE_IMAGES/system_ext/apex"
fi
if bool "${ENABLE_OPLUS_OVERLAYS:-false}" && [[ -d "$EXTRAS_DIR/overlay" ]]; then
    copy_tree "$EXTRAS_DIR/overlay" "$BASE_IMAGES/system/my_product/overlay"
fi
if bool "${ENABLE_BLUETOOTH_QTI_FIX:-false}" && [[ -d "$EXTRAS_DIR/vendor" ]]; then
    copy_tree "$EXTRAS_DIR/vendor" "$BASE_IMAGES/vendor"
fi
if bool "${ENABLE_CRYPTOENG_HAL:-false}" && [[ -d "$EXTRAS_DIR/femboyAidL/odm" ]]; then
    copy_tree "$EXTRAS_DIR/femboyAidL/odm" "$odm_root"
    [[ -f "$EXTRAS_DIR/femboyAidL/add_to_build.prop" ]] && cat "$EXTRAS_DIR/femboyAidL/add_to_build.prop" >> "$odm_prop"
    if [[ "$odm_root" == "$BASE_IMAGES/odm" ]]; then
        context_path='/odm/bin/hw/vendor-oplus-hardware-cryptoeng-service'
        context_file="$BASE_IMAGES/config/odm_file_contexts"
    else
        context_path='/vendor/odm/bin/hw/vendor-oplus-hardware-cryptoeng-service'
        context_file="$BASE_IMAGES/config/vendor_file_contexts"
    fi
    touch "$context_file"
    grep -Fq "$context_path " "$context_file" || printf '%s %s\n' "$context_path" 'u:object_r:hal_allocator_default_exec:s0' >> "$context_file"
fi

patch_property_contexts "$BASE_IMAGES" "${PROPERTY_CONTEXT_PATCH_FILE:-}"

# Remove accidental desktop metadata and reject common unsafe placeholder values.
log PORT "Running final composition validation"
run_logged_task PORT "Remove desktop metadata" "$BASE_IMAGES" \
    find "$BASE_IMAGES" -type f \( -name '.DS_Store' -o -name 'Thumbs.db' \) -delete
# Restrict the content scan to property files.  The previous recursive grep
# read every APK, shared library and firmware blob in the 10+ GiB ROM tree and
# appeared stuck for tens of minutes on GitHub-hosted runners.
if grep -Rqs --include='build.prop' --include='*.prop' '#add your' "$BASE_IMAGES"; then
    die "Unresolved tutorial placeholder found in build.prop"
fi

log PORT "OPlus framework port composition completed"
