#!/bin/bash
# Bash脚本：每周定时运行时间段工作流
# 用于 macOS/Linux Cron 任务（建议 crontab：每周一 10:30）
# 功能：生成指定时间段或过去7天的竞品周报
#
# 用法：
#   ./run-weekly-period-workflow.sh                    # 默认：过去7天（7天前至昨天）
#   ./run-weekly-period-workflow.sh --start-date 2026-01-13 --end-date 2026-01-19

# 切换到脚本所在目录（项目根）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 解析可选参数：--start-date YYYY-MM-DD --end-date YYYY-MM-DD
CUSTOM_START=""
CUSTOM_END=""
while [ $# -gt 0 ]; do
    case "$1" in
        --start-date)
            CUSTOM_START="$2"
            shift 2
            ;;
        --end-date)
            CUSTOM_END="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# 设置 Python 路径，确保能找到项目根目录的模块
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# 激活虚拟环境（若存在），cron 下可正确找到 python3 和依赖
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# 日志文件路径
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# 确定日期范围：若指定了起止日期则用指定的，否则计算过去7天
if [ -n "$CUSTOM_START" ] && [ -n "$CUSTOM_END" ]; then
    LAST_WEEK_START="$CUSTOM_START"
    LAST_WEEK_END="$CUSTOM_END"
else
    # 计算过去7天：昨天往前推7天（共7天，如周一到周日）
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        LAST_WEEK_END=$(date -v-1d +%Y-%m-%d)
        LAST_WEEK_START=$(date -v-7d +%Y-%m-%d)
    else
        # Linux
        LAST_WEEK_END=$(date -d "yesterday" +%Y-%m-%d)
        LAST_WEEK_START=$(date -d "7 days ago" +%Y-%m-%d)
    fi
fi

LOG_FILE="$LOG_DIR/weekly_period_workflow_$(date +%Y-%m-%d).log"

# 记录开始时间
START_TIME=$(date)

echo "========================================" | tee -a "$LOG_FILE"
echo "开始执行每周时间段工作流任务" | tee -a "$LOG_FILE"
echo "时间段: $LAST_WEEK_START 至 $LAST_WEEK_END" | tee -a "$LOG_FILE"
echo "时间: $START_TIME" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 运行时间段工作流
# 使用新的项目结构路径
# --skip-send 参数可以取消注释，如果只想生成报告文件而不发送
python3 workflows/period_workflow.py --start-date "$LAST_WEEK_START" --end-date "$LAST_WEEK_END" 2>&1 | tee -a "$LOG_FILE"

# 如果不想发送到飞书，只生成报告文件，使用下面的命令：
# python3 workflows/period_workflow.py --start-date "$LAST_WEEK_START" --end-date "$LAST_WEEK_END" --skip-send 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

END_TIME=$(date)

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 周报生成任务执行成功" | tee -a "$LOG_FILE"
    echo "📊 周报时间段: $LAST_WEEK_START 至 $LAST_WEEK_END" | tee -a "$LOG_FILE"
else
    echo "❌ 周报生成任务执行失败，错误码: $EXIT_CODE" | tee -a "$LOG_FILE"
fi
echo "结束时间: $END_TIME" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
