"""
官网内容爬虫模块（混合方案：RSS 优先 + Jina Reader + Requests 降级）
抓取 AI 产品官网的关键信息：产品介绍、功能列表、定价、更新日志等
"""
import hashlib
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

import env_loader  # noqa: F401

# 常见 RSS/Atom 路径，按优先级探测
RSS_CANDIDATE_PATHS = [
    "/feed", "/blog/feed.xml", "/rss.xml", "/feed.xml",
    "/blog/rss", "/blog/feed", "/atom.xml", "/index.xml",
    "/updates/feed", "/news/feed", "/rss",
]

SITEMAP_CANDIDATE_PATHS = [
    "/sitemap.xml", "/sitemap_index.xml",
]

# Jina Reader API 基础 URL
JINA_READER_BASE = "https://r.jina.ai/"

# 请求超时
_REQUEST_TIMEOUT = 30

# 随机 User-Agent 列表
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def _get_random_ua() -> str:
    """获取随机 User-Agent"""
    import random
    return random.choice(_USER_AGENTS)


def _make_url(base_url: str, path: str) -> str:
    """拼接 URL，处理末尾斜杠"""
    base = base_url.rstrip("/")
    return f"{base}{path}"


def _compute_content_hash(text: str) -> str:
    """计算文本内容的 MD5 哈希"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ─── 第1层：RSS/Sitemap 探测与解析 ───

def detect_rss(base_url: str) -> Optional[str]:
    """
    探测官网是否有 RSS/Atom feed。
    
    策略：
    1. 先请求首页 HTML，检查 <link rel="alternate" type="application/rss+xml"> 标签
    2. 再逐个尝试常见 RSS 路径（HEAD 请求，快速判断）
    
    Returns:
        feed URL 或 None
    """
    headers = {"User-Agent": _get_random_ua()}
    
    # 策略1：从首页 HTML 中提取 RSS 链接
    try:
        resp = requests.get(base_url, headers=headers, timeout=_REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            html = resp.text[:50000]  # 只看前 50KB
            # 匹配 <link rel="alternate" type="application/rss+xml" href="...">
            rss_pattern = re.compile(
                r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
                re.IGNORECASE
            )
            match = rss_pattern.search(html)
            if match:
                href = match.group(2)
                if href.startswith("/"):
                    return _make_url(base_url, href)
                if href.startswith("http"):
                    return href
    except Exception:
        pass
    
    # 策略2：逐个尝试常见 RSS 路径
    for path in RSS_CANDIDATE_PATHS:
        try:
            test_url = _make_url(base_url, path)
            resp = requests.head(test_url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "xml" in content_type or "rss" in content_type or "atom" in content_type:
                    return test_url
        except Exception:
            continue
    
    return None


def parse_rss_feed(feed_url: str, days_ago: int = 1) -> Dict[str, Any]:
    """
    解析 RSS feed，提取最近 N 天的条目。
    
    使用纯 requests + XML 解析（避免 feedparser 依赖问题）。
    """
    headers = {"User-Agent": _get_random_ua()}
    entries = []
    
    try:
        resp = requests.get(feed_url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        xml_content = resp.text
    except Exception as exc:
        return {"feed_url": feed_url, "entries": [], "error": str(exc)}
    
    # 简单 XML 解析（不依赖 feedparser，用正则提取关键信息）
    # 提取 <item> 或 <entry> 块
    item_pattern = re.compile(r"<item[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
    entry_pattern = re.compile(r"<entry[^>]*>(.*?)</entry>", re.DOTALL | re.IGNORECASE)
    
    blocks = item_pattern.findall(xml_content) + entry_pattern.findall(xml_content)
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
    
    for block in blocks:
        title = _extract_xml_tag(block, "title") or ""
        link = _extract_xml_tag(block, "link") or ""
        # Atom 的 link 标签可能是 <link href="..."/>
        if not link:
            href_match = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', block, re.IGNORECASE)
            if href_match:
                link = href_match.group(1)
        description = _extract_xml_tag(block, "description") or _extract_xml_tag(block, "summary") or ""
        pub_date_str = _extract_xml_tag(block, "pubDate") or _extract_xml_tag(block, "published") or _extract_xml_tag(block, "updated") or ""
        
        # 尝试解析发布时间
        pub_date = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                pub_date = datetime.strptime(pub_date_str.strip(), fmt).replace(tzinfo=timezone.utc) if pub_date_str else None
                if pub_date:
                    break
            except (ValueError, AttributeError):
                continue
        
        # 过滤：只保留指定天数内的条目
        if pub_date and pub_date < cutoff:
            continue
        
        # 清理 HTML 标签
        clean_desc = re.sub(r"<[^>]+>", "", description).strip()
        
        entries.append({
            "title": re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title).strip(),
            "link": link.strip(),
            "text": clean_desc[:1000] if clean_desc else "",
            "published_at": pub_date.isoformat() if pub_date else pub_date_str,
        })
    
    return {"feed_url": feed_url, "entries": entries}


def _extract_xml_tag(block: str, tag: str) -> Optional[str]:
    """从 XML 块中提取标签内容"""
    pattern = re.compile(rf"<{tag}[^>]*>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(block)
    if match:
        content = match.group(1).strip()
        # 处理 CDATA
        cdata = re.match(r"<!\[CDATA\[(.*?)\]\]>", content, re.DOTALL)
        if cdata:
            return cdata.group(1).strip()
        return content
    return None


# ─── 第2层：Jina Reader API ───

def scrape_via_jina_reader(url: str) -> Dict[str, Any]:
    """
    通过 Jina Reader API 将网页转为 Markdown。
    
    GET https://r.jina.ai/{url}
    返回页面内容的 Markdown 格式。
    """
    jina_url = f"{JINA_READER_BASE}{url}"
    api_key = os.environ.get("JINA_READER_API_KEY", "")
    
    headers = {
        "User-Agent": _get_random_ua(),
        "Accept": "text/plain",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    try:
        resp = requests.get(jina_url, headers=headers, timeout=_REQUEST_TIMEOUT)
        if resp.status_code == 429:
            print(f"      ⚠️ Jina Reader 限流 (429)，将降级到 Requests")
            return {"error": "rate_limited", "source_type": "jina"}
        resp.raise_for_status()
        
        content = resp.text
        # Jina Reader 返回的第一行通常是标题
        lines = content.split("\n")
        title = ""
        for line in lines:
            line = line.strip()
            if line and not line.startswith("![") and not line.startswith("http"):
                title = line.lstrip("# ").strip()
                break
        
        content_hash = _compute_content_hash(content)
        
        return {
            "source_type": "jina",
            "title": title[:200],
            "content_markdown": content[:10000],  # 限制长度
            "content_hash": content_hash,
        }
    except Exception as exc:
        return {"error": str(exc), "source_type": "jina"}


# ─── 第3层：Requests + BeautifulSoup 降级 ───

def scrape_via_requests(url: str) -> Dict[str, Any]:
    """
    降级方案：Requests + 基础 HTML 解析。
    至少拿到 meta 标签和基础 HTML 文本。
    """
    headers = {"User-Agent": _get_random_ua()}
    
    try:
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        return {"error": str(exc), "source_type": "requests"}
    
    # 提取 meta 信息
    title = _extract_meta(html, "og:title") or _extract_title(html) or ""
    description = _extract_meta(html, "og:description") or _extract_meta(html, "description") or ""
    
    # 提取 headings
    headings = re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.DOTALL | re.IGNORECASE)
    clean_headings = [re.sub(r"<[^>]+>", "", h).strip() for h in headings if h.strip()]
    
    # 提取可见文本（简单去标签）
    # 移除 script/style
    text_html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text_content = re.sub(r"<[^>]+>", " ", text_html)
    text_content = re.sub(r"\s+", " ", text_content).strip()[:5000]
    
    content_hash = _compute_content_hash(text_content)
    
    return {
        "source_type": "requests",
        "title": title[:200],
        "description": description[:500],
        "headings": clean_headings[:20],
        "text_content": text_content,
        "content_hash": content_hash,
    }


def _extract_meta(html: str, name: str) -> Optional[str]:
    """从 HTML 中提取 meta 标签内容"""
    # 匹配 <meta property="og:title" content="..."> 或 <meta name="description" content="...">
    patterns = [
        rf'<meta[^>]+(?:property|name)=["\']({re.escape(name)})["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']({re.escape(name)})["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(2) if len(match.groups()) >= 2 else match.group(1)
    return None


def _extract_title(html: str) -> Optional[str]:
    """从 HTML 中提取 <title> 标签"""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


# ─── 主入口：三层降级 ───

def scrape_website_content(
    url: str,
    days_ago: int = 1,
    content_hash_previous: Optional[str] = None,
) -> Dict[str, Any]:
    """
    混合方案抓取官网内容（三层降级）
    
    1. 探测 RSS → 有则解析 feed 条目
    2. 无 RSS → Jina Reader API
    3. Jina 失败 → Requests + 基础 HTML 解析
    
    Args:
        url: 官网 URL
        days_ago: 爬取最近几天的内容（仅对 RSS 有效）
        content_hash_previous: 上次的内容哈希，用于增量对比
    
    Returns:
        {
            "url": "...",
            "source_type": "rss" | "jina" | "requests",
            "title": "页面标题",
            "description": "meta description",
            "content_markdown": "Markdown 内容（Jina）",
            "headings": ["h1", "h2", ...],
            "feed_entries": [...],  # RSS 条目（如有）
            "content_hash": "md5",
            "content_changed": True/False,
            "scraped_at": "ISO时间"
        }
    """
    scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # 确保 URL 有协议前缀
    if not url.startswith("http"):
        url = f"https://{url}"
    
    # 提取 base_url（用于 RSS 探测）
    from urllib.parse import urlparse
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    result: Dict[str, Any] = {
        "url": url,
        "source_type": "unknown",
        "title": "",
        "description": "",
        "content_markdown": "",
        "headings": [],
        "feed_entries": [],
        "content_hash": "",
        "content_changed": True,
        "scraped_at": scraped_at,
    }
    
    # ── 第1层：RSS 探测 ──
    print(f"      [Website] 探测 RSS feed...")
    feed_url = detect_rss(base_url)
    
    if feed_url:
        print(f"      [Website] ✓ 发现 RSS: {feed_url}")
        feed_data = parse_rss_feed(feed_url, days_ago=days_ago)
        entries = feed_data.get("entries", [])
        
        if entries:
            result["source_type"] = "rss"
            result["feed_entries"] = entries
            result["title"] = base_url  # RSS 条目自带标题
            # 对所有条目文本做哈希
            all_text = " ".join(e.get("text", "") for e in entries)
            result["content_hash"] = _compute_content_hash(all_text) if all_text else ""
            result["content_changed"] = (
                result["content_hash"] != content_hash_previous
                if content_hash_previous and result["content_hash"]
                else True
            )
            print(f"      [Website] ✓ RSS 解析到 {len(entries)} 条更新")
            return result
        else:
            print(f"      [Website] RSS 存在但无近期条目，降级到 Jina Reader")
    
    # ── 第2层：Jina Reader ──
    print(f"      [Website] 尝试 Jina Reader...")
    jina_result = scrape_via_jina_reader(url)
    
    if not jina_result.get("error"):
        result["source_type"] = "jina"
        result["title"] = jina_result.get("title", "")
        result["content_markdown"] = jina_result.get("content_markdown", "")
        result["content_hash"] = jina_result.get("content_hash", "")
        result["content_changed"] = (
            result["content_hash"] != content_hash_previous
            if content_hash_previous and result["content_hash"]
            else True
        )
        print(f"      [Website] ✓ Jina Reader 获取成功（{len(result['content_markdown'])} 字符）")
        return result
    
    # ── 第3层：Requests 降级 ──
    print(f"      [Website] Jina Reader 失败，降级到 Requests...")
    req_result = scrape_via_requests(url)
    
    if not req_result.get("error"):
        result["source_type"] = "requests"
        result["title"] = req_result.get("title", "")
        result["description"] = req_result.get("description", "")
        result["headings"] = req_result.get("headings", [])
        result["content_hash"] = req_result.get("content_hash", "")
        result["content_changed"] = (
            result["content_hash"] != content_hash_previous
            if content_hash_previous and result["content_hash"]
            else True
        )
        print(f"      [Website] ✓ Requests 降级获取成功")
        return result
    
    # 全部失败
    print(f"      [Website] ❌ 所有方案均失败")
    result["source_type"] = "failed"
    result["content_changed"] = False
    return result
