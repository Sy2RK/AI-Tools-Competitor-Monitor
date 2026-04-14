"""
使用 Google YouTube Data API v3 获取 YouTube 频道视频数据
支持常规视频和 Shorts（通过 duration 判断），提供精确时间戳和完整互动数据

当 YOUTUBE_API_KEY 未配置或 API 不可用时，调用方应降级到 RapidAPI 方案
"""
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple

import requests

import env_loader  # noqa: F401  # 确保 .env 被加载


# YouTube Data API v3 基础 URL
_YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Channel ID 缓存：handle → channel_id，避免重复查询
_channel_id_cache: Dict[str, str] = {}


def _get_api_key() -> Optional[str]:
    """获取 YouTube Data API v3 的 API Key"""
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    return key if key else None


def parse_iso8601_duration(duration: str) -> int:
    """
    将 ISO 8601 duration 转为秒数
    
    Examples:
        PT45S → 45
        PT1H2M10S → 3730
        PT5M30S → 330
    """
    if not duration:
        return 0
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def is_short(duration: str) -> bool:
    """
    判断是否为 YouTube Short（时长 ≤ 60 秒）
    
    Args:
        duration: ISO 8601 duration 字符串，如 "PT45S"
    
    Returns:
        是否为 Short
    """
    return parse_iso8601_duration(duration) <= 60


