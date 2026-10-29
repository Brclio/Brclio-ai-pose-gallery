#!/usr/bin/env python3
"""Import visually reviewed built-in image_gen PNGs and merge male ledgers.

Uses Python's standard library and macOS sips for JPEG thumbnails. This helper
does not generate images, contact a network service, rebuild HTML or delete
original assets. Batch JSON is a list of {id, source_path, prompt} objects.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS = tuple("localization/male-generated-" + name + ".json"
                  for name in ("standard", "standard-tail", "upper", "expressive"))
_SPEC = importlib.util.spec_from_file_location("import_male_catalog", ROOT / "scripts/male_catalog.py")
catalog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(catalog)


def checked_path(relative):
    path = ROOT / relative
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Destination escapes the project: " + relative)
    if path.is_symlink():
        raise ValueError("Refusing a symlink destination: " + relative)
    return path


def image_info(path, relative=None):
    content = path.read_bytes()
    if path.suffix.lower() == ".png":
        valid = (content.startswith(b"\x89PNG\r\n\x1a\n")
                 and content.endswith(b"\x00\x00\x00\x00IEND\xaeB\x60\x82"))
        offset, chunks = 8, []
        while valid and offset < len(content):
            if offset + 12 > len(content):
                valid = False
                break
            size = int.from_bytes(content[offset:offset + 4], "big")
            end = offset + 12 + size
            if end > len(content):
                valid = False
                break
            kind = content[offset + 4:offset + 8]
            chunk = content[offset + 4:end - 4]
            checksum = int.from_bytes(content[end - 4:end], "big")
            if zlib.crc32(chunk) & 0xffffffff != checksum:
                valid = False
                break
            chunks.append(kind)
            if len(chunks) == 1:
                valid = (kind == b"IHDR" and size == 13
                         and int.from_bytes(content[offset + 8:offset + 12], "big") > 0
                         and int.from_bytes(content[offset + 12:offset + 16], "big") > 0)
            if kind == b"IEND" and (size != 0 or end != len(content)):
                valid = False
            offset = end
        valid = (valid and offset == len(content) and chunks.count(b"IHDR") == 1
                 and b"IDAT" in chunks and chunks[-1:] == [b"IEND"])
    else:
        valid = content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
    if not valid:
        raise ValueError("Invalid or incomplete image: " + str(path))
    result = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    return {"path": relative, **result} if relative is not None else result


def validate_entries(entries, targets):
    """Validate before publication, using the catalog's file checks as well."""
    if not isinstance(entries, list):
        raise ValueError("Ledger assets must be a list")
    indexed = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("Invalid ledger entry")
        image_id = entry["id"]
        if image_id not in targets or image_id in indexed:
            raise ValueError("Unknown or duplicate ledger ID: " + image_id)
        target = targets[image_id]
        if entry.get("reviewed") is not True:
            raise ValueError("Image has not passed visual review: " + image_id)
        if entry.get("record") != target["record"]:
            raise ValueError("Image record differs from generation plan: " + image_id)
        if ("original_source_id" not in entry
                or entry["original_source_id"] != target["original_source_id"]):
            raise ValueError("Image source reference differs from plan: " + image_id)
        if not isinstance(entry.get("prompt"), str) or not entry["prompt"].strip():
            raise ValueError("Image prompt is missing: " + image_id)
        files = entry.get("files")
        if not isinstance(files, list) or len(files) != 2 or not all(isinstance(f, dict) for f in files):
            raise ValueError("Image must register PNG and JPEG: " + image_id)
        by_path = {f.get("path"): f for f in files if isinstance(f.get("path"), str)}
        required = {target["record"][field] for field in ("原寸", "サムネ")}
        if set(by_path) != required:
            raise ValueError("Image file paths differ from plan: " + image_id)
        for relative, info in by_path.items():
            path = catalog._check_file(ROOT, info, relative)
            catalog._verify_file(path, info)
        indexed[image_id] = entry
    return indexed


def read_ledger(relative, targets):
    path = checked_path(relative)
    if not path.exists():
        return {"version": 1, "assets": []}, {}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("Unsupported ledger version: " + relative)
    return manifest, validate_entries(manifest.get("assets"), targets)


def ordered_entries(indexed, plan):
    return [indexed[item["id"]] for item in plan["entries"] if item["id"] in indexed]


