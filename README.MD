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

Android ROM porting can brick devices or erase data. Verify the exact device,
super partition size, boot chain and SELinux denials before flashing.
