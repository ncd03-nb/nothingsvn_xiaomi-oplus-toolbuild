from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PropertyEditorTests(unittest.TestCase):
    def test_set_replaces_first_and_removes_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prop = Path(directory) / "build.prop"
            prop.write_text("ro.test=old\nro.keep=yes\nro.test=duplicate\n", encoding="utf-8")
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "set_prop.py"), str(prop), "ro.test", "new/value&safe"],
                check=True,
            )
            self.assertEqual(prop.read_text(encoding="utf-8"), "ro.test=new/value&safe\nro.keep=yes\n")


class FileContextsNormalizationTests(unittest.TestCase):
    def test_escapes_utf8_bytes_without_changing_ascii_regex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contexts = Path(directory) / "system_file_contexts"
            contexts.write_bytes(
                "/system/my_product/app/天气 u:object_r:system_file:s0\n"
                "/system(/.*)? u:object_r:system_file:s0\n".encode("utf-8")
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "normalize-file-contexts.py"),
                    str(contexts),
                ],
                check=True,
            )
            normalized = contexts.read_bytes()
            self.assertTrue(normalized.isascii())
            self.assertIn(b"/app/\\xe5\\xa4\\xa9\\xe6\\xb0\\x94 ", normalized)
            self.assertIn(b"/system(/.*)? u:object_r:system_file:s0", normalized)

    @unittest.skipUnless(
        (ROOT / "bin" / "Linux" / "x86_64" / "mkfs.erofs").exists()
        or shutil.which("mkfs.erofs"),
        "mkfs.erofs is Linux-only",
    )
    def test_normalized_unicode_path_is_accepted_by_mkfs_erofs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src"
            source.mkdir()
            (source / "天气").write_text("test", encoding="utf-8")
            fs_config = root / "system_fs_config"
            fs_config.write_text(
                "/ 0 0 0755\nsystem 0 0 0755\nsystem/天气 0 0 0644\n",
                encoding="utf-8",
            )
            contexts = root / "system_file_contexts"
            contexts.write_text(
                "/system(/.*)? u:object_r:system_file:s0\n"
                "/system/天气 u:object_r:system_file:s0\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "normalize-file-contexts.py"),
                    str(contexts),
                ],
                check=True,
            )
            image = root / "system.img"
            bundled_mkfs = ROOT / "bin" / "Linux" / "x86_64" / "mkfs.erofs"
            mkfs = str(bundled_mkfs) if bundled_mkfs.exists() else "mkfs.erofs"
            subprocess.run(
                [
                    mkfs,
                    "--quiet",
                    "-zlz4hc,9",
                    "--mount-point",
                    "system",
                    f"--fs-config-file={fs_config}",
                    f"--file-contexts={contexts}",
                    str(image),
                    str(source),
                ],
                check=True,
            )
            self.assertGreater(image.stat().st_size, 0)