def write_atomic(path, value):
    """Replace only the ledger, after all referenced files have been verified."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if path.exists() and path.read_bytes() == encoded:
        return
    with tempfile.NamedTemporaryFile(prefix=".male-ledger-", suffix=".tmp",
                                     dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(encoded)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def publish_image(staged, relative):
    """Atomically create an image; a different existing file is never replaced."""
    destination = checked_path(relative)
    staged_info = image_info(staged)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Staging is inside this project, so this is an atomic, same-volume create.
        os.link(staged, destination)
    except FileExistsError:
        if image_info(destination) != staged_info:
            raise ValueError("Refusing to overwrite a different image: " + relative)
    return {"path": relative, **staged_info}


@contextmanager
def import_lock():
    cache = checked_path(".cache")
    cache.mkdir(exist_ok=True)
    with (cache / "male-import.lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def import_batch(batch_path, ledger, plan, targets):
    if ledger not in FRAGMENTS:
        raise ValueError("--ledger must be one of: " + ", ".join(FRAGMENTS))
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if not isinstance(batch, list) or not batch:
        raise ValueError("Batch must be a nonempty list of {id, source_path, prompt}")
    manifest, indexed = read_ledger(ledger, targets)
    prepared = []
    seen = set()
    for item in batch:
        if not isinstance(item, dict):
            raise ValueError("Invalid batch item")
        image_id = item.get("id")
        if not isinstance(image_id, str) or image_id not in targets or image_id in seen:
            raise ValueError("Unknown or duplicate batch ID: " + repr(image_id))
        seen.add(image_id)
        prompt = item.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Batch image prompt is missing: " + image_id)
        if not isinstance(item.get("source_path"), str):
            raise ValueError("Batch image source_path is missing: " + image_id)
        source = Path(item["source_path"]).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != ".png":
            raise ValueError("Batch source must be an existing PNG: " + str(source))
        source_info = image_info(source)
        if image_id in indexed:
            old = indexed[image_id]
            original_info = next(f for f in old["files"] if f["path"] == old["record"]["原寸"])
            if (old["prompt"] != prompt or source_info != {
                    "bytes": original_info["bytes"], "sha256": original_info["sha256"]}):
                raise ValueError("Conflicting re-import for registered ID: " + image_id)
            continue  # Preserve timestamp and provenance on an identical retry.
        destination = checked_path(targets[image_id]["record"]["原寸"])
        if destination.exists() and image_info(destination) != source_info:
            raise ValueError("Refusing to overwrite a different image: " + str(destination))
        prepared.append((image_id, source, source_info, prompt))
    if prepared and shutil.which("sips") is None:
        raise ValueError("macOS sips is required to create JPEG thumbnails")
    with tempfile.TemporaryDirectory(prefix="male-import-", dir=checked_path(".cache")) as directory:
        staging = Path(directory)
        generated = []
        for image_id, source, source_info, prompt in prepared:
            png = staging / (image_id + ".png")
            jpg = staging / (image_id + ".jpg")
            shutil.copyfile(source, png)
            if image_info(png) != source_info:
                raise ValueError("Source PNG changed while importing: " + image_id)
            result = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85",
                                     "-Z", "400", str(png), "--out", str(jpg)],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise ValueError("Thumbnail conversion failed for " + image_id + ": " + result.stderr.strip())
            image_info(jpg)
            target = targets[image_id]
            # Check all collisions before publishing any images in this batch.
            for staged, field in ((png, "原寸"), (jpg, "サムネ")):
                existing = checked_path(target["record"][field])
                if existing.exists() and image_info(existing) != image_info(staged):
                    raise ValueError("Refusing to overwrite a different image: " + str(existing))
            generated.append((image_id, png, jpg, source, prompt))
        for image_id, png, jpg, source, prompt in generated:
            target = targets[image_id]
            indexed[image_id] = {
                "id": image_id, "original_source_id": target["original_source_id"],
                "record": target["record"],
                "files": [publish_image(png, target["record"]["原寸"]),
                          publish_image(jpg, target["record"]["サムネ"])],
                "prompt": prompt, "model": "built-in image_gen",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_source_filename": source.name, "reviewed": True,
            }
    assets = ordered_entries(indexed, plan)
    validate_entries(assets, targets)
    write_atomic(checked_path(ledger), {**manifest, "assets": assets})
    return len(prepared), len(assets)


def merge_fragments(original_records, plan, targets):
    relative = "localization/male-assets.json"
    manifest, combined = read_ledger(relative, targets)
    for fragment in FRAGMENTS:
        _, additions = read_ledger(fragment, targets)
        for image_id, entry in additions.items():
            if image_id in combined and combined[image_id] != entry:
                raise ValueError("Conflicting duplicate across ledgers: " + image_id)
            combined[image_id] = entry
    assets = ordered_entries(combined, plan)
    validate_entries(assets, targets)
    write_atomic(checked_path(relative), {**manifest, "assets": assets})
    verified = catalog.load_male_assets(ROOT, original_records, verify_files=True)
    if verified != assets:
        raise ValueError("Published male manifest differs from its validated merge")
    return len(assets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, help="JSON list of reviewed built-in output PNGs")
    parser.add_argument("--ledger", help="Project-relative male-generated-{standard,standard-tail,upper,expressive}.json path")
    parser.add_argument("--reviewed", action="store_true", help="Confirm each batch image has passed visual review")
    parser.add_argument("--merge-fragments", action="store_true", help="Merge reviewed fragment ledgers into male-assets.json")
    args = parser.parse_args()
    if not args.batch and not args.merge_fragments:
        parser.error("Provide --batch or --merge-fragments")
    if args.batch and (not args.ledger or not args.reviewed):
        parser.error("--batch requires both --ledger and --reviewed")
    if not args.batch and args.ledger:
        parser.error("--ledger requires --batch")
    try:
        original_records, _ = catalog.load_original(ROOT)
        plan = catalog.generation_plan(original_records)
        targets = {entry["id"]: entry for entry in plan["entries"]}
        with import_lock():
            if args.batch:
                added, total = import_batch(args.batch, args.ledger, plan, targets)
                print(f"Imported {added} new reviewed images; fragment contains {total} images.")
            if args.merge_fragments:
                total = merge_fragments(original_records, plan, targets)
                print(f"Merged and verified {total}/{plan['expected_image_count']} male images.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print("Import failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
