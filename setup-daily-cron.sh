#!/bin/bash
# 安装 crontab：每天早上 10:00 运行每日爬虫
# 用法: ./setup-daily-cron.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRAPER_SCRIPT="$SCRIPT_DIR/run-daily-scraper.sh"
LOG_DIR="$SCRIPT_DIR/logs"
CRON_LOG="$LOG_DIR/cron.log"
CRON_LINE="0 10 * * * $SCRAPER_SCRIPT >> $CRON_LOG 2>&1"

mkdir -p "$LOG_DIR"

if [ ! -x "$SCRAPER_SCRIPT" ]; then
    chmod +x "$SCRAPER_SCRIPT" 2>/dev/null || true
fi

# 检查是否已有相同任务（避免重复添加）
if crontab -l 2>/dev/null | grep -F "run-daily-scraper.sh" >/dev/null 2>&1; then
    echo "⚠️  crontab 中已存在每日爬虫任务，未重复添加。"
    echo "当前 crontab："
    crontab -l 2>/dev/null | grep -F "run-daily-scraper" || true
    exit 0
fi

# 追加新任务（保留原有 crontab）
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "✅ 已添加 crontab 任务：每天 10:00 运行每日爬虫"
echo "   执行: $SCRAPER_SCRIPT"
echo "   日志: $CRON_LOG"
echo ""
echo "查看当前 crontab: crontab -l"
echo "编辑 crontab:     crontab -e"
echo "删除本任务:       crontab -e  然后删除对应行"
