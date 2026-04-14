"""
Facebook 平台爬虫模块（已废弃）

⚠️ 当前 AI 产品竞品监控不使用 Facebook 平台。
保留此文件仅供参考，如需恢复 Facebook 监控可重新启用。
仅提供底层函数供 daily_scraper.py 调用
"""
import os
from datetime import datetime
from typing import Any, Dict, List

import requests

import env_loader  # noqa: F401
from scrapers.rapidapi import get_rapidapi_key, RAPIDAPI_HOSTS


def _fetch_facebook_raw(page_id: str) -> Dict[str, Any]:
    """调用 RapidAPI 获取 Facebook page 原始 JSON"""
    api_key = get_rapidapi_key()
    if not api_key:
        print("  ❌ 未配置 RAPIDAPI_KEY")
        return {}
    host = RAPIDAPI_HOSTS.get("facebook") or "facebook-scraper3.p.rapidapi.com"
    url = f"https://{host}/page/posts"
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": host,
    }
    params = {"page_id": page_id}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  ❌ Facebook API 调用失败: {exc}")
        return {}


def _collect_posts_recursive(obj: Any, posts: List[Dict[str, Any]]) -> None:
    """递归从任意 JSON 结构中收集包含 post_id 和 timestamp 的对象"""
    if isinstance(obj, dict):
        if "post_id" in obj and "timestamp" in obj:
            posts.append(obj)
        for v in obj.values():
            _collect_posts_recursive(v, posts)
    elif isinstance(obj, list):
        for it in obj:
            _collect_posts_recursive(it, posts)


def parse_facebook_posts(raw_json: Dict[str, Any], max_posts: int = 5) -> List[Dict[str, Any]]:
    """解析 Facebook API 返回的原始 JSON，提取帖子列表"""
    posts_raw: List[Dict[str, Any]] = []
    _collect_posts_recursive(raw_json, posts_raw)

    out: List[Dict[str, Any]] = []
    import datetime as _dt

    for p in posts_raw:
        ts = p.get("timestamp")
        try:
            ts_int = int(ts)
            time_iso = _dt.datetime.utcfromtimestamp(ts_int).isoformat() + "Z"
        except Exception:
            time_iso = str(ts)

        # 标题
        title = ""
        author = p.get("author")
        if isinstance(author, dict):
            title = author.get("name") or p.get("author_title") or ""
        if not title:
            title = p.get("author_title") or ""

        text = (
            p.get("message")
            or p.get("message_rich")
            or p.get("story")
            or p.get("description")
            or ""
        )
        link = p.get("url") or p.get("external_url") or ""

        out.append({"time": time_iso, "title": title, "text": text, "link": link})

    # 根据时间倒序取前 max_posts 条
    out.sort(key=lambda x: x.get("time", ""), reverse=True)
    return out[:max_posts]
