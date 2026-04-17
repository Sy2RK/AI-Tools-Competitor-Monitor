#!/bin/bash
# 备份 SQLite 数据库
# 用法: ./scripts/backup-db.sh [保留份数]
# 默认保留最近 10 份备份

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DB_DIR="$PROJECT_DIR/db"
BACKUP_DIR="$PROJECT_DIR/db/backups"
KEEP_COUNT="${1:-10}"

echo "========================================"
echo "💾 开始备份数据库"
echo "========================================"

# 确保备份目录存在
mkdir -p "$BACKUP_DIR"

# 查找所有 .db 文件
if [ ! -d "$DB_DIR" ]; then
    echo "❌ 数据库目录不存在: $DB_DIR"
    exit 1
fi

DB_FILES=$(find "$DB_DIR" -maxdepth 1 -name "*.db" -type f)
if [ -z "$DB_FILES" ]; then
    echo "⚠️  未找到数据库文件"
    exit 0
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 备份每个 .db 文件
echo "$DB_FILES" | while read -r DB_FILE; do
    DB_NAME=$(basename "$DB_FILE")
    BACKUP_NAME="${DB_NAME%.db}_${TIMESTAMP}.db"

    # 使用 SQLite 自带的 .backup 命令确保一致性
    # 如果 sqlite3 不可用，则回退到文件拷贝
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/$BACKUP_NAME'" 2>/dev/null
        if [ $? -eq 0 ]; then
            BACKUP_SIZE=$(du -sh "$BACKUP_DIR/$BACKUP_NAME" 2>/dev/null | cut -f1)
            echo "✅ 已备份: $DB_NAME → $BACKUP_NAME ($BACKUP_SIZE)"
        else
            # sqlite3 backup 失败，回退到拷贝
            cp "$DB_FILE" "$BACKUP_DIR/$BACKUP_NAME"
            BACKUP_SIZE=$(du -sh "$BACKUP_DIR/$BACKUP_NAME" 2>/dev/null | cut -f1)
            echo "✅ 已备份(拷贝): $DB_NAME → $BACKUP_NAME ($BACKUP_SIZE)"
        fi
    else
        cp "$DB_FILE" "$BACKUP_DIR/$BACKUP_NAME"
        BACKUP_SIZE=$(du -sh "$BACKUP_DIR/$BACKUP_NAME" 2>/dev/null | cut -f1)
        echo "✅ 已备份(拷贝): $DB_NAME → $BACKUP_NAME ($BACKUP_SIZE)"
    fi
done

# 清理过期备份（每个 db 文件只保留最近 KEEP_COUNT 份）
echo ""
echo "🗑️  清理过期备份（保留最近 ${KEEP_COUNT} 份）..."
echo "$DB_FILES" | while read -r DB_FILE; do
    DB_NAME=$(basename "$DB_FILE" .db)
    BACKUP_COUNT=$(ls -1t "$BACKUP_DIR/${DB_NAME}"_*.db 2>/dev/null | wc -l)
    if [ "$BACKUP_COUNT" -gt "$KEEP_COUNT" ]; then
        DELETE_COUNT=$((BACKUP_COUNT - KEEP_COUNT))
        ls -1t "$BACKUP_DIR/${DB_NAME}"_*.db | tail -n "$DELETE_COUNT" | while read -r OLD_FILE; do
            rm -f "$OLD_FILE"
            echo "   删除: $(basename "$OLD_FILE")"
        done
    else
        echo "   $DB_NAME: 当前 $BACKUP_COUNT 份，无需清理"
    fi
done

# 显示备份目录总大小
BACKUP_TOTAL=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
echo ""
echo "📊 备份目录总大小: $BACKUP_TOTAL"
echo "========================================"
echo "💾 备份完成"