class DeviceDetectionTests(unittest.TestCase):
    def run_detection(
        self, root: Path, metadata: Path, output: Path, device_specs: Path | None = None,
        ota_metadata: Path | None = None, rom_name: str = ""
    ) -> dict[str, str]:
        command = [
                sys.executable,
                str(ROOT / "scripts" / "detect-device.py"),
                "--root",
                str(root),
                "--payload-metadata",
                str(metadata),
                "--output",
                str(output),
            ]
        if device_specs:
            command.extend(("--device-specs", str(device_specs)))
        if ota_metadata:
            command.extend(("--ota-metadata", str(ota_metadata)))
        if rom_name:
            command.extend(("--rom-name", rom_name))
        subprocess.run(command, check=True)
        return json.loads(output.read_text(encoding="utf-8"))

    def test_detects_properties_and_payload_group_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "images"
            vendor = root / "vendor"
            vendor.mkdir(parents=True)
            (vendor / "build.prop").write_text(
                "\n".join(
                    (
                        "ro.product.vendor.device=mondrian",
                        "ro.product.vendor.model=23013RK75C",
                        "ro.product.marketname=Redmi K60",
                        "ro.soc.model=SM8475",
                        "ro.product.first_api_level=32",
                        "ro.build.version.release=15",
                        "ro.sf.lcd_density=480",
                        "ro.build.ab_update=true",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            metadata = Path(directory) / "payload.json"
            metadata.write_text(
                json.dumps(
                    {
                        "dynamic_partition_metadata": {
                            "groups": [
                                {"name": "qti_dynamic_partitions", "size": 8_000_000_000}
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            output = Path(directory) / "device.json"
            detected = self.run_detection(root, metadata, output)
            self.assertEqual(detected["device_codename"], "mondrian")
            self.assertEqual(detected["soc_model"], "SM8475")
            self.assertEqual(detected["first_api_level"], "32")
            self.assertEqual(detected["display_density"], "480")
            self.assertEqual(detected["ab_update"], "true")
            self.assertEqual(detected["dynamic_group_size"], "8000000000")
            self.assertEqual(detected["super_size"], str(8_000_000_000 + 256 * 1024 * 1024))

    def test_detects_group_size_from_legacy_text_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "images"
            vendor = root / "vendor"
            vendor.mkdir(parents=True)
            (vendor / "build.prop").write_text(
                "ro.product.vendor.device=marble\nro.product.first_api_level=33\n",
                encoding="utf-8",
            )
            metadata = Path(directory) / "payload_metadata.txt"
            metadata.write_text(
                "Dynamic Partition Metadata:\n"
                "  Group 'qti_dynamic_partitions': size=9126805504, partitions=[system, vendor]\n",
                encoding="utf-8",
            )
            detected = self.run_detection(root, metadata, Path(directory) / "device.json")
            self.assertEqual(detected["dynamic_group_size"], "9126805504")
            self.assertEqual(detected["super_size"], str(9_126_805_504 + 256 * 1024 * 1024))

    def test_detects_xiaomi_variant_features_and_catalog_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "images"
            vendor = root / "vendor"
            features = root / "product" / "etc" / "device_features"
            vendor.mkdir(parents=True)
            features.mkdir(parents=True)
            (vendor / "build.prop").write_text(
                "ro.product.vendor.device=marble\n"
                "ro.product.vendor.model=marble\n"
                "ro.board.platform=taro\n",
                encoding="utf-8",
            )
            (vendor / "marble_build.prop").write_text(
                "ro.product.vendor.device=marble\n"
                "ro.product.vendor.model=23049RAD8C\n"
                "ro.product.vendor.marketname=Redmi Note 12 Turbo\n",
                encoding="utf-8",
            )
            (features / "marble.xml").write_text(
                "<!-- camera id 0 set sensor size 64M, camera id 1 set sensor size 16M -->\n"
                '<string name="battery_capacity_typ">5000</string>\n',
                encoding="utf-8",
            )
            specs = Path(directory) / "specs.json"
            specs.write_text(
                json.dumps(
                    {
                        "marble": {
                            "soc_model": "Snapdragon 7+ Gen 2",
                            "back_camera_mp": "64MP+8MP+2MP",
                            "screen_size_inches": "6.67",
                        }
                    }
                ),
                encoding="utf-8",
            )
            metadata = Path(directory) / "missing-payload.json"
            detected = self.run_detection(
                root, metadata, Path(directory) / "device.json", device_specs=specs
            )
            self.assertEqual(detected["device_model"], "23049RAD8C")
            self.assertEqual(detected["device_name"], "Redmi Note 12 Turbo")
            self.assertEqual(detected["soc_model"], "Snapdragon 7+ Gen 2")
            self.assertEqual(detected["front_camera_mp"], "16MP")
            self.assertEqual(detected["back_camera_mp"], "64MP+8MP+2MP")
            self.assertEqual(detected["screen_size_inches"], "6.67")
            self.assertEqual(detected["battery_capacity_mah"], "5000")

    def test_detects_hyperos_release_android_sdk_and_region(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "images"
            vendor = root / "vendor"
            vendor.mkdir(parents=True)
            (vendor / "build.prop").write_text(
                "ro.product.vendor.device=marble\n"
                "ro.product.first_api_level=33\n"
                "ro.vendor.build.version.incremental=OS3.0.5.0.VMRCNXM\n"
                "ro.vendor.miui.build.region=cn\n",
                encoding="utf-8",
            )
            ota = Path(directory) / "ota_metadata.txt"
            ota.write_text("post-sdk-level=35\n", encoding="utf-8")
            detected = self.run_detection(
                root, Path(directory) / "payload.json", Path(directory) / "device.json",
                ota_metadata=ota,
                rom_name="marble-ota_full-OS3.0.5.0.VMRCNXM-user-15.0.zip",
            )
            self.assertEqual(detected["android_version"], "15")
            self.assertEqual(detected["android_sdk"], "35")
            self.assertEqual(detected["base_rom_version"], "OS3.0.5.0.VMRCNXM")
            self.assertEqual(detected["base_region"], "China")
            self.assertEqual(detected["soc_id"], "SM7475")


if __name__ == "__main__":
    unittest.main()
