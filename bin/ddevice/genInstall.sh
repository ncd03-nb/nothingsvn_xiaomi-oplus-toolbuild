#!/usr/bin/env bash
set -Eeuo pipefail

work_dir=${WORK_DIR:-$(pwd)}
device_code=$(cat "$work_dir/bin/ddevice/device_code.txt" 2>/dev/null || printf unknown)
codename=$(cat "$work_dir/bin/ddevice/device_f.txt" 2>/dev/null || printf '%s' "$device_code")
name=$(cat "$work_dir/bin/ddevice/name_devices.txt" 2>/dev/null || printf '%s' "$device_code")
base_rom_code=$(cat "$work_dir/bin/ddevice/base_rom_code.txt" 2>/dev/null || printf unknown)
port_rom_code=$(cat "$work_dir/bin/ddevice/port_rom_code.txt" 2>/dev/null || printf unknown)
rom_region=$(cat "$work_dir/bin/ddevice/device_type.txt" 2>/dev/null || printf unknown)
android_version=$(cat "$work_dir/bin/ddevice/androidver.txt" 2>/dev/null || printf unknown)
tool_version=$(cat "$work_dir/Version" 2>/dev/null || printf 1.0)
output_file="$work_dir/bin/script2flash/${device_code}.install"
meta_data="$work_dir/bin/script2flash/META-INF/Data"

mkdir -p "$meta_data"
printf '%s\n' "$codename" > "$meta_data/CNAME"
cat "$work_dir/bin/ddevice/slot_type.txt" > "$meta_data/A"

cat > "$output_file" <<EOF
{
    "Devices": {
        "Name": "${name}",
        "Brand": "Xiaomi",
        "Codename": "${codename}"
    },
    "ROM": {
        "BaseType": "HyperOS",
        "BaseVersion": "${base_rom_code}",
        "PortType": "ColorOS",
        "PortVersion": "${port_rom_code}",
        "Region": "${rom_region}",
        "Android": "${android_version}"
    },
    "ToolBuild": {
        "Version": "${tool_version}",
        "BuildDate": "$(date +%Y-%m-%d)",
        "Author": "${builder_name:-NothingsVN}",
        "BuildType": "Xiaomi-OPlus-Port"
    },
    "Directory": {
        "Firmware": "images",
        "System": "super"
    }
}
EOF

printf 'Generated %s\n' "$output_file"
