#!/usr/bin/env python3
"""Build a self-contained, offline multilingual gallery with no dependencies."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("gallery_male_catalog", ROOT / "scripts/male_catalog.py")
male_catalog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(male_catalog)


def inline_json(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def load_catalog():
    records, meta = male_catalog.load_original(ROOT)
    translations = {}
    for name in ("poses-full.i18n.json", "poses-upper-pair.i18n.json"):
        part = json.loads((ROOT / "localization" / name).read_text(encoding="utf-8"))
        if translations.keys() & part.keys():
            raise ValueError("Duplicate pose translation keys")
        translations.update(part)
    expected = {d["系統"] + "|" + d["ポーズ番号"] for d in records}
    if set(translations) != expected:
        raise ValueError("Pose translations do not exactly cover the source gallery")
    ui = json.loads((ROOT / "localization/ui.i18n.json").read_text(encoding="utf-8"))
    return male_catalog.extend_catalog(ROOT, records, meta, ui, translations)


def build_html(catalog=None):
    records, meta, ui, translations = catalog if catalog is not None else load_catalog()
    script = (ROOT / "src/app.js").read_text(encoding="utf-8")
    for token, value in [("__DATA__", records), ("__META__", meta),
                         ("__UI_I18N__", ui), ("__POSE_I18N__", translations)]:
        if script.count(token) != 1:
            raise ValueError(f"Expected exactly one {token} placeholder")
        script = script.replace(token, inline_json(value))
    template = (ROOT / "src/template.html").read_text(encoding="utf-8")
    return (template
            .replace("__ORIGINAL_CSS__", (ROOT / "src/original.css").read_text(encoding="utf-8"))
            .replace("__BRCLIO_CSS__", (ROOT / "src/brclio.css").read_text(encoding="utf-8"))
            .replace("__APP_SCRIPT__", script))


def main():
    catalog = load_catalog()
    result = build_html(catalog)
    (ROOT / "index.html").write_text(result, encoding="utf-8")
    source_path = ROOT / "localization/source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["local_sha256"] = hashlib.sha256(result.encode()).hexdigest()
    source["changes"] = ["Removed Cloudflare Analytics and disabled external connections",
                         "Removed header and footer promotion blocks and their outbound links",
                         "Applied Brclio Design System as a separate CSS layer without changing content or interaction code",
                         "Added complete Chinese and English translations and a Chinese/English/Japanese switch",
                         "Added persistent language choice and multilingual search",
                         "Improved dialog keyboard focus and thumbnail activation"]
    male_count = sum(row["id"].startswith("male_") for row in catalog[0])
    if male_count:
        source["changes"].append("Added independently generated male solo images without modifying original records or assets")
    source["male_generation"] = {
        "planned_pose_count": 233, "planned_image_count": 1165,
        "registered_image_count": male_count,
        "complete": male_count == 1165,
    }
    source["preserved"] = ["Original CSS in first style block", "Original gallery records and image bytes",
                           "Original source snapshot and usage terms in Japanese"]
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pose_count = len({(row["系統"], row["ポーズ番号"]) for row in catalog[0]})
    print(f"Built index.html with all 3 languages, {pose_count} poses and {male_count}/1165 male images; no runtime dependencies.")


if __name__ == "__main__":
    main()
