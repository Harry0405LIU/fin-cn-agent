#!/bin/bash
# 每日股票分析报告 - 启动脚本
# 工作日9:00运行

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON3="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
SCRIPT="$PROJECT_DIR/stock/daily_report.py"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/daily_stock_${TODAY}.log"

DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "[$(date)] 周末,跳过运行" >> "$LOG_FILE"
    exit 0
fi

echo "[$(date)] 开始运行每日股票报告..." >> "$LOG_FILE"
cd "$PROJECT_DIR"
$PYTHON3 "$SCRIPT" --once >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date)] 运行失败 (退出码: $EXIT_CODE)" >> "$LOG_FILE"
else
    echo "[$(date)] 运行完成" >> "$LOG_FILE"
fi
exit $EXIT_CODE
