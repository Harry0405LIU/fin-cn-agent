#!/bin/bash
# FinAgent 定时任务安装脚本
# 安装所有 launchd plist 到 ~/Library/LaunchAgents/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_DIR="$SCRIPT_DIR/../config/schedules"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "FinAgent 定时任务安装"
echo "====================="
echo ""

# 安装每个 plist
for plist in "$PLIST_DIR"/*.plist; do
    [ -f "$plist" ] || continue
    name=$(basename "$plist")
    echo "安装 $name ..."
    
    # 如果已加载，先卸载
    if launchctl list | grep -q "${name%.plist}"; then
        launchctl unload "$LAUNCH_AGENTS/$name" 2>/dev/null
    fi
    
    # 复制到 LaunchAgents
    cp "$plist" "$LAUNCH_AGENTS/"
    
    # 加载
    launchctl load "$LAUNCH_AGENTS/$name"
    echo "  ✓ 已加载"
done

echo ""
echo "安装完成！当前已加载的 FinAgent 服务："
launchctl list | grep -E "elliott|stock|xueqiu|crawler" || echo "  (无)"
