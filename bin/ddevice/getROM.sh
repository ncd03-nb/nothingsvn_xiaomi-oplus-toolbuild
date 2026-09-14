#!/bin/bash

baserom="$1"
work_dir=$(pwd)
source $work_dir/functions.sh

# Work out the file name a download link will land on. Xiaomi's own CDN appends
# a "?t=..." token, while SourceForge - where the xiaomi.eu releases live -
# hides the real name behind a trailing "/download" and redirects to a mirror
# that adds "?viasf=1", so neither trick alone is enough.
url_filename() {
    local url="${1%%\?*}"
    url="${url%%#*}"
    url="${url%/}"
    local name=$(basename "$url")
    if [ "$name" = "download" ]; then
        url="${url%/download}"
        name=$(basename "$url")
    fi
    echo "$name"
}

# Check whether it is a local package or a link
if [ ! -f "${baserom}" ] && [ "$(echo $baserom |grep http)" != "" ]; then
    info "Download link detected, starting a download..."
    target=$(url_filename "${baserom}")
    if echo "$baserom" | grep -qi "sourceforge"; then
        info "SourceForge (xiaomi.eu) link detected: ${target}"
    fi
    # SourceForge answers with a redirect to a mirror and some nodes turn away
    # the default aria2 agent, so send a browser agent and force the resolved
    # name instead of trusting the last path segment.
    aria2c --max-download-limit=1024M --file-allocation=none -s10 -x10 -j10 \
           --max-tries=5 --retry-wait=10 --continue=true --allow-overwrite=true \
           --auto-file-renaming=false \
           --user-agent="Mozilla/5.0" --referer="https://sourceforge.net/" \
           -o "${target}" "${baserom}"
    if [ -f "$work_dir/${target}" ]; then
        baserom="${target}"
    else
        # aria2c may have kept a Content-Disposition name of its own - fall back
        # to the archive it just wrote.
        baserom=$(ls -t "$work_dir"/*.zip 2>/dev/null | head -n 1)
        [ -n "$baserom" ] && baserom=$(basename "$baserom")
    fi
    if [ -z "$baserom" ] || [ ! -f "$work_dir/${baserom}" ]; then
        error "Download error!"
        exit 1
    fi
    info "BASEROM: ${baserom}"
elif [ -f "${baserom}" ]; then
    info "BASEROM: ${baserom}"
else
    error "BASEROM: Invalid parameter"
    exit
fi


# Get ROM Info
baserom_name=$(basename "$baserom")
rom_source="official"

if [ "$(echo $baserom_name |grep xiaomi.eu_)" != "" ]; then
    # xiaomi.eu_multi_<Device>_<RomVersion>_<v..>.zip
    rom_source="xiaomi.eu"
    device_code=$(echo "$baserom_name" |cut -d '_' -f 3)
    base_rom_code=$(echo "$baserom_name" |cut -d '_' -f 4)
elif [ "$(echo $baserom_name |grep miui_)" != "" ]; then
    device_code=$(echo "$baserom_name" |cut -d '_' -f 2)
    base_rom_code=$(echo "$baserom_name" |cut -d '_' -f 3)
elif [ "$(echo $baserom_name | grep -E '.*-ota_full-.*')" != "" ]; then
    device_code=$(echo "$baserom_name" | cut -d '-' -f 1)
    base_rom_code=$(echo "$baserom_name" | cut -d '-' -f 3)

    # Transform device_code
    device_code=$(echo $device_code | awk -F '_' '{
        if (NF == 1) {
            # If one part, e.g., shennong
            print toupper($1)
        } else if (NF == 2) {
            # If two parts, e.g., tapas_global
            print toupper($1) toupper(substr($2, 1, 1)) substr($2, 2)
        } else if (NF == 3) {
            # If three parts, e.g., houji_tw_global
            printf toupper($1) toupper($2) toupper(substr($3, 1, 1)) substr($3, 2)
        }
    }')
else
    device_code="YourDevice"
    base_rom_code="Unknown"
fi

device_f=$(echo $device_code | sed 's/\(Global\|EEAGlobal\|INGlobal\|IDGlobal\|RUGlobal\|TWGlobal\|TRGlobal\|JPGlobal\)$//' | tr '[:upper:]' '[:lower:]')

# Determine Device Type
info "Get Device Type"
if [ "$rom_source" = "xiaomi.eu" ]; then
    # xiaomi.eu builds are multi-region: they already carry every language and
    # GMS, so neither the China-only nor the Global-only mods should fire.
    DEVICE_TYPE="EU"
elif echo "$device_code" | grep -q 'EEAGlobal'; then
    DEVICE_TYPE="EEAGlobal"
elif echo "$device_code" | grep -q 'INGlobal'; then
    DEVICE_TYPE="INGlobal"
elif echo "$device_code" | grep -q 'IDGlobal'; then
    DEVICE_TYPE="IDGlobal"
elif echo "$device_code" | grep -q 'RUGlobal'; then
    DEVICE_TYPE="RUGlobal"
elif echo "$device_code" | grep -q 'JPGlobal'; then
    DEVICE_TYPE="JPGlobal"
elif echo "$device_code" | grep -q 'Global'; then
    DEVICE_TYPE="Global"
elif echo "$device_code" | grep -q 'TWGlobal'; then
    DEVICE_TYPE="TWGlobal"
elif echo "$device_code" | grep -q 'TRGlobal'; then
    DEVICE_TYPE="TRGlobal"
else
    DEVICE_TYPE="China"
fi

#Check MIUI or Hyper
if echo "$base_rom_code" | grep -q "OS1"; then
    ROM_OS="OS1"
elif echo "$base_rom_code" | grep -q "OS2"; then
    ROM_OS="OS2"
elif echo "$base_rom_code" | grep -q "OS3"; then
    ROM_OS="OS3"
elif echo "$base_rom_code" | grep -q "OS4"; then
    ROM_OS="OS4"
elif echo "$base_rom_code" | grep -qE "V1[234]"; then
    ROM_OS="MIUI"
else
    echo "Unsupported ROM, exiting..."
    exit 1
fi

echo $base_rom_code > $work_dir/bin/ddevice/base_rom_code.txt
echo $base_rom_code > $work_dir/bin/ddevice/os_code.txt
echo $device_code > $work_dir/bin/ddevice/device_code.txt
echo $DEVICE_TYPE > $work_dir/bin/ddevice/device_type.txt
echo $ROM_OS > $work_dir/bin/ddevice/rom_os.txt
echo $rom_source > $work_dir/bin/ddevice/rom_source.txt
