#!/bin/bash
# 详细样式每日选股报告 - 启动脚本
# 每日9:00运行(由launchd调度)

# Python3路径
PYTHON3="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"

# 脚本路径（脚本所在目录的上一级 = 项目根目录）
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_NAME="generate_daily_selection_md.py"

# 输出根目录：优先 FINAGENT_BASE_DIR，否则 ~/Documents/Harry's Vault
VAULT_DEFAULT="$HOME/Documents/Harry's Vault"
BASE_DIR="${FINAGENT_BASE_DIR:-$VAULT_DEFAULT}"

# 日志路径
LOG_DIR="$BASE_DIR/每日选股/logs"
mkdir -p "$LOG_DIR"

# 日期
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/daily_selection_md_${TODAY}.log"

# 检查是否为工作日(周一至周五)
DOW=$(date +%u)
if [ "$DOW" -gt 5 ]; then
    echo "[$(date)] 周末,跳过运行" >> "$LOG_FILE"
    exit 0
fi

# 等待 OneDrive 开机同步完成：股票池文件可读后再运行。
# 机器开机时 launchd RunAtLoad 会立即触发本脚本，此时 OneDrive 尚未完成
# 同步，读取文件会报 "Resource deadlock avoided"，导致个股数据为空。
STOCK_POOL="$BASE_DIR/自选股票池.md"
MAX_WAIT_SECONDS=5400  # 最多等 90 分钟
WAITED=0
while [ "$WAITED" -lt "$MAX_WAIT_SECONDS" ]; do
    if head -c 1 "$STOCK_POOL" >/dev/null 2>&1; then
        [ "$WAITED" -gt 0 ] && echo "[$(date)] 股票池文件已可读 (等待了 ${WAITED}s)" >> "$LOG_FILE"
        break
    fi
    echo "[$(date)] 股票池文件暂不可读(OneDrive同步中)，30秒后重试... (已等 ${WAITED}s)" >> "$LOG_FILE"
    sleep 30
    WAITED=$((WAITED + 30))
done

# 运行脚本
echo "[$(date)] 开始生成详细样式每日选股报告..." >> "$LOG_FILE"
cd "$SCRIPT_DIR"
$PYTHON3 "$SCRIPT_NAME" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$(date)] 运行失败 (退出码: $EXIT_CODE)" >> "$LOG_FILE"
else
    echo "[$(date)] 运行完成" >> "$LOG_FILE"
fi
exit $EXIT_CODE