def get_channel_id_by_handle(handle: str) -> Optional[str]:
    """
    通过 handle/@username 获取 YouTube channel ID
    
    使用 YouTube Data API v3 的 channels.list(forHandle=xxx) 端点
    
    Args:
        handle: YouTube handle（如 "PixVerse_Official"，可带或不带 @）
    
    Returns:
        Channel ID（如 "UCxxxxxx"），失败返回 None
    """
    api_key = _get_api_key()
    if not api_key:
        return None
    
    # 清理 handle
    handle_clean = handle.lstrip("@")
    
    # 检查缓存
    if handle_clean in _channel_id_cache:
        return _channel_id_cache[handle_clean]
    
    # 如果已经是 channel ID 格式（UC 开头，24 字符），直接返回
    if handle_clean.startswith("UC") and len(handle_clean) == 24:
        _channel_id_cache[handle_clean] = handle_clean
        return handle_clean
    
    url = f"{_YOUTUBE_API_BASE}/channels"
    params = {
        "part": "id",
        "forHandle": handle_clean,
        "key": api_key,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        items = data.get("items", [])
        if items:
            channel_id = items[0].get("id", "")
            if channel_id:
                _channel_id_cache[handle_clean] = channel_id
                print(f"  ✓ [YouTube API] Handle @{handle_clean} → Channel ID: {channel_id}")
                return channel_id
        
        # forHandle 没找到，尝试用 forUsername（兼容旧用户名）
        params2 = {
            "part": "id",
            "forUsername": handle_clean,
            "key": api_key,
        }
        resp2 = requests.get(url, params=params2, timeout=15)
        resp2.raise_for_status()
        data2 = resp2.json()
        
        items2 = data2.get("items", [])
        if items2:
            channel_id = items2[0].get("id", "")
            if channel_id:
                _channel_id_cache[handle_clean] = channel_id
                print(f"  ✓ [YouTube API] Username @{handle_clean} → Channel ID: {channel_id}")
                return channel_id
        
        print(f"  ⚠️ [YouTube API] 未找到 handle @{handle_clean} 对应的频道")
        return None
    
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response else 0
        if status == 403:
            print(f"  ❌ [YouTube API] 配额耗尽或 Key 无效 (403)")
        elif status == 400:
            print(f"  ❌ [YouTube API] 请求参数错误 (400): {handle_clean}")
        else:
            print(f"  ❌ [YouTube API] 获取 channel ID 失败: {exc}")
        return None
    except Exception as exc:
        print(f"  ❌ [YouTube API] 获取 channel ID 异常: {exc}")
        return None


def get_recent_videos(
    channel_id: str,
    days_ago: int = 1,
    max_results: int = 50
) -> List[Dict[str, Any]]:
    """
    获取频道最近发布的视频（含 Shorts）
    
    使用 search.list 端点，按发布时间排序，支持精确日期过滤
    
    Args:
        channel_id: YouTube Channel ID（UC 开头）
        days_ago: 获取多少天前的视频
        max_results: 最大返回数量
    
    Returns:
        视频列表，每个视频包含标题、时间戳、URL、互动数据等
    """
    api_key = _get_api_key()
    if not api_key:
        return []
    
    # 计算 publishedAfter 时间点
    # 语义：days_ago=N → 从 N 天前 0:00 UTC 到现在（范围过滤）
    # days_ago=0 表示今天 0:00 至今，days_ago=7 表示 7 天前 0:00 至今
    now = datetime.now(timezone.utc)
    target_day = now - timedelta(days=days_ago)
    published_after = target_day.replace(hour=0, minute=0, second=0, microsecond=0)
    published_after_iso = published_after.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    url = f"{_YOUTUBE_API_BASE}/search"
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "publishedAfter": published_after_iso,
        "maxResults": min(max_results, 50),
        "key": api_key,
    }
    
    try:
        resp = requests.get(url, params=params, timeout=20)
        
        # 检查配额耗尽
        if resp.status_code == 403:
            resp_data = {}
            try:
                resp_data = resp.json()
            except Exception:
                pass
            error_reason = ""
            errors = resp_data.get("error", {}).get("errors", [])
            if errors:
                error_reason = errors[0].get("reason", "")
            if error_reason == "quotaExceeded":
                print(f"  ❌ [YouTube API] 配额耗尽 (403 quotaExceeded)")
            else:
                print(f"  ❌ [YouTube API] 禁止访问 (403): {error_reason}")
            return []
        
        resp.raise_for_status()
        data = resp.json()
        
        items = data.get("items", [])
        if not items:
            print(f"  ℹ️ [YouTube API] 频道 {channel_id} 在最近 {days_ago} 天内无新视频")
            return []
        
        # 收集所有 video ID，批量获取详情（duration + statistics）
        video_ids = [item["id"].get("videoId", "") for item in items if item.get("id", {}).get("videoId")]
        
        video_details = {}
        if video_ids:
            video_details = get_video_details(video_ids)
        
        # 构建返回结果
        posts = []
        for item in items:
            video_id = item.get("id", {}).get("videoId", "")
            if not video_id:
                continue
            
            snippet = item.get("snippet", {})
            title = snippet.get("title", "")
            description = snippet.get("description", "")
            published_at = snippet.get("publishedAt", "")
            channel_title = snippet.get("channelTitle", "")
            
            # 缩略图
            thumbnails = snippet.get("thumbnails", {})
            media_urls = []
            # 优先取最高质量缩略图
            for quality in ["maxres", "high", "medium", "default"]:
                thumb = thumbnails.get(quality, {})
                if thumb and thumb.get("url"):
                    media_urls.append(thumb["url"])
                    break
            
            # 从详情中获取 duration 和 statistics
            details = video_details.get(video_id, {})
            duration = details.get("duration", "")
            duration_seconds = parse_iso8601_duration(duration)
            stats = details.get("statistics", {})
            
            # 格式化发布时间
            published_at_display = published_at
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                published_at_display = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            
            # 判断是否为 Short
            is_short_flag = is_short(duration) if duration else False
            
            post = {
                "text": title,
                "description": description[:500] if description else "",  # 截断过长描述
                "published_at": published_at,
                "published_at_display": published_at_display,
                "post_url": f"https://www.youtube.com/watch?v={video_id}",
                "media_urls": media_urls,
                "engagement": {
                    "view": int(stats.get("viewCount", 0)),
                    "like": int(stats.get("likeCount", 0)),
                    "comment": int(stats.get("commentCount", 0)),
                },
                "is_short": is_short_flag,
                "duration": duration,
                "duration_seconds": duration_seconds,
                "channel_title": channel_title,
                "video_id": video_id,
            }
            posts.append(post)
        
        # 分离统计
        shorts_count = sum(1 for p in posts if p.get("is_short"))
        videos_count = len(posts) - shorts_count
        print(f"  ✓ [YouTube API] 获取到 {len(posts)} 条视频（常规 {videos_count} + Shorts {shorts_count}）")
        
        return posts
    
    except Exception as exc:
        print(f"  ❌ [YouTube API] 获取视频失败: {exc}")
        return []


