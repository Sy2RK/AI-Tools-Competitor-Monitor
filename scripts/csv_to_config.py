#!/usr/bin/env python3
"""
将 CSV 格式的竞品社媒账号表转换为 config/config.yaml

用法:
    python scripts/csv_to_config.py --csv "竞品社媒账号 - Sheet1.csv" --output config/config.yaml
    # 或不指定输出，仅打印 YAML 到 stdout
    python scripts/csv_to_config.py --csv "竞品社媒账号 - Sheet1.csv"
"""
import argparse
import csv
import os
import sys
from typing import Any, Dict, List, Optional

import yaml


# 平台列名 → 平台类型映射
PLATFORM_COLUMN_MAP = {
    "tiktok (tk)": "tiktok",
    "tiktok": "tiktok",
    "instagram (ig)": "instagram",
    "instagram": "instagram",
    "x (twitter)": "twitter",
    "x": "twitter",
    "twitter": "twitter",
    "youtube (yt)": "youtube",
    "youtube": "youtube",
}

# 平台类型 → URL 模板
PLATFORM_URL_TEMPLATES = {
    "tiktok": "https://www.tiktok.com/@{username}",
    "instagram": "https://www.instagram.com/{username}/",
    "twitter": "https://x.com/{username}",
    "youtube": "https://www.youtube.com/@{username}",
}


def normalize_platform_type(col_name: str) -> Optional[str]:
    """将 CSV 列名标准化为平台类型"""
    lower = col_name.strip().lower()
    return PLATFORM_COLUMN_MAP.get(lower)


def parse_csv(csv_path: str) -> List[Dict[str, Any]]:
    """解析 CSV 文件，返回竞品列表"""
    products = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # 跳过空行
            app_name = row.get("App 名称", "").strip()
            if not app_name:
                continue

            product: Dict[str, Any] = {
                "name": app_name,
                "priority": "high",
                "platforms": [],
            }

            # 官网
            website = row.get("官方网址", "").strip()
            if website:
                if not website.startswith("http"):
                    website = f"https://{website}"
                product["platforms"].append({
                    "url": website,
                    "type": "website",
                    "enabled": True,
                })

            # 社媒平台
            for col_name, cell_value in row.items():
                platform_type = normalize_platform_type(col_name)
                if not platform_type:
                    continue

                username = cell_value.strip().lstrip("@")
                if not username:
                    continue

                platform_entry: Dict[str, Any] = {
                    "username": username,
                    "type": platform_type,
                    "enabled": True,
                }

                # 自动补全 URL
                url_template = PLATFORM_URL_TEMPLATES.get(platform_type)
                if url_template:
                    platform_entry["url"] = url_template.format(username=username)

                # 预留 ID 字段（首次运行时自动解析或手动填入）
                if platform_type == "tiktok":
                    platform_entry["sec_uid"] = ""
                elif platform_type == "twitter":
                    platform_entry["user_id"] = ""
                elif platform_type == "youtube":
                    platform_entry["channel_id"] = ""

                product["platforms"].append(platform_entry)

            products.append(product)

    return products


def build_config(products: List[Dict[str, Any]], existing_config: Optional[Dict] = None) -> Dict[str, Any]:
    """构建完整的 config.yaml 结构"""
    if existing_config:
        config = dict(existing_config)
    else:
        config = {}

    config["competitors"] = products
    return config


def main():
    parser = argparse.ArgumentParser(
        description="将 CSV 格式的竞品社媒账号表转换为 config/config.yaml"
    )
    parser.add_argument(
        "--csv", required=True,
        help="CSV 文件路径"
    )
    parser.add_argument(
        "--output", "-o",
        help="输出 YAML 文件路径（不指定则打印到 stdout）"
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="与现有 config.yaml 合并（保留 notification 等配置）"
    )

    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"❌ CSV 文件不存在: {args.csv}")
        sys.exit(1)

    products = parse_csv(args.csv)
    print(f"✓ 解析到 {len(products)} 个 AI 产品", file=sys.stderr)

    existing_config = None
    if args.merge and args.output:
        config_path = args.output
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    existing_config = yaml.safe_load(f) or {}
                print(f"✓ 已加载现有配置: {config_path}", file=sys.stderr)
            except Exception as exc:
                print(f"⚠️ 加载现有配置失败: {exc}", file=sys.stderr)

    config = build_config(products, existing_config)

    yaml_str = yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(yaml_str)
        print(f"✅ 已写入: {args.output}", file=sys.stderr)
    else:
        print(yaml_str)


if __name__ == "__main__":
    main()
