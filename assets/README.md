# Optional compatibility assets

Binary files from Telegram/AyuGram are intentionally not committed. Several VNDK
APEX files exceed GitHub's 100 MB file limit and their redistribution rights are
unknown. Put locally obtained files under `assets/local/` using this layout:

```text
assets/local/
├── femboyAidL/
│   ├── add_to_build.prop
│   └── odm/...
├── overlay/                 # APK overlays (contents of overlay/overlay)
├── system_ext/apex/         # com.android.vndk.v*.apex
└── vendor/                  # QTI Bluetooth compatibility libraries
```

The build applies each group only when its environment flag is enabled and its
source directory is present. Cryptoeng gets the file context shown in the supplied reference:
`u:object_r:hal_allocator_default_exec:s0`.

Use `scripts/import-ayugram-assets.ps1` on the reference Windows machine. For
GitHub Actions, attach the archive to the private asset repository's `assets-v1`
release and set a read token in `PORT_ASSETS_TOKEN`; do not commit proprietary
blobs to a public repository.