def get_video_details(video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    批量获取视频详情（duration + statistics）
    
    使用 videos.list 端点，每次最多 50 个 ID
    
    Args:
        video_ids: 视频 ID 列表
    
    Returns:
        {video_id: {"duration": "PT45S", "statistics": {...}}}
    """
    api_key = _get_api_key()
    if not api_key or not video_ids:
        return {}
    
    result = {}
    
    # 分批处理（每次最多 50 个）
    batch_size = 50
    for i in range(0, len(video_ids), batch_size):
        batch = video_ids[i:i + batch_size]
        
        url = f"{_YOUTUBE_API_BASE}/videos"
        params = {
            "part": "contentDetails,statistics",
            "id": ",".join(batch),
            "key": api_key,
        }
        
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            
            for item in data.get("items", []):
                vid = item.get("id", "")
                content_details = item.get("contentDetails", {})
                statistics = item.get("statistics", {})
                
                result[vid] = {
                    "duration": content_details.get("duration", ""),
                    "statistics": statistics,
                }
        
        except Exception as exc:
            print(f"  ⚠️ [YouTube API] 获取视频详情失败: {exc}")
    
    return result


def get_channel_id_with_fallback(handle: str) -> Optional[str]:
    """
    获取 Channel ID，带多种降级策略
    
    1. 优先使用 YouTube Data API v3 (forHandle)
    2. 降级使用 RapidAPI (channel/details)
    
    Args:
        handle: YouTube handle
    
    Returns:
        Channel ID 或 None
    """
    # 策略 1：官方 API
    channel_id = get_channel_id_by_handle(handle)
    if channel_id:
        return channel_id
    
    # 策略 2：RapidAPI 降级
    try:
        from scrapers.rapidapi import get_youtube_channel_id_from_handle
        channel_id = get_youtube_channel_id_from_handle(handle)
        if channel_id:
            return channel_id
    except Exception:
        pass
    
    return None


def get_video_stream_url(video_url: str, quality: str = "best") -> Optional[str]:
    """
    使用 yt-dlp 提取视频流媒体 URL（不下载文件）
    
    提取的 URL 可直接供多模态模型分析（如 GPT-4V、Gemini 等）
    
    Args:
        video_url: YouTube 视频 URL（如 https://www.youtube.com/watch?v=xxx）
        quality: 视频质量偏好
            - "best": 最高质量（默认）
            - "medium": 中等质量（720p）
            - "low": 低质量（480p，适合节省带宽）
    
    Returns:
        视频流媒体直链 URL，失败返回 None
    """
    try:
        import yt_dlp
    except ImportError:
        print(f"  ⚠️ yt-dlp 未安装，无法提取视频流 URL（pip install yt-dlp）")
        return None
    
    # 根据质量偏好设置 format 选择器
    format_selectors = {
        "best": "bestvideo+bestaudio/best",
        "medium": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "low": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    }
    format_selector = format_selectors.get(quality, format_selectors["best"])
    
    # 视频下载代理（用于访问被墙的 googlevideo.com）
    _proxy = os.getenv("VIDEO_DOWNLOAD_PROXY", "").strip()
    
    ydl_opts = {
        "format": format_selector,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # 不下载，只提取信息
    }
    
    if _proxy:
        ydl_opts["proxy"] = _proxy
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            # 优先获取直接流媒体 URL
            url = info.get("url")
            if url:
                return url
            
            # 如果是组合格式，尝试从 formats 中找
            formats = info.get("formats", [])
            if not formats:
                return None
            
            # 按质量排序，找有直接 URL 的格式
            # 优先选同时包含视频+音频的格式
            for fmt in reversed(formats):
                fmt_url = fmt.get("url")
                if not fmt_url:
                    continue
                # 检查是否同时有视频和音频
                vcodec = fmt.get("vcodec", "none")
                acodec = fmt.get("acodec", "none")
                if vcodec != "none" and acodec != "none":
                    return fmt_url
            
            # 降级：只找视频格式
            for fmt in reversed(formats):
                fmt_url = fmt.get("url")
                if not fmt_url:
                    continue
                vcodec = fmt.get("vcodec", "none")
                if vcodec != "none":
                    return fmt_url
            
            return None
    
    except Exception as exc:
        print(f"  ⚠️ [yt-dlp] 提取视频流 URL 失败: {exc}")
        return None


def enrich_posts_with_stream_urls(
    posts: List[Dict[str, Any]],
    quality: str = "low",
    max_posts: int = 5
) -> List[Dict[str, Any]]:
    """
    为帖子列表批量添加视频流媒体 URL
    
    使用 yt-dlp 提取直链，供多模态模型分析。
    为避免耗时过长，默认只处理前 max_posts 条。
    
    Args:
        posts: 视频帖子列表（来自 get_recent_videos）
        quality: 视频质量（"best"/"medium"/"low"），默认 low 节省带宽
        max_posts: 最多处理多少条帖子（避免耗时过长）
    
    Returns:
        添加了 stream_url 字段的帖子列表
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print(f"  ⚠️ yt-dlp 未安装，跳过视频流 URL 提取")
        return posts
    
    processed = 0
    for post in posts:
        if processed >= max_posts:
            break
        
        post_url = post.get("post_url", "")
        if not post_url:
            continue
        
        stream_url = get_video_stream_url(post_url, quality=quality)
        if stream_url:
            post["stream_url"] = stream_url
            processed += 1
    
    if processed > 0:
        print(f"  ✓ [yt-dlp] 为 {processed}/{min(len(posts), max_posts)} 条视频提取了流媒体 URL")
    
    return posts


def is_api_available() -> bool:
    """检查 YouTube Data API v3 是否可用（Key 已配置）"""
    return _get_api_key() is not None
