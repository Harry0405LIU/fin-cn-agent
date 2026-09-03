#!/bin/bash
# 艾略特波浪每日预测更新 - 启动脚本
# 每日9:00运行(由launchd调度)

# Python3路径
PYTHON3="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"

# 脚本路径
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_NAME="elliott/daily_update.py"

# 日志路径
VAULT_DEFAULT="$HOME/Documents/Harry's Vault"
LOG_DIR="${FINAGENT_BASE_DIR:-$VAULT_DEFAULT}/波浪预测/logs"
mkdir -p "$LOG_DIR"

# 日期
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/elliott_update_${TODAY}.log"

# 检查是否为工作日(周一至周五)
DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "[$(date)] 周末,跳过运行" >> "$LOG_FILE"
    exit 0
fi

# 检查港股假期(简化判断 - 需手动维护)
# 常见港股假期: 元旦, 春节, 清明, 劳动节, 端午, 回归日, 中秋, 国庆, 圣诞
# 如果需要跳过,在 /tmp/elliott_skip 文件中写入日期即可
if [ -f /tmp/elliott_skip ] && grep -q "$TODAY" /tmp/elliott_skip 2>/dev/null; then
    echo "[$(date)] 假期,跳过运行" >> "$LOG_FILE"
    exit 0
fi

# 运行脚本
echo "[$(date)] 开始运行艾略特波浪每日更新..." >> "$LOG_FILE"
cd "$SCRIPT_DIR"
$PYTHON3 "$SCRIPT_NAME" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date)] 运行失败 (退出码: $EXIT_CODE)" >> "$LOG_FILE"
else
    echo "[$(date)] 运行完成" >> "$LOG_FILE"
fi
exit $EXIT_CODE
