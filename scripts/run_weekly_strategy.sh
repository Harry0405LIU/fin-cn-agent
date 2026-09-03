#!/bin/bash
# 周策略报告 - 启动脚本
# 每周五17:00运行

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON3="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
SCRIPT="$PROJECT_DIR/stock/weekly_report.py"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/weekly_strategy_${TODAY}.log"

echo "[$(date)] 开始运行周策略报告..." >> "$LOG_FILE"
cd "$PROJECT_DIR"
$PYTHON3 "$SCRIPT" --once >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date)] 运行失败 (退出码: $EXIT_CODE)" >> "$LOG_FILE"
else
    echo "[$(date)] 运行完成" >> "$LOG_FILE"
fi
exit $EXIT_CODE
