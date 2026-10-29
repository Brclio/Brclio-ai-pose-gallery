#!/usr/bin/env python3
"""Verify the local gallery against its saved source and image manifest, offline."""

import argparse
import hashlib
import importlib.util
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://ai-pose-gallery.pages.dev/"
LOCAL_CSP = ("default-src 'none'; img-src 'self' data:; "
             "style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'")
CSP_TAG = re.compile(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">')


class VerificationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.automatic = []
        self.links = []
        self.promotional_elements = []
        self.language_buttons = []
        self.language_groups = []
        self.div_groups = []
        self.translation_keys = set()
        self.list_keys = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if {"cta", "btn-oc", "chip-by"} & set(attrs.get("class", "").split()):
            self.promotional_elements.append(tag)
        for key in ("data-i18n", "data-i18n-aria"):
            if attrs.get(key):
                self.translation_keys.add(attrs[key])
        if attrs.get("data-i18n-list"):
            self.list_keys.add(attrs["data-i18n-list"])
        if tag == "div":
            group = [] if "lang-switch" in attrs.get("class", "").split() else None
            self.div_groups.append(group)
            if group is not None:
                self.language_groups.append(group)
        if tag == "button" and attrs.get("data-lang"):
            self.language_buttons.append(attrs["data-lang"])
            group = next((group for group in reversed(self.div_groups) if group is not None), None)
            if group is not None:
                group.append(attrs["data-lang"])
        for key in ("src", "srcset", "poster", "data"):
            if attrs.get(key):
                self.automatic.append(attrs[key])
        if tag == "link" and attrs.get("href"):
            self.automatic.append(attrs["href"])
        if tag == "a" and attrs.get("href", "").startswith(("http://", "https://", "//")):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "div" and self.div_groups:
            self.div_groups.pop()


def read_constant(html, name):
    match = re.search(r"\bconst\s+" + re.escape(name) + r"\s*=\s*", html)
    require(match is not None, f"未找到内嵌 JSON 常量 {name}。")
    value, _ = json.JSONDecoder().raw_decode(html[match.end():])
    return value


def read_records(html):
    return read_constant(html, "D")


def json_shape(value):
    """Compare nested keys, item counts and value types, not translated prose."""
    if isinstance(value, dict):
        return {key: json_shape(child) for key, child in value.items()}
    if isinstance(value, list):
        return [json_shape(child) for child in value]
    return type(value).__name__


def nonempty_strings(value, label):
    if isinstance(value, dict):
        for key, child in value.items():
            nonempty_strings(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            nonempty_strings(child, f"{label}[{index}]")
    else:
        require(isinstance(value, str) and bool(value.strip()), f"翻译为空或不是文本：{label}")
        require(not re.search(r"\\u[0-9a-fA-F]{4}", value), f"翻译含有未解码的 Unicode 转义文本：{label}")


def verify_translations(records):
    ui = json.loads((ROOT / "localization/ui.i18n.json").read_text(encoding="utf-8"))
    require(set(ui) == {"zh", "en", "ja"}, "UI 字典必须完整包含 zh、en、ja。")
    original_shape = json_shape(ui["ja"])
    series = {row["系統"] for row in records}
    categories = {row["分類"].strip() for row in records if row["分類"].strip()}
    angles = {row["アングル"] for row in records}
    for language, dictionary in ui.items():
        require(json_shape(dictionary) == original_shape, f"{language} 的 UI 深层键/类型/列表长度与日文不一致。")
        nonempty_strings(dictionary, language)
        for key, value in dictionary["labels"].items():
            require(set(re.findall(r"\{(\w+)\}", value)) ==
                    set(re.findall(r"\{(\w+)\}", ui["ja"]["labels"][key])),
                    f"{language} 的 UI 插值参数与原版不一致：{key}")
        for field, expected in [("lines", series), ("categories", categories), ("angles", angles)]:
            require(set(dictionary[field]) == expected, f"{language} 的 {field} 翻译未精确覆盖原始数据。")
        if language == "ja":
            for field in ("lines", "categories", "angles"):
                require(all(key == value for key, value in dictionary[field].items()),
                        f"日文 {field} 名称与原始数据不一致。")
        require(len(dictionary["usage"]) == 4 and len(dictionary["notes"]) == 5,
                f"{language} 的使用提示或注意事项条数不完整。")

    poses = {}
    for filename in ("poses-full.i18n.json", "poses-upper-pair.i18n.json"):
        part = json.loads((ROOT / "localization" / filename).read_text(encoding="utf-8"))
        require(not (set(poses) & set(part)), "姿势翻译文件之间存在重复键。")
        poses.update(part)
    expected = {row["系統"] + "|" + row["ポーズ番号"] for row in records}
    require(set(poses) == expected, "姿势翻译存在缺失或多余条目。")
    for key, translations in poses.items():
        require(set(translations) == {"zh", "en"}, f"姿势未完整提供中文和英文：{key}")
        nonempty_strings(translations, key)
        for language, value in translations.items():
            require(not re.search(r"[\u3040-\u30ff]", value), f"姿势译文残留日文假名：{language}/{key}")
        require(not re.search(r"[\u3400-\u9fff]", translations["en"]), f"英文姿势译文残留中日韩文字：{key}")
    print(f"✓ 三语 UI、系列、分类、角度及全部 {len(poses):,} 个姿势的中英文翻译覆盖完整。")
    return ui, poses


def safe_path(value):
    require(isinstance(value, str), "图片路径不是字符串。")
    path = PurePosixPath(value)
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in value and path.parts[0] in ("thumbs", "img")
            and path.suffix in (".jpg", ".png"), f"非法图片路径：{value}")
    resolved = (ROOT / value).resolve()
    require(resolved.is_relative_to(ROOT.resolve()), f"图片路径超出项目目录：{value}")
    return resolved


def load_catalog_module():
    spec = importlib.util.spec_from_file_location("male_catalog_verify", ROOT / "scripts/male_catalog.py")
    require(spec is not None and spec.loader is not None, "无法加载男性素材目录校验模块。")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_male_catalog(local, original_records, original_meta, source_ui, source_translations):
    """Validate additions separately; no original record or translation may change."""
    catalog = load_catalog_module()
    plan = catalog.generation_plan(original_records)
    saved_plan = json.loads((ROOT / "localization/male-generation-plan.json").read_text(encoding="utf-8"))
    require(saved_plan == plan, "男性生成计划与原站全部单人姿势不一致。")
    require(plan["pose_count"] == 233 and plan["expected_image_count"] == 1165,
            "男性生成计划必须覆盖全部 233 个单人姿势及五个角度。")
    targets = {entry["id"]: entry for entry in plan["entries"]}
    require(len(targets) == 1165, "男性生成计划有重复图片 ID。")
    entries = catalog.load_male_assets(ROOT, original_records, verify_files=False)
    expected_records = original_records + [entry["record"] for entry in entries]
    require(read_records(local) == expected_records, "本地图库并非原站记录原样保留后追加已登记男性素材。")

    active = {entry["record"]["系統"] for entry in entries}
    expected_meta = {**original_meta, "lines": list(original_meta["lines"])}
    expected_ui = json.loads(json.dumps(source_ui))
    expected_translations = dict(source_translations)
    for details in catalog.SERIES.values():
        key = details["key"]
        if key not in active:
            continue
        expected_meta["lines"].append(key)
        for language in ("zh", "en", "ja"):
            expected_ui[language]["lines"][key] = key if language == "ja" else details[language]
    for entry in entries:
        row = entry["record"]
        target = targets[entry["id"]]
        require(entry.get("reviewed") is True, f"男性图片尚未确认通过视觉检查：{entry['id']}")
        require(row == target["record"], f"男性素材元数据不符合对应原始姿势：{entry['id']}")
        require(entry["original_source_id"] == target["original_source_id"],
                f"男性素材源图片对应关系不一致：{entry['id']}")
        key = row["系統"] + "|" + row["ポーズ番号"]
        expected_translations[key] = source_translations[target["source_pose_key"]]
    require(read_constant(local, "META") == expected_meta, "原站元数据或新增男性系列顺序不一致。")
    require(read_constant(local, "UI") == expected_ui,
            "内嵌 UI 文案必须保留全部原有译文，仅追加已登记男性系列名称。")
    require(read_constant(local, "POSE_I18N") == expected_translations,
            "内嵌姿势译文必须保留原文并完整覆盖已登记男性姿势。")
    print(f"✓ 男性系列已登记 {len(entries):,}/1,165 张；原有全部文案和图库记录保持不变。")
    return entries, targets


def verify_page():
    original_bytes = (ROOT / "localization/original.html").read_bytes()
    local_bytes = (ROOT / "index.html").read_bytes()
    original = original_bytes.decode("utf-8")
    local = local_bytes.decode("utf-8")
    source_info = json.loads((ROOT / "localization/source.json").read_text(encoding="utf-8"))
    require(source_info["url"] == SOURCE_URL, "保存的源站 URL 不一致。")
    require(hashlib.sha256(original_bytes).hexdigest() == source_info["original_sha256"],
            "原站 HTML 的 SHA-256 与来源记录不一致。")
    require(hashlib.sha256(local_bytes).hexdigest() == source_info["local_sha256"],
            "本地 HTML 的 SHA-256 与来源记录不一致。")

    require(len(CSP_TAG.findall(original)) == 1, "原站 CSP 数量异常。")
    require(len(CSP_TAG.findall(local)) == 1, "本地 CSP 数量异常。")
    expected_csp = f'<meta http-equiv="Content-Security-Policy" content="{LOCAL_CSP}">'
    require(CSP_TAG.findall(local) == [expected_csp], "本地 CSP 未完全禁止后台联网。")

    spec = importlib.util.spec_from_file_location("gallery_build", ROOT / "scripts/build.py")
    require(spec is not None and spec.loader is not None, "无法加载构建脚本。")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    require(local == builder.build_html(), "index.html 与本地源文件构建结果不一致，请运行 python3 scripts/build.py。")
    require(not re.search(r"__(?:APP_SCRIPT|ORIGINAL_CSS|BRCLIO_CSS|DATA|META|UI_I18N|POSE_I18N)__", local), "页面残留未替换的构建占位符。")
    source_css = re.findall(r"<style>([\s\S]*?)</style>", original)
    local_css = re.findall(r"<style(?:\s[^>]*)?>([\s\S]*?)</style>", local)
    require(bool(source_css) and bool(local_css) and source_css[0] == local_css[0],
            "原站基础 CSS 被修改。三语补充样式应独立保存。")
    original_records = read_records(original)
    original_meta = read_constant(original, "META")
    records = read_records(local)
    require(records[:len(original_records)] == original_records, "原站图库记录被修改、删除或重新排序。")
    require(len({row["id"] for row in records}) == len(records), "图库存在重复 ID。")
    paths = {row[key] for row in records for key in ("サムネ", "原寸")}
    for path in paths:
        safe_path(path)
    poses = {(row["系統"], row["ポーズ番号"]) for row in records}

    ui, translations = verify_translations(original_records)
    male_entries, male_targets = verify_male_catalog(local, original_records, original_meta, ui, translations)
    require(source_info.get("male_generation") == {
        "planned_pose_count": 233, "planned_image_count": 1165,
        "registered_image_count": len(male_entries), "complete": len(male_entries) == 1165,
    }, "来源记录中的男性生成进度与实际登记数量不一致。")
    for panel, field in [("ipanel0", "usage"), ("ipanel1", "notes")]:
        match = re.search(r'id="' + panel + r'"[\s\S]*?<ul>(.*?)</ul>', original, re.DOTALL)
        require(match is not None, f"原站缺少 {field} 面板。")
        source_items = [unescape(re.sub(r"<[^>]+>", "", text))
                        for text in re.findall(r"<li>(.*?)</li>", match.group(1), re.DOTALL)]
        require(ui["ja"][field] == source_items, f"日文 {field} 内容与原站不一致。")

    resources = Resources()
    resources.feed(local)
    referenced_keys = resources.translation_keys | set(re.findall(r"\bt\(\s*['\"](\w+)['\"]", local))
    referenced_keys |= {"poseCount", "poseCountOne", "imageCount", "imageCountOne"}
    require(referenced_keys <= set(ui["ja"]["labels"]),
            "页面引用了缺失的 UI 文案键：" + ", ".join(sorted(referenced_keys - set(ui["ja"]["labels"]))))
    require(resources.list_keys <= {"usage", "notes"}, "页面引用了缺失的翻译列表。")
    require(not resources.automatic, "页面包含意外的自动加载资源。")
    require(bool(resources.language_groups) and
            all(sorted(group) == ["en", "ja", "zh"] for group in resources.language_groups) and
            sum(map(len, resources.language_groups)) == len(resources.language_buttons),
            "每组三语切换按钮必须完整且唯一地包含中文、英文、日文。")
    require(not resources.promotional_elements, "页面仍包含作者或社群推广区域。")
    require(not resources.links, "页面仍包含外部推广链接。")
    require(not re.search(r"@import|url\s*\(", "".join(local_css)),
            "CSS 包含额外资源依赖。")
    print("✓ 三语页面构建可复现；原站基础 CSS、图库元数据及图片记录完整保留。")
    print(f"✓ 数据：{len(poses):,} 个姿势，{len(records):,} 张图片，{len(paths):,} 个资源文件。")
    print("✓ 页首及页尾推广区与外部推广链接已移除；无自动外部资源依赖。")
    original_paths = {row[key] for row in original_records for key in ("サムネ", "原寸")}
    original_poses = {(row["系統"], row["ポーズ番号"]) for row in original_records}
    return original_records, original_poses, original_paths, male_entries, male_targets


def image_info(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        head = handle.read(16)
        require(head.startswith(b"\x89PNG\r\n\x1a\n") if path.suffix == ".png"
                else head.startswith(b"\xff\xd8\xff"), f"图片格式签名不正确：{path.name}")
        handle.seek(-12 if path.suffix == ".png" else -2, 2)
        ending = handle.read()
        require(ending == b"\x00\x00\x00\x00IEND\xaeB\x60\x82" if path.suffix == ".png"
                else ending == b"\xff\xd9", f"图片末尾不完整：{path.name}")
        handle.seek(0)
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def verify_assets(records, poses, paths):
    manifest = json.loads((ROOT / "localization/asset-manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("complete") is True and not manifest.get("failures"),
            "图片下载清单尚未完成，或包含失败项目。")
    require(manifest["source"] == SOURCE_URL, "图片来源 URL 与原站不一致。")
    for field, expected in [("record_count", len(records)), ("pose_count", len(poses)),
                            ("expected_asset_count", len(paths)), ("asset_count", len(paths))]:
        require(manifest[field] == expected, f"图片清单统计不一致：{field}")
    assets = manifest["assets"]
    require(len(assets) == len(paths) and {a["path"] for a in assets} == paths,
            "图片清单存在缺失、多余或重复路径。")
    errors = []
    total = 0
    for asset in assets:
        try:
            relative = asset["path"]
            path = safe_path(relative)
            require(path.is_file(), f"图片不存在：{relative}")
            require(asset["url"] == SOURCE_URL + relative, f"图片原始 URL 不一致：{relative}")
            size, digest = image_info(path)
            require(size == asset["bytes"], f"文件大小不一致：{relative}")
            require(digest == asset["sha256"], f"SHA-256 不一致：{relative}")
            total += size
        except (VerificationError, OSError, KeyError) as error:
            errors.append(str(error))
    require(not errors, f"{len(errors)} 个图片校验失败：\n" + "\n".join(errors[:15]))
    require(total == manifest["total_bytes"], "图片清单总字节数不一致。")
    print(f"✓ 原站全部 {len(assets):,} 个图片文件的格式、完整性、大小及 SHA-256 校验通过。")
    print(f"✓ 原站图片总大小：{total:,} 字节（{total / 1024**2:.2f} MiB）。")


def verify_male_assets(entries):
    paths = set()
    total = 0
    errors = []
    for entry in entries:
        for asset in entry["files"]:
            try:
                relative = asset["path"]
                require(relative not in paths, f"男性资源文件被重复登记：{relative}")
                paths.add(relative)
                path = safe_path(relative)
                require(path.is_file(), f"男性图片不存在：{relative}")
                size, digest = image_info(path)
                require(size == asset["bytes"], f"男性文件大小不一致：{relative}")
                require(digest == asset["sha256"], f"男性 SHA-256 不一致：{relative}")
                total += size
            except (VerificationError, OSError, KeyError) as error:
                errors.append(str(error))
    require(not errors, f"{len(errors)} 个男性资源校验失败：\n" + "\n".join(errors[:15]))
    require(len(paths) == 2 * len(entries), "每张男性图片必须登记原图和缩略图。")
    print(f"✓ 已登记男性资源 {len(paths):,} 个文件格式、大小及 SHA-256 校验通过，共 {total:,} 字节。")


def report_male_coverage(entries, targets, require_complete=False):
    actual = {entry["id"] for entry in entries}
    missing = set(targets) - actual
    require(not (actual - set(targets)), "已登记男性素材包含计划外 ID。")
    poses = {}
    for entry in entries:
        row = entry["record"]
        poses.setdefault((row["系統"], row["ポーズ番号"]), set()).add(row["アングル"])
    complete_poses = sum(len(angles) == 5 for angles in poses.values())
    if missing:
        print(f"男性全量生成尚未完成：{len(actual):,}/{len(targets):,} 张，"
              f"{complete_poses}/233 个姿势具备全部五角度；仍缺 {len(missing):,} 张。")
    else:
        require(complete_poses == 233, "男性素材角度覆盖不完整。")
        print("✓ 男性全部 233 个单人姿势、1,165 张五角度图片已齐全。")
    require(not require_complete or not missing,
            f"男性全量验收未通过：仍缺 {len(missing):,} 张，不能视为全部完成。")
    return not missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-only", action="store_true", help="仅校验页面；不代表图片完整性通过")
    parser.add_argument("--require-male-complete", action="store_true",
                        help="要求全部 233 个男性姿势、1,165 张五角度图片及其缩略图校验通过")
    args = parser.parse_args()
    if args.page_only and args.require_male_complete:
        parser.error("--require-male-complete 必须包含图片完整性校验，不能与 --page-only 同用")
    try:
        records, poses, paths, male_entries, male_targets = verify_page()
        if args.page_only:
            print("页面校验通过（未校验图片，不能视为完整校验）。")
        else:
            verify_assets(records, poses, paths)
            verify_male_assets(male_entries)
            print("当前页面及已登记资源完整性校验通过。全程仅读取本地文件，无网络请求。")
        report_male_coverage(male_entries, male_targets, args.require_male_complete)
        return 0
    except (VerificationError, OSError, KeyError, ValueError, TypeError) as error:
        print(f"校验失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
