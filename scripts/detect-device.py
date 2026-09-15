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


def read_props(root: Path, codename: str = "") -> dict[str, list[str]]:
    paths: list[Path] = []
    if codename:
        # Xiaomi ships generic build.prop files plus SKU-specific files such as
        # marble_build.prop. The latter contain the real model and market name.
        for candidate in sorted(root.rglob(f"{codename}_build.prop")):
            if candidate.is_file():
                paths.append(candidate)
    for relative in PRIORITY_FILES:
        candidate = root / relative
        if candidate.is_file() and candidate not in paths:
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


def device_feature_files(root: Path, codename: str) -> list[Path]:
    exact = [path for path in root.rglob(f"{codename}.xml") if "device_features" in str(path).lower()]
    if exact:
        return sorted(exact)
    candidates = [path for path in root.rglob("*.xml") if "device_features" in str(path).lower()]
    return candidates if len(candidates) == 1 else []


def detect_xiaomi_features(root: Path, codename: str) -> dict[str, str]:
    result = {"front_camera_mp": "", "back_camera_mp": "", "battery_capacity_mah": ""}
    for path in device_feature_files(root, codename):
        text = path.read_text(encoding="utf-8", errors="ignore")
        battery = re.search(
            r'<(?:string|integer)\s+name="battery_capacity(?:_typ)?"\s*>\s*([0-9.]+)',
            text,
            re.I,
        )
        if battery and not result["battery_capacity_mah"]:
            result["battery_capacity_mah"] = battery.group(1).split(".", 1)[0]

        # MIUI/HyperOS describes Antutu's physical-camera override either in
        # a comment or in the adjacent ssize command.
        sizes = re.search(
            r"camera\s+id\s*0[^\r\n<]*?([0-9]+(?:\.[0-9]+)?)\s*M"
            r"[^\r\n<]*camera\s+id\s*1[^\r\n<]*?([0-9]+(?:\.[0-9]+)?)\s*M",
            text,
            re.I,
        )
        if sizes:
            result["back_camera_mp"] = normalize_mp(sizes.group(1))
            result["front_camera_mp"] = normalize_mp(sizes.group(2))
            continue

        command = re.search(
            r"0\s*,\s*ssize\s*,\s*(\d+)\s*,\s*(\d+)\s*;\s*1\s*,\s*ssize\s*,\s*(\d+)\s*,\s*(\d+)",
            text,
            re.I,
        )
        if command:
            rear_mp = round(int(command.group(1)) * int(command.group(2)) / 1_000_000)
            front_mp = round(int(command.group(3)) * int(command.group(4)) / 1_000_000)
            result["back_camera_mp"] = f"{rear_mp}MP"
            result["front_camera_mp"] = f"{front_mp}MP"
    return result


def detect_battery(root: Path) -> str:
    pattern = re.compile(r'<item\s+name="battery\.capacity"\s*>\s*([0-9.]+)', re.I)
    for path in root.rglob("*.xml"):
        if "power_profile" not in str(path).lower():
            continue
        match = pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return match.group(1).split(".", 1)[0]
    return ""


def load_device_spec(path: Path | None, codename: str) -> dict[str, str]:
    if not path or not path.is_file() or not codename:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    value = data.get(codename, {}) if isinstance(data, dict) else {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


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
    parser.add_argument(
        "--device-specs",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "devices" / "xiaomi.json",
        help="optional codename catalog for values absent from ROM runtime metadata",
    )
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
    props = read_props(args.root, codename)
    model = choose(props, "ro.product.vendor.model", "ro.product.odm.model", "ro.product.model")
    market_name = choose(
        props,
        "ro.product.marketname",
        "ro.product.vendor.marketname",
        "ro.product.odm.marketname",
        "ro.product.product.marketname",
        "ro.product.model",
    )
    explicit_soc = choose(props, "ro.soc.model", "ro.vendor.soc.model")
    soc = explicit_soc or choose(props, "ro.board.platform", "ro.hardware", "ro.product.board")
    first_api = choose(props, "ro.product.first_api_level", "ro.board.first_api_level")
    android = choose(props, "ro.build.version.release", "ro.system.build.version.release")
    ab_update = choose(props, "ro.build.ab_update")
    front_camera = normalize_mp(find_by_key_pattern(props, ("camera", "front")))
    back_camera = normalize_mp(find_by_key_pattern(props, ("camera", "back")))
    screen_inches = find_by_key_pattern(props, ("screen", "inch"))
    xiaomi_features = detect_xiaomi_features(args.root, codename)
    front_camera = front_camera or xiaomi_features["front_camera_mp"]
    back_camera = back_camera or xiaomi_features["back_camera_mp"]
    battery_capacity = detect_battery(args.root) or xiaomi_features["battery_capacity_mah"]
    device_spec = load_device_spec(args.device_specs, codename)

    # Physical marketing specs (especially panel diagonal) are not normally
    # present in Android runtime properties, so the catalog is the final source.
    if not model or model.lower() == codename:
        model = device_spec.get("device_model", "") or model
    if not market_name or market_name.lower() == codename:
        market_name = device_spec.get("device_name", "") or market_name
    if not explicit_soc:
        soc = device_spec.get("soc_model", "") or soc
    front_camera = front_camera or device_spec.get("front_camera_mp", "")
    catalog_back = device_spec.get("back_camera_mp", "")
    if not back_camera or (catalog_back.count("+") > back_camera.count("+")):
        back_camera = catalog_back or back_camera
    screen_inches = screen_inches or device_spec.get("screen_size_inches", "")
    battery_capacity = battery_capacity or device_spec.get("battery_capacity_mah", "")
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
        "battery_capacity_mah": battery_capacity,
        "super_size": super_size,
        "dynamic_group_size": group_size,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
