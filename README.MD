# NothingsVN Xiaomi → OPlus Toolbuild

Automated Linux pipeline for composing a ColorOS/OxygenOS framework with Xiaomi
device firmware, repacking dynamic partitions, and dispatching builds from a
Telegram bot. See [README_VI.MD](README_VI.MD) for the full Vietnamese guide.

Quick start:

```bash
sudo bash setup.sh
sudo bash build.sh <xiaomi-stock-ota> <oplus-ota> y local/repo xiaomi-oplus Builder ''
```

The build deliberately keeps Xiaomi vendor/ODM/DLKM partitions, imports OPlus
system/product/system_ext and merges `my_*` into system. Optional proprietary
compatibility blobs belong in ignored `assets/local/`; see `assets/README.md`.
GitHub Actions downloads the private `assets-v1` release using the repository
secret `PORT_ASSETS_TOKEN`, so Telegram users still provide only two ROM links.

The GitHub Actions workflow accepts only the two OTA URLs and detects device
properties plus dynamic partition sizing from the extracted Xiaomi payload.
The existing `nothingsvn-rom-bot` dispatches it with `/bp <xiaomi> -port <oplus>`.

The output name records both inputs, for example
`HyperOS_OS3.0.5.0.VMRCNXM_to_ColorOS_16.0.10.500(EX01)_marble.zip`.
To upload successful builds to Google Drive and include the public link in the
Telegram result, configure `GDRIVE_FOLDER_ID` plus either
`GOOGLE_OAUTH_CREDENTIALS_JSON` or `GOOGLE_SERVICE_ACCOUNT_JSON` as Actions
secrets. The Drive account/service account must have write access to the root
folder.

Android ROM porting can brick devices or erase data. Verify the exact device,
super partition size, boot chain and SELinux denials before flashing.
