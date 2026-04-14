"""
使用 RapidAPI 抓取竞品社媒账号的帖子数据
支持 Instagram, TikTok, YouTube, Twitter/X 四个平台
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, parse_qs

import requests
import yaml

import env_loader  # noqa: F401  # 确保 .env 中的 RAPIDAPI_KEY 被加载


# RapidAPI 配置
# 支持多个 API Key，用分号(;)或逗号(,)分隔（自动识别全角和半角逗号）
# 例如：RAPIDAPI_KEY=key1;key2;key3 或 RAPIDAPI_KEY=key1,key2,key3 或 RAPIDAPI_KEY=key1，key2，key3
_rapidapi_keys_str = os.getenv("RAPIDAPI_KEY", "")
_rapidapi_keys = []
if _rapidapi_keys_str:
    # 将全角逗号转换为半角逗号
    normalized_str = _rapidapi_keys_str.replace("，", ",")  # 全角逗号 -> 半角逗号
    # 支持分号和逗号分隔
    if ";" in normalized_str:
        _rapidapi_keys = [k.strip() for k in normalized_str.split(";") if k.strip()]
    elif "," in normalized_str:
        _rapidapi_keys = [k.strip() for k in normalized_str.split(",") if k.strip()]
    else:
        _rapidapi_keys = [normalized_str.strip()] if normalized_str.strip() else []
    
    # 验证并清理 API keys，确保只包含 ASCII 字符
    cleaned_keys = []
    for key in _rapidapi_keys:
        # 移除任何不可见字符和空格
        cleaned_key = ''.join(c for c in key if c.isprintable() and ord(c) < 128)
        cleaned_key = cleaned_key.strip()
        if cleaned_key:
            cleaned_keys.append(cleaned_key)
    
    _rapidapi_keys = cleaned_keys
    
    # 如果清理后没有有效的 key，给出警告
    if not _rapidapi_keys and _rapidapi_keys_str.strip():
        print(f"⚠️  警告：RAPIDAPI_KEY 中包含非 ASCII 字符，已自动清理。请检查 .env 文件中的 API key 配置。")
        print(f"   原始值（前50字符）: {_rapidapi_keys_str[:50]}")

# 当前使用的 API Key 索引
_current_key_index = 0

def get_rapidapi_key() -> str:
    """获取当前可用的 RapidAPI Key（支持多个 Key 轮换）"""
    global _current_key_index
    if not _rapidapi_keys:
        return ""
    # 返回当前索引的 Key
    return _rapidapi_keys[_current_key_index % len(_rapidapi_keys)]

def switch_to_next_rapidapi_key() -> bool:
    """切换到下一个 RapidAPI Key，用于 429/403 错误时"""
    global _current_key_index
    if len(_rapidapi_keys) <= 1:
        return False  # 没有备用 Key
    _current_key_index = (_current_key_index + 1) % len(_rapidapi_keys)
    return True

def get_all_rapidapi_keys_count() -> int:
    """获取配置的 API Key 数量"""
    return len(_rapidapi_keys)


# Twitter241：实际发出的 HTTP 次数（含 429/403 换 key 后的重试），供每日爬虫日志统计用量
_twitter_api_stats: Dict[str, int] = {"user_lookup": 0, "user_tweets_page": 0}


def reset_twitter_api_stats() -> None:
    """重置 Twitter 相关 HTTP 计数（建议每日爬虫每轮任务开始时调用）。"""
    global _twitter_api_stats
    _twitter_api_stats = {"user_lookup": 0, "user_tweets_page": 0}


def get_twitter_api_stats() -> Dict[str, int]:
    """返回当前累计的 Twitter RapidAPI HTTP 次数（字典拷贝）。"""
    return dict(_twitter_api_stats)


def _twitter_stats_record_request(host: str, url: str) -> None:
    """在每次对 twitter241 成功发出 requests 后调用（与 RAPIDAPI_HOSTS['twitter'] 一致）。"""
    if host != "twitter241.p.rapidapi.com":
        return
    global _twitter_api_stats
    if "user-tweets" in url:
        _twitter_api_stats["user_tweets_page"] = _twitter_api_stats.get("user_tweets_page", 0) + 1
    elif "/user" in url and "user-tweets" not in url:
        _twitter_api_stats["user_lookup"] = _twitter_api_stats.get("user_lookup", 0) + 1


def _make_rapidapi_request(
    method: str,
    url: str,
    host: str,
    headers: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    max_retries: int = 1,
    timeout: int = 30
) -> Optional[requests.Response]:
    """
    统一的 RapidAPI 请求包装函数，自动处理 429/403 错误和 API Key 轮换
    
    Args:
        method: HTTP 方法 ('GET' 或 'POST')
        url: 请求 URL
        host: RapidAPI host（用于 headers）
        headers: 请求头（如果不提供则自动构建）
        params: GET 请求参数
        json_data: POST 请求的 JSON 数据
        max_retries: 最大重试次数（遇到 429/403 时）
        timeout: 请求超时时间
    
    Returns:
        响应对象，如果失败则返回 None
    """
    if headers is None:
        api_key = get_rapidapi_key()
        if not api_key:
            print("  ❌ 未配置 RAPIDAPI_KEY")
            return None
        
        # 确保 API key 是 ASCII 字符串（避免编码错误）
        if isinstance(api_key, str):
            # 只保留 ASCII 字符，确保可以用于 HTTP 请求头
            api_key = ''.join(c for c in api_key if ord(c) < 128).strip()
            if not api_key:
                print("  ❌ RAPIDAPI_KEY 包含无效字符")
                return None
        
        headers = {
            'x-rapidapi-key': api_key,
            'x-rapidapi-host': host
        }
        if json_data is not None:
            headers['Content-Type'] = 'application/json'
    
    # 额外检查：确保所有 headers 值都是 ASCII 字符串
    cleaned_headers = {}
    for key, value in headers.items():
        if isinstance(value, str):
            # 确保 header 值只包含 ASCII 字符
            cleaned_value = ''.join(c for c in value if ord(c) < 128).strip()
            cleaned_headers[key] = cleaned_value
        else:
            cleaned_headers[key] = value
    headers = cleaned_headers
    
    retry_count = 0
    key_switch_count = 0  # 已切换 key 的次数
    key_count = get_all_rapidapi_keys_count()
    # 429/403 时最多尝试所有可用 key；非限流错误用 max_retries
    max_key_retries = max(key_count - 1, max_retries) if key_count > 1 else max_retries
    last_response = None
    
    while retry_count <= max_key_retries:
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
            elif method.upper() == 'POST':
                response = requests.post(url, json=json_data, headers=headers, timeout=timeout)
            else:
                print(f"  ❌ 不支持的 HTTP 方法: {method}")
                return None

            # 统计 Twitter241 实际 HTTP 次数（每次 requests 算 1 次，含后续可能因 429 触发的重试）
            _twitter_stats_record_request(host, url)
            
            # 处理 429（限流）和 403（Forbidden，如订阅/权限问题）错误，尝试切换 API Key 重试
            if response.status_code in (429, 403):
                error_msg = response.text
                if response.status_code == 429:
                    print(f"  ⚠️ API 限流 (429 Too Many Requests)")
                else:
                    print(f"  ⚠️ API 拒绝 (403 Forbidden)")
                
                # 尝试切换到备用 API Key（尝试所有可用 key）
                if key_count > 1 and key_switch_count < key_count - 1:
                    print(f"  🔄 检测到多个 API Key（共 {key_count} 个），尝试切换...")
                    if switch_to_next_rapidapi_key():
                        new_key = get_rapidapi_key()
                        headers['x-rapidapi-key'] = new_key
                        key_switch_count += 1
                        print(f"  ✓ 已切换到备用 Key（索引: {_current_key_index % len(_rapidapi_keys) + 1}/{key_count}）")
                        retry_count += 1
                        continue  # 重试请求
                    else:
                        print(f"  ⚠️ 无法切换到备用 Key")
                else:
                    if key_count <= 1:
                        print(f"  💡 建议：配置多个 API Key（在 .env 中用分号分隔，如：RAPIDAPI_KEY=key1;key2;key3）")
                    else:
                        print(f"  ⚠️ 已尝试所有 {key_count} 个 API Key，均被限流/拒绝")
                
                if "quota" in error_msg.lower() or "limit" in error_msg.lower():
                    print(f"  [错误详情] {error_msg[:200]}")
                
                last_response = response
                break  # 429/403 且无法切换 key，退出循环
            
            # 非 429/403 错误，直接返回响应
            return response
            
        except requests.exceptions.HTTPError as exc:
            # 检查是否是 429/403 错误（由其他代码 raise_for_status 触发时）
            if hasattr(exc, 'response') and exc.response and exc.response.status_code in (429, 403):
                last_response = exc.response
                break
            # 其他 HTTP 错误，直接抛出
            raise
        except Exception as exc:
            # 其他异常，直接抛出
            raise
    
    # 如果所有重试都失败，返回最后的响应（通常是 429/403）
    return last_response

# 为了兼容旧代码，保留 RAPIDAPI_KEY 变量（但会在运行时动态获取）
# 注意：所有使用 RAPIDAPI_KEY 的地方都会自动使用 get_rapidapi_key() 获取当前 Key

RAPIDAPI_HOSTS = {
    "instagram": "instagram120.p.rapidapi.com",
    "tiktok": "tiktok-api23.p.rapidapi.com",
    "youtube": "youtube138.p.rapidapi.com",
    "youtube_shorts": "yt-api.p.rapidapi.com",  # YouTube Shorts 使用不同的 API
    "twitter": "twitter241.p.rapidapi.com",
    "facebook": "facebook-scraper3.p.rapidapi.com",
}

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config() -> Dict[str, Any]:
    """加载配置文件（项目根目录 config/config.yaml，或由环境变量 CONFIG_PATH 指定）。"""
    candidates = []
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        candidates.append(env_path)
    candidates.append(os.path.join(_PROJECT_ROOT, "config", "config.yaml"))
    # Docker 默认路径
    docker_path = "/app/config/config.yaml"
    if docker_path not in candidates:
        candidates.append(docker_path)

    for config_path in candidates:
        if not config_path or not os.path.exists(config_path):
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            print(f"⚠️ 读取配置失败 ({config_path}): {exc}")
            return {}
    print("⚠️ 未找到配置文件，已尝试: " + ", ".join(candidates))
    return {}


def get_competitor_accounts(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从配置文件读取竞品账号信息（AI 产品竞品监控，产品→平台 结构）"""
    competitors = cfg.get("competitor_monitor", {}).get("competitors") or cfg.get("competitors") or []
    
    if not competitors:
        section = cfg.get("competitor_monitor") or {}
        if not section.get("enable", True):
            return []
        accounts = section.get("social_accounts") or []
        norm_accounts = []
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            name = (acc.get("name") or "").strip()
            url = (acc.get("url") or "").strip()
            if not name or not url:
                continue
            platform = (acc.get("platform") or "unknown").strip()
            norm_accounts.append({
                "company": name,
                "game": None,
                "platform_type": platform,
                "url": url,
                "priority": "medium"
            })
        return norm_accounts
    
    norm_accounts = []
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        company_name = (competitor.get("name") or "").strip()
        if not company_name:
            continue
        company_priority = (competitor.get("priority") or "medium").strip().lower()
        
        # 处理产品级别的平台（原 games 层级已废弃，统一为 platforms）
        for platform in (competitor.get("platforms") or []):
            if not isinstance(platform, dict) or not platform.get("enabled", True):
                continue
            url = (platform.get("url") or "").strip()
            if not url:
                continue
            platform_type = (platform.get("type") or "unknown").strip()
            norm_accounts.append({
                "company": company_name,
                "game": None,
                "platform_type": platform_type,
                "url": url,
                "priority": company_priority
            })
    
    return norm_accounts


