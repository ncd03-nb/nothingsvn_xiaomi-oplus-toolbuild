work_dir=$(pwd)
source $work_dir/functions.sh
RCLONE_CONFIG_1DRIVE="$work_dir/rclone.conf"
ONEDRIVE_REMOTE="starxONEDRIVE"
os_type=$(cat $work_dir/bin/ddevice/os_type.txt)
base_rom_code=$(cat $work_dir/bin/ddevice/base_rom_code.txt)
androidVER=$(cat $work_dir/bin/ddevice/androidver.txt)
rom_os=$(cat $work_dir/bin/ddevice/rom_os.txt)
regionTYPE=$(cat $work_dir/bin/ddevice/device_type.txt)
device_code=$(cat $work_dir/bin/ddevice/device_code.txt)
baserom_type=$(cat $work_dir/bin/ddevice/romtype.txt)
device_f=$(cat $work_dir/bin/ddevice/device_f.txt)

if [ "$1" == "setup" ]; then
  if [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
    echo "[ERROR] - Please provide rclone token and remote name"
    exit 1
  fi
  curl  -s -o $work_dir/rclone.conf \
        -H "Authorization: token $2" \
        -H "Accept: application/vnd.github.v3.raw" \
        -L https://api.github.com/repos/$3/contents/$4
        
  TOKEN_DIR=$(dirname "$4")
  if [ "$TOKEN_DIR" == "." ]; then
    TOKEN_PATH="token.pickle"
  else
    TOKEN_PATH="$TOKEN_DIR/token.pickle"
  fi
  
  curl  -s -o $work_dir/token.pickle \
        -H "Authorization: token $2" \
        -H "Accept: application/vnd.github.v3.raw" \
        -L https://api.github.com/repos/$3/contents/$TOKEN_PATH
        
  exit 0
fi


if [[ $(git branch --show-current) == "beta" ]]; then
    polyxver="$(cat Version)"
	status="Development"
else
    polyxver="$(cat Version)"
	status="Official"
fi

if [[ $rom_os == "MIUI" ]];then
    os_type="MIUI"
else
    os_type="HyperOS"
fi

repack "Generating flashing script"
if [[ ${baserom_type} == 'payload' || ${baserom_type} == 'eu' ]]; then
    mkdir -p $work_dir/out/${os_type}_${device_code}_${base_rom_code}/images/
    mkdir -p $work_dir/out/${os_type}_${device_code}_${base_rom_code}/super/
	mv -f $work_dir/build/baserom/images/super.img $work_dir/out/${os_type}_${device_code}_${base_rom_code}/super/
    mv -f $work_dir/build/baserom/images/*.img $work_dir/out/${os_type}_${device_code}_${base_rom_code}/images/
elif [[ ${baserom_type} == 'br' ]]; then
    mkdir -p $work_dir/out/${os_type}_${device_code}_${base_rom_code}/images/
    mv -f $work_dir/build/baserom/firmware-update/* $work_dir/out/${os_type}_${device_code}_${base_rom_code}/images/
    mv -f $work_dir/build/baserom/images/super.img $work_dir/out/${os_type}_${device_code}_${base_rom_code}/super/
fi

# A xiaomi.eu package brings its own cust.img - keep it over the generic one.
if [[ ! -f $work_dir/out/${os_type}_${device_code}_${base_rom_code}/images/cust.img ]]; then
    cp -rf $work_dir/bin/script2flash/cust.img $work_dir/out/${os_type}_${device_code}_${base_rom_code}/images/ 2>/dev/null || true
fi
cp -rf $work_dir/bin/script2flash/*.install $work_dir/out/${os_type}_${device_code}_${base_rom_code}/

find out/${os_type}_${device_code}_${base_rom_code} |xargs touch
pushd out/${os_type}_${device_code}_${base_rom_code}/ || exit
zip -r ${os_type}_${device_code}_${base_rom_code}.zip ./*
mv ${os_type}_${device_code}_${base_rom_code}.zip ../
popd || exit
hash=$(md5sum out/${os_type}_${device_code}_${base_rom_code}.zip |head -c 5)
install_mods=$(config_flag install_mods)
install_toolbox=$(config_flag install_toolbox)
if [[ "$install_mods" == "true" && "$install_toolbox" == "true" ]]; then
    build_type="Full"
elif [[ "$install_mods" == "true" && "$install_toolbox" != "true" ]]; then
    build_type="NoToolbox"
elif [[ "$install_mods" != "true" && "$install_toolbox" == "true" ]]; then
    build_type="NoMods"
else
    build_type="PureStock"
fi
current_date=$(date +"%d%m%Y")
mv out/${os_type}_${device_code}_${base_rom_code}.zip out/${os_type}_${polyxver}_${device_code}_${base_rom_code}_${hash}_${status}_${current_date}_${build_type}.zip
repack "Build completed"    
repack "Output: "
repack "$(pwd)/out/${os_type}_${polyxver}_${device_code}_${base_rom_code}_${hash}_${status}_${current_date}_${build_type}.zip"
upload "Uploading"
output_file="out/${os_type}_${polyxver}_${device_code}_${base_rom_code}_${hash}_${status}_${current_date}_${build_type}.zip"
echo "${os_type}_${polyxver}_${device_code}_${base_rom_code}_${hash}_${status}_${current_date}_${build_type}.zip" > $work_dir/bin/ddevice/output_zip.txt

if [[ $rom_os == "MIUI" ]];then
    uploaddir="MIUI"
else
    uploaddir="HyperOS"
fi

# 1drive
# if [[ $rom_os == "MIUI" ]]; then
#     rclone -v --config="$RCLONE_CONFIG_1DRIVE" copy "$output_file" "$ONEDRIVE_REMOTE:NTBuild/${uploaddir}/${polyxver}/${device_code}/" || {
#         upload "Error uploading file to OneDrive: $FILENAME"
#         exit 1
#     }
# else
#     rclone -v --config="$RCLONE_CONFIG_1DRIVE" copy "$output_file" "$ONEDRIVE_REMOTE:NTBuild/${uploaddir}/${polyxver}/${device_code}/" || {
#         upload "Error uploading file to OneDrive: $FILENAME"
#         exit 1
#     }
# fi  

# Google Drive
upload "Uploading to Google Drive..."
python $work_dir/upload_rom_api.py "$output_file" --folder_id "1AyblSimZU3gz9GlsA62UMuyQJFCeYGN8" --path "${uploaddir}/${polyxver}/${device_code}/" --share --link_out "$work_dir/bin/ddevice/gdrive_link.txt" || {
    upload "Error uploading file to Google Drive"
    exit 1
}

upload "Clean Workflow.."
rm -rf $work_dir/out
rm -rf $work_dir/build

upload "Build ${os_type}_${polyxver} for ${device_code} successfull!"