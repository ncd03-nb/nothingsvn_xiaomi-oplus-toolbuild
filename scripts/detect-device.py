#!/usr/bin/env python3
"""Detect Xiaomi target metadata from extracted partitions and payload metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


PRIORITY_FILES = (
    "vendor/build.prop",
    "odm/etc/build.prop",
    "odm/build.prop",
    "product/etc/build.prop",
    "product/build.prop",
    "system/system/build.prop",
    "system/build.prop",
)


def read_props(root: Path) -> dict[str, list[str]]:
    paths: list[Path] = []
    for relative in PRIORITY_FILES:
        candidate = root / relative
        if candidate.is_file():
            paths.append(candidate)
    for candidate in sorted(root.rglob("build.prop")):
        if candidate not in paths:
            paths.append(candidate)

    values: dict[str, list[str]] = {}
    for path in paths:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if value and value not in values.setdefault(key.strip(), []):
                values[key.strip()].append(value)
    return values


def choose(props: dict[str, list[str]], *keys: str) -> str:
    invalid = {"unknown", "generic", "default", "yourdevice"}
    for key in keys:
        for value in props.get(key, []):
            if value.strip().lower() not in invalid:
                return value.strip()
    return ""


def find_by_key_pattern(props: dict[str, list[str]], patterns: tuple[str, ...]) -> str:
    for key, values in props.items():
        lowered = key.lower()
        if all(token in lowered for token in patterns) and values:
            return values[0]
    return ""


def normalize_mp(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:mp)?", value, re.I)
    return f"{match.group(1)}MP" if match else ""


def detect_battery(root: Path) -> str:
    pattern = re.compile(r'<item\s+name="battery\.capacity"\s*>\s*([0-9.]+)', re.I)
    for path in root.rglob("*.xml"):
        if "power_profile" not in str(path).lower():
            continue
        match = pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return match.group(1).split(".", 1)[0]
    return ""


def group_sizes(value: Any) -> list[int]:
    found: list[int] = []
    if isinstance(value, dict):
        name = str(value.get("name", "")).lower()
        size = value.get("size", value.get("maximum_size", value.get("maximumSize")))
        if "group" in name or "dynamic" in name:
            try:
                number = int(size)
            except (TypeError, ValueError):
                number = 0
            if number > 0:
                found.append(number)
        for nested in value.values():
            found.extend(group_sizes(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(group_sizes(nested))
    return found


def detect_super_size(metadata_path: Path | None) -> tuple[str, str]:
    if not metadata_path or not metadata_path.is_file():
        return "", ""
    try:
        raw = metadata_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", ""
    try:
        sizes = group_sizes(json.loads(raw))
    except json.JSONDecodeError:
        # Legacy payload-extract format:
        #   Group 'qti_dynamic_partitions': size=123, partitions=[...]
        # Strip ANSI styling first because some builds force colored labels.
        plain = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        sizes = [
            int(value)
            for value in re.findall(r"\bGroup\s+['\"][^'\"]+['\"]:\s*size=(\d+)\b", plain)
            if int(value) > 0
        ]
    if not sizes:
        return "", ""
    group_size = max(sizes)
    # Keep the same verified 256 MiB metadata/alignment margin used by the
    # Xiaomi base builder, but derive the device-specific group from payload.
    return str(group_size + 256 * 1024 * 1024), str(group_size)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--payload-metadata", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    props = read_props(args.root)
    codename = choose(
        props,
        "ro.product.vendor.device",
        "ro.product.odm.device",
        "ro.product.device",
        "ro.build.product",
        "ro.product.system.device",
    ).lower()
    model = choose(props, "ro.product.vendor.model", "ro.product.odm.model", "ro.product.model")
    market_name = choose(
        props,
        "ro.product.marketname",
        "ro.product.vendor.marketname",
        "ro.product.odm.marketname",
        "ro.product.product.marketname",
        "ro.product.model",
    )
    soc = choose(props, "ro.soc.model", "ro.vendor.soc.model", "ro.board.platform", "ro.hardware", "ro.product.board")
    first_api = choose(props, "ro.product.first_api_level", "ro.board.first_api_level")
    android = choose(props, "ro.build.version.release", "ro.system.build.version.release")
    ab_update = choose(props, "ro.build.ab_update")
    front_camera = normalize_mp(find_by_key_pattern(props, ("camera", "front")))
    back_camera = normalize_mp(find_by_key_pattern(props, ("camera", "back")))
    screen_inches = find_by_key_pattern(props, ("screen", "inch"))
    display_density = choose(
        props,
        "ro.sf.lcd_density",
        "ro.vendor.display.lcd_density",
        "ro.product.display.lcd_density",
    )
    super_size, group_size = detect_super_size(args.payload_metadata)

    result = {
        "device_codename": codename,
        "device_model": model or codename,
        "device_name": market_name or model or codename,
        "soc_model": soc,
        "first_api_level": first_api,
        "android_version": android,
        "ab_update": ab_update,
        "front_camera_mp": front_camera,
        "back_camera_mp": back_camera,
        "screen_size_inches": screen_inches,
        "display_density": display_density,
        "battery_capacity_mah": detect_battery(args.root),
        "super_size": super_size,
        "dynamic_group_size": group_size,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
