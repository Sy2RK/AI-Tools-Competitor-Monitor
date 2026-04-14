"""
竞品社媒时间段监控工作流
统一三个部分：数据提取、AI分析、报告生成
支持分别执行和中间产物保存
"""
import os
import sys

# 保证从项目根目录运行脚本时能正确导入 reports、analyzers 等包
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import json
import argparse
from datetime import date
from typing import Optional

from dotenv import load_dotenv
load_dotenv()
from reports.period_extractor import CompetitorPeriodDataExtractor
from analyzers.period_ai import (
    analyze_extracted_data,
    save_analysis_result
)
from reports.period_generator import generate_period_reports


def run_workflow(
    start_date: date,
    end_date: date,
    companies: Optional[list] = None,
    db_path: Optional[str] = None,
    platforms: Optional[list] = None,
    skip_extract: bool = False,
    skip_analysis: bool = False,
    skip_report: bool = False,
    extracted_data_path: Optional[str] = None,
    analysis_result_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    skip_send: bool = False,
    send_to_wework: bool = False,
    report_save_mode: str = "overwrite"
) -> int:
    """
    运行完整的工作流
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        companies: 要处理的公司列表，如果为None则处理所有公司
        db_path: 数据库文件路径
        platforms: 要包含的平台类型列表（如 twitter, tiktok），为None则包含全部
        skip_extract: 是否跳过数据提取步骤
        skip_analysis: 是否跳过AI分析步骤
        skip_report: 是否跳过报告生成步骤
        extracted_data_path: 提取数据的文件路径（如果跳过提取步骤，需要提供）
        analysis_result_path: 分析结果的文件路径（如果跳过分析步骤，需要提供）
        output_dir: 输出目录
        skip_send: 是否跳过发送到飞书
        send_to_wework: 是否发送到企业微信
        report_save_mode: 周报保存模式。overwrite=覆盖数据库周报；use_cached=有缓存则不覆盖
    
    Returns:
        退出码（0表示成功）
    """
    print("=" * 60)
    print("🚀 竞品社媒时间段监控工作流")
    print("=" * 60)
    print(f"📅 时间段: {start_date} 至 {end_date} (共 {(end_date - start_date).days + 1} 天)")
    if companies:
        print(f"🏢 指定公司: {', '.join(companies)}")
    else:
        print(f"🏢 处理所有公司")
    if platforms:
        print(f"📱 指定平台: {', '.join(platforms)}")
    print(f"💾 周报保存: {'使用缓存（不覆盖）' if report_save_mode == 'use_cached' else '覆盖写入'}")
    print("=" * 60)
    print()
    
    # 设置输出目录
    if output_dir:
        os.environ["OUTPUT_DIR"] = output_dir
    elif not os.environ.get("OUTPUT_DIR"):
        output_dir = os.path.join(os.path.dirname(__file__), "output")
        os.makedirs(output_dir, exist_ok=True)
        os.environ["OUTPUT_DIR"] = output_dir
    
    # 第一部分：数据提取
    extracted_data = None
    extracted_file_path = None
    
    if not skip_extract:
        print("【第一部分】数据提取")
        print("-" * 60)
        
        extractor = CompetitorPeriodDataExtractor(db_path)
        extracted_data = extractor.extract_data_by_period(
            start_date=start_date,
            end_date=end_date,
            companies=companies,
            platforms=platforms
        )
        
        # 保存中间产物
        extracted_file_path = extractor.save_extracted_data(extracted_data)
        print()
    else:
        print("【第一部分】跳过数据提取")
        # 只有当需要执行第二部分（AI分析）时才需要提取数据文件
        if not skip_analysis:
            if not extracted_data_path:
                print("❌ 跳过数据提取步骤但未提供提取数据文件路径（执行AI分析需要提取数据）")
                return 1
            
            print(f"📂 从文件读取提取数据: {extracted_data_path}")
            try:
                with open(extracted_data_path, "r", encoding="utf-8") as f:
                    extracted_data = json.load(f)
            except Exception as e:
                print(f"❌ 读取提取数据文件失败: {e}")
                return 1
            extracted_file_path = extracted_data_path
        else:
            print("   跳过（只执行报告生成，不需要提取数据）")
        print()
    
    # 检查是否有数据（仅在需要执行AI分析时检查）
    if not skip_analysis:
        if not extracted_data or not extracted_data.get("companies"):
            print("⚠️ 未找到任何数据，工作流终止")
            return 0
    
    # 第二部分：AI分析
    analysis_result = None
    analysis_file_path = None
    
    if not skip_analysis:
        print("【第二部分】AI分析")
        print("-" * 60)
        
        analysis_result = analyze_extracted_data(extracted_data)
        
        # 保存中间产物
        analysis_file_path = save_analysis_result(analysis_result)
        print()
    else:
        print("【第二部分】跳过AI分析")
        if not analysis_result_path:
            print("❌ 跳过AI分析步骤但未提供分析结果文件路径")
            return 1
        
        print(f"📂 从文件读取分析结果: {analysis_result_path}")
        try:
            with open(analysis_result_path, "r", encoding="utf-8") as f:
                analysis_result = json.load(f)
        except Exception as e:
            print(f"❌ 读取分析结果文件失败: {e}")
            return 1
        analysis_file_path = analysis_result_path
        print()
    
    # 第三部分：报告生成
    if not skip_report:
        print("【第三部分】报告生成")
        print("-" * 60)
        
        reports = generate_period_reports(
            analysis_result=analysis_result,
            db_path=db_path,
            skip_send=skip_send,
            send_to_wework=send_to_wework,
            report_save_mode=report_save_mode
        )
        print()
    else:
        print("【第三部分】跳过报告生成")
        print()
    
    # 总结
    print("=" * 60)
    print("✅ 工作流完成")
    print("=" * 60)
    print(f"📂 中间产物:")
    if extracted_file_path:
        print(f"   • 提取数据: {extracted_file_path}")
    if analysis_file_path:
        print(f"   • 分析结果: {analysis_file_path}")
    print()
    
    return 0


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="竞品社媒时间段监控工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整工作流
  python workflows/period_workflow.py --start-date 2026-01-07 --end-date 2026-01-13

  # 只执行数据提取
  python workflows/period_workflow.py --start-date 2026-01-07 --end-date 2026-01-13 \\
      --skip-analysis --skip-report

  # 只执行 AI 分析（使用已有提取 JSON）
  python workflows/period_workflow.py --start-date 2026-01-07 --end-date 2026-01-13 \\
      --skip-extract --skip-report \\
      --extracted-data workflows/output/competitor_extracted_data_2026-01-07_to_2026-01-13.json

  # 只生成报告（使用已有分析 JSON）
  python workflows/period_workflow.py --start-date 2026-01-07 --end-date 2026-01-13 \\
      --skip-extract --skip-analysis \\
      --analysis-result workflows/output/competitor_analysis_result_2026-01-07_to_2026-01-13.json

  # 指定公司、不推送飞书
  python workflows/period_workflow.py --start-date 2026-01-07 --end-date 2026-01-13 \\
      --companies voodoo dream_games --skip-send
        """
    )
    
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
        help="指定要处理的公司列表（可选，不指定则处理所有公司）"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="数据库文件路径（可选，默认为 db/competitor_data.db）"
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="跳过数据提取步骤（需要提供 --extracted-data）"
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="跳过AI分析步骤（需要提供 --analysis-result）"
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="跳过报告生成步骤"
    )
    parser.add_argument(
        "--extracted-data",
        type=str,
        help="提取数据的文件路径（当跳过提取步骤时使用）"
    )
    parser.add_argument(
        "--analysis-result",
        type=str,
        help="分析结果的文件路径（当跳过分析步骤时使用）"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="中间产物输出目录（可选，默认 workflows/output/）"
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
        "--platforms",
        type=str,
        nargs="*",
        help="只包含指定平台（如 twitter tiktok youtube），不指定则包含全部平台"
    )
    parser.add_argument(
        "--report-save-mode",
        type=str,
        choices=["overwrite", "use_cached"],
        default="overwrite",
        help="周报保存模式: overwrite=覆盖数据库中的周报(默认); use_cached=若已有该周期周报则不写入"
    )
    
    args = parser.parse_args()
    
    # 解析日期
    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as e:
        print(f"❌ 日期格式错误: {e}")
        print("   请使用 YYYY-MM-DD 格式，例如: 2026-01-07")
        return 1
    
    if start_date > end_date:
        print("❌ 开始日期不能晚于结束日期")
        return 1
    
    # 运行工作流
    exit_code = run_workflow(
        start_date=start_date,
        end_date=end_date,
        companies=args.companies,
        db_path=args.db_path,
        platforms=args.platforms,
        skip_extract=args.skip_extract,
        skip_analysis=args.skip_analysis,
        skip_report=args.skip_report,
        extracted_data_path=args.extracted_data,
        analysis_result_path=args.analysis_result,
        output_dir=args.output_dir,
        skip_send=args.skip_send,
        send_to_wework=args.send_to_wework,
        report_save_mode=args.report_save_mode
    )
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