def extract_username_from_url(url: str, platform: str) -> Optional[str]:
    """从URL中提取用户名/ID"""
    platform_lower = platform.lower()
    
    if "instagram" in platform_lower:
        # https://www.instagram.com/username/ or https://instagram.com/username/
        match = re.search(r'instagram\.com/([^/?]+)', url)
        return match.group(1) if match else None
    
    elif "tiktok" in platform_lower:
        # https://www.tiktok.com/@username
        match = re.search(r'tiktok\.com/@([^/?]+)', url)
        return match.group(1) if match else None
    
    elif "youtube" in platform_lower:
        # https://www.youtube.com/@username or https://www.youtube.com/c/channel or https://www.youtube.com/channel/UCxxxxx
        # 也支持包含 /shorts 的情况：https://www.youtube.com/@username/shorts
        match = re.search(r'youtube\.com/(?:@|channel/|c/)([^/?]+)', url)
        if match:
            identifier = match.group(1)
            # 如果提取的标识符包含 /shorts，去掉它
            identifier = identifier.split('/')[0]
            return identifier
        return None
    
    elif "twitter" in platform_lower or "x.com" in url.lower():
        # https://x.com/username or https://twitter.com/username
        match = re.search(r'(?:twitter\.com|x\.com)/([^/?]+)', url)
        return match.group(1) if match else None
    
    return None


