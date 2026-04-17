#!/bin/bash
# 一键安装所有 crontab 定时任务
# 包括：每日爬虫、每周周报、日志清理、数据库备份
# 用法: ./setup-cron.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# 确保所有脚本可执行
for script in \
    "$SCRIPT_DIR/run-daily-scraper.sh" \
    "$SCRIPT_DIR/run-weekly-period-workflow.sh" \
    "$SCRIPT_DIR/scripts/cleanup-logs.sh" \
    "$SCRIPT_DIR/scripts/backup-db.sh"; do
    if [ -f "$script" ]; then
        chmod +x "$script" 2>/dev/null
    fi
done

# 定义所有 cron 任务
DAILY_SCRAPER_CRON="0 10 * * * $SCRIPT_DIR/run-daily-scraper.sh >> $LOG_DIR/cron.log 2>&1"
WEEKLY_WORKFLOW_CRON="30 10 * * 1 $SCRIPT_DIR/run-weekly-period-workflow.sh >> $LOG_DIR/cron.log 2>&1"
CLEANUP_LOGS_CRON="0 3 * * 0 $SCRIPT_DIR/scripts/cleanup-logs.sh >> $LOG_DIR/cleanup.log 2>&1"
BACKUP_DB_CRON="0 2 * * * $SCRIPT_DIR/scripts/backup-db.sh >> $LOG_DIR/backup.log 2>&1"

# 当前 crontab 内容
CURRENT_CRON=$(crontab -l 2>/dev/null || true)

# 逐个添加（跳过已存在的）
add_cron_if_not_exists() {
    local marker="$1"
    local line="$2"
    local desc="$3"

    if echo "$CURRENT_CRON" | grep -F "$marker" >/dev/null 2>&1; then
        echo "⚠️  已存在: $desc"
    else
        echo "$line" >> /tmp/cron_new.txt
        echo "✅ 已添加: $desc"
    fi
}

# 先写入已有内容
echo "$CURRENT_CRON" > /tmp/cron_new.txt

echo "========================================"
echo "📋 安装定时任务"
echo "========================================"

add_cron_if_not_exists "run-daily-scraper.sh" "$DAILY_SCRAPER_CRON" "每日爬虫（每天 10:00）"
add_cron_if_not_exists "run-weekly-period-workflow.sh" "$WEEKLY_WORKFLOW_CRON" "每周周报（每周一 10:30）"
add_cron_if_not_exists "cleanup-logs.sh" "$CLEANUP_LOGS_CRON" "日志清理（每周日 03:00）"
add_cron_if_not_exists "backup-db.sh" "$BACKUP_DB_CRON" "数据库备份（每天 02:00）"

# 安装新 crontab
crontab /tmp/cron_new.txt
rm -f /tmp/cron_new.txt

echo ""
echo "========================================"
echo "📋 当前 crontab 任务列表"
echo "========================================"
crontab -l 2>/dev/null | while IFS= read -r line; do
    if [ -n "$line" ]; then
        echo "   $line"
    fi
done
echo ""
echo "管理命令:"
echo "   查看: crontab -l"
echo "   编辑: crontab -e"
