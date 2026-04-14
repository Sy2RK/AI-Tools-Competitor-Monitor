#!/bin/bash
# Bash脚本：每天定时运行爬虫程序
# 用于 macOS/Linux Cron 任务
# 功能：爬取前一天的社媒更新信息

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 设置 Python 路径，确保能找到项目根目录的模块（如 env_loader）
export PYTHONPATH="$(pwd):$PYTHONPATH"

# 激活虚拟环境（如果使用虚拟环境）
# 如果使用虚拟环境，取消下面这行的注释并修改路径
source .venv/bin/activate

# 日志文件路径
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/daily_scraper_$(date +%Y-%m-%d).log"

# 记录开始时间
START_TIME=$(date)
START_SECONDS=$(date +%s)

# macOS 和 Linux 的日期计算方式不同
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    TARGET_DATE=$(date -v-1d +%Y-%m-%d)
else
    # Linux
    TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
fi

echo "========================================" | tee -a "$LOG_FILE"
echo "开始执行每日爬虫任务" | tee -a "$LOG_FILE"
echo "目标: 爬取前一天的数据 (日期: $TARGET_DATE)" | tee -a "$LOG_FILE"
echo "时间: $START_TIME" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 运行爬虫程序，爬取前一天的数据（days-ago=1）
# 使用新的项目结构路径
python3 scrapers/daily_scraper.py --days-ago 1 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

END_TIME=$(date)
END_SECONDS=$(date +%s)
DURATION=$((END_SECONDS - START_SECONDS))

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 爬虫任务执行成功" | tee -a "$LOG_FILE"
else
    echo "❌ 爬虫任务执行失败，错误码: $EXIT_CODE" | tee -a "$LOG_FILE"
fi
echo "执行时长: ${DURATION} 秒" | tee -a "$LOG_FILE"
echo "结束时间: $END_TIME" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

exit $EXIT_CODE
