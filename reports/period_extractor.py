"""
竞品社媒数据提取模块 (第一部分)
从数据库中提取指定时间范围内的社媒更新动态
针对 AI 产品竞品监控，game 字段兼容旧数据（新结构下始终为 None）
"""
import json
import os
from datetime import date, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

from database.competitor_db import CompetitorDatabaseDB

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CompetitorPeriodDataExtractor:
    """从数据库提取一段时间内的社媒数据"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据提取器
        
        Args:
            db_path: 数据库文件路径，默认为 db/competitor_data.db
        """
        self.db = CompetitorDatabaseDB(db_path)
    
    def extract_data_by_period(
        self,
        start_date: date,
        end_date: date,
        companies: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        提取指定时间范围内的所有社媒数据
        
        Args:
            start_date: 开始日期（包含）
            end_date: 结束日期（包含）
            companies: 要提取的产品列表，如果为None则提取所有产品
            platforms: 要包含的平台类型列表（如 twitter, tiktok, website），为None则包含全部平台
        
        Returns:
            数据字典，格式：
            {
                "period": {
                    "start_date": "YYYY-MM-DD",
                    "end_date": "YYYY-MM-DD",
                    "days": 7
                },
                "companies": {
                    "product_name": {
                        "company": "product_name",
                        "platforms_data": [
                            {
                                "fetch_date": "YYYY-MM-DD",
                                "platform_type": "twitter",
                                "game": None,  # 兼容旧字段，新结构下始终为 None
                                "url": "...",
                                "username": "...",
                                "posts": [...],
                                "posts_count": 10,
                                "fetched_at": "..."
                            },
                            ...
                        ],
                        "platforms_summary": {
                            "twitter": {"posts_count": 10, "dates": ["2026-01-07", ...]},
                            "tiktok": {"posts_count": 5, "dates": ["2026-01-08", ...]},
                            ...
                        }
                    }
                },
                "extracted_at": "..."
            }
        """
        print(f"📊 开始提取数据: {start_date} 至 {end_date}")
        
        # 确定要提取的公司列表：优先从 config.yaml 获取，确保只处理配置中的公司
        if companies is None:
            try:
                from competitor_config import load_config_dict
                config_dict = load_config_dict()
                if config_dict and config_dict.get("competitors"):
                    companies = [c["name"] for c in config_dict["competitors"] if c.get("name")]
            except Exception:
                pass
            if not companies:
                companies = self.db.get_all_companies()
        
        if not companies:
            print("⚠️ 未找到任何公司")
            return {
                "period": {
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "days": (end_date - start_date).days + 1
                },
                "companies": {},
                "extracted_at": ""
            }
        
        print(f"✓ 找到 {len(companies)} 个产品")
        if platforms:
            print(f"✓ 平台过滤: {', '.join(platforms)}")
        companies_data = {}
        
        # 遍历每个日期
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            
            for company in companies:
                # 加载该日期的数据
                raw_data = self.db.load_raw_data(company, current_date)
                
                if not raw_data:
                    continue
                
                if company not in companies_data:
                    companies_data[company] = {
                        "company": company,
                        "platforms_data": [],
                        "platforms_summary": {}
                    }
                
                # 处理平台数据
                platforms_dict = raw_data.get("platforms", {})
                allowed_platforms = None
                if platforms is not None:
                    allowed_platforms = {p.strip().lower() for p in platforms if p}
                for platform_key, platform_info in platforms_dict.items():
                    platform_type = platform_info.get("platform_type", "")
                    game = platform_info.get("game")
                    posts = platform_info.get("posts", [])
                    posts_count = platform_info.get("posts_count", 0)
                    # 若配置了平台过滤，只保留指定平台
                    if allowed_platforms is not None and platform_type.strip().lower() not in allowed_platforms:
                        continue
                    # 只包含有帖子的平台
                    if posts_count > 0:
                        platform_data = {
                            "fetch_date": date_str,
                            "platform_type": platform_type,
                            "game": game,
                            "url": platform_info.get("url", ""),
                            "username": platform_info.get("username"),
                            "page_id": platform_info.get("page_id"),
                            "channel_id": platform_info.get("channel_id"),
                            "handle": platform_info.get("handle"),
                            "posts": posts,
                            "posts_count": posts_count,
                            "fetched_at": platform_info.get("fetched_at"),
                        }
                        
                        companies_data[company]["platforms_data"].append(platform_data)
                        
                        # 更新平台摘要
                        summary_key = f"{platform_type}_{game or 'company'}"
                        if summary_key not in companies_data[company]["platforms_summary"]:
                            companies_data[company]["platforms_summary"][summary_key] = {
                                "platform_type": platform_type,
                                "game": game,
                                "posts_count": 0,
                                "dates": []
                            }
                        
                        companies_data[company]["platforms_summary"][summary_key]["posts_count"] += posts_count
                        if date_str not in companies_data[company]["platforms_summary"][summary_key]["dates"]:
                            companies_data[company]["platforms_summary"][summary_key]["dates"].append(date_str)
            
            current_date += timedelta(days=1)
        
        result = {
            "period": {
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "days": (end_date - start_date).days + 1
            },
            "companies": companies_data,
            "extracted_at": date.today().isoformat()
        }
        
        print(f"✓ 提取完成，共 {len(companies_data)} 个产品有数据")
        for company, data in companies_data.items():
            total_posts = sum(p["posts_count"] for p in data["platforms_data"])
            print(f"  • {company}: {len(data['platforms_data'])} 个平台数据，共 {total_posts} 条帖子")
        
        return result
    
    def save_extracted_data(
        self,
        data: Dict[str, Any],
        output_path: Optional[str] = None
    ) -> str:
        """
        保存提取的数据到JSON文件
        
        Args:
            data: 提取的数据
            output_path: 输出文件路径，如果为None则自动生成
        
        Returns:
            保存的文件路径
        """
        if output_path is None:
            # 自动生成路径
            start_date = data["period"]["start_date"]
            end_date = data["period"]["end_date"]
            output_dir = os.environ.get("OUTPUT_DIR")
            if not output_dir or not os.path.exists(output_dir):
                output_dir = os.path.join(_PROJECT_ROOT, "workflows", "output")
                os.makedirs(output_dir, exist_ok=True)
            
            output_path = os.path.join(
                output_dir,
                f"competitor_extracted_data_{start_date}_to_{end_date}.json"
            )
        
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"💾 提取的数据已保存: {output_path}")
            return output_path
        except Exception as exc:
            print(f"❌ 保存数据失败: {exc}")
            raise


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="从数据库提取一段时间内的社媒数据")
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="开始日期 (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="结束日期 (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--companies",
        type=str,
        nargs="+",
        help="指定要提取的公司列表（可选，不指定则提取所有公司）"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="输出文件路径（可选，不指定则自动生成）"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="数据库文件路径（可选，默认为 db/competitor_data.db）"
    )
    
    args = parser.parse_args()
    
    # 解析日期
    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as e:
        print(f"❌ 日期格式错误: {e}")
        return 1
    
    if start_date > end_date:
        print("❌ 开始日期不能晚于结束日期")
        return 1
    
    # 创建提取器
    extractor = CompetitorPeriodDataExtractor(args.db_path)
    
    # 提取数据
    data = extractor.extract_data_by_period(
        start_date=start_date,
        end_date=end_date,
        companies=args.companies
    )
    
    # 保存数据
    output_path = extractor.save_extracted_data(data, args.output)
    
    print(f"\n✅ 数据提取完成: {output_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
