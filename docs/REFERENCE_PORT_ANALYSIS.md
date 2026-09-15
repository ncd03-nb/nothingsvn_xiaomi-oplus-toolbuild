# Reference marble port analysis

Compared locally on 2026-09-15:

- Xiaomi target: `marble_2026-05-08` (HyperOS `OS3.0.5.0.VMRCNXM`, Android 15, China)
- OPlus donor: `CPH2841_16.0.10.500(EX01)` (Find X9 Ultra, Android 16)
- Reference output: `OppoFindX9U_ColorOS_16.0.10_MARBLE_FX3.1`

The output is not an OPlus base with Xiaomi files copied into it. Its hardware
partitions (`vendor`, `odm`, `vendor_dlkm` and firmware images) follow marble,
while the framework is taken from OPlus.

Observed composition:

1. Keep Xiaomi `vendor`, `odm`, `mi_ext`, DLKM and device firmware.
2. Replace `system`, `system_ext` and `product` with the OPlus versions.
3. Merge OPlus `my_bigball`, `my_carrier`, `my_engineering`, `my_heytap`,
   `my_manifest`, `my_product`, `my_region` and `my_stock` under `/system`.
4. Retain `my_stock` and `my_product`, but remove the reference set of optional
   and source-device applications listed in `devices/reference-port-prune.txt`.
5. Import the OPlus ODM build properties and selected framework-facing OPlus
   HALs over Xiaomi ODM. Do not replace the complete OPlus ODM because it is
   source-device-specific and about 3.9 GiB.
6. Import the merged trees from `/odm/etc/build.prop` using `/system/my_*`
   paths. The OPlus `system/build.prop` remains untouched.
7. Copy OPlus vendor `passwd` and `group`, then apply target SoC, model, camera,
   display and battery properties detected from the Xiaomi ROM.
8. Rebuild the dynamic images and validate their actual compressed total
   against the Xiaomi super group. Never delete all of `my_stock` based on its
   donor image size.

For the sample input, notification metadata must resolve to HyperOS
`OS3.0.5.0.VMRCNXM`, Android 15 / SDK 35, region China, first API 33, target
`marble`, and donor release `16.0.10.500(EX01)`.
