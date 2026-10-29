#!/usr/bin/env python3
"""Mirror the image files referenced by the gallery, preserving their bytes.

Requires Python 3 and curl. Downloads are resumable by re-running the command;
valid existing files are retained, and each completed file is hashed. The
source page is only parsed, never executed.
"""

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlparse


ROOT = Path(__file__).resolve().parents[1]


def validate_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Unsafe image path: " + repr(value))
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute()
            or ".." in path.parts or "\\" in value
            or path.parts[0] not in ("thumbs", "img")
            or path.suffix.lower() not in (".jpg", ".jpeg", ".png")):
        raise ValueError("Unsafe image path: " + repr(value))
    return str(path)


def inspect_file(path):
    with path.open("rb") as file:
        file.seek(0, 2)
        length = file.tell()
        if length < 100:
            raise ValueError("Image is unexpectedly small")
        file.seek(-12, 2)
        tail = file.read()
        file.seek(0)
        head = file.read(16)
        if path.suffix.lower() == ".png":
            if not head.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid PNG signature")
            if tail != b"\x00\x00\x00\x00IEND\xaeB`\x82":
                raise ValueError("Missing PNG end marker")
        elif not head.startswith(b"\xff\xd8\xff"):
            raise ValueError("Invalid JPEG signature")
        elif tail[-2:] != b"\xff\xd9":
            raise ValueError("Missing JPEG end marker")
        file.seek(0)
        digest = hashlib.sha256()
        size = 0
        while True:
            block = file.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    if size < 100:
        raise ValueError("Image is unexpectedly small")
    return {"bytes": size, "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "index.html")
    parser.add_argument("--base-url", default="https://ai-pose-gallery.pages.dev/")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.workers <= 24:
        parser.error("--workers must be between 1 and 24")
    if urlparse(args.base_url).scheme not in ("http", "https"):
        parser.error("--base-url must be an HTTP(S) URL")

    html = args.source.read_text(encoding="utf-8")
    match = re.search(r"const D=(.*);\r?\n", html)
    if not match:
        parser.error("Could not find the gallery's const D JSON data")
    records = json.loads(match.group(1))
    paths = sorted({validate_path(row[key]) for row in records
                    for key in ("サムネ", "原寸")},
                   key=lambda value: (not value.startswith("thumbs/"), value))
    manifest_path = ROOT / "localization" / "asset-manifest.json"
    previous = {}
    if manifest_path.exists():
        previous = {item["path"]: item for item in
                    json.loads(manifest_path.read_text()).get("assets", [])}
    assets = {}
    failures = []
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def save_manifest():
        # Retain baseline checksums for not-yet-visited or failed files when a
        # resumed run is interrupted; completion only counts this run's checks.
        retained = {path: previous[path] for path in paths if path in previous}
        retained.update(assets)
        manifest = {
            "source": args.base_url,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(records),
            "pose_count": len({row["系統"] + "|" + row["ポーズ番号"] for row in records}),
            "expected_asset_count": len(paths),
            "asset_count": len(retained),
            "verified_asset_count": len(assets),
            "total_bytes": sum(item["bytes"] for item in retained.values()),
            "complete": len(assets) == len(paths) and not failures,
            "failures": failures,
            "assets": [retained[path] for path in paths if path in retained],
        }
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(manifest_path)

    def download(relative):
        destination = ROOT / relative
        # Resolve symlinks too: no path may escape the project directory.
        destination.resolve().relative_to(ROOT.resolve())
        url = args.base_url.rstrip("/") + "/" + quote(relative, safe="/")
        if destination.is_file():
            try:
                info = inspect_file(destination)
                old = previous.get(relative)
                if old and old.get("sha256") != info["sha256"]:
                    raise ValueError("Existing file differs from its recorded checksum")
                return {"path": relative, "url": url, **info}, True
            except ValueError:
                pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Keep the real extension so inspect_file can verify the file type.
        temporary = destination.with_name("." + destination.stem + ".partial" + destination.suffix)
        try:
            result = subprocess.run([
                "curl", "--fail", "--location", "--silent", "--show-error",
                "--retry", "3", "--retry-all-errors", "--retry-delay", "1", "--connect-timeout", "20",
                "--max-time", "120", "--output", str(temporary), url,
            ], capture_output=True, text=True, timeout=510)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "curl failed")
            info = inspect_file(temporary)
            old = previous.get(relative)
            if old and old.get("sha256") != info["sha256"]:
                raise ValueError("Downloaded source differs from its recorded checksum; "
                                 "original checksum retained")
            temporary.replace(destination)
            return {"path": relative, "url": url, **info}, False
        finally:
            temporary.unlink(missing_ok=True)

    print(f"Mirroring {len(paths):,} assets from {len(records):,} records with {args.workers} workers", flush=True)
    reused = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download, path): path for path in paths}
        for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
            path = futures[future]
            try:
                item, existing = future.result()
                assets[path] = item
                reused += int(existing)
            except Exception as error:
                failures.append({"path": path, "error": str(error)})
                print(f"FAILED {path}: {error}", flush=True)
            if number % 100 == 0 or number == len(paths):
                save_manifest()
                total = sum(item["bytes"] for item in assets.values())
                print(f"{number:,}/{len(paths):,} processed; {len(assets):,} valid; "
                      f"{total / 1024**2:.1f} MiB; {reused:,} reused; {len(failures)} failed", flush=True)
    save_manifest()
    print(f"Manifest: {manifest_path}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
