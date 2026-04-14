#!/bin/bash
# 安装 crontab：每周一早上 10:30 运行周期工作流（生成上周竞品周报）
# 用法: ./setup-weekly-cron.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKFLOW_SCRIPT="$SCRIPT_DIR/run-weekly-period-workflow.sh"
LOG_DIR="$SCRIPT_DIR/logs"
CRON_LOG="$LOG_DIR/cron.log"
CRON_LINE="30 10 * * 1 $WORKFLOW_SCRIPT >> $CRON_LOG 2>&1"

mkdir -p "$LOG_DIR"

if [ ! -x "$WORKFLOW_SCRIPT" ]; then
    chmod +x "$WORKFLOW_SCRIPT" 2>/dev/null || true
fi

# 检查是否已有相同任务（避免重复添加）
if crontab -l 2>/dev/null | grep -F "run-weekly-period-workflow.sh" >/dev/null 2>&1; then
    echo "⚠️  crontab 中已存在周报工作流任务，未重复添加。"
    echo "当前 crontab："
    crontab -l 2>/dev/null | grep -F "run-weekly-period-workflow" || true
    exit 0
fi

# 追加新任务（保留原有 crontab）
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "✅ 已添加 crontab 任务：每周一 10:30 运行周期工作流"
echo "   执行: $WORKFLOW_SCRIPT"
echo "   日志: $CRON_LOG"
echo ""
echo "查看当前 crontab: crontab -l"
echo "编辑 crontab:     crontab -e"
echo "删除本任务:       crontab -e  然后删除对应行"
