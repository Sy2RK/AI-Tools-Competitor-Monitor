"""
从数据库读取竞品公司社媒配置，爬取当天的更新并保存到数据库
支持 Twitter, TikTok, Instagram, YouTube, Website
"""
import os
import sys
import json
import re
import time
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter

import env_loader  # noqa: F401

from database.competitor_db import CompetitorDatabaseDB
from competitor_config import get_competitors_from_config_yaml
from scrapers.rapidapi import (
    get_posts_from_twitter,
    get_posts_from_tiktok,
    get_posts_from_instagram,
    get_twitter_user_id_from_username,
    get_tiktok_secuid_from_username,
    extract_username_from_url,
    reset_twitter_api_stats,
    get_twitter_api_stats,
)
from scrapers.website_scraper import scrape_website_content

# 本趟每日爬虫中尝试爬取的 Twitter 账号（产品、子产品），用于日志汇总
_daily_twitter_accounts: List[Tuple[str, str]] = []


def _reset_daily_twitter_run_log() -> None:
    global _daily_twitter_accounts
    _daily_twitter_accounts = []


def _record_twitter_account_attempt(company: str, game: Optional[str]) -> None:
    _daily_twitter_accounts.append((company, game or "(公司级)"))


def scrape_twitter_platform(
    company: str,
    game: Optional[str],
    platform: Dict[str, Any],
    db: CompetitorDatabaseDB,
    days_ago: int = 0
) -> Optional[Dict[str, Any]]:
    """爬取Twitter平台数据"""
    username = platform.get("username", "")
    user_id = platform.get("user_id", "")
    url = platform.get("url", "")
    
    display_name = f"{company} - {game}" if game else company
    
    _record_twitter_account_attempt(company, game)
    
    print(f"    [Twitter] {display_name}")
    print(f"      URL: {url}")
    
    # 如果没有user_id，尝试获取
    if not user_id and username:
        print(f"      [调试] 未找到user_id，正在获取...")
        user_id = get_twitter_user_id_from_username(username)
        if user_id:
            # 可以更新数据库中的user_id（可选）
            pass
    
    identifier = user_id if user_id else username
    if not identifier:
        # 尝试从URL提取
        identifier = extract_username_from_url(url, "twitter")
        if not identifier:
            print(f"      ❌ 无法确定Twitter标识符")
            return None
    
    # 传入期望的 username，只保留该账号发的推文，避免混入转推/他人内容（如 Starlink）
    expected_username = username or (extract_username_from_url(url, "twitter") if url else None)
    
    try:
        posts = get_posts_from_twitter(
            identifier,
            days_ago=days_ago,
            count=50,
            expected_username=expected_username,
        )
        print(f"      ✓ 获取到 {len(posts)} 条推文")
        
        return {
            "platform_type": "twitter",
            "game": game,
            "url": url or f"https://x.com/{username}",
            "username": username,
            "user_id": user_id,
            "posts": posts,
            "posts_count": len(posts),
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        print(f"      ❌ Twitter爬取失败: {exc}")
        return None


def scrape_tiktok_platform(
    company: str,
    game: Optional[str],
    platform: Dict[str, Any],
    db: CompetitorDatabaseDB,
    days_ago: int = 0
) -> Optional[Dict[str, Any]]:
    """爬取TikTok平台数据"""
    username = platform.get("username", "")
    sec_uid = platform.get("sec_uid", "")
    url = platform.get("url", "")
    
    display_name = f"{company} - {game}" if game else company
    
    print(f"    [TikTok] {display_name}")
    print(f"      URL: {url}")
    
    # 如果没有sec_uid，尝试获取
    if not sec_uid and username:
        print(f"      [调试] 未找到sec_uid，正在获取...")
        sec_uid = get_tiktok_secuid_from_username(username)
        if sec_uid:
            # 可以更新数据库中的sec_uid（可选）
            pass
    
    identifier = sec_uid if sec_uid else username
    if not identifier:
        # 尝试从URL提取
        identifier = extract_username_from_url(url, "tiktok")
        if not identifier:
            print(f"      ❌ 无法确定TikTok标识符")
            return None
    
    try:
        posts = get_posts_from_tiktok(identifier, days_ago=days_ago, original_username=username)
        print(f"      ✓ 获取到 {len(posts)} 条视频")
        
        # 添加延迟，避免 API 限流（TikTok API 较严格）
        time.sleep(2)  # 每个 TikTok 请求后等待 2 秒
        
        return {
            "platform_type": "tiktok",
            "game": game,
            "url": url or f"https://www.tiktok.com/@{username}",
            "username": username,
            "sec_uid": sec_uid,
            "posts": posts,
            "posts_count": len(posts),
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        print(f"      ❌ TikTok爬取失败: {exc}")
        return None


def scrape_instagram_platform(
    company: str,
    game: Optional[str],
    platform: Dict[str, Any],
    db: CompetitorDatabaseDB,
    days_ago: int = 0
) -> Optional[Dict[str, Any]]:
    """爬取Instagram平台数据"""
    username = platform.get("username", "")
    url = platform.get("url", "")
    
    display_name = f"{company} - {game}" if game else company
    
    print(f"    [Instagram] {display_name}")
    print(f"      URL: {url}")
    
    # 如果没有username，尝试从URL提取
    if not username and url:
        username = extract_username_from_url(url, "instagram")
    
    if not username:
        print(f"      ❌ 未提供Instagram用户名")
        return None
    
    try:
        posts = get_posts_from_instagram(username, days_ago=days_ago, original_username=username)
        print(f"      ✓ 获取到 {len(posts)} 条帖子")
        
        return {
            "platform_type": "instagram",
            "game": game,
            "url": url or f"https://www.instagram.com/{username}/",
            "username": username,
            "posts": posts,
            "posts_count": len(posts),
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        print(f"      ❌ Instagram爬取失败: {exc}")
        return None


def scrape_facebook_platform(
    company: str,
    game: Optional[str],
    platform: Dict[str, Any],
    db: CompetitorDatabaseDB,
    days_ago: int = 0
) -> Optional[Dict[str, Any]]:
    """爬取Facebook平台数据"""
    from scrapers.facebook import _fetch_facebook_raw, parse_facebook_posts
    
    page_id = platform.get("page_id", "")
    url = platform.get("url", "")
    
    display_name = f"{company} - {game}" if game else company
    
    print(f"    [Facebook] {display_name}")
    print(f"      URL: {url}")
    
    if not page_id:
        print(f"      ❌ 未提供Facebook page_id")
        return None
    
    try:
        raw_json = _fetch_facebook_raw(page_id)
        if not raw_json:
            print(f"      ❌ 无法获取Facebook数据")
            return None
        
        posts = parse_facebook_posts(raw_json, max_posts=50)
        
        # 日期范围过滤：days_ago=N → 从 N 天前到现在的所有帖子
        if days_ago is not None:
            cutoff_date = date.today() - timedelta(days=days_ago)
            filtered_posts = []
            for post in posts:
                post_time_str = post.get("time", "")
                if post_time_str:
                    try:
                        if post_time_str.endswith("Z"):
                            post_dt = datetime.fromisoformat(post_time_str.replace("Z", "+00:00"))
                        else:
                            post_dt = datetime.fromisoformat(post_time_str)
                        post_date = post_dt.date()
                        
                        if post_date >= cutoff_date:
                            filtered_posts.append(post)
                    except Exception:
                        pass
            posts = filtered_posts
        
        print(f"      ✓ 获取到 {len(posts)} 条帖子")
        
        return {
            "platform_type": "facebook",
            "game": game,
            "url": url,
            "page_id": page_id,
            "posts": posts,
            "posts_count": len(posts),
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        print(f"      ❌ Facebook爬取失败: {exc}")
        return None


def scrape_youtube_platform(
    company: str,
    game: Optional[str],
    platform: Dict[str, Any],
    db: CompetitorDatabaseDB,
    days_ago: int = 0
) -> Optional[Dict[str, Any]]:
    """
    爬取YouTube平台数据（混合方案：官方 API 优先 + RapidAPI 降级）
    
    优先使用 Google YouTube Data API v3（精确时间戳 + Shorts 支持），
    当官方 API 不可用时降级到 RapidAPI（无精确时间戳，Shorts 不支持）。
    """
    username = platform.get("username", "")
    channel_id = platform.get("channel_id", "")
    url = platform.get("url", "")
    
    display_name = f"{company} - {game}" if game else company
    
    print(f"    [YouTube] {display_name}")
    print(f"      URL: {url}")
    
    identifier = channel_id if channel_id else username
    if not identifier:
        print(f"      ❌ 未提供 channel_id 或 username")
        return None
    
    posts = []
    used_api = "unknown"
    resolved_channel_id = channel_id
    
    # ===== 优先：Google YouTube Data API v3 =====
    try:
        from scrapers.youtube_official import (
            is_api_available,
            get_channel_id_by_handle,
            get_recent_videos,
        )
        
        if is_api_available():
            print(f"      🔄 使用 YouTube Data API v3（官方）")
            
            # 解析 channel ID
            if not resolved_channel_id:
                resolved_channel_id = get_channel_id_by_handle(identifier)
            
            if resolved_channel_id:
                posts = get_recent_videos(resolved_channel_id, days_ago=days_ago)
                used_api = "official"
            else:
                print(f"      ⚠️ 官方 API 无法解析 channel ID，降级到 RapidAPI")
    except ImportError:
        print(f"      ⚠️ youtube_official 模块不可用，降级到 RapidAPI")
    except Exception as exc:
        print(f"      ⚠️ 官方 API 调用失败: {exc}，降级到 RapidAPI")
    
    # ===== 降级：RapidAPI =====
    if used_api != "official":
        print(f"      🔄 使用 RapidAPI（降级模式，无精确时间戳，Shorts 不支持）")
        from scrapers.rapidapi import get_posts_from_youtube
        
        try:
            posts = get_posts_from_youtube(identifier, days_ago=days_ago)
            used_api = "rapidapi"
        except Exception as exc:
            print(f"      ❌ RapidAPI YouTube 爬取也失败: {exc}")
            return None
    
    # 使用 yt-dlp 提取视频流媒体 URL（供多模态分析）
    if posts and used_api == "official":
        try:
            from scrapers.youtube_official import enrich_posts_with_stream_urls
            posts = enrich_posts_with_stream_urls(posts, quality="low", max_posts=5)
        except ImportError:
            print(f"      ⚠️ youtube_official 模块不可用，跳过视频流 URL 提取")
        except Exception as exc:
            print(f"      ⚠️ 视频流 URL 提取失败: {exc}")
    
    # 视频AI分析：下载视频 → 多模态模型分析 → 添加 video_analysis 字段
    if posts and used_api == "official":
        try:
            from analyzers.video_ai import analyze_youtube_posts
            video_max = int(os.getenv("VIDEO_ANALYSIS_MAX_POSTS", "5"))
            print(f"      🎥 开始视频AI分析（最多 {video_max} 条）...")
            posts = analyze_youtube_posts(posts, max_posts=video_max)
            analyzed_count = sum(1 for p in posts if p.get("video_analysis"))
            print(f"      ✓ 视频AI分析完成: {analyzed_count}/{len(posts)} 条有分析结果")
        except ImportError:
            print(f"      ⚠️ video_ai 模块不可用，跳过视频AI分析")
        except Exception as exc:
            print(f"      ⚠️ 视频AI分析失败: {exc}")
    
    # 统计 Shorts 数量
    shorts_count = sum(1 for p in posts if p.get("is_short"))
    videos_count = len(posts) - shorts_count
    
    if posts:
        if used_api == "official":
            print(f"      ✓ 获取到 {len(posts)} 条视频（常规 {videos_count} + Shorts {shorts_count}）[官方 API]")
        else:
            print(f"      ✓ 获取到 {len(posts)} 条视频 [RapidAPI 降级]")
    
    return {
        "platform_type": "youtube",
        "game": game,
        "url": url or f"https://www.youtube.com/@{username}",
        "username": username,
        "channel_id": resolved_channel_id or channel_id,
        "posts": posts,
        "posts_count": len(posts),
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "api_source": used_api,
    }


def scrape_website_platform(
    company: str,
    game: Optional[str],
    platform: Dict[str, Any],
    db: CompetitorDatabaseDB,
    days_ago: int = 0
) -> Optional[Dict[str, Any]]:
    """爬取官网内容（混合方案：RSS 优先 + Jina Reader + Requests 降级）"""
    url = platform.get("url", "")
    
    display_name = f"{company} - {game}" if game else company
    
    print(f"    [Website] {display_name}")
    print(f"      URL: {url}")
    
    if not url:
        print(f"      ❌ 未提供官网 URL")
        return None
    
    try:
        # 获取上次的内容哈希（用于增量对比）
        content_hash_previous = None
        # TODO: 从数据库获取上次的 content_hash
        
        result = scrape_website_content(
            url=url,
            days_ago=days_ago,
            content_hash_previous=content_hash_previous,
        )
        
        source_type = result.get("source_type", "unknown")
        content_changed = result.get("content_changed", True)
        
        # 构建 posts 列表（统一格式）
        posts = []
        
        # RSS 条目直接作为 posts
        feed_entries = result.get("feed_entries", [])
        for entry in feed_entries:
            posts.append({
                "text": entry.get("title", ""),
                "published_at": entry.get("published_at", ""),
                "post_url": entry.get("link", ""),
                "engagement": {},
            })
        
        # Jina/Requests 结果作为单条 post
        if not feed_entries:
            content_text = ""
            if result.get("content_markdown"):
                content_text = result["content_markdown"][:2000]
            elif result.get("description"):
                content_text = result["description"]
            
            if content_text or result.get("title"):
                posts.append({
                    "text": content_text or result.get("title", ""),
                    "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "post_url": url,
                    "engagement": {},
                    "source_type": source_type,
                    "content_changed": content_changed,
                    "content_hash": result.get("content_hash", ""),
                })
        
        print(f"      ✓ 获取到 {len(posts)} 条内容（来源: {source_type}，变化: {'是' if content_changed else '否'}）")
        
        return {
            "platform_type": "website",
            "game": game,
            "url": url,
            "posts": posts,
            "posts_count": len(posts),
            "source_type": source_type,
            "content_changed": content_changed,
            "content_hash": result.get("content_hash", ""),
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except Exception as exc:
        print(f"      ❌ Website爬取失败: {exc}")
        return None


def scrape_company_platforms_from_db(
    company: str,
    db: CompetitorDatabaseDB,
    days_ago: int = 1
) -> List[Dict[str, Any]]:
    """
    从数据库读取公司配置，爬取所有平台数据
    
    Args:
        company: 公司名称
        db: 数据库实例
        days_ago: 爬取最近 N 天的数据（1表示从昨天到现在）
    
    Returns:
        平台数据列表
    """
    print(f"\n  📊 开始爬取公司: {company}")
    print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # 获取公司级平台
    company_platforms = db.get_company_platforms(
        company=company,
        game_name=None,
        enabled_only=True
    )
    
    # 兼容旧数据：获取 game_name 不为空的子产品级平台
    conn = db._get_connection()
    game_platforms = []
    try:
        cursor = conn.execute("""
            SELECT game_name, platform_type, username, url, user_id, page_id,
                   channel_id, handle, sec_uid, enabled, priority
            FROM company_platforms
            WHERE company_name = ? 
              AND game_name IS NOT NULL
              AND enabled = 1
            ORDER BY game_name, platform_type
        """, (company,))
        
        rows = cursor.fetchall()
        for row in rows:
            platform = {
                "type": row["platform_type"],
                "enabled": bool(row["enabled"]),
                "game": row["game_name"]
            }
            if row["url"]:
                platform["url"] = row["url"]
            if row["username"]:
                platform["username"] = row["username"]
            if row["user_id"]:
                platform["user_id"] = row["user_id"]
            if row["page_id"]:
                platform["page_id"] = row["page_id"]
            if row["channel_id"]:
                platform["channel_id"] = row["channel_id"]
            if row["handle"]:
                platform["handle"] = row["handle"]
            if row["sec_uid"]:
                platform["sec_uid"] = row["sec_uid"]
            game_platforms.append(platform)
    finally:
        conn.close()
    
    all_platforms = company_platforms + game_platforms
    
    if not all_platforms:
        print(f"  ⚠️ {company} 没有启用的平台")
        return []
    
    print(f"  📋 找到 {len(all_platforms)} 个启用的平台")
    
    platforms_data = []
    
    for platform in all_platforms:
        platform_type = platform.get("type", "").lower()
        game = platform.get("game")
        
        result = None
        
        if platform_type == "twitter":
            result = scrape_twitter_platform(company, game, platform, db, days_ago)
            if result:
                time.sleep(1)
        elif platform_type == "tiktok":
            result = scrape_tiktok_platform(company, game, platform, db, days_ago)
            # TikTok API 限流较严格，延迟已在函数内部处理
        elif platform_type == "instagram":
            result = scrape_instagram_platform(company, game, platform, db, days_ago)
            if result:
                time.sleep(1.5)
        elif platform_type == "youtube":
            result = scrape_youtube_platform(company, game, platform, db, days_ago)
        elif platform_type == "website":
            result = scrape_website_platform(company, game, platform, db, days_ago)
        elif platform_type == "facebook":
            result = scrape_facebook_platform(company, game, platform, db, days_ago)
        else:
            print(f"    ⚠️ 不支持的平台类型: {platform_type}")
            continue
        
        if result:
            # 只保存有数据的平台（posts_count > 0）
            posts_count = result.get("posts_count", 0)
            if posts_count > 0:
                platforms_data.append(result)
                print(f"      ✓ 已添加到数据列表（{posts_count} 条帖子）")
            else:
                print(f"      ⚠️ 无数据，跳过保存（posts_count: 0）")
    
    print(f"\n  ✓ {company} 爬取完成，共 {len(platforms_data)} 个平台有数据")
    return platforms_data


def load_companies_to_database(
    data: Dict[str, Any],
    db: Optional[CompetitorDatabaseDB] = None,
    db_path: Optional[str] = None,
    source_label: str = "配置",
) -> bool:
    """
    将已解析的数据（含 competitors 列表）写入数据库。
    """
    try:
        competitors = data.get("competitors", [])
        if not competitors:
            print(f"⚠️ {source_label} 中未找到任何公司配置")
            return False

        if db is None:
            db = CompetitorDatabaseDB(db_path)

        print(f"📋 找到 {len(competitors)} 个公司配置")

        success_count = 0
        fail_count = 0

        for competitor in competitors:
            company_name = competitor.get("name", "").strip()
            if not company_name:
                continue

            priority = competitor.get("priority", "high")

            social_media_config = {
                "platforms": competitor.get("platforms", []),
                "games": competitor.get("games", []),
            }

            print(f"\n  📝 更新公司配置: {company_name}")
            success = db.save_company_social_media_config(
                company=company_name,
                priority=priority,
                social_media_config=social_media_config,
            )

            if success:
                success_count += 1
            else:
                fail_count += 1
                print(f"    ❌ {company_name} 配置更新失败")

        print("\n" + "=" * 60)
        print("✅ 配置更新完成")
        print("=" * 60)
        print(f"  成功: {success_count} 个公司")
        if fail_count > 0:
            print(f"  失败: {fail_count} 个公司")
        print("=" * 60)

        return success_count > 0

    except Exception as exc:
        print(f"❌ 从 {source_label} 加载失败: {exc}")
        import traceback
        print(f"[调试] 错误详情: {traceback.format_exc()}")
        return False


def load_companies_config_into_database(
    db: Optional[CompetitorDatabaseDB] = None,
    db_path: Optional[str] = None,
) -> bool:
    """
    从 config/config.yaml 根级 ``competitors`` 加载并更新到数据库。
    """
    competitors_yaml = get_competitors_from_config_yaml()
    if competitors_yaml:
        print("\n" + "=" * 60)
        print("📖 从 config/config.yaml（competitors）加载并更新公司配置到数据库")
        print("=" * 60)
        return load_companies_to_database(
            {"competitors": competitors_yaml},
            db=db,
            db_path=db_path,
            source_label="config.yaml",
        )

    print("⚠️ config.yaml 中无 competitors，跳过配置更新")
    return False


def scrape_all_companies_to_database(
    db_path: Optional[str] = None,
    target_date: Optional[date] = None,
    days_ago: int = 1,
    companies: Optional[List[str]] = None,
    load_config: bool = True,
) -> int:
    """
    从数据库读取所有公司配置，爬取数据并保存到数据库
    
    Args:
        db_path: 数据库路径
        target_date: 目标日期（如果指定，则使用该日期；否则使用 days_ago 计算）
        days_ago: 爬取最近 N 天的数据（1表示从昨天到现在，7表示从7天前到现在）
        companies: 指定要爬取的公司列表，如果为None则爬取所有公司
        load_config: 是否将 config.yaml 配置同步到数据库（默认: True）
    
    Returns:
        退出码（0表示成功）
    """
    print("=" * 60)
    print("🕷️ 从数据库读取配置，爬取竞品社媒数据")
    print("=" * 60)
    
    # 确定目标日期；若指定了 target_date，则用其反算 days_ago 供各平台爬虫使用
    if target_date is None:
        target_date = date.today() - timedelta(days=days_ago)
    else:
        days_ago = (date.today() - target_date).days
        if days_ago < 0:
            print(f"⚠️ 目标日期 {target_date} 在未来，已按「今天」处理")
            days_ago = 0
            target_date = date.today()
    
    print(f"📅 目标日期: {target_date} (days_ago={days_ago})")
    print()
    
    reset_twitter_api_stats()
    _reset_daily_twitter_run_log()
    
    # 初始化数据库
    db = CompetitorDatabaseDB(db_path)
    
    # 步骤 0: 从 config.yaml 加载 competitors 配置到数据库
    if load_config:
        load_companies_config_into_database(db=db, db_path=db_path)
        print()  # 空行分隔
    
    # 获取公司列表
    if companies is None:
        companies = db.get_all_companies()
    
    if not companies:
        print("⚠️ 数据库中未找到任何公司")
        return 1
    
    print(f"📋 找到 {len(companies)} 个公司")
    print()
    
    total_platforms = 0
    total_posts = 0
    success_count = 0
    fail_count = 0
    
    # 处理每个公司
    for company in companies:
        print(f"\n{'=' * 60}")
        print(f"🏢 处理公司: {company}")
        print(f"{'=' * 60}")
        
        try:
            # 爬取该公司所有平台的数据
            platforms_data = scrape_company_platforms_from_db(
                company=company,
                db=db,
                days_ago=days_ago
            )
            
            if platforms_data:
                # 保存到数据库
                print(f"\n  💾 保存数据到数据库...")
                save_success = db.save_raw_data(
                    company=company,
                    platforms_data=platforms_data,
                    fetch_date=target_date
                )
                
                if save_success:
                    company_posts = sum(p["posts_count"] for p in platforms_data)
                    total_posts += company_posts
                    total_platforms += len(platforms_data)
                    success_count += 1
                    print(f"  ✓ {company} 数据保存成功（{len(platforms_data)} 个平台，{company_posts} 条帖子）")
                else:
                    print(f"  ❌ {company} 数据保存失败")
                    fail_count += 1
            else:
                print(f"  ⚠️ {company} 没有可保存的数据")
                # 即使没有数据，也保存空数据（用于记录查询时间）
                empty_data = []
                db.save_raw_data(company, empty_data, fetch_date=target_date)
        
        except Exception as exc:
            print(f"  ❌ 处理 {company} 时出错: {exc}")
            import traceback
            print(f"  [调试] 错误详情: {traceback.format_exc()}")
            fail_count += 1
    
    # 总结
    print()
    print("=" * 60)
    print("📊 爬取总结")
    print("=" * 60)
    print(f"  处理公司数: {len(companies)}")
    print(f"  处理平台数: {total_platforms}")
    print(f"  总帖子数: {total_posts}")
    print(f"  成功: {success_count} 个公司")
    if fail_count > 0:
        print(f"  失败: {fail_count} 个公司")
    print("=" * 60)
    
    # Twitter RapidAPI 用量与本趟账号清单（写入日志便于估算月度请求量）
    tw_stats = get_twitter_api_stats()
    n_user = tw_stats.get("user_lookup", 0)
    n_pages = tw_stats.get("user_tweets_page", 0)
    n_total = n_user + n_pages
    n_accounts = len(_daily_twitter_accounts)
    print()
    print("=" * 60)
    print("🐦 Twitter RapidAPI 本趟统计（twitter241）")
    print("=" * 60)
    print(f"  GET /user（按 username 解析 user_id）: {n_user} 次")
    print(f"  GET /user-tweets（每页 1 次，含翻页与 429 换 key 重试）: {n_pages} 次")
    print(f"  本趟 Twitter HTTP 合计: {n_total} 次")
    print(f"  本趟尝试爬取的 Twitter 账号数: {n_accounts}（按 产品 - 子产品 计次如下）")
    if n_accounts == 0:
        print("    （本趟未执行任何 Twitter 爬取）")
    else:
        for (co, gm), cnt in sorted(Counter(_daily_twitter_accounts).items()):
            suffix = f" ×{cnt}" if cnt > 1 else ""
            print(f"    • {co} / {gm}{suffix}")
    print("=" * 60)
    
    return 0 if fail_count == 0 else 1


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="从数据库读取配置，爬取竞品社媒数据并保存到数据库"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="目标日期 (YYYY-MM-DD)，如果不指定则使用 --days-ago"
    )
    parser.add_argument(
        "--days-ago",
        type=int,
        default=1,
        help="爬取最近 N 天的数据（默认: 1，即从昨天到现在的范围）"
    )
    parser.add_argument(
        "--companies",
        type=str,
        nargs="+",
        help="指定要爬取的公司列表（可选，不指定则爬取所有公司）"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="数据库文件路径（可选，默认为 db/competitor_data.db）"
    )
    parser.add_argument(
        "--skip-load-config",
        action="store_true",
        help="跳过将 config.yaml 配置写入数据库",
    )
    
    args = parser.parse_args()
    
    # 解析日期
    target_date = None
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"❌ 无效的日期格式: {args.date}，请使用 YYYY-MM-DD")
            return 1
    
    # 运行爬虫
    exit_code = scrape_all_companies_to_database(
        db_path=args.db_path,
        target_date=target_date,
        days_ago=args.days_ago,
        companies=args.companies,
        load_config=not args.skip_load_config,
    )
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
