"""
竞品社媒AI分析模块 (第二部分)
对提取的数据进行AI分析，重点关注 AI 产品功能更新和产品动态
"""
import json
import os
import time
from typing import Dict, List, Any, Optional
from datetime import datetime

from openai import OpenAI

import env_loader  # noqa: F401

from analyzers.daily_ai import call_model_with_retry

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

API_KEY = os.getenv("OPENROUTER_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
DEFAULT_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "40"))
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY, timeout=DEFAULT_TIMEOUT)


def _collect_company_posts(platforms_data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将某公司下所有平台的帖子合并为一条列表，带 post_url，按时间排序。"""
    all_posts = []
    for platform_data in platforms_data_list:
        posts = platform_data.get("posts", [])
        for p in posts:
            post_url = p.get("post_url") or p.get("link", "")
            all_posts.append({
                "text": p.get("text") or p.get("title") or "",
                "published_at": p.get("published_at", ""),
                "published_at_display": p.get("published_at_display", ""),
                "post_url": post_url,
                "engagement": p.get("engagement", {}),
                "media_urls": p.get("media_urls", []),
                "platform_type": platform_data.get("platform_type", ""),
                "game": platform_data.get("game"),
                "video_analysis": p.get("video_analysis"),
            })
    try:
        all_posts.sort(
            key=lambda x: x.get("published_at", "") or "",
            reverse=True
        )
    except Exception:
        pass
    return all_posts


def build_period_analysis_prompt(
    company: str,
    all_posts: List[Dict[str, Any]],
    period_days: int
) -> str:
    """
    构建时间段分析提示词（按产品维度：该产品该时间段内所有社媒帖子一起分析）。
    重点：新功能/新能力、产品动态；无则写无；记录对应帖子 URL；日常维护一笔带过；保留建议动作。
    """
    if not all_posts:
        return f"""你是一个资深的 AI 产品经理，专门帮团队做「AI 竞品社媒监控」。

现在给你的是 AI 竞品【{company}】在社交媒体上过去 {period_days} 天内的监控结果：

---
【竞品产品】{company}
【时间段】过去 {period_days} 天
【状态】该产品在过去 {period_days} 天内无任何社媒更新
---

请严格按以下 JSON 结构输出（不要出现多余字段或自然语言）：

{{
  "company": "{company}",
  "summary": "该产品在过去 {period_days} 天内无社媒更新。",
  "top_post_urls": []
}}"""
    
    # 构建帖子列表（每条带链接，便于模型标注哪些是新功能/产品动态）
    posts_block = []
    for i, post in enumerate(all_posts[:80], 1):
        text = (post.get("text") or "")[:400]
        post_url = post.get("post_url") or ""
        pub = post.get("published_at_display") or post.get("published_at") or ""
        platform = post.get("platform_type") or ""
        game = post.get("game")
        video_analysis = post.get("video_analysis")
        label = f"[帖子{i}]"
        if post_url:
            label += f" 链接: {post_url}"
        block = f"{label}\n平台: {platform}" + (f" 子产品: {game}" if game else "") + f"\n时间: {pub}\n内容: {text}"
        # 如果有视频AI分析结果，附加到帖子内容中
        if video_analysis and isinstance(video_analysis, dict):
            va_summary = video_analysis.get("video_summary", "")
            va_insight = video_analysis.get("competitive_insight", "")
            va_parts = []
            if va_summary:
                va_parts.append(f"摘要: {va_summary}")
            if va_insight:
                va_parts.append(f"分析: {va_insight}")
            if va_parts:
                block += "\n🎥视频: " + " | ".join(va_parts)
        posts_block.append(block)
    
    posts_content = "\n\n".join(posts_block)
    total = len(all_posts)
    shown = min(total, 80)

    return f"""你是一个资深的 AI 产品经理，专门帮团队做「AI 竞品社媒监控」。

现在给你的是 AI 竞品【{company}】在该时间段内、**所有平台**上的社媒更新帖子（已合并在一起），请整体分析。

---
【竞品产品】{company}
【时间段】过去 {period_days} 天
【帖子总数】{total} 条（以下展示前 {shown} 条）

{posts_content}
---

分析要求：
1. **摘要**：用一段话总结该产品在这段时间内社媒上的整体动态（summary），重点突出新功能、产品动态、营销策略等关键信息。
2. **最相关链接**：从以上帖子中选出最相关的 3 条帖子 URL（优先选择有新功能发布、产品更新、重要营销活动的帖子），填入 top_post_urls。

请严格按以下 JSON 结构输出（不要出现多余字段或自然语言）：

{{
  "company": "{company}",
  "summary": "一段话总结该产品该时间段内社媒整体动态，重点突出新功能、产品动态等关键信息。",
  "top_post_urls": ["最相关的3条帖子完整URL，不足3条则按实际数量"]
}}"""


def analyze_company_period_data(
    company: str,
    platforms_data_list: List[Dict[str, Any]],
    period_days: int
) -> Optional[Dict[str, Any]]:
    """
    按产品分析：将该时间段内该产品所有平台的帖子合并后做一次分析。
    
    Args:
        company: 产品名称
        platforms_data_list: 该产品下各平台、各日期的数据列表（每项含 posts, platform_type, game 等）
        period_days: 时间段天数
    
    Returns:
        AI 分析结果（含 summary, top_post_urls, video_highlights），失败返回 None
    """
    all_posts = _collect_company_posts(platforms_data_list)
    prompt = build_period_analysis_prompt(company=company, all_posts=all_posts, period_days=period_days)
    data = call_model_with_retry(prompt)
    if not data:
        return None

    total_posts = sum(len(pd.get("posts") or []) for pd in platforms_data_list)

    def _norm_urls(v: Any) -> List[str]:
        if not v:
            return []
        if isinstance(v, list):
            return [str(u).strip() for u in v if u]
        return []

    # 收集视频分析亮点（从有 video_analysis 的帖子中提取）
    video_highlights = []
    for post in all_posts:
        va = post.get("video_analysis")
        if va and isinstance(va, dict):
            post_url = post.get("post_url", "")
            highlight = {
                "post_url": post_url,
                "video_summary": va.get("video_summary", ""),
                "competitive_insight": va.get("competitive_insight", ""),
            }
            # 只保留有实质内容的
            if highlight["video_summary"] or highlight["competitive_insight"]:
                video_highlights.append(highlight)

    return {
        "company": data.get("company") or company,
        "summary": data.get("summary") or "",
        "top_post_urls": _norm_urls(data.get("top_post_urls"))[:3],
        "posts_count": total_posts,
        "period_days": period_days,
        "video_highlights": video_highlights,
    }


def analyze_extracted_data(extracted_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    分析提取的数据。按产品维度：该产品该时间段内所有社媒帖子合并后做一次分析。
    
    Args:
        extracted_data: 从 CompetitorPeriodDataExtractor 提取的数据
    
    Returns:
        分析结果，格式：
        {
            "period": {...},
            "companies": {
                "product_name": {
                    "company": "product_name",
                    "company_analysis": {
                        "summary", "new_features", "new_features_post_urls",
                        "product_updates", "product_updates_post_urls", "routine_note",
                        "direct_action_suggestions", "posts_count", "period_days"
                    }
                }
            },
            "analyzed_at": "..."
        }
    """
    period = extracted_data.get("period", {})
    companies_data = extracted_data.get("companies", {})
    period_days = period.get("days", 7)
    
    print(f"🤖 开始AI分析，时间段: {period.get('start_date')} 至 {period.get('end_date')} ({period_days} 天)")
    
    result = {
        "period": period,
        "companies": {},
        "analyzed_at": datetime.utcnow().isoformat() + "Z"
    }
    
    for company, company_data in companies_data.items():
        print(f"\n  分析公司: {company}")
        platforms_data_list = company_data.get("platforms_data", [])
        
        if not platforms_data_list:
            print(f"    ⚠️ {company} 无数据，跳过")
            continue
        
        analysis_result = analyze_company_period_data(
            company=company,
            platforms_data_list=platforms_data_list,
            period_days=period_days
        )
        
        if analysis_result:
            result["companies"][company] = {
                "company": company,
                "company_analysis": analysis_result
            }
            posts_count = analysis_result.get("posts_count", 0)
            weekly_score = analysis_result.get("weekly_score")
            weekly_title = analysis_result.get("weekly_title", "")[:30]
            if weekly_title and len(analysis_result.get("weekly_title", "")) > 30:
                weekly_title += "…"
            print(f"    ✓ 分析完成，帖子数: {posts_count}，评分: {weekly_score}/10，标题: {weekly_title or '-'}")
        else:
            print(f"    ⚠️ 分析失败，跳过")
    
    print(f"\n✓ AI分析完成")
    return result


def save_analysis_result(analysis_result: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """
    保存分析结果到JSON文件
    
    Args:
        analysis_result: 分析结果
        output_path: 输出文件路径，如果为None则自动生成
    
    Returns:
        保存的文件路径
    """
    if output_path is None:
        period = analysis_result.get("period", {})
        start_date = period.get("start_date", "")
        end_date = period.get("end_date", "")
        output_dir = os.environ.get("OUTPUT_DIR")
        if not output_dir or not os.path.exists(output_dir):
            output_dir = os.path.join(_PROJECT_ROOT, "workflows", "output")
            os.makedirs(output_dir, exist_ok=True)
        
        output_path = os.path.join(
            output_dir,
            f"competitor_analysis_result_{start_date}_to_{end_date}.json"
        )
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)
        
        print(f"💾 分析结果已保存: {output_path}")
        return output_path
    except Exception as exc:
        print(f"❌ 保存分析结果失败: {exc}")
        raise


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="对提取的数据进行AI分析")
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="输入的提取数据JSON文件路径（从CompetitorPeriodDataExtractor生成）"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="输出文件路径（可选，不指定则自动生成）"
    )
    
    args = parser.parse_args()
    
    # 读取提取的数据
    if not os.path.exists(args.input):
        print(f"❌ 输入文件不存在: {args.input}")
        return 1
    
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            extracted_data = json.load(f)
    except Exception as e:
        print(f"❌ 读取输入文件失败: {e}")
        return 1
    
    # 分析数据
    analysis_result = analyze_extracted_data(extracted_data)
    
    # 保存结果
    output_path = save_analysis_result(analysis_result, args.output)
    
    print(f"\n✅ AI分析完成: {output_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