def get_posts_from_instagram(username: str, days_ago: int = None, original_username: str = None) -> List[Dict[str, Any]]:
    """
    使用 RapidAPI 获取 Instagram 帖子
    
    Args:
        username: Instagram 用户名
        days_ago: 相对今天的天数，如果为None则不过滤日期
        original_username: 原始用户名（用于构建post_url），如果为None则使用username
    """
    api_key = get_rapidapi_key()
    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return []
    
    host = RAPIDAPI_HOSTS["instagram"]
    url = f"https://{host}/api/instagram/posts"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host,
        'Content-Type': 'application/json'
    }
    
    payload = {"username": username, "maxId": ""}
    
    try:
        response = _make_rapidapi_request('POST', url, host, headers=headers, json_data=payload, max_retries=2, timeout=30)
        if response is None:
            return []
        response.raise_for_status()
        data = response.json()
        
        posts = []
        result = data.get("result", {})
        edges = result.get("edges", [])
        
        # 计算日期过滤范围（如果指定了days_ago）
        # 语义：days_ago=N → 从 N 天前 0:00 到现在（范围过滤，非单日过滤）
        day_start_ts = None
        day_end_ts = None
        if days_ago is not None:
            target_day = datetime.now() - timedelta(days=days_ago)
            day_start_ts = target_day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            day_end_ts = datetime.now().timestamp()  # 到现在为止
        
        for edge in edges:
            node = edge.get("node", {})
            
            # 获取时间戳（根据示例，字段名是 taken_at）
            taken_at = node.get("taken_at") or node.get("taken_at_timestamp", 0)
            if not taken_at:
                continue  # 如果没有时间戳，跳过
            
            # 日期过滤（如果指定了days_ago）
            if day_start_ts is not None and day_end_ts is not None:
                if not (day_start_ts <= taken_at <= day_end_ts):
                    continue
            
            # 提取标题/文本
            caption_node = node.get("caption", {})
            caption_text = caption_node.get("text", "") if caption_node else ""
            
            # 提取媒体URL
            media_urls = []
            
            # 图片（image_versions2.candidates）
            image_versions = node.get("image_versions2", {})
            candidates = image_versions.get("candidates", [])
            if candidates:
                # 取最高质量的图片（通常是第一个）
                for candidate in candidates:
                    img_url = candidate.get("url", "")
                    if img_url:
                        media_urls.append(img_url)
                        break  # 只取第一个
            
            # 视频（video_versions）
            video_versions = node.get("video_versions", [])
            if video_versions:
                # 取最高质量的视频（通常是第一个）
                for video in video_versions:
                    video_url = video.get("url", "")
                    if video_url:
                        media_urls.append(video_url)
                        break  # 只取第一个
            
            # 互动数据（根据示例，可能需要从不同字段获取）
            like_count = node.get("like_count") or node.get("edge_liked_by", {}).get("count", 0)
            comment_count = node.get("comment_count") or node.get("edge_media_to_comment", {}).get("count", 0)
            
            engagement = {
                "like": like_count,
                "comment": comment_count,
            }
            
            # 构建帖子URL
            code = node.get("code", "")
            post_url = f"https://www.instagram.com/p/{code}/" if code else ""
            
            # 格式化发布时间
            if taken_at:
                try:
                    published_at = datetime.fromtimestamp(taken_at)
                    published_at_iso = published_at.isoformat()
                    published_at_display = published_at.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    published_at_iso = ""
                    published_at_display = ""
            else:
                published_at_iso = ""
                published_at_display = ""
            
            post = {
                "text": caption_text,
                "published_at": published_at_iso,
                "published_at_display": published_at_display,
                "post_url": post_url,
                "media_urls": media_urls,
                "engagement": engagement,
            }
            posts.append(post)
        
        return posts
    
    except Exception as exc:
        print(f"  ❌ Instagram API 调用失败: {exc}")
        import traceback
        print(f"  [调试] 错误详情: {traceback.format_exc()}")
        return []


