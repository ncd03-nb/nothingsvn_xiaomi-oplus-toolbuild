from __future__ import annotations

import json
from pathlib import Path
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


class DeviceDetectionTests(unittest.TestCase):
    def run_detection(self, root: Path, metadata: Path, output: Path) -> dict[str, str]:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "detect-device.py"),
                "--root",
                str(root),
                "--payload-metadata",
                str(metadata),
                "--output",
                str(output),
            ],
            check=True,
        )
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


if __name__ == "__main__":
    unittest.main()
