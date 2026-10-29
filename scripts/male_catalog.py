#!/usr/bin/env python3
"""Plan and validate additive male images without modifying the source gallery.

The plan describes all requested images. The male asset manifest contains only
completed images, never pending placeholders. Both files are project-local and
this module makes no network requests or image-generation API calls.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ANGLES = (("正面", "front"), ("上から", "high"), ("下から", "low"),
          ("横", "side"), ("斜め", "diag"))
SERIES = {
    "全身1人・セクシー系": {
        "key": "男性1人・表現系", "zh": "单人男性 · 表现类",
        "en": "Male solo · Expressive", "prefix": "male_full_sexy",
    },
    "全身1人・標準系": {
        "key": "男性1人・標準系", "zh": "单人男性 · 标准类",
        "en": "Male solo · Standard", "prefix": "male_full_single",
    },
    "上半身1人": {
        "key": "男性・上半身", "zh": "男性半身",
        "en": "Male upper body", "prefix": "male_upper80v2",
    },
}


def load_original(root=ROOT):
    """Read the immutable saved source, not an already extended build."""
    html = (Path(root) / "localization/original.html").read_text(encoding="utf-8")
    values = []
    for name in ("D", "META"):
        match = re.search(r"^const " + name + r"=(.*);$", html, re.MULTILINE)
        if match is None:
            raise ValueError("Original gallery is missing " + name)
        values.append(json.loads(match.group(1)))
    return tuple(values)


def generation_plan(original_records):
    """Map each original solo pose to five new, independent male images."""
    poses = {}
    for row in original_records:
        if row["系統"] in SERIES:
            key = (row["系統"], row["ポーズ番号"])
            pose = poses.setdefault(key, {})
            if row["アングル"] in pose:
                raise ValueError("Duplicate source pose angle: " + row["id"])
            pose[row["アングル"]] = row
    entries = []
    missing = []
    for source_series, config in SERIES.items():
        numbers = sorted(number for series, number in poses if series == source_series)
        for number in numbers:
            source_angles = poses[(source_series, number)]
            reference = source_angles.get("正面") or next(iter(source_angles.values()))
            for angle, suffix in ANGLES:
                source = source_angles.get(angle)
                ref = source or reference
                image_id = config["prefix"] + "_" + number + "_" + suffix
                record = dict(ref)
                record.update({
                    "id": image_id, "系統": config["key"], "アングル": angle,
                    "サムネ": "thumbs/" + image_id + ".jpg",
                    "原寸": "img/" + image_id + ".png",
                })
                entry = {
                    "id": image_id,
                    "original_source_id": source["id"] if source else None,
                    "reference_source_id": ref["id"],
                    "reference_path": ref["原寸"],
                    "source_pose_key": source_series + "|" + number,
                    "requires_new_angle": source is None,
                    "record": record,
                }
                entries.append(entry)
                if source is None:
                    missing.append(image_id)
    return {
        "version": 1,
        "source": "localization/original.html",
        "pose_count": len(poses),
        "expected_image_count": len(entries),
        "expected_asset_count": len(entries) * 2,
        "missing_original_angles": missing,
        "entries": entries,
    }


def _check_file(root, info, expected_path):
    if info.get("path") != expected_path:
        raise ValueError("Generated asset path differs from plan: " + expected_path)
    size = info.get("bytes")
    digest = info.get("sha256")
    if type(size) is not int or size <= 0:
        raise ValueError("Generated asset has invalid byte size: " + expected_path)
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Generated asset has invalid SHA-256: " + expected_path)
    resolved = (root / expected_path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Generated asset escapes project: " + expected_path)
    return resolved


def _verify_file(path, info):
    content = path.read_bytes()
    if path.suffix == ".png":
        valid = (content.startswith(b"\x89PNG\r\n\x1a\n")
                 and content.endswith(b"\x00\x00\x00\x00IEND\xaeB\x60\x82"))
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        if len(content) < 24 or not width or not height or width * 4 != height * 3:
            raise ValueError("Generated image must keep a 3:4 portrait canvas: " + info["path"])
    else:
        valid = content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
    if not valid:
        raise ValueError("Invalid or incomplete generated image: " + info["path"])
    if len(content) != info["bytes"] or hashlib.sha256(content).hexdigest() != info["sha256"]:
        raise ValueError("Generated image checksum mismatch: " + info["path"])


def load_male_assets(root, original_records, verify_files=True):
    """Return strictly validated completed entries in deterministic plan order.

    Unknown IDs, altered pose metadata, duplicates, unsafe paths and invalid
    provenance are errors. With verify_files=False only bytes are skipped;
    records still require their full registration metadata and checksums.
    """
    root = Path(root)
    manifest_path = root / "localization/male-assets.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("Unsupported male asset manifest version")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Male asset manifest must contain an assets list")
    plan = generation_plan(original_records)
    expected = {item["id"]: item for item in plan["entries"]}
    registered = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Male asset entry must be an object")
        image_id = asset.get("id")
        if not isinstance(image_id, str) or image_id not in expected:
            raise ValueError("Unexpected generated image ID: " + repr(image_id))
        if image_id in registered:
            raise ValueError("Duplicate generated image ID: " + image_id)
        if asset.get("reviewed") is not True:
            raise ValueError("Generated image has not passed visual review: " + image_id)
        item = expected[image_id]
        if asset.get("record") != item["record"]:
            raise ValueError("Generated pose metadata differs from plan: " + image_id)
        if "original_source_id" not in asset or asset["original_source_id"] != item["original_source_id"]:
            raise ValueError("Generated image source reference differs from plan: " + image_id)
        if not isinstance(asset.get("prompt"), str) or not asset["prompt"].strip():
            raise ValueError("Generated image prompt is missing: " + image_id)
        files = asset.get("files")
        if not isinstance(files, list) or len(files) != 2 or not all(isinstance(f, dict) for f in files):
            raise ValueError("Generated image must register original and thumbnail: " + image_id)
        by_path = {f.get("path"): f for f in files if isinstance(f.get("path"), str)}
        required_paths = {item["record"][field] for field in ("原寸", "サムネ")}
        if set(by_path) != required_paths:
            raise ValueError("Generated file set differs from plan: " + image_id)
        for relative in sorted(required_paths):
            info = by_path[relative]
            path = _check_file(root, info, relative)
            if verify_files:
                _verify_file(path, info)
        registered[image_id] = deepcopy(asset)
    return [registered[item["id"]] for item in plan["entries"] if item["id"] in registered]


def extend_catalog(root, records, meta, ui, translations):
    """Append only completed male images, leaving every source value intact."""
    entries = load_male_assets(root, records, verify_files=True)
    combined_records = deepcopy(records)
    combined_meta = deepcopy(meta)
    combined_ui = deepcopy(ui)
    combined_translations = deepcopy(translations)
    combined_records.extend(deepcopy(entry["record"]) for entry in entries)
    active_series = {entry["record"]["系統"] for entry in entries}
    for source_series, config in SERIES.items():
        if config["key"] not in active_series:
            continue
        if config["key"] in combined_meta["lines"]:
            raise ValueError("Male series collides with original series: " + config["key"])
        combined_meta["lines"].append(config["key"])
        for language in ("zh", "en", "ja"):
            combined_ui[language]["lines"][config["key"]] = config["key"] if language == "ja" else config[language]
        numbers = {entry["record"]["ポーズ番号"] for entry in entries
                   if entry["record"]["系統"] == config["key"]}
        for number in sorted(numbers):
            source_key = source_series + "|" + number
            new_key = config["key"] + "|" + number
            if new_key in combined_translations:
                raise ValueError("Male pose translation collides with source: " + new_key)
            combined_translations[new_key] = deepcopy(translations[source_key])
    return combined_records, combined_meta, combined_ui, combined_translations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-plan", action="store_true", help="Write the deterministic full generation plan")
    parser.add_argument("--verify-files", action="store_true", help="Verify bytes of all registered male image files")
    args = parser.parse_args()
    records, _ = load_original(ROOT)
    plan = generation_plan(records)
    if args.write_plan:
        (ROOT / "localization/male-generation-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entries = load_male_assets(ROOT, records, verify_files=args.verify_files)
    poses = {}
    for entry in entries:
        row = entry["record"]
        poses.setdefault((row["系統"], row["ポーズ番号"]), set()).add(row["アングル"])
    complete = sum(len(angles) == len(ANGLES) for angles in poses.values())
    print(json.dumps({"planned_poses": plan["pose_count"], "planned_images": plan["expected_image_count"],
                      "registered_images": len(entries), "complete_five_angle_poses": complete,
                      "files_verified": args.verify_files}, ensure_ascii=False))


if __name__ == "__main__":
    main()
