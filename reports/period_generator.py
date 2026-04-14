"""
竞品社媒周报生成模块（第三部分）
按公司生成飞书/企微周报卡片，包含 AI 分析结果、监控时间段和平台信息。
"""
import json
import os
import re
import time
import yaml
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date

import requests

import env_loader  # noqa: F401

from database.competitor_db import CompetitorDatabaseDB

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_config_path() -> str:
    """项目根目录下的 config/config.yaml，或由 CONFIG_PATH / 环境指定。"""
    env_path = os.environ.get("CONFIG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    root_cfg = os.path.join(_PROJECT_ROOT, "config", "config.yaml")
    if os.path.exists(root_cfg):
        return root_cfg
    docker_cfg = "/app/config/config.yaml"
    if os.path.exists(docker_cfg):
        return docker_cfg
    return ""


def _get_company_color(company: str) -> str:
    """为不同公司分配不同颜色的边框"""
    colors = [
        "blue", "wathet", "turquoise", "green", "yellow", "orange",
        "red", "carmine", "violet", "purple", "indigo", "grey",
    ]
    hash_value = hash(company.lower()) % len(colors)
    return colors[hash_value]


def _platform_icon(platform: str) -> str:
    """根据平台类型返回图标"""
    p = (platform or "").lower()
    if "twitter" in p or "x.com" in p or p == "x":
        return "🐦"
    if "instagram" in p or "ig" == p:
        return "📸"
    if "tiktok" in p:
        return "🎵"
    if "youtube" in p:
        return "▶️"
    if "facebook" in p or "fb" == p:
        return "📘"
    if "website" in p:
        return "🌐"
    return "📡"


def get_feishu_webhook() -> str:
    """获取飞书webhook地址"""
    for env_key in ("FEISHU_WEBHOOK_URL", "FEISHU_URL", "FEISHU_WEBHOOK"):
        if os.environ.get(env_key):
            return os.environ[env_key]

    config_path = _resolve_config_path()
    if not config_path:
        return ""

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (
            cfg.get("notification", {})
            .get("webhooks", {})
            .get("feishu_url", "")
        )
    except Exception:
        return ""


def get_wework_webhook() -> Tuple[str, str]:
    """
    获取企业微信webhook地址和消息类型
    
    Returns:
        (webhook_url, msg_type) - webhook地址和消息类型（markdown/text）
    """
    # 优先从环境变量获取
    webhook = os.environ.get("WEWORK_WEBHOOK_URL") or os.environ.get("WEWORK_URL") or ""
    msg_type = os.environ.get("WEWORK_MSG_TYPE", "markdown")
    
    # 如果环境变量没有，从配置文件读取
    if not webhook:
        config_path = _resolve_config_path()
        if not config_path:
            return "", "markdown"

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            webhooks = cfg.get("notification", {}).get("webhooks", {})
            webhook = webhooks.get("wework_url", "")
            msg_type = webhooks.get("wework_msg_type", "markdown")
        except Exception:
            return "", "markdown"
    
    return webhook, msg_type


def get_company_platforms_from_db(
    db: CompetitorDatabaseDB,
    company: str
) -> List[Dict[str, Any]]:
    """
    从数据库获取产品监控的所有平台信息
    
    Args:
        db: 数据库实例
        company: 产品名称
    
    Returns:
        平台列表，格式：
        [
            {
                "type": "twitter",
                "game": None,  # 兼容旧字段，新结构下始终为 None
                "url": "...",
                "username": "...",
                "enabled": True
            },
            ...
        ]
    """
    # 获取产品级平台（game_name=None，新结构下所有平台都在产品级）
    company_platforms = db.get_company_platforms(company, game_name=None, enabled_only=False)
    
    # 兼容旧数据：获取 game_name 不为空的子产品级平台（旧结构遗留数据）
    conn = db._get_connection()
    sub_product_platforms = []
    try:
        cursor = conn.execute("""
            SELECT game_name, platform_type, username, url, user_id, page_id,
                   channel_id, handle, sec_uid, enabled, priority
            FROM company_platforms
            WHERE company_name = ? AND game_name IS NOT NULL
            ORDER BY platform_type
        """, (company,))
        
        rows = cursor.fetchall()
        for row in rows:
            platform = {
                "type": row["platform_type"],
                "enabled": bool(row["enabled"])
            }
            if row["game_name"]:
                platform["game"] = row["game_name"]
            if row["username"]:
                platform["username"] = row["username"]
            if row["url"]:
                platform["url"] = row["url"]
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
            if row["priority"]:
                platform["priority"] = row["priority"]
            sub_product_platforms.append(platform)
    finally:
        conn.close()
    
    # 合并产品级和子产品级平台
    all_platforms = company_platforms + sub_product_platforms
    
    result = []
    for platform in all_platforms:
        result.append({
            "type": platform.get("type", ""),
            "game": platform.get("game"),
            "url": platform.get("url", ""),
            "username": platform.get("username"),
            "page_id": platform.get("page_id"),
            "channel_id": platform.get("channel_id"),
            "handle": platform.get("handle"),
            "enabled": platform.get("enabled", True)
        })
    
    return result


def _format_post_urls_as_links(urls: List[str]) -> str:
    """将 URL 列表格式化为飞书 markdown 可点击链接。"""
    if not urls:
        return ""
    return "  \n".join([f"[{u}]({u})" for u in urls if u])


def build_company_period_feishu_card(
    company: str,
    period: Dict[str, Any],
    company_analysis: Optional[Dict[str, Any]],
    monitored_platforms: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    构建产品时间段周报的飞书卡片（按产品维度：摘要、新功能/产品动态及可点击链接、日常说明、建议动作）。
    
    Args:
        company: 产品名称
        period: 时间段信息 {"start_date": "...", "end_date": "...", "days": 7}
        company_analysis: 该产品该时间段的 AI 分析结果（summary, top_post_urls, video_highlights）
        monitored_platforms: 监控的平台列表（从数据库获取）
    
    Returns:
        飞书卡片字典
    """
    company_color = _get_company_color(company)
    start_date = period.get("start_date", "")
    end_date = period.get("end_date", "")
    days = period.get("days", 7)
    
    elements: List[Dict[str, Any]] = []
    
    # 时间段与监控平台
    header_info = [
        f"📅 **监控时间段**: {start_date} 至 {end_date} (共 {days} 天)"
    ]
    
    sources = []
    if monitored_platforms:
        platform_icons = {
            "twitter": "🐦", "tiktok": "🎵", "youtube": "▶️",
            "facebook": "📘", "instagram": "📷", "website": "🌐",
        }
        platform_groups: Dict[str, List[Dict[str, Any]]] = {}
        for platform in monitored_platforms:
            platform_type = platform.get("type", "").lower()
            if platform_type not in platform_groups:
                platform_groups[platform_type] = []
            platform_groups[platform_type].append(platform)
        
        for platform_type, platforms_list in sorted(platform_groups.items()):
            icon = platform_icons.get(platform_type, "🌐")
            for platform in platforms_list:
                game = platform.get("game")
                url = platform.get("url", "")
                if not url:
                    username = platform.get("username")
                    if platform_type == "twitter" and username:
                        url = f"https://x.com/{username}"
                    elif platform_type == "tiktok" and username:
                        url = f"https://www.tiktok.com/@{username}"
                    elif platform_type == "instagram" and username:
                        url = f"https://www.instagram.com/{username}/"
                    elif platform_type == "facebook":
                        page_id = platform.get("page_id", "")
                        if page_id:
                            url = f"https://www.facebook.com/{page_id}"
                    elif platform_type == "youtube":
                        handle = platform.get("handle")
                        channel_id = platform.get("channel_id")
                        if handle:
                            url = f"https://www.youtube.com/@{handle}"
                        elif channel_id:
                            url = f"https://www.youtube.com/channel/{channel_id}"
                if url:
                    label = f"{icon} {platform_type.upper()}"
                    if game:
                        label += f" - {game}"
                    enabled_status = "✅" if platform.get("enabled", True) else "⏸️"
                    sources.append(f"{label} {enabled_status}: [{url}]({url})")
    
    if sources:
        header_info.append(f"📎 **监控平台** ({len(sources)} 个):\n" + "\n".join([f"   • {s}" for s in sources]))
    else:
        header_info.append("📎 **监控平台**: 未配置")
    
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "\n".join(header_info)}
    })
    elements.append({"tag": "hr"})
    
    if not company_analysis:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "📝 **说明**: 该时间段内无社媒更新或分析未产出。"}
        })
    else:
        summary = company_analysis.get("summary") or ""
        top_post_urls = company_analysis.get("top_post_urls") or []
        posts_count = company_analysis.get("posts_count", 0)
        period_days = company_analysis.get("period_days", days)
        video_highlights = company_analysis.get("video_highlights") or []
        
        content_lines = []
        
        if summary:
            content_lines.append(f"📝 **摘要**: {summary}")
        
        if posts_count:
            content_lines.append(f"📊 **更新帖子数**: {posts_count} 条 (过去 {period_days} 天)")
        
        # 最相关链接（最多3条）
        if top_post_urls:
            content_lines.append("🔗 **相关链接**:\n" + _format_post_urls_as_links(top_post_urls))
        
        if content_lines:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n\n".join(content_lines)}
            })
        
        # 视频AI分析亮点（独立区块，精简版）
        if video_highlights:
            video_lines = [f"🎥 **视频分析** ({len(video_highlights)} 条):"]
            for vh in video_highlights[:5]:  # 最多展示5条
                post_url = vh.get("post_url", "")
                va_summary = vh.get("video_summary", "")
                va_insight = vh.get("competitive_insight", "")
                
                link = f"[视频]({post_url})" if post_url else "视频"
                parts = [f"  **{link}**"]
                if va_summary:
                    parts.append(f"  摘要: {va_summary}")
                if va_insight:
                    parts.append(f"  分析: {va_insight}")
                video_lines.append("\n".join(parts))
            
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n\n".join(video_lines)}
            })
    
    # 卡片标题
    header_title = f"🏁 竞品监控 · {company}"
    if company_analysis and company_analysis.get("summary"):
        # 从摘要中提取前30字作为副标题
        short_summary = company_analysis.get("summary", "")[:30]
        if len(company_analysis.get("summary", "")) > 30:
            short_summary += "…"
        header_title += f" · {short_summary}"
    else:
        header_title += " (时间段报告)"
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": company_color,
            "title": {"tag": "plain_text", "content": header_title}
        },
        "elements": elements
    }
    return card


def send_company_period_report_to_feishu(
    company: str,
    card: Dict[str, Any]
) -> bool:
    """
    发送公司时间段报告到飞书
    
    Args:
        company: 公司名称
        card: 飞书卡片
    
    Returns:
        是否发送成功
    """
    webhook = get_feishu_webhook()
    
    if not webhook:
        print(f"  ⚠️ 未找到飞书webhook，跳过推送")
        return False
    
    payload = {"msg_type": "interactive", "card": card}
    
    sent = False
    for attempt in range(3):
        try:
            resp = requests.post(webhook, json=payload, timeout=20)
            resp_data = {}
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {}
            
            code = resp_data.get("StatusCode", resp_data.get("code", 0))
            if resp.status_code == 200 and code in (0,):
                print(f"  ✓ {company} 时间段报告已推送到飞书")
                return True
            else:
                print(f"  ❌ 飞书推送失败 (尝试 {attempt + 1}/3): {resp.text[:200]}")
        except Exception as exc:
            print(f"  ❌ 飞书推送异常 (尝试 {attempt + 1}/3): {exc}")
        
        if attempt < 2:
            time.sleep(2)
    
    return False


def convert_feishu_card_to_wework_markdown(
    company: str,
    card: Dict[str, Any]
) -> str:
    """
    将飞书卡片转换为企业微信markdown格式
    
    Args:
        company: 公司名称
        card: 飞书卡片字典
    
    Returns:
        企业微信markdown格式的字符串
    """
    header = card.get("header", {})
    title = header.get("title", {}).get("content", f"🏁 竞品监控 · {company}")
    elements = card.get("elements", [])
    
    markdown_lines = [f"# {title}\n"]
    
    for element in elements:
        tag = element.get("tag", "")
        
        if tag == "hr":
            markdown_lines.append("---")
        
        elif tag == "div":
            # 处理文本内容
            text = element.get("text", {})
            if text:
                content = text.get("content", "")
                if content:
                    markdown_lines.append(content)
            
            # 处理字段
            fields = element.get("fields", [])
            if fields:
                for field in fields:
                    field_text = field.get("text", {})
                    if field_text:
                        content = field_text.get("content", "")
                        if content:
                            markdown_lines.append(content)
    
    return "\n".join(markdown_lines)


def send_company_period_report_to_wework(
    company: str,
    card: Dict[str, Any]
) -> bool:
    """
    发送公司时间段报告到企业微信
    
    Args:
        company: 公司名称
        card: 飞书卡片（会被转换为markdown格式）
    
    Returns:
        是否发送成功
    """
    webhook, msg_type = get_wework_webhook()
    
    if not webhook:
        print(f"  ⚠️ 未找到企业微信webhook，跳过推送")
        return False
    
    # 转换为企业微信格式
    if msg_type.lower() == "markdown":
        # markdown格式
        markdown_content = convert_feishu_card_to_wework_markdown(company, card)
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": markdown_content
            }
        }
    else:
        # text格式（简化版）
        header = card.get("header", {})
        title = header.get("title", {}).get("content", f"竞品监控 · {company}")
        elements = card.get("elements", [])
        
        text_lines = [title, ""]
        for element in elements:
            tag = element.get("tag", "")
            if tag == "hr":
                text_lines.append("-" * 20)
            elif tag == "div":
                text = element.get("text", {})
                if text:
                    content = text.get("content", "")
                    # 移除markdown格式，只保留文本
                    content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)  # 移除加粗
                    content = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', content)  # 移除链接，保留文本
                    if content:
                        text_lines.append(content)
                fields = element.get("fields", [])
                if fields:
                    for field in fields:
                        field_text = field.get("text", {})
                        if field_text:
                            content = field_text.get("content", "")
                            content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)
                            content = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', content)
                            if content:
                                text_lines.append(content)
        
        text_content = "\n".join(text_lines)
        payload = {
            "msgtype": "text",
            "text": {
                "content": text_content
            }
        }
    
    sent = False
    for attempt in range(3):
        try:
            resp = requests.post(webhook, json=payload, timeout=20)
            resp_data = {}
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {}
            
            # 企业微信返回格式：{"errcode": 0, "errmsg": "ok"}
            errcode = resp_data.get("errcode", -1)
            if resp.status_code == 200 and errcode == 0:
                print(f"  ✓ {company} 时间段报告已推送到企业微信")
                return True
            else:
                errmsg = resp_data.get("errmsg", resp.text[:200])
                print(f"  ❌ 企业微信推送失败 (尝试 {attempt + 1}/3): {errmsg}")
        except Exception as exc:
            print(f"  ❌ 企业微信推送异常 (尝试 {attempt + 1}/3): {exc}")
        
        if attempt < 2:
            time.sleep(2)
    
    return False


def generate_period_reports(
    analysis_result: Dict[str, Any],
    db_path: Optional[str] = None,
    skip_send: bool = False,
    send_to_wework: bool = False,
    report_save_mode: str = "overwrite"
) -> Dict[str, Any]:
    """
    生成时间段报告并发送到飞书/企业微信
    
    Args:
        analysis_result: AI分析结果（从CompetitorPeriodAnalysisAI生成）
        db_path: 数据库路径（用于获取监控平台信息）
        skip_send: 是否跳过发送到飞书
        send_to_wework: 是否发送到企业微信
        report_save_mode: 周报保存模式。"overwrite"=覆盖数据库中的周报；
            "use_cached"=若数据库中已有该周期周报则不再写入（使用缓存）
    
    Returns:
        报告生成结果
    """
    period = analysis_result.get("period", {})
    companies_analysis = analysis_result.get("companies", {})
    
    print(f"📄 开始生成时间段报告")
    print(f"   时间段: {period.get('start_date')} 至 {period.get('end_date')}")
    print(f"   公司数: {len(companies_analysis)}")
    
    # 解析日期
    start_date_str = period.get("start_date", "")
    end_date_str = period.get("end_date", "")
    try:
        start_date_obj = date.fromisoformat(start_date_str) if start_date_str else None
        end_date_obj = date.fromisoformat(end_date_str) if end_date_str else None
    except ValueError:
        start_date_obj = None
        end_date_obj = None
    
    # 初始化数据库（用于获取监控平台信息）
    db = CompetitorDatabaseDB(db_path) if db_path else CompetitorDatabaseDB()
    
    reports = {}
    
    for company, company_data in companies_analysis.items():
        print(f"\n  📄 生成报告: {company}")
        
        company_analysis = company_data.get("company_analysis")
        monitored_platforms = get_company_platforms_from_db(db, company)
        print(f"   监控平台数: {len(monitored_platforms)}")
        
        card = build_company_period_feishu_card(
            company=company,
            period=period,
            company_analysis=company_analysis,
            monitored_platforms=monitored_platforms
        )
        
        report_data = {
            "card": card,
            "monitored_platforms_count": len(monitored_platforms),
            "company_analysis": company_analysis,
            "monitored_platforms": monitored_platforms
        }
        
        reports[company] = report_data
        
        # 发送到飞书
        if not skip_send:
            send_company_period_report_to_feishu(company, card)
        
        # 发送到企业微信
        if send_to_wework:
            send_company_period_report_to_wework(company, card)
        
        # 保存周报到数据库
        if start_date_obj and end_date_obj:
            try:
                use_cached = (report_save_mode or "overwrite").strip().lower() == "use_cached"
                if use_cached:
                    existing = db.get_weekly_report(
                        company=company,
                        start_date=start_date_obj,
                        end_date=end_date_obj
                    )
                    if existing:
                        print(f"    📋 使用数据库缓存的周报，未覆盖")
                        continue
                report_content = {
                    "company": company,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "period": period,
                    "card": card,
                    "monitored_platforms_count": len(monitored_platforms),
                    "company_analysis": company_analysis,
                    "monitored_platforms": monitored_platforms
                }
                save_success = db.save_weekly_report(
                    company=company,
                    start_date=start_date_obj,
                    end_date=end_date_obj,
                    report_content=report_content
                )
                if save_success:
                    print(f"    💾 周报已保存到数据库")
                else:
                    print(f"    ⚠️ 周报保存到数据库失败")
            except Exception as exc:
                print(f"    ⚠️ 保存周报到数据库时出错: {exc}")
    
    # 保存报告到文件（与 period_workflow 默认的 workflows/output 一致）
    output_dir = os.environ.get("OUTPUT_DIR")
    if not output_dir or not os.path.exists(output_dir):
        output_dir = os.path.join(_PROJECT_ROOT, "workflows", "output")
        os.makedirs(output_dir, exist_ok=True)
    
    report_file = os.path.join(
        output_dir,
        f"competitor_period_reports_{start_date_str}_to_{end_date_str}.json"
    )
    
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)
        print(f"\n💾 报告已保存到文件: {report_file}")
    except Exception as exc:
        print(f"⚠️ 保存报告到文件失败: {exc}")
    
    print(f"\n✓ 报告生成完成，共 {len(reports)} 个公司")
    return reports


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="生成时间段报告并发送到飞书")
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="输入的AI分析结果JSON文件路径（从CompetitorPeriodAnalysisAI生成）"
    )
    parser.add_argument(
        "--skip-send",
        action="store_true",
        help="跳过发送到飞书，只生成报告文件"
    )
    parser.add_argument(
        "--send-to-wework",
        action="store_true",
        help="同时发送到企业微信（需要配置 WEWORK_WEBHOOK_URL）"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="数据库文件路径（可选，默认为 db/competitor_data.db）"
    )
    parser.add_argument(
        "--report-save-mode",
        type=str,
        choices=["overwrite", "use_cached"],
        default="overwrite",
        help="周报保存: overwrite=覆盖; use_cached=若已有该周期周报则不写入"
    )
    
    args = parser.parse_args()
    
    # 读取AI分析结果
    if not os.path.exists(args.input):
        print(f"❌ 输入文件不存在: {args.input}")
        return 1
    
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            analysis_result = json.load(f)
    except Exception as e:
        print(f"❌ 读取输入文件失败: {e}")
        return 1
    
    # 生成报告
    reports = generate_period_reports(
        analysis_result=analysis_result,
        db_path=args.db_path,
        skip_send=args.skip_send,
        send_to_wework=args.send_to_wework,
        report_save_mode=args.report_save_mode
    )
    
    print(f"\n✅ 报告生成完成，共 {len(reports)} 个公司")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