def get_tiktok_secuid_from_username(username: str) -> Optional[str]:
    """
    从 username (uniqueId) 获取 TikTok secUid
    使用 RapidAPI: /api/user/info?uniqueId=xxx
    """
    api_key = get_rapidapi_key()
    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return None
    
    host = RAPIDAPI_HOSTS["tiktok"]
    url = f"https://{host}/api/user/info"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    params = {"uniqueId": username}
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None:
            return None
        
        if response.status_code == 429:
            print(f"  ❌ TikTok API 调用失败: 429 Too Many Requests（所有 API Key 都已尝试）")
            return None
        
        response.raise_for_status()
        
        # 检查响应内容是否为空
        response_text = response.text.strip()
        if not response_text:
            print(f"  ❌ TikTok API 返回空响应（状态码: {response.status_code}）")
            return None
        
        # 尝试解析 JSON
        try:
            data = response.json()
        except ValueError as json_exc:
            print(f"  ❌ TikTok API 返回非 JSON 响应（状态码: {response.status_code}）")
            print(f"  [响应内容类型] {response.headers.get('Content-Type', 'unknown')}")
            print(f"  [响应内容预览] {response_text[:200]}...")
            return None
        
        # 从响应中提取 secUid
        # 响应结构: userInfo.user.secUid
        user_info = data.get("userInfo", {})
        user = user_info.get("user", {})
        sec_uid = user.get("secUid")
        
        if sec_uid:
            print(f"  ✓ 获取到 secUid: {sec_uid[:30]}... (username: {username})")
            return sec_uid
        else:
            print(f"  ⚠️ 响应中未找到 secUid，响应结构: {list(data.keys())}")
            if "userInfo" in data:
                print(f"  [调试] userInfo keys: {list(data['userInfo'].keys())}")
                if "user" in data["userInfo"]:
                    print(f"  [调试] user keys: {list(data['userInfo']['user'].keys())}")
    except requests.exceptions.HTTPError as e:
        print(f"  ❌ HTTP 错误: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                print(f"  [调试] 错误响应: {error_data}")
            except:
                print(f"  [调试] 错误响应文本: {e.response.text[:200]}")
    except Exception as e:
        print(f"  ❌ 获取 secUid 失败: {e}")
    
    return None


def get_posts_from_tiktok(username_or_secuid: str, days_ago: int = 1, original_username: str = None) -> List[Dict[str, Any]]:
    """
    使用 RapidAPI 获取 TikTok 视频
    
    Args:
        username_or_secuid: username 或 secUid
        days_ago: 日期过滤（None 表示不过滤）
        original_username: 原始 username（用于生成 post_url），如果为 None 则从 API 响应中提取
    """
    api_key = get_rapidapi_key()
    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return []
    
    host = RAPIDAPI_HOSTS["tiktok"]
    url = f"https://{host}/api/user/posts"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    # 判断传入的是 secUid（长字符串，通常以 MS4w 开头）还是 username
    # secUid 通常很长（50+ 字符），username 通常较短
    if len(username_or_secuid) > 30 and username_or_secuid.startswith("MS4w"):
        # 看起来是 secUid，直接使用
        sec_uid = username_or_secuid
        username_for_url = original_username or username_or_secuid  # 如果没有提供原始 username，使用传入值
        print(f"  [调试] 检测到 secUid，直接使用: {sec_uid[:30]}...")
    else:
        # 是 username，需要获取 secUid
        username_for_url = username_or_secuid
        print(f"  [调试] 检测到 username，正在获取 secUid: {username_or_secuid}")
        sec_uid = get_tiktok_secuid_from_username(username_or_secuid)
        if not sec_uid:
            print(f"  ⚠️ 无法获取 secUid，跳过")
            return []
    
    params = {
        "secUid": sec_uid,  # 使用 secUid 参数
        "count": 35,
        "cursor": 0
    }
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None:
            return []
        
        # 如果仍然是 429 错误，返回空列表
        if response.status_code == 429:
            print(f"  ❌ TikTok API 调用失败: 429 Too Many Requests（所有 API Key 都已尝试）")
            return []
        
        response.raise_for_status()
        
        # 检查响应内容是否为空
        response_text = response.text.strip()
        if not response_text:
            print(f"  ❌ TikTok API 返回空响应（状态码: {response.status_code}）")
            return []
        
        # 尝试解析 JSON，提供更详细的错误信息
        try:
            data = response.json()
        except ValueError as json_exc:
            # JSON 解析失败，可能是 API 返回了非 JSON 格式的响应
            print(f"  ❌ TikTok API 返回非 JSON 响应（状态码: {response.status_code}）")
            print(f"  [响应内容类型] {response.headers.get('Content-Type', 'unknown')}")
            print(f"  [响应内容预览] {response_text[:200]}...")
            
            # 尝试判断响应类型
            if response_text.startswith('<!DOCTYPE') or response_text.startswith('<html'):
                print(f"  💡 响应看起来是 HTML 页面（可能是错误页面）")
            elif response_text.startswith('{') or response_text.startswith('['):
                print(f"  💡 响应以 JSON 字符开头但解析失败，可能是格式错误")
            else:
                print(f"  💡 响应可能是纯文本错误消息")
            
            return []
        
        # 调试：打印 API 响应结构
        print(f"  [调试] TikTok API 响应状态码: {response.status_code}")
        print(f"  [调试] 响应 keys: {list(data.keys())}")
        if "data" in data:
            data_obj = data.get("data", {})
            print(f"  [调试] data keys: {list(data_obj.keys())}")
            item_list = data_obj.get("itemList", [])
            print(f"  [调试] itemList 长度: {len(item_list)}")
        else:
            print(f"  [调试] 响应数据（前500字符）: {str(data)[:500]}")
            item_list = []
        
        posts = []
        
        # 日期过滤（可选）：如果 days_ago 为 None，则不做日期过滤
        # 语义：days_ago=N → 从 N 天前 0:00 到现在（范围过滤，非单日过滤）
        day_start_ts = None
        day_end_ts = None
        if days_ago is not None:
            # 计算从 N 天前 0:00 到现在的时间戳范围（TikTok使用秒级时间戳）
            target_day = datetime.now() - timedelta(days=int(days_ago))
            day_start_ts = target_day.replace(hour=0, minute=0, second=0).timestamp()
            day_end_ts = datetime.now().timestamp()  # 到现在为止
        
        for item in item_list:
            create_time = item.get("createTime", 0)
            
            # 日期过滤（如果启用）
            if day_start_ts is not None and day_end_ts is not None:
                if not (day_start_ts <= create_time <= day_end_ts):
                    continue
            
            # 提取内容（无论是否启用日期过滤都要提取）
            contents = item.get("contents", [])
            desc = contents[0].get("desc", "") if contents else item.get("desc", "")
            
            # 提取视频URL
            media_urls = []
            video_info = item.get("video", {})
            if video_info:
                play_addr = video_info.get("bitrateInfo", [{}])[0].get("PlayAddr", {})
                url_list = play_addr.get("UrlList", [])
                if url_list:
                    media_urls.append(url_list[0])
            
            # 互动数据
            stats = item.get("stats", {})
            engagement = {
                "like": stats.get("diggCount", 0),
                "comment": stats.get("commentCount", 0),
                "share": stats.get("shareCount", 0),
                "view": stats.get("playCount", 0),
            }
            
            post = {
                "text": desc,
                "published_at": datetime.fromtimestamp(create_time).isoformat(),
                "published_at_display": datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S"),
                "post_url": f"https://www.tiktok.com/@{username_for_url}/video/{item.get('id', '')}",
                "media_urls": media_urls,
                "engagement": engagement,
            }
            posts.append(post)
        
        return posts
    
    except requests.exceptions.HTTPError as exc:
        if exc.response and exc.response.status_code == 429:
            print(f"  ⚠️ TikTok API 限流 (429 Too Many Requests)")
            print(f"  💡 请求过于频繁，请稍后重试")
        else:
            print(f"  ❌ TikTok API 调用失败: {exc}")
        return []
    except Exception as exc:
        print(f"  ❌ TikTok API 调用失败: {exc}")
        return []


def get_youtube_channel_id_from_handle(handle: str, debug: bool = False) -> Optional[str]:
    """通过 handle/@username 获取 YouTube channel ID"""
    api_key = get_rapidapi_key()

    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return None
    
    host = RAPIDAPI_HOSTS["youtube"]
    
    # 去掉 @ 符号
    handle_clean = handle.lstrip("@")
    
    # 尝试使用 channel/details 或其他可能的端点
    # 注意：这取决于 RapidAPI YouTube API 是否支持从 handle 获取 channel ID
    # 如果 API 不支持，可能需要先获取频道详情
    
    # 方法1：直接尝试用 handle 调用，看 API 是否支持
    url = f"https://{host}/channel/details/"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    params = {"handle": handle_clean}
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None or response.status_code != 200:
            if debug and response and response.status_code == 429:
                print(f"  [调试] channel/details 调用失败: 429 Too Many Requests")
            return None
        
        data = response.json()
        if debug:
            print(f"  [调试] channel/details 响应: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}...")
        # 尝试从响应中提取 channel ID
        # 这里需要根据实际 API 响应格式调整
        channel_id = data.get("channelId") or data.get("id") or data.get("channel", {}).get("id")
        if channel_id:
            print(f"  ✓ 获取到 channel ID: {channel_id} (handle: {handle_clean})")
            return channel_id
    except Exception as e:
        if debug:
            print(f"  [调试] channel/details 调用失败: {e}")
    
    # 方法2：如果上面失败，尝试直接用 handle 作为 id（某些 API 可能支持）
    # 如果 API 不支持 handle，返回 None，让调用者直接使用 handle 试试
    print(f"  ⚠️ 无法通过 API 获取 channel ID，将尝试直接使用 handle: {handle_clean}")
    return None


def get_posts_from_youtube(channel_id_or_handle: str, days_ago: int = 1) -> List[Dict[str, Any]]:
    """使用 RapidAPI 获取 YouTube 视频"""
    api_key = get_rapidapi_key()

    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return []
    
    host = RAPIDAPI_HOSTS["youtube"]
    url = f"https://{host}/channel/videos/"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    # 判断是 channel ID (UC开头，通常是24个字符) 还是 handle
    channel_id = channel_id_or_handle.lstrip("@")
    
    # Channel ID 通常是 UC 开头，24个字符
    is_channel_id = channel_id.startswith("UC") and len(channel_id) == 24
    
    if not is_channel_id:
        # 如果不是 channel ID，尝试获取
        print(f"  [YouTube] 检测到 handle/custom URL: {channel_id}")
        print(f"  [YouTube] 尝试获取对应的 channel ID...")
        resolved_id = get_youtube_channel_id_from_handle(channel_id)
        if resolved_id:
            channel_id = resolved_id
        else:
            print(f"  [YouTube] 无法获取 channel ID，直接使用 handle 尝试...")
            # 继续使用 handle，某些 API 可能支持
    
    params = {
        "id": channel_id,
        "filter": "videos_latest",
        "hl": "en",
        "gl": "US"
    }
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None:
            return []
        
        if response.status_code == 429:
            print(f"  ❌ YouTube API 调用失败: 429 Too Many Requests（所有 API Key 都已尝试）")
            return []
        
        response.raise_for_status()
        data = response.json()
        
        posts = []
        contents = data.get("contents", [])
        
        # 计算昨天
        yesterday = datetime.now() - timedelta(days=days_ago)
        yesterday_start = yesterday.replace(hour=0, minute=0, second=0)
        yesterday_end = yesterday.replace(hour=23, minute=59, second=59)
        
        for content in contents:
            published_time_text = content.get("publishedTimeText", "")
            
            # 解析时间文本（如 "13 minutes ago", "3 hours ago"）
            # 简化处理：如果包含 "hour" 或 "minute" 且数字<=24，认为是昨天
            is_yesterday = False
            if "hour" in published_time_text.lower():
                hours_match = re.search(r'(\d+)\s*hour', published_time_text)
                if hours_match:
                    hours = int(hours_match.group(1))
                    if hours <= 24:
                        is_yesterday = True
            elif "minute" in published_time_text.lower():
                is_yesterday = True  # 几分钟前肯定是最近的
            
            # 更精确：尝试从 publishedTimeText 解析完整时间
            # 这里简化处理，实际应该解析完整时间
            
            if is_yesterday or True:  # 暂时都包含，实际应该精确判断
                title = content.get("title", "")
                video_id = content.get("videoId", "")
                
                # 提取缩略图
                media_urls = []
                thumbnails = content.get("thumbnails", [])
                if thumbnails:
                    media_urls.append(thumbnails[-1].get("url", ""))
                
                # 互动数据
                stats = content.get("stats", {})
                engagement = {
                    "view": stats.get("views", 0),
                }
                
                post = {
                    "text": title,
                    "published_at_display": published_time_text,
                    "post_url": f"https://www.youtube.com/watch?v={video_id}",
                    "media_urls": media_urls,
                    "engagement": engagement,
                }
                posts.append(post)
        
        return posts
    
    except Exception as exc:
        print(f"  ❌ YouTube API 调用失败: {exc}")
        return []


def get_youtube_channel_id_from_handle_for_shorts(handle: str) -> Optional[str]:
    """
    通过 handle/@username 获取 YouTube channel ID（用于 Shorts API）
    使用 Shorts API 的 meta 信息来获取 channel ID
    """
    api_key = get_rapidapi_key()

    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return None
    
    host = RAPIDAPI_HOSTS["youtube_shorts"]
    url = f"https://{host}/channel/shorts"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    # 去掉 @ 符号
    handle_clean = handle.lstrip("@")
    
    # 尝试直接用 handle 调用，看是否支持
    params = {"id": handle_clean}
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None or response.status_code != 200:
            if response and response.status_code == 429:
                print(f"  [调试] Shorts API 调用失败: 429 Too Many Requests")
            return None
        
        data = response.json()
        # 从 meta 中提取 channelId
        meta = data.get("meta", {})
        channel_id = meta.get("channelId")
        if channel_id:
            print(f"  ✓ 获取到 channel ID: {channel_id} (handle: {handle_clean})")
            return channel_id
    except Exception as e:
        print(f"  [调试] Shorts API 调用失败: {e}")
    
    # 如果 handle 不行，尝试通过原有方法获取
    return get_youtube_channel_id_from_handle(handle)


def get_youtube_shorts_from_channel(
    channel_id_or_handle: str,
    count: int = 10,
    historical_video_ids: Optional[set[str]] = None
) -> List[Dict[str, Any]]:
    """
    使用 RapidAPI 获取 YouTube Shorts
    
    Args:
        channel_id_or_handle: Channel ID 或 handle (如 @username)
        count: 获取的 Shorts 数量（5-10条）
        historical_video_ids: 历史视频ID集合，用于过滤已存在的视频
    
    Returns:
        Shorts 列表，只返回不在历史数据中的新 Shorts
    """
    api_key = get_rapidapi_key()

    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return []
    
    host = RAPIDAPI_HOSTS["youtube_shorts"]
    url = f"https://{host}/channel/shorts"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    # 判断是 channel ID (UC开头，通常是24个字符) 还是 handle
    channel_id = channel_id_or_handle.lstrip("@")
    
    # Channel ID 通常是 UC 开头，24个字符
    is_channel_id = channel_id.startswith("UC") and len(channel_id) == 24
    
    if not is_channel_id:
        # 如果不是 channel ID，尝试获取
        print(f"  [YouTube Shorts] 检测到 handle: {channel_id}")
        print(f"  [YouTube Shorts] 尝试获取对应的 channel ID...")
        resolved_id = get_youtube_channel_id_from_handle_for_shorts(channel_id)
        if resolved_id:
            channel_id = resolved_id
        else:
            print(f"  [YouTube Shorts] 无法获取 channel ID，将尝试直接使用 handle...")
            # 继续使用 handle，某些 API 可能支持
    
    params = {"id": channel_id}
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None:
            return []
        
        if response.status_code == 429:
            print(f"  ❌ YouTube Shorts API 调用失败: 429 Too Many Requests（所有 API Key 都已尝试）")
            return []
        
        response.raise_for_status()
        data = response.json()
        
        shorts = []
        data_list = data.get("data", [])
        
        # 限制获取数量
        data_list = data_list[:count]
        
        # 如果没有提供历史数据，则初始化空集合
        if historical_video_ids is None:
            historical_video_ids = set()
        
        for item in data_list:
            video_id = item.get("videoId", "")
            
            # 跳过历史数据中已存在的视频
            if video_id in historical_video_ids:
                continue
            
            title = item.get("title", "")
            view_count_text = item.get("viewCountText", "")
            
            # 提取缩略图
            media_urls = []
            thumbnails = item.get("thumbnail", [])
            if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
                # 取第一个缩略图（通常是最高质量的）
                thumb = thumbnails[0]
                if isinstance(thumb, dict):
                    media_urls.append(thumb.get("url", ""))
                elif isinstance(thumb, str):
                    media_urls.append(thumb)
            
            # 解析观看数（如 "7K views", "1.1M views"）
            view_count = 0
            if view_count_text:
                view_match = re.search(r'([\d.]+)([KMB]?)', view_count_text.replace(',', '').upper())
                if view_match:
                    num = float(view_match.group(1))
                    unit = view_match.group(2)
                    if unit == 'K':
                        view_count = int(num * 1000)
                    elif unit == 'M':
                        view_count = int(num * 1000000)
                    elif unit == 'B':
                        view_count = int(num * 1000000000)
                    else:
                        view_count = int(num)
            
            engagement = {
                "view": view_count,
            }
            
            short = {
                "text": title,
                "video_id": video_id,  # 保存 videoId 用于比对
                "post_url": f"https://www.youtube.com/shorts/{video_id}",
                "media_urls": media_urls,
                "engagement": engagement,
                "view_count_text": view_count_text,
            }
            shorts.append(short)
        
        print(f"  ✓ 获取到 {len(shorts)} 条新的 Shorts（共爬取 {len(data_list)} 条，过滤掉 {len(data_list) - len(shorts)} 条历史数据）")
        return shorts
    
    except Exception as exc:
        print(f"  ❌ YouTube Shorts API 调用失败: {exc}")
        import traceback
        print(f"  [调试] 错误详情: {traceback.format_exc()}")
        return []


def load_historical_youtube_shorts(
    company: str,
    game: Optional[str],
    platform_type: str,
    url: str,
    days_ago: int = 1
) -> set[str]:
    """
    历史 Shorts 视频 ID（用于去重）。当前项目不维护独立 history 库，返回空集合，
    即不做跨日历史去重；若需去重可改为查询 competitor 库中的昨日帖子。
    """
    return set()


def get_twitter_user_id_from_username(username: str, debug: bool = False) -> Optional[str]:
    """通过 username 获取 Twitter user ID"""
    api_key = get_rapidapi_key()

    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return None
    
    host = RAPIDAPI_HOSTS["twitter"]
    url = f"https://{host}/user"
    
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    params = {"username": username}
    
    try:
        response = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
        if response is None:
            return None
        
        if response.status_code == 429:
            print(f"  ❌ Twitter API 调用失败: 429 Too Many Requests（所有 API Key 都已尝试）")
            return None
        if response.status_code == 403:
            print(f"  ❌ Twitter API 调用失败: 403 Forbidden（所有 API Key 都已尝试，请检查订阅/权限）")
            return None
        
        response.raise_for_status()
        data = response.json()
        
        # 调试：打印响应
        if debug:
            print(f"\n  [调试] API 响应状态码: {response.status_code}")
            print(f"  [调试] 响应数据: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}...")
        
        # 从响应中提取 rest_id
        # API 响应结构: result.data.user.result.rest_id
        user_result = data.get("result", {}).get("data", {}).get("user", {}).get("result", {})
        user_id = user_result.get("rest_id", "")
        
        if user_id:
            print(f"  ✓ 获取到 user ID: {user_id} (username: {username})")
            return user_id
        else:
            print(f"  ⚠️ 未能从响应中提取 user ID")
            if debug:
                print(f"  [调试] user_result keys: {list(user_result.keys())}")
            return None
    
    except requests.exceptions.HTTPError as exc:
        print(f"  ❌ HTTP 错误: {exc}")
        if debug and hasattr(exc, 'response') and exc.response is not None:
            print(f"  [调试] 错误响应: {exc.response.text[:500]}")
        return None
    except Exception as exc:
        print(f"  ❌ 获取 Twitter user ID 失败: {exc}")
        return None


def _parse_twitter_created_at(created_at_str: str) -> Optional[datetime]:
    """
    解析 Twitter created_at 格式：\"Tue Jun 06 19:31:02 +0000 2023\"
    返回带时区的 datetime（通常是 UTC）。
    """
    if not created_at_str:
        return None
    try:
        return datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def _unwrap_tweet_result(tweet_result: Any) -> Optional[Dict[str, Any]]:
    """
    twitter241 的 tweet_results.result 有时是 Tweet，也可能是 TweetWithVisibilityResults 等包装类型。
    返回最终的 Tweet dict（__typename == 'Tweet'），否则返回 None。
    """
    if not isinstance(tweet_result, dict):
        return None
    cur = tweet_result
    # 最多解包 3 层，避免死循环
    for _ in range(3):
        t = cur.get("__typename")
        if t == "Tweet":
            return cur
        if t == "TweetWithVisibilityResults":
            # 常见结构：{"tweet": {"result": {...}}}
            cur = (cur.get("tweet") or {}).get("result") or {}
            continue
        # 其他类型暂不支持
        return None
    return None


def _tweet_author_screen_name(tweet: Dict[str, Any]) -> str:
    """
    从 tweet.core.user_results.result.legacy.screen_name 提取作者 handle
    """
    try:
        return (
            tweet.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("legacy", {})
            .get("screen_name", "")
        ) or ""
    except Exception:
        return ""


def _iter_tweet_results(obj: Any) -> List[Dict[str, Any]]:
    """
    递归遍历 dict/list，收集所有 tweet_results.result（原始、未解包）。
    用于兼容 TimelineTimelineItem / TimelineTimelineModule 等多种结构。
    """
    out: List[Dict[str, Any]] = []
    if isinstance(obj, dict):
        if "tweet_results" in obj and isinstance(obj["tweet_results"], dict):
            res = obj["tweet_results"].get("result")
            if isinstance(res, dict):
                out.append(res)
        for v in obj.values():
            out.extend(_iter_tweet_results(v))
    elif isinstance(obj, list):
        for it in obj:
            out.extend(_iter_tweet_results(it))
    return out


def _find_bottom_cursor(obj: Any) -> Optional[str]:
    """
    在 instruction/entry 结构中查找下一页的 bottom cursor（cursorType == 'Bottom'）。
    """
    if isinstance(obj, dict):
        # 形式一：{"cursorType": "Bottom", "value": "...."}
        if (obj.get("cursorType") == "Bottom") and isinstance(obj.get("value"), str):
            return obj["value"]
        # 形式二：{"content":{"operation":{"cursor":{"cursorType":"Bottom","value":"..."}}}}
        cur = obj.get("cursor")
        if isinstance(cur, dict) and cur.get("cursorType") == "Bottom" and isinstance(cur.get("value"), str):
            return cur["value"]
        for v in obj.values():
            found = _find_bottom_cursor(v)
            if found:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _find_bottom_cursor(it)
            if found:
                return found
    return None


def get_posts_from_twitter(
    username_or_id: str,
    days_ago: Optional[int] = None,
    count: int = 20,
    expected_username: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    使用 RapidAPI 获取 Twitter/X 推文
    - days_ago=None: 不做日期过滤，返回最新 count 条（解析到多少返回多少）
    - days_ago=int: 返回该天(相对今天)的全部推文（按 UTC 日历日）
      此时 count 仅作为单页请求大小，而不是最终结果上限
    - expected_username: 可选，期望的作者 handle；仅保留该作者的推文，避免混入转推/他人内容
    """
    api_key = get_rapidapi_key()

    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return []
    
    host = RAPIDAPI_HOSTS["twitter"]
    
    # 判断传入的是 user ID 还是 username
    user_id = username_or_id
    username_for_url: Optional[str] = None
    if not user_id.isdigit():
        username_for_url = username_or_id.strip().lstrip("@")
        # 如果是 username，先获取 user ID
        print(f"  [Twitter] 检测到 username，正在获取 user ID...")
        user_id = get_twitter_user_id_from_username(username_for_url)
        if not user_id:
            print("  ❌ 无法获取 user ID，跳过")
            return []
    
    # 用 expected_username 或 username_for_url 作为作者过滤，避免 timeline 里混入转推/他人推文
    author_for_filter = (expected_username or username_for_url or "").strip().lstrip("@").lower()
    target_author = author_for_filter if author_for_filter else None
    
    url = f"https://{host}/user-tweets"
    headers = {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': host
    }
    
    page_size = max(1, min(int(count), 100))
    params = {
        "user": user_id,
        "count": page_size,
    }
    
    try:
        posts: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        # 如果需要日期过滤：按 UTC 日历日范围过滤
        # 语义：days_ago=N → 从 N 天前 0:00 UTC 到现在（范围过滤，非单日过滤）
        day_start_utc: Optional[datetime] = None
        day_end_utc: Optional[datetime] = None
        if days_ago is not None:
            target_day = datetime.now(timezone.utc) - timedelta(days=int(days_ago))
            day_start_utc = target_day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end_utc = datetime.now(timezone.utc)  # 到现在为止

        next_cursor: Optional[str] = None
        page = 0
        max_pages = 20 if days_ago is not None else 3

        while True:
            page += 1
            reached_before_target_day = False
            page_added = 0
            resp = _make_rapidapi_request('GET', url, host, headers=headers, params=params, max_retries=2, timeout=30)
            if resp is None:
                print(f"  ⚠️ Twitter API 调用失败（第 {page} 页）")
                break
            
            if resp.status_code == 429:
                print(f"  ❌ Twitter API 调用失败: 429 Too Many Requests（所有 API Key 都已尝试）")
                break
            if resp.status_code == 403:
                print(f"  ❌ Twitter API 调用失败: 403 Forbidden（所有 API Key 都已尝试，请检查订阅/权限）")
                break
            
            resp.raise_for_status()
            data = resp.json()

            result = data.get("result", {})
            timeline = result.get("timeline", {})
            instructions = timeline.get("instructions", [])

            for instruction in instructions:
                # 收集推文
                if instruction.get("type") == "TimelineAddEntries":
                    entries = instruction.get("entries", [])
                    for entry in entries:
                        tweet_results_raw = _iter_tweet_results(entry)
                        for raw in tweet_results_raw:
                            tweet = _unwrap_tweet_result(raw)
                            if not tweet:
                                continue
                            tweet_id = tweet.get("rest_id", "")
                            if not tweet_id or tweet_id in seen_ids:
                                continue

                            author = _tweet_author_screen_name(tweet).lower()
                            if target_author and author and author != target_author:
                                continue

                            legacy = tweet.get("legacy", {}) or {}
                            created_at = _parse_twitter_created_at(legacy.get("created_at", ""))
                            if created_at is None:
                                continue
                            created_at_utc = created_at.astimezone(timezone.utc)

                            if day_start_utc and day_end_utc:
                                if created_at_utc < day_start_utc:
                                    reached_before_target_day = True
                                    continue
                                if not (day_start_utc <= created_at_utc <= day_end_utc):
                                    continue

                            full_text = (legacy.get("full_text") or "").strip()
                            engagement = {
                                "like": legacy.get("favorite_count", 0),
                                "retweet": legacy.get("retweet_count", 0),
                                "reply": legacy.get("reply_count", 0),
                                "quote": legacy.get("quote_count", 0),
                                "bookmark": legacy.get("bookmark_count", 0),
                            }
                            views = (tweet.get("views") or {}).get("count")
                            if views is not None:
                                engagement["view"] = views

                            handle = (expected_username or username_for_url or author or username_or_id).strip().lstrip("@")
                            post_url = f"https://x.com/{handle}/status/{tweet_id}"

                            posts.append(
                                {
                                    "text": full_text,
                                    "published_at": created_at_utc.isoformat(),
                                    "published_at_display": created_at_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                                    "post_url": post_url,
                                    "engagement": engagement,
                                }
                            )
                            seen_ids.add(tweet_id)
                            page_added += 1

                # 查找下一页游标
                if next_cursor is None:
                    cur = _find_bottom_cursor(instruction)
                    if cur:
                        next_cursor = cur

            # 不按日期过滤时，仍按 count 截断为最新 N 条
            if days_ago is None and len(posts) >= int(count):
                break

            # 按日期过滤时，若已经翻到目标日期之前，则后续页面只会更旧，可以停止
            if days_ago is not None and reached_before_target_day:
                break

            # 当前页没有新增且没有下一页，或达到安全翻页上限，退出
            if not next_cursor or page >= max_pages:
                break

            # 准备下一页
            params = dict(params)
            params["cursor"] = next_cursor
            next_cursor = None

        posts.sort(key=lambda p: p.get("published_at", ""), reverse=True)
        if days_ago is None:
            return posts[: int(count)]
        return posts
    
    except Exception as exc:
        print(f"  ❌ Twitter API 调用失败: {exc}")
        return []


def scrape_posts_with_rapidapi(
    account: Dict[str, Any],
    days_ago: int = 1,
    count: int = 10,
    use_shorts: bool = False
) -> List[Dict[str, Any]]:
    """
    根据平台类型调用对应的 API
    
    Args:
        account: 账号信息字典
        days_ago: 日期过滤（用于有发布时间的情况）
        count: 获取数量（用于 Shorts 等没有发布时间的情况）
        use_shorts: 是否使用 Shorts API（仅对 YouTube 有效）
    """
    platform_type = account.get("platform_type", "").lower()
    url = account.get("url", "")
    
    identifier = extract_username_from_url(url, platform_type)
    if not identifier:
        print(f"  ⚠️ 无法从 URL 提取标识符: {url}")
        return []
    
    print(f"  [RapidAPI] 平台: {platform_type}, 标识符: {identifier}")
    
    # 判断是否为 YouTube Shorts
    is_youtube_shorts = False
    if "youtube" in platform_type:
        # 如果 URL 包含 /shorts 或者明确指定使用 Shorts
        if "/shorts" in url.lower() or use_shorts:
            is_youtube_shorts = True
    
    if is_youtube_shorts:
        # 加载历史数据用于比对
        company = account.get("company", "")
        game = account.get("game")
        historical_video_ids = load_historical_youtube_shorts(
            company=company,
            game=game,
            platform_type=platform_type,
            url=url,
            days_ago=1  # 查看昨天的数据
        )
        print(f"  [YouTube Shorts] 历史数据中有 {len(historical_video_ids)} 个视频ID")
        
        # 获取 Shorts（会自动过滤历史数据）
        return get_youtube_shorts_from_channel(
            channel_id_or_handle=identifier,
            count=count,
            historical_video_ids=historical_video_ids
        )
    elif "instagram" in platform_type:
        return get_posts_from_instagram(identifier, days_ago)
    elif "tiktok" in platform_type:
        return get_posts_from_tiktok(identifier, days_ago)
    elif "youtube" in platform_type:
        return get_posts_from_youtube(identifier, days_ago)
    elif "twitter" in platform_type or "x.com" in url.lower():
        return get_posts_from_twitter(identifier, days_ago)
    else:
        print(f"  ⚠️ 不支持的平台类型: {platform_type}")
        return []


def scrape_competitor_social_with_rapidapi() -> None:
    """主函数：使用 RapidAPI 抓取竞品社媒帖子"""
    api_key = get_rapidapi_key()

    if not api_key:
        print("❌ 未配置 RAPIDAPI_KEY，请在 .env 文件中设置")
        return
    
    cfg = load_config()
    accounts = get_competitor_accounts(cfg)
    if not accounts:
        print("⚠️ 未找到竞品账号配置")
        return
    
    print(f"[*] 发现 {len(accounts)} 个竞品平台需要抓取")
    
    items = []
    for acc in accounts:
        company = acc["company"]
        game = acc.get("game")
        platform_type = acc["platform_type"]
        url = acc["url"]
        priority = acc.get("priority", "medium")
        
        display_name = f"{company} - {game}" if game else company
        print(f"\n[*] 正在抓取：{display_name} - {platform_type} ({url}) [优先级: {priority}]")
        
        # 判断是否为 YouTube Shorts
        use_shorts = False
        count = 10  # 默认获取10条
        if "youtube" in platform_type.lower():
            if "/shorts" in url.lower():
                use_shorts = True
                count = 10  # Shorts 默认获取10条
            # 也可以从配置中读取数量
        
        # 获取帖子/Shorts
        if use_shorts:
            posts = scrape_posts_with_rapidapi(acc, days_ago=None, count=count, use_shorts=True)
            print(f"  ✓ 解析到 {len(posts)} 条新的 Shorts")
        else:
            posts = scrape_posts_with_rapidapi(acc, days_ago=1)
            print(f"  ✓ 解析到 {len(posts)} 条昨天的帖子")
        
        item = {
            "company": company,
            "game": game,
            "platform_type": platform_type,
            "url": url,
            "priority": priority,
            "posts": posts,
            "posts_count": len(posts),
        }
        items.append(item)
    
    if not items:
        print("⚠️ 未成功抓取到任何竞品社媒内容。")
        return
    
    # 保存结果
    output_dir = "/app/output"
    if not os.path.exists(output_dir):
        output_dir = os.path.join(os.path.dirname(__file__), "output")
        os.makedirs(output_dir, exist_ok=True)
    
    out_path = os.path.join(output_dir, "competitor_social_raw.json")
    payload = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "items": items,
    }
    
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 竞品社媒原始数据已保存至: {out_path}")
    except Exception as exc:
        print(f"❌ 保存结果失败: {exc}")



if __name__ == "__main__":
    scrape_competitor_social_with_rapidapi()
