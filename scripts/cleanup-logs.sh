#!/bin/bash
# 清理过期日志文件和视频缓存
# 用法: ./scripts/cleanup-logs.sh [保留天数]
# 默认保留 30 天的日志，7 天的视频缓存

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 保留天数参数
LOG_KEEP_DAYS="${1:-30}"
VIDEO_CACHE_KEEP_DAYS="${2:-7}"

LOG_DIR="$PROJECT_DIR/logs"
VIDEO_CACHE_DIR="$PROJECT_DIR/cache/videos"

echo "========================================"
echo "🧹 开始清理过期文件"
echo "   日志保留: ${LOG_KEEP_DAYS} 天"
echo "   视频缓存保留: ${VIDEO_CACHE_KEEP_DAYS} 天"
echo "========================================"

# 清理日志文件
if [ -d "$LOG_DIR" ]; then
    DELETED_LOGS=$(find "$LOG_DIR" -name "*.log" -type f -mtime +${LOG_KEEP_DAYS} -print -delete 2>/dev/null)
    if [ -n "$DELETED_LOGS" ]; then
        echo "🗑️  已删除过期日志（>${LOG_KEEP_DAYS}天）:"
        echo "$DELETED_LOGS"
    else
        echo "✅ 无过期日志需要清理"
    fi
else
    echo "⚠️  日志目录不存在: $LOG_DIR"
fi

# 清理视频缓存
if [ -d "$VIDEO_CACHE_DIR" ]; then
    DELETED_VIDEOS=$(find "$VIDEO_CACHE_DIR" -name "*.mp4" -type f -mtime +${VIDEO_CACHE_KEEP_DAYS} -print -delete 2>/dev/null)
    if [ -n "$DELETED_VIDEOS" ]; then
        echo "🗑️  已删除过期视频缓存（>${VIDEO_CACHE_KEEP_DAYS}天）:"
        echo "$DELETED_VIDEOS"
    else
        echo "✅ 无过期视频缓存需要清理"
    fi
else
    echo "⚠️  视频缓存目录不存在: $VIDEO_CACHE_DIR"
fi

# 显示当前磁盘占用
echo ""
echo "📊 当前磁盘占用:"
if [ -d "$LOG_DIR" ]; then
    LOG_SIZE=$(du -sh "$LOG_DIR" 2>/dev/null | cut -f1)
    echo "   日志目录: $LOG_SIZE"
fi
if [ -d "$VIDEO_CACHE_DIR" ]; then
    VIDEO_SIZE=$(du -sh "$VIDEO_CACHE_DIR" 2>/dev/null | cut -f1)
    echo "   视频缓存: $VIDEO_SIZE"
fi
if [ -d "$PROJECT_DIR/db" ]; then
    DB_SIZE=$(du -sh "$PROJECT_DIR/db" 2>/dev/null | cut -f1)
    echo "   数据库:   $DB_SIZE"
fi

echo "========================================"
echo "🧹 清理完成"